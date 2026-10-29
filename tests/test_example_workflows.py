"""example_workflows/: the files are what tools/example_workflows.py makes, their wiring holds together, the Model
Librarian nodes' saved values fit the nodes' inputs, the model loaders carry checked download links, each has a
thumbnail, and the installer ships them."""
import importlib.util
import json
import os
import sys

import test_shared as T

check = T.check

spec = importlib.util.spec_from_file_location("ml_examples", os.path.join(T.PLUGIN, "tools", "example_workflows.py"))
ex = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ex)

base, user = T.fake_install("EXAMPLES")
smf = T.load_smf(base, user)
import smf.character_node  # noqa: E402
import smf.gallery_node  # noqa: E402

SOCKET_TYPES = {"IMAGE", "MODEL", "CLIP", "LATENT", "VAE", "CONDITIONING"}


def widget_count(node_cls) -> int:
    """The widgets a node saves: its inputs that aren't sockets, plus the seed's control_after_generate."""
    n = 0
    for group in ("required", "optional"):
        for typ, opts in (node_cls.INPUT_TYPES().get(group) or {}).values():
            if typ in SOCKET_TYPES or (opts or {}).get("forceInput"):
                continue
            n += 1 + bool((opts or {}).get("control_after_generate"))
    return n


EXTRA = {"MLCharacterSelect": 1}  # the picker's panel (character_view), added by js/lib/characters.js
NODES = {"MLCharacterSelect": smf.character_node.CharacterSelect, "MLGalleryInfo": smf.gallery_node.GalleryInfo}

check(set(ex.WORKFLOWS) == {os.path.splitext(f)[0] for f in os.listdir(ex.OUT) if f.endswith(".json")},
      "one file per workflow in example_workflows/, none left over")
for name, make in ex.WORKFLOWS.items():
    path = os.path.join(ex.OUT, name + ".json")
    with open(path, encoding="utf-8") as f:
        wf = json.load(f)
    check(wf == json.loads(json.dumps(make())), f"{name}: the file is what the generator makes (run tools/example_workflows.py)")
    nodes = {n["id"]: n for n in wf["nodes"]}
    ok = True
    for lid, a, aslot, b, bslot, kind in wf["links"]:
        ok &= lid in nodes[a]["outputs"][aslot]["links"] and nodes[b]["inputs"][bslot]["link"] == lid
        ok &= kind == nodes[a]["outputs"][aslot]["type"]
    check(ok and wf["last_link_id"] == len(wf["links"]) and wf["last_node_id"] == max(nodes), f"{name}: every link is held at both ends")
    unwired = [f"{n['type']}.{i['name']}" for n in nodes.values() for i in n["inputs"]
               if i["link"] is None and i["name"] not in ("before", "after", "model", "clip")]
    check(not unwired, f"{name}: every required input is wired {unwired or ''}")
    for n in nodes.values():
        if n["type"] in NODES:
            want = widget_count(NODES[n["type"]]) + EXTRA.get(n["type"], 0)
            check(len(n["widgets_values"]) == want, f"{name}: {n['type']} saves {want} values ({len(n['widgets_values'])})")
    loaders = [n for n in nodes.values() if n["type"] in ("CheckpointLoaderSimple", "UpscaleModelLoader")]
    check(loaders and all(len(n["properties"].get("models") or []) == 1 and n["properties"]["models"][0]["name"] == n["widgets_values"][0]
                          for n in loaders), f"{name}: each model loader carries the link to the file it loads")
    check(all(m["url"].startswith("https://huggingface.co/") and len(m["hash"]) == 64 and m["hash_type"] == "SHA256"
              for n in loaders for m in n["properties"]["models"]), f"{name}: links are HuggingFace https, with a SHA256")
    check(any(n["type"] == "MLGalleryInfo" for n in nodes.values()) and any(n["type"] == "MarkdownNote" for n in nodes.values()),
          f"{name}: has Gallery Info and a note on how to use it")
    check(all("<" not in n["widgets_values"][0] for n in nodes.values() if n["type"] == "MarkdownNote"),
          f"{name}: no <...> in the note (the Markdown note reads it as HTML and drops it)")
    thumb = os.path.join(ex.OUT, name + ".jpg")
    check(os.path.isfile(thumb) and 5_000 < os.path.getsize(thumb) < 200_000, f"{name}: has a thumbnail")

spec = importlib.util.spec_from_file_location("ml_install", os.path.join(T.PLUGIN, "tools", "install.py"))
inst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inst)
check("example_workflows" in inst.INCLUDE, "tools/install.py installs example_workflows/")

print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
sys.exit(1 if check.failed else 0)
