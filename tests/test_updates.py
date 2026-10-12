"""Update alerts: newer CivitAI versions of installed models (stubbed CivitAI, real Library entries)."""
import asyncio
import json
import os
import shutil
import sys

import test_shared as T

check = T.check


def model(path, mid, vid, base="Illustrious", lm=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "wb").write(os.path.basename(path).encode())
    stem = os.path.splitext(path)[0]
    if lm:  # LoRA Manager's sidecar instead of Stability Matrix's
        json.dump({"model_name": "x", "civitai": {"id": vid, "modelId": mid, "baseModel": base}}, open(stem + ".metadata.json", "w"))
    else:
        json.dump({"ModelId": mid, "VersionId": vid, "ModelName": "x", "BaseModel": base}, open(stem + ".cm-info.json", "w"))


def version(vid, base, name=None, status="Published", files=True):
    return {"id": vid, "name": name or f"v{vid}", "baseModel": base, "status": status, "publishedAt": f"2026-0{vid % 9 + 1}-01",
            "files": [{"name": f"file_{vid}.safetensors", "primary": True}] if files else []}


def main():
    base, user = T.fake_install("Updates")
    smf = T.load_smf(base, user)
    L = T.LORA
    model(os.path.join(L, "Illustrious", "style_v1.safetensors"), 100, 1001)        # update: 1003 (same base)
    model(os.path.join(L, "Illustrious", "newest.safetensors"), 200, 2002)          # already the newest
    model(os.path.join(L, "Pony", "ported.safetensors"), 300, 3001, base="Pony")    # newer versions are other bases only
    model(os.path.join(L, "Illustrious", "char_v1.safetensors"), 400, 4001, lm=True)  # LM sidecar; v2 also installed
    model(os.path.join(L, "Illustrious", "char_v2.safetensors"), 400, 4002, lm=True)
    model(os.path.join(L, "gone.safetensors"), 500, 5001)                           # removed from CivitAI
    open(os.path.join(L, "no_meta.safetensors"), "wb").write(b"x")                    # not from CivitAI: never asked
    model(os.path.join(L, "Wan", "motion_LOW.safetensors"), 600, 6001, base="Wan Video 2.2 I2V-A14B")   # variants as versions
    model(os.path.join(L, "Wan", "lightning_4step.safetensors"), 700, 7001, base="Qwen")
    model(os.path.join(L, "ckpt_v8.safetensors"), 800, 8001)                          # several versions kept on purpose
    model(os.path.join(L, "ckpt_v15.safetensors"), 800, 8002)

    models = {
        100: {"name": "Watercolor", "modelVersions": [version(1004, "Illustrious", status="Draft"), version(1003, "Illustrious", "v3"),
                                                       version(1002, "SDXL 1.0"), version(1001, "Illustrious")]},
        200: {"name": "Newest", "modelVersions": [version(2002, "Illustrious"), version(2001, "Illustrious")]},
        300: {"name": "Ported", "modelVersions": [version(3003, "Flux.1 D"), version(3002, "Illustrious"), version(3001, "Pony")]},
        400: {"name": "Char", "modelVersions": [version(4002, "Illustrious"), version(4001, "Illustrious")]},
        600: {"name": "Motion", "modelVersions": [version(6004, "Wan Video 2.2 I2V-A14B", "v2.1 HN"), version(6003, "Wan Video 2.2 I2V-A14B", "v2.1 LN"),
                                                   version(6002, "Wan Video 2.2 I2V-A14B", "v1.0 HN"), version(6001, "Wan Video 2.2 I2V-A14B", "v1.0 LN")]},
        700: {"name": "Lightning", "modelVersions": [version(7002, "Qwen", "8steps bf16"), version(7001, "Qwen", "4steps bf16")]},
        800: {"name": "Ckpt", "modelVersions": [version(8003, "Illustrious", "v18"), version(8002, "Illustrious", "v15"), version(8001, "Illustrious", "v8")]},
    }
    calls = []

    async def fake_get_json(url, params=None, timeout=30):
        calls.append(url)
        mid = int(url.rstrip("/").split("/")[-1])
        return models.get(mid)  # None = 404
    smf.net.get_json = fake_get_json
    smf.updates.POLITE = 0

    async def run(force=False):
        await smf.updates.check(force)
        while smf.updates.job_status()["status"] == "running":
            await asyncio.sleep(0.01)
        return smf.updates.job_status()

    st = asyncio.run(run())
    check(st["status"] == "done" and st["total"] == 8 and st["updates"] == 3, f"one CivitAI call per model id; three updates found ({st})")
    check(sorted(int(u.split("/")[-1]) for u in calls) == [100, 200, 300, 400, 500, 600, 700, 800], "each model id asked once (two files of model 400)")
    entries = {e["name"]: e for e in smf.updates.annotate(smf.library.build("loras"))}
    u = entries["style_v1.safetensors"].get("update")
    check(u and u["id"] == 1003 and u["name"] == "v3" and u["newer_count"] == 1 and u["model_name"] == "Watercolor",
          f"newest published same-base version (drafts and other bases skipped) ({u})")
    check(u["page_url"] == "https://civitai.com/models/100?modelVersionId=1003", "page link to the new version")
    check(not entries["newest.safetensors"].get("update"), "already newest: no alert")
    check(not entries["ported.safetensors"].get("update"), "newer versions only for other base models: no alert")
    check(not entries["char_v1.safetensors"].get("update"), "newer version already installed (LoRA Manager sidecar): no alert")
    check(not entries["gone.safetensors"].get("update") and smf.updates.load()["models"]["500"].get("gone"), "removed model remembered, no alert")
    check(not st["stale"] and st["last_check"] > 0, "last check recorded")
    check(entries["motion_LOW.safetensors"].get("update", {}).get("name") == "v2.1 LN", "a low-noise file is offered the newer low-noise version, not high")
    check(not entries["lightning_4step.safetensors"].get("update"), "8 steps isn't an update of 4 steps (a variant)")
    check(entries["ckpt_v15.safetensors"].get("update", {}).get("name") == "v18" and not entries["ckpt_v8.safetensors"].get("update"),
          "with several versions kept, only the newest you have is flagged")
    V = smf.updates.variant
    check(V("2.2 Lightning I2V H") == {"i2v", "h"} and V("v1.0") == set() and V("Illustrious v3.0") == set()
          and V("Q4_K_M 14B") == {"q4", "14b"} and V("4steps bf16 (2511)") == {"4steps", "bf16"} and V("v3.0 unpruned") == set() and V("Smooth Negative Hands") == {"negative"},
          "variant markers (noise half, precision, steps, quant, size); plain releases have none")

    calls.clear()
    asyncio.run(run())
    check(calls == [], "second check within a day: nothing asked again")
    models[200]["modelVersions"].insert(0, version(2003, "Illustrious"))
    asyncio.run(run(force=True))
    check(len(calls) == 8 and smf.updates.annotate(smf.library.build("loras")) and
          any(e.get("update", {}).get("id") == 2003 for e in smf.updates.annotate(smf.library.build("loras"))), "forced check finds a new version")

    smf.updates.dismiss(100, 1003)
    entries = {e["name"]: e for e in smf.updates.annotate(smf.library.build("loras"))}
    check(not entries["style_v1.safetensors"].get("update"), "dismissed version hidden")
    models[100]["modelVersions"].insert(0, version(1005, "Illustrious"))
    asyncio.run(run(force=True))
    entries = {e["name"]: e for e in smf.updates.annotate(smf.library.build("loras"))}
    check(entries["style_v1.safetensors"].get("update", {}).get("id") == 1005, "an even newer version shows again after a dismissal")

    # ---- HTTP: library carries the update; candidate keeps the old file and avoids its name
    from aiohttp import web, ClientSession

    async def fake_by_version(vid, want_hash=None):
        return {"url": f"https://civitai.com/api/download/models/{vid}", "filename": "style_v1.safetensors" if vid == 1005 else f"file_{vid}.safetensors",
                "sha256": "ab" * 32, "size": 10, "source": "civitai", "confidence": "high"}
    smf.sources.civitai_by_version = fake_by_version

    async def http():
        routes = web.RouteTableDef()
        smf.routes.register(routes)
        app = web.Application()
        app.add_routes(routes)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        url = f"http://127.0.0.1:{port}/sm-fetcher"
        try:
            async with ClientSession() as s:
                async with s.get(url + "/library?section=loras") as r:
                    lib = await r.json()
                e = next(x for x in lib["entries"] if x["name"] == "style_v1.safetensors")
                async with s.post(url + "/updates/candidate", json={"id": e["id"], "version_id": 1005, "version_name": "v 5"}) as r:
                    same_name = await r.json()
                e2 = next(x for x in lib["entries"] if x["name"] == "newest.safetensors")
                async with s.post(url + "/updates/candidate", json={"id": e2["id"], "version_id": 2003}) as r:
                    other = await r.json()
                async with s.post(url + "/updates/dismiss", json={"model_id": "x"}) as r:
                    bad = r.status
                async with s.get(url + "/updates") as r:
                    status = await r.json()
                return e, same_name, other, bad, status
        finally:
            await runner.cleanup()
    e, same_name, other, bad, status = asyncio.run(http())
    check(e.get("update", {}).get("id") == 1005, "the library route carries the update")
    check(same_name["rel"] == "Illustrious/style_v1_v_5.safetensors" and same_name["folder"] == "loras",
          f"new version reusing the old file name gets a version suffix; old file kept ({same_name.get('rel')})")
    check(other["rel"] == "Illustrious/file_2003.safetensors" and other["candidate"]["sha256"] == "ab" * 32, "new version saved next to the old one")
    check(bad == 400 and status["status"] == "done", "bad dismiss → 400; status route")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
