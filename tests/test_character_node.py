"""Character Select: the prompt from a character (escaped brackets, parts and tags left out, before / after), finding the
character by id, name or tag, its outfit, its LoRA loaded through ComfyUI's LoRA loader (faked here), a rerun when the
character changes, and the picker's route. Made-up characters only."""
import asyncio
import json
import os
import sys
import types

import test_shared as T

check = T.check

base, user = T.fake_install("CHARNODE")
os.makedirs(os.path.join(T.LORA, "chars"), exist_ok=True)
with open(os.path.join(T.LORA, "chars", "aurelia_v2.safetensors"), "wb") as f:
    f.write(b"x")
smf = T.load_smf(base, user)
import smf.character_node  # noqa: E402  (not imported by the routes)
node_mod, chars, cs = smf.character_node, smf.characters, smf.charstore

aurelia = {"tag": "aurelia_(lighthouse_tales)", "name": "Aurelia", "series": "Lighthouse Tales", "appearance": ["silver hair", "long hair"],
           "outfit": {"name": "default", "tags": ["white dress", "straw hat"]}}
cid = chars.save_import(aurelia)["character"]["id"]
chars.save_import({**aurelia, "outfit": {"name": "winter", "tags": ["red coat"]}})
nova = chars.save_import({"tag": "nova", "name": "Nova"})["character"]["id"]

# ---------------------------------------------------------------- the prompt
check(node_mod.escape("aurelia_(lighthouse_tales)") == r"aurelia \(lighthouse tales\)" and node_mod.escape(r"a \(b\)") == r"a \(b\)",
      "escape: spaces, brackets escaped (once)")
c = node_mod.resolve(cid)
p = node_mod.build(c, "default")
check(p == r"aurelia \(lighthouse tales\), silver hair, long hair, white dress, straw hat", f"build: its tag, appearance and the outfit ({p})")
p = node_mod.build(c, "winter", include_character=False, include_series=True, include_appearance=True, include_outfit=True,
                   off_tags="Long_Hair, nothing", before="masterpiece, best quality,", after="lighthouse, dusk")
check(p == "masterpiece, best quality, lighthouse tales, silver hair, red coat, lighthouse, dusk",
      f"build: parts switched, a tag turned off (any spelling), before and after ({p})")
check(node_mod.build(c, "", include_appearance=False) == r"aurelia \(lighthouse tales\)", "build: no outfit")

# ---------------------------------------------------------------- finding it
check(node_mod.resolve("chr_gone", "aurelia")["id"] == cid and node_mod.resolve("", "Aurelia (Lighthouse Tales)")["id"] == cid,
      "resolve: by id, else by name, else by its tag")
for args, want in ((("", "Somebody"), "isn't in your characters"), (("", ""), "pick a character")):
    try:
        node_mod.resolve(*args)
        check(False, f"resolve: {want}")
    except ValueError as ex:
        check(want in str(ex), f"resolve: {want} ({ex})")
N = node_mod.CharacterSelect
check(N.VALIDATE_INPUTS(character="Somebody") != True and N.VALIDATE_INPUTS(character="Aurelia", character_id=cid) is True,  # noqa: E712
      "VALIDATE_INPUTS: a character that's gone stops the run before it starts")

# ---------------------------------------------------------------- running it
run = lambda **kw: N().run(**{"character": "Aurelia", "outfit": "default", "include_character": True, "include_series": False,  # noqa: E731
                              "include_appearance": True, "include_outfit": True, "lora_strength": 0.8, "character_id": cid, **kw})
out = run()
check(out[0].startswith(r"aurelia \(lighthouse tales\)") and out[1] == "Aurelia" and out[2] is None and out[3] is None,
      "run: the prompt, the name for Gallery Info; nothing wired, nothing loaded")
try:
    run(outfit="ballgown")
    check(False, "run: an outfit it doesn't have is an error naming the ones it has")
except ValueError as ex:
    check("default, winter" in str(ex), f"run: an outfit it doesn't have is an error naming the ones it has ({ex})")

loaded = []
fake_nodes = types.ModuleType("nodes")
fake_nodes.LoraLoader = lambda: types.SimpleNamespace(load_lora=lambda m, cl, name, sm, sc: (loaded.append((name, sm, sc)) or (f"{m}+lora", f"{cl}+lora")))
sys.modules["nodes"] = fake_nodes
out = run(model="MODEL", clip="CLIP")
check(out[2] == "MODEL" and not loaded, "run: a character without a LoRA passes model and clip through")


def give_lora(name, trigger):
    def change(d):
        for x in d["characters"]:
            if x["id"] == cid:
                x["lora"] = {"name": name, "trigger": trigger}
                x["updated"] = 999.0
    smf.config.update_json(cs.FILE, cs.empty(), change)


