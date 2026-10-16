"""Recipe models you have under another name: matched by name, similar name or a
link you made by hand (remembered), or given a download from a pasted link."""
import asyncio
import os

import test_shared as T

check = T.check


def main():
    base, user = T.fake_install("LINKS")
    smf = T.load_smf(base, user)
    os.makedirs(os.path.join(T.LORA, "Illustrious"), exist_ok=True)
    made = []
    for rel in ("Illustrious/ILFF7_Tifa_v2.safetensors", "Illustrious/aerith_ff7.safetensors", "Illustrious/aerith_ff7_v3.safetensors", "mystery_style.safetensors"):
        p = os.path.join(T.LORA, *rel.split("/"))
        open(p, "wb").write(b"x")
        made.append(p)

    async def nothing(*a, **k):
        return None
    smf.sources.civitai_by_hash = nothing
    smf.sources.civitai_by_version = nothing

    async def no_cands(*a, **k):
        return []
    smf.sources.resolve = no_cands
    rp = smf.recipes

    def plan(loras):
        return asyncio.run(rp.plan_recipe({"schema": "recipe/1", "prompt": {"positive": "x"}, "loras": loras}))["items"]

    # ---- automatic: by name, then similar name (case, punctuation, a version tail)
    it = plan([{"name": "ILFF7Tifa", "weight": 1}])[0]
    check(it["status"] == "present" and it["matched_by"] == "similar name" and it["comfy_name"].endswith("ILFF7_Tifa_v2.safetensors"),
          f"ILFF7Tifa → ILFF7_Tifa_v2 by a similar name ({it['status']}, {it['matched_by']})")
    it = plan([{"name": "mystery_style"}])[0]
    check(it["matched_by"] == "name", "a name-only reference matches the file of that name")
    it = plan([{"name": "aerith ff7"}])[0]
    check(it["status"] == "unavailable", "two similar files (aerith_ff7, aerith_ff7_v3): no guess")
    check(it["note"] == "No download source found", "…and nothing to download")
    check(rp._similar(["abc"], "lora", smf.paths.Inventory()) is None, "very short names aren't guessed")

    # ---- by hand: use a file I have; remembered for the next recipe
    it = plan([{"name": "AerithFF7", "hash": "deadbeef12"}])[0]
    linked = rp.link_item(it, "Illustrious/aerith_ff7_v3.safetensors")
    check(linked["status"] == "present" and linked["matched_by"] == "your link", "linked by hand")
    again = plan([{"name": "Aerith-FF7"}])[0]
    check(again["matched_by"] == "your link" and again["comfy_name"].endswith("aerith_ff7_v3.safetensors"), "the next recipe naming it finds it")
    by_hash = plan([{"name": "something else", "hash": "DEADBEEF12"}])[0]
    check(by_hash["matched_by"] == "your link", "…also by the hash the recipe gave")
    try:
        rp.link_item(it, "not_installed.safetensors")
        check(False, "linking a file that isn't installed is refused")
    except ValueError:
        check(True, "linking a file that isn't installed is refused")
    rp.link_item(it, None)
    check(plan([{"name": "Aerith-FF7"}])[0]["status"] == "unavailable", "unlinked: back to not found")

    # ---- by hand: paste the page it's on
    async def from_url(url):
        return smf.sources._cand("civitai", "https://civitai.com/api/download/models/555", "TifaLockhart_IL.safetensors", confidence="high",
                                 sha256="ab" * 32, size=1234, page_url=url, title="Tifa — IL", meta={"baseModel": "Illustrious"})
    smf.sources.from_url = from_url
    miss = plan([{"name": "CloudStrife"}])[0]
    got = asyncio.run(rp.item_from_url(miss, "https://civitai.com/models/55?modelVersionId=555"))
    d = got["download"] or {}
    check(got["status"] == "missing" and d.get("url", "").endswith("/555") and d.get("sha256") == "ab" * 32
          and d.get("rel", "").endswith("TifaLockhart_IL.safetensors"), f"a pasted page becomes its download ({d.get('rel')})")
    check(got["page_url"] == "https://civitai.com/models/55?modelVersionId=555", "the page is kept")
    # once downloaded, the recipe's name finds it
    dest = d["dest"]
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    open(dest, "wb").write(b"y")
    made.append(dest)
    check(plan([{"name": "CloudStrife"}])[0]["matched_by"] == "your link", "after the download, the recipe's name finds that file")

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
        try:
            async with ClientSession() as s:
                async with s.post(f"http://127.0.0.1:{port}/sm-fetcher/recipe/link", json={"item": it, "file": "mystery_style.safetensors"}) as r:
                    a = (r.status, await r.json())
                async with s.post(f"http://127.0.0.1:{port}/sm-fetcher/recipe/link-url", json={"item": it, "url": "http://insecure"}) as r:
                    b = r.status
            return a, b
        finally:
            await runner.cleanup()
    (st, body), bad = asyncio.run(http())
    check(st == 200 and body["item"]["matched_by"] == "your link", "POST /recipe/link")
    check(bad == 400, "only https links are taken")

    for p in made:
        if os.path.exists(p):
            os.remove(p)
    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
