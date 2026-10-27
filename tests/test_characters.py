"""Characters filed from a booru post by the Chrome extension: the shared characters.json (charstore.py, the same file
as the Gallery's), adding an outfit to a character you have, a fresh copy, the picture, the merge into the shared
folder, and the extension's routes. Made-up characters only."""
import asyncio
import base64
import json
import os
import sys
import types

import test_shared as T

check = T.check

base, user = T.fake_install("CHARS")
smf = T.load_smf(base, user)
cs, chars, config = smf.charstore, smf.characters, smf.config

WEBP = b"RIFF\x24\x00\x00\x00WEBPVP8 " + b"\x00" * 24
url = lambda b: "data:image/webp;base64," + base64.b64encode(b).decode()  # noqa: E731
post = {"site": "danbooru", "post": "4242", "url": "https://danbooru.donmai.us/posts/4242", "post_count": 310, "solo": True}
aurelia = {"tag": "aurelia_(lighthouse_tales)", "name": "Aurelia", "series": "Lighthouse Tales", "appearance": ["silver hair", "long_hair", "Silver Hair"],
           "outfit": {"name": "Default", "tags": ["white dress", "straw hat"]}, "source": post}

# ---------------------------------------------------------------- the pure part
check(cs.norm("Aurelia_(Lighthouse_Tales) ") == cs.norm("aurelia (lighthouse tales)"), "norm: Danbooru's form and a prompt's are the same tag")
imp = cs.clean_import(aurelia)
check(imp["appearance"] == ["silver hair", "long hair"] and imp["outfit"] == {"name": "default", "tags": ["white dress", "straw hat"]} and imp["mode"] == "outfit",
      "clean_import: tags with spaces, no repeats; the outfit's name in lower case; adding an outfit by default")
check(cs.clean_import({"tag": "", "name": ""}) is None and cs.clean_import("x") is None, "clean_import: nothing to file it under -> None")
bad = cs.clean_import({"tag": "x", "source": {"site": "evil.example", "url": "javascript:alert(1)", "post_count": "lots"}})
check(bad["source"]["site"] is None and bad["source"]["url"] is None and bad["source"]["post_count"] == 0, "clean_import: only known sites, https links, a number")
check(len(cs.clean_import({"tag": "x", "appearance": [str(i) for i in range(500)]})["appearance"]) == cs.CAPS["tags"], "clean_import: tags capped")

data = cs.empty()
c1, made = cs.apply_import(data, imp, 100.0, "chr_aaaa0001")
check(made and c1["id"] == "chr_aaaa0001" and c1["outfits"] == {"default": ["white dress", "straw hat"]} and c1["created"] == 100.0,
      "apply_import: a new character with its outfit")
again = cs.clean_import({**aurelia, "appearance": ["blue eyes", "long hair"], "outfit": {"name": "default", "tags": ["red coat", "scarf"]}})
c2, made2 = cs.apply_import(data, again, 200.0, "chr_aaaa0002")
check(not made2 and c2 is c1 and c1["appearance"] == ["silver hair", "long hair", "blue eyes"] and c1["outfits"]["default 2"] == ["red coat", "scarf"]
      and c1["updated"] == 200.0 and len(data["characters"]) == 1,
      "apply_import, same tag: new appearance tags join, the outfit is added under a free name, still one character")
c3, made3 = cs.apply_import(data, cs.clean_import({**aurelia, "mode": "new"}), 300.0, "chr_aaaa0003")
check(made3 and c3["name"] == "Aurelia 2" and len(data["characters"]) == 2 and cs.find(data, "Aurelia (Lighthouse Tales)") is c1,
      "apply_import, a fresh copy: a new character with a name of its own; find() still gives the first")
check(cs.picture(url(WEBP)) == (WEBP, "webp") and cs.picture("data:image/png;base64,aGVsbG8=") is None and cs.picture("https://x/y.webp") is None
      and cs.picture(url(b"RIFF" + b"\x00" * 4 + b"WEBP" + b"\x00" * cs.CAPS["picture"])) is None,
      "picture: a small WebP/JPEG/PNG only")
