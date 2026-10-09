"""Review fixes: cm-info merge, sidecar ownership, operation lock, not-found TTL,
rate-limit retry, settings choices."""
import asyncio
import json
import os
import shutil
import sys
import time

import test_shared as T

check = T.check


def main():
    lora = T.LORA
    os.makedirs(lora, exist_ok=True)
    base, user = T.fake_install("Fixes")
    smf = T.load_smf(base, user)

    # ---- cm-info merge on refresh
    m = os.path.join(lora, "merge.safetensors")
    open(m, "wb").write(b"\1" * 64)
    json.dump({"ModelName": "Old", "ModelDescription": "written by SM", "ImportedAt": "2024-01-01",
               "Stats": {"downloads": 5}, "Hashes": {"SHA256": "AA", "BLAKE3": "keep"}},
              open(m[:-12] + ".cm-info.json", "w"))
    smf.smmeta.write_cm_info(m, {"modelName": "New", "hashes": {"SHA256": "BB"}, "trainedWords": ["tw"]}, overwrite=True)
    cm = json.load(open(m[:-12] + ".cm-info.json"))
    check(cm["ModelName"] == "New" and cm["TrainedWords"] == ["tw"], "refresh updates CivitAI fields")
    check(cm["ModelDescription"] == "written by SM" and cm["Stats"] == {"downloads": 5}, "fields SM wrote are kept")
    check(cm["ImportedAt"] == "2024-01-01", "original ImportedAt kept")
    check(cm["Hashes"] == {"SHA256": "BB", "BLAKE3": "keep"}, "hashes merged")
    check(smf.smmeta.write_cm_info(m, {"modelName": "X"}) is None, "no overwrite without force")

    # ---- sidecar ownership with a shared stem
    a = os.path.join(lora, "twin.safetensors")
    b = os.path.join(lora, "twin.gguf")
    open(a, "wb").write(b"\2" * 64)
    open(b, "wb").write(b"\3" * 64)
    smf.hashing.store(a, "ab" * 32)
    st = os.path.join(lora, "twin")
    json.dump({"Hashes": {"SHA256": "AB" * 32}}, open(st + ".cm-info.json", "w"))
    json.dump({"file_path": b.replace("\\", "/")}, open(st + ".metadata.json", "w"))
    open(st + ".preview.png", "wb").write(b"png")
    names = lambda lst: sorted(os.path.basename(x) for x in lst)  # noqa: E731
    check(names(smf.smmeta.sidecars(a)) == ["twin.cm-info.json"], "shared stem: .safetensors takes only its cm-info (hash match)")
    check(names(smf.smmeta.sidecars(b)) == ["twin.metadata.json"], "shared stem: .gguf takes only its LM metadata (file_path)")
    solo = os.path.join(lora, "solo.safetensors")
    open(solo, "wb").write(b"\4")
    open(os.path.join(lora, "solo.preview.png"), "wb").write(b"png")
    check(names(smf.smmeta.sidecars(solo)) == ["solo.preview.png"], "unique stem: every sidecar moves")

    # ---- operation lock
    smf.library.build("loras")
    fid = next(e["id"] for e in smf.library._index.values() if e["name"] == "solo.safetensors")
    smf.busy.begin("Fetching metadata")
    try:
        smf.organize.apply([{"id": fid, "to_rel": "X/solo.safetensors"}])
        check(False, "move refused during a metadata fetch")
    except smf.busy.Busy as ex:
        check("Fetching metadata" in str(ex), "move refused during a metadata fetch, with the reason")
    smf.busy.end("Fetching metadata")
    r = smf.organize.apply([{"id": fid, "to_rel": "X/solo.safetensors"}])
    check(r["moved"] == 1 and smf.busy.current() is None, "move runs once the fetch ends; lock released")
    smf.organize.undo(r["run_id"])

    async def dup_while_moving():
        smf.busy.begin("Moving files")
        try:
            await smf.organize.find_duplicates(["loras"])
            return False
        except smf.busy.Busy:
            return True
        finally:
            smf.busy.end("Moving files")
    check(asyncio.run(dup_while_moving()), "duplicate scan refused while files move")

    # ---- not-found TTL
    smf.hashing.store(solo, "cd" * 32)
    smf.config.write_json("civitai_not_found.json", {"cd" * 32: time.time() - 31 * 86400})
    e = next(e for e in smf.library.build("loras") if e["name"] == "solo.safetensors")
    check(not e["lookup_failed"], "'not on CivitAI' older than 30 days is retried")
    smf.config.write_json("civitai_not_found.json", {"cd" * 32: time.time() - 86400})
    e = next(e for e in smf.library.build("loras") if e["name"] == "solo.safetensors")
    check(e["lookup_failed"], "recent 'not on CivitAI' is remembered")

    # ---- rate-limit retry against a real local server
    from aiohttp import web
    hits = []

    async def handler(request):
        hits.append(time.time())
        if len(hits) == 1:
            return web.Response(status=429, headers={"Retry-After": "0.5"})
        return web.json_response({"ok": True})

    async def run_server():
        app = web.Application()
        app.router.add_get("/x", handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            data = await smf.net.get_json(f"http://127.0.0.1:{port}/x")
        finally:
            await smf.net.close()
            await runner.cleanup()
        return data
    data = asyncio.run(run_server())
    check(data == {"ok": True} and len(hits) == 2, "429 is retried and then succeeds")
    check(hits[1] - hits[0] >= 0.45, "Retry-After honoured")

    # ---- settings choices
    smf.config.save({"auto_check_action": "open"})
    check(smf.config.load()["auto_check_action"] == "open", "auto-check action saved")
    smf.config.save({"auto_check_action": "explode"})
    check(smf.config.load()["auto_check_action"] == "notify", "invalid choice falls back to the default")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
