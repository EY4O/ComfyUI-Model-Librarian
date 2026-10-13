"""Your notes on models (rating, note, tags) and use counts, through the Library routes."""
import asyncio
import os
import shutil
import sys

import test_shared as T

check = T.check


def main():
    base, user = T.fake_install("Notes")
    os.makedirs(os.path.join(T.LORA, "Illustrious"), exist_ok=True)
    for rel in ("Illustrious/style_a.safetensors", "style_b.safetensors"):
        open(os.path.join(T.LORA, *rel.split("/")), "wb").write(rel.encode())
    smf = T.load_smf(base, user)
    nt = smf.notes

    # ---- validation
    c = nt.clean({"rating": 9, "note": "x" * 5000, "tags": "Portrait, portrait , , moody"})
    check(c["rating"] == 5 and len(c["note"]) == nt.MAX_NOTE and c["tags"] == ["Portrait", "moody"], "rating clamped, note trimmed, tags de-duplicated")
    try:
        nt.clean({"rating": "lots"})
        check(False, "bad rating refused")
    except ValueError:
        check(True, "bad rating refused")

    # ---- save, merge, clear; keyed by file name so moves keep them
    nt.save("loras", "Illustrious\\style_a.safetensors", {"rating": 4, "tags": ["portrait"]})
    nt.save("loras", "style_a.safetensors", {"note": "great at 0.7"})
    got = nt.load()[nt.key("loras", "Illustrious/Other/STYLE_A.safetensors")]
    check(got["rating"] == 4 and got["note"] == "great at 0.7" and got["tags"] == ["portrait"], "fields merge; the key follows the file name, not the folder")
    nt.save("loras", "style_b.safetensors", {"rating": 2})
    nt.save("loras", "style_b.safetensors", {"rating": 0})
    check(nt.key("loras", "style_b.safetensors") not in nt.load(), "a record with nothing left is removed")

    # ---- use counts: one per prompt, never double-counted between the folder and name keys
    tg = smf.tiering
    tg.record_use([("loras", "Illustrious\\style_a.safetensors"), ("loras", "Illustrious\\style_a.safetensors")])
    tg.record_use([("loras", "Illustrious\\style_a.safetensors")])
    tg.record_use([("*", "style_b.safetensors")])
    entries = {e["name"]: e for e in tg.annotate_usage(nt.annotate(smf.library.build("loras")))}
    a, b = entries["style_a.safetensors"], entries["style_b.safetensors"]
    check(a["use_count"] == 2 and a["last_used"] and a["notes"]["rating"] == 4, f"use count per prompt ({a['use_count']}), last used, notes attached")
    check(b["use_count"] == 1 and "notes" not in b, "a use recorded without its folder still counts")
    merged = tg._merge_usage({"count": {"loras:x": 5}}, {"count": {"loras:x": 3, "loras:y": 1}})
    check(merged["count"] == {"loras:x": 5, "loras:y": 1}, "merging install data keeps the larger count")

    # ---- HTTP
    from aiohttp import web, ClientSession

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
                eb = next(x for x in lib["entries"] if x["name"] == "style_b.safetensors")
                async with s.post(url + "/library/notes", json={"id": eb["id"], "rating": 5, "note": "keeper", "tags": "film, grain"}) as r:
                    saved = (r.status, await r.json())
                async with s.post(url + "/library/notes", json={"id": eb["id"], "rating": "x"}) as r:
                    bad = r.status
                async with s.post(url + "/library/notes", json={"id": "nope", "rating": 1}) as r:
                    missing = r.status
                async with s.get(url + "/library?section=loras") as r:
                    lib2 = await r.json()
                return lib, saved, bad, missing, lib2
        finally:
            await runner.cleanup()
    lib, (st, body), bad, missing, lib2 = asyncio.run(http())
    ea = next(x for x in lib["entries"] if x["name"] == "style_a.safetensors")
    check(ea["use_count"] == 2 and ea["notes"]["note"] == "great at 0.7", "library route carries notes and use counts")
    check(st == 200 and body["notes"] == {"rating": 5, "note": "keeper", "tags": ["film", "grain"]}, f"notes saved through the route ({body})")
    check(bad == 400 and missing == 404, "bad rating → 400, unknown model → 404")
    check(next(x for x in lib2["entries"] if x["name"] == "style_b.safetensors")["notes"]["rating"] == 5, "saved notes come back with the library")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