check(cs.picture_path("chr_AB/../x", "webp") == "characters/chr_abx.webp", "picture_path: always inside characters/")
m = cs.merge({"characters": [{"id": "a", "updated": 5, "name": "old"}]}, {"characters": [{"id": "a", "updated": 9, "name": "new"}, {"id": "b", "updated": 1}]})
check(sorted(c["id"] for c in m["characters"]) == ["a", "b"] and next(c for c in m["characters"] if c["id"] == "a")["name"] == "new",
      "merge: by id, the newer copy wins")
check(config._mergers.get(cs.FILE) is cs.merge, "characters.json is merged into the shared folder like the other data files")

# ---------------------------------------------------------------- characters.py: the file and its pictures
r = chars.save_import(aurelia, url(WEBP))
cid = r["character"]["id"]
pic = os.path.join(config.data_dir(), "characters", f"{cid}.webp")
check(r["created"] and r["character"]["image"] == f"characters/{cid}.webp" and os.path.isfile(pic), "save_import: filed, with its picture beside the list")
with open(config.data_path(cs.FILE), encoding="utf-8") as f:
    on_disk = json.load(f)
check(on_disk["v"] == 1 and [c["name"] for c in on_disk["characters"]] == ["Aurelia"], "characters.json in the data folder")
r2 = chars.save_import({**aurelia, "outfit": {"name": "winter", "tags": ["red coat"]}}, url(WEBP))
check(not r2["created"] and r2["character"]["id"] == cid and r2["character"]["outfits"]["winter"] == ["red coat"]
      and len(os.listdir(os.path.dirname(pic))) == 1, "save_import, same tag: an outfit added; the character's own picture kept (no stray copy)")
check(chars.picture_file(cid) == pic and chars.picture_file("chr_nothere") is None, "picture_file: the character's picture")
check(chars.listing() == [{"id": cid, "name": "Aurelia", "series": "Lighthouse Tales", "tag": "aurelia_(lighthouse_tales)",
                           "outfits": ["default", "winter"], "has_image": True}], "listing: tag, name and outfit names")
try:
    chars.save_import({"tag": "", "name": ""})
    check(False, "save_import: refuses what isn't a character")
except ValueError:
    check(True, "save_import: refuses what isn't a character")

# ---------------------------------------------------------------- the routes
try:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
except ImportError:
    web = None
    print("skip: aiohttp not installed")
if web:
    sys.modules.setdefault("server", types.SimpleNamespace(PromptServer=None))
    from smf.routes import characters_routes, ext_routes

    async def routes_check():
        rt = web.RouteTableDef()
        ext_routes.register(rt)
        characters_routes.register(rt)
        app = web.Application()
        app.add_routes(rt)
        c = TestClient(TestServer(app))
        await c.start_server()
        try:
            r = await c.get("/sm-fetcher/ext/characters")
            check(r.status == 200 and [x["name"] for x in (await r.json())["characters"]] == ["Aurelia"], "GET ext/characters: the list")
            nova = {"tag": "nova_(starfall)", "name": "Nova", "series": "Starfall", "appearance": ["red hair"], "outfit": {"name": "default", "tags": ["flight suit"]}}
            r = await c.post("/sm-fetcher/ext/characters", json={"character": nova, "picture": url(WEBP)})
            d = await r.json()
            check(r.status == 200 and d["created"] and d["character"]["name"] == "Nova", "POST ext/characters: filed")
            r = await c.get(f"/sm-fetcher/characters/{d['character']['id']}/picture")
            check(r.status == 200 and await r.read() == WEBP, "GET characters/{id}/picture: its picture")
            r = await c.post("/sm-fetcher/ext/characters", data=json.dumps({"character": nova}), headers={"Content-Type": "text/plain"})
            check(r.status == 415, "POST ext/characters: JSON only (a web page can't send it without asking)")
            r = await c.post("/sm-fetcher/ext/characters", json={"character": {"tag": ""}})
            check(r.status == 400, "POST ext/characters: something that isn't a character is refused")
        finally:
            await c.close()
    asyncio.run(routes_check())

print(f"\n{'all passed' if not check.failed else f'{check.failed} failed'}")
sys.exit(1 if check.failed else 0)