before = N.IS_CHANGED(character="Aurelia", character_id=cid)
give_lora("aurelia_v2.safetensors", ["aurelia_lt"])
check(N.IS_CHANGED(character="Aurelia", character_id=cid) != before, "IS_CHANGED: an edit to the character runs the node again")
out = run(model="MODEL", clip="CLIP")
check(loaded == [(os.path.join("chars", "aurelia_v2.safetensors"), 0.8, 0.8)] and out[2] == "MODEL+lora" and out[0].startswith(r"aurelia_lt, aurelia \(lighthouse tales\)"),
      f"run: its LoRA found by file name in the loras folder, loaded at the strength set, its trigger words first, as trained ({loaded}, {out[0][:40]})")
loaded.clear()
out = run()
check(not loaded and not out[0].startswith("aurelia_lt"), "run: nothing wired: no LoRA, no trigger words")
give_lora("someone_else.safetensors", [])
try:
    run(model="MODEL")
    check(False, "run: a LoRA you don't have is an error")
except ValueError as ex:
    check("isn't in your loras folder" in str(ex), f"run: a LoRA you don't have is an error ({ex})")

# ---------------------------------------------------------------- linking a LoRA (from the node, the Library, the Gallery, the extension)
with open(os.path.join(T.LORA, "chars", "aurelia_v2.civitai.info"), "w") as f:
    json.dump({"trainedWords": ["aurelia_lt, silver hair", "Aurelia_LT"]}, f)
lora_name = os.path.join("chars", "aurelia_v2.safetensors")
check(chars.trained_words(lora_name) == ["aurelia_lt", "silver hair"], "trained_words: from its metadata, split on commas, as trained, none twice")
before_lora = cs.changed_at(node_mod.resolve(cid), "lora")
c = chars.set_lora(cid, lora_name)
check(c["lora"] == {"name": lora_name, "trigger": ["aurelia_lt", "silver hair"]} and cs.changed_at(c, "lora") > before_lora,
      "set_lora: linked, its trigger words from its metadata, the change stamped (for the Gallery)")
check(chars.set_lora(cid, lora_name, ["aurelia_lt"])["lora"]["trigger"] == ["aurelia_lt"], "set_lora: trigger words you chose")
check(chars.set_lora(cid, "chars/Aurelia_v2.safetensors")["lora"]["name"] == lora_name, "set_lora: a name with / (the Library's) or any case, as ComfyUI names it")
for bad, err in ((("chr_gone", lora_name), LookupError), ((cid, "not_there.safetensors"), ValueError)):
    try:
        chars.set_lora(*bad)
        check(False, f"set_lora: {err.__name__}")
    except err:
        check(True, f"set_lora: {err.__name__} for {bad[1] if err is ValueError else 'a missing character'}")
check(chars.set_lora(cid, "")["lora"] is None, "set_lora: unlinked")

# ---------------------------------------------------------------- random picks
give_lora("", [])
seen = {run(random_character=True, seed=s)[1] for s in range(40)}
check(seen == {"Aurelia", "Nova"}, f"random character: any of them, by seed ({seen})")
check(run(random_character=True, seed=7)[0] == run(random_character=True, seed=7)[0], "  the same seed, the same pick")
check(N.VALIDATE_INPUTS(character="Somebody", random_character=True) is True, "  a missing picked character doesn't stop a random run")
outfits = {run(random_outfit=True, seed=s, outfit="")[0].split(", ")[-1] for s in range(40)}
check(outfits == {"straw hat", "red coat"}, f"random outfit: one of the character's outfits, by seed ({outfits})")
nova_out = [run(random_character=True, outfit="winter", seed=s) for s in range(40)]
check(all(n[0] == "nova" for n in nova_out if n[1] == "Nova"), "  a character without that outfit: its own first one (none here)")
check(N.IS_CHANGED(random_character=True) != N.IS_CHANGED(character="Aurelia", character_id=cid), "IS_CHANGED: picking at random, the whole list counts")

# ---------------------------------------------------------------- the picker's route
try:
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
except ImportError:
    web = None
    print("skip: aiohttp not installed")
if web:
    from smf.routes import characters_routes

    async def routes_check():
        rt = web.RouteTableDef()
        characters_routes.register(rt)
        app = web.Application()
        app.add_routes(rt)
        c = TestClient(TestServer(app))
        await c.start_server()
        try:
            r = await c.get("/sm-fetcher/characters")
            got = (await r.json())["characters"]
            check([x["name"] for x in got] == ["Aurelia", "Nova"] and got[0]["outfits"] == {"default": ["white dress", "straw hat"], "winter": ["red coat"]}
                  and got[0]["has_image"] is False and "source" not in got[0], "GET characters: every character, A to Z, with its tags and outfits")
        finally:
            await c.close()
    asyncio.run(routes_check())

check(smf.character_node.NODE_CLASS_MAPPINGS == {"MLCharacterSelect": N}, "the node is registered as MLCharacterSelect")
print(f"\n{'all passed' if not check.failed else f'{check.failed} failed'}")
sys.exit(1 if check.failed else 0)
