"""The Gallery Info node: its entry, the caps, the folder pattern, and how it reaches the saved file."""
import datetime
import json
import os
import sys
import types

import test_shared as T

check = T.check

PLUGIN = T.PLUGIN
if PLUGIN not in sys.path:
    sys.path.insert(0, PLUGIN)
fp = types.ModuleType("folder_paths")
fp.get_full_path = lambda folder, name: None
sys.modules.setdefault("folder_paths", fp)

from smf import gallery_node as G  # noqa: E402

GRAPH = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "SDXL\\sample_xl_base.safetensors"}},
    "2": {"class_type": "LoraLoader", "inputs": {"model": ["1", 0], "clip": ["1", 1], "lora_name": "aurelia_v3.safetensors", "strength_model": 0.65, "strength_clip": 0.5}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": "a lighthouse"}},
    "4": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["3", 0], "negative": ["3", 0], "seed": 1, "steps": 8, "cfg": 1,
                                             "sampler_name": "euler", "scheduler": "simple", "latent_image": ["5", 0]}},
    "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 512, "height": 512, "batch_size": 1}},
    "6": {"class_type": "MLGalleryInfo", "inputs": {"images": ["7", 0], "tags": "dusk, coast"}},
}

# ---------------------------------------------------------------- the entry
e = G.entry(albums="Coast, coast, Night", tags=[f"t{i}" for i in range(80)], characters="Aurelia", project="Lighthouses",
            rating=7, favourite=True, note="n" * 5000, prompt=GRAPH, workflow_name="lighthouse.json", ml_version="1.22.0")
check(e["v"] == 1, "entry: version 1")
check(e["albums"] == ["Coast", "Night"], "albums: split on commas, duplicates (any case) dropped")
check(len(e["tags"]) == 64 and len(e["note"]) == 2048, "tags capped at 64, the note at 2 KB")
check(e["rating"] is None, "a rating outside 1-5 is no rating")
check(e["favourite"] is True and e["characters"] == ["Aurelia"] and e["project"] == "Lighthouses", "favourite, characters, project")
check(e["models"]["checkpoint"] == [{"name": "SDXL\\sample_xl_base.safetensors", "sha256": None}], "the checkpoint that ran (no hash known: none, not computed)")
check(e["models"]["loras"] == [{"name": "aurelia_v3.safetensors", "model": 0.65, "clip": 0.5, "sha256": None}], "the LoRA with both strengths")
check(e["source"] == {"ml": "1.22.0", "workflow": "lighthouse.json"}, "source: Model Librarian's version and the workflow")
check(G.entry(rating="x")["rating"] is None and G.entry(prompt="not a graph")["models"] == {"checkpoint": [], "loras": []}, "bad inputs don't fail")
json.dumps(e)  # it's written into the file as JSON

# hashes: only ones Model Librarian already has
orig = G.hashing.cached
fp.get_full_path = lambda folder, name: f"C:/models/{folder}/{name}"
G.hashing.cached = lambda path: "abc123" if path.endswith("aurelia_v3.safetensors") and "/loras/" in path else None
e2 = G.entry(prompt=GRAPH)
check(e2["models"]["loras"][0]["sha256"] == "abc123" and e2["models"]["checkpoint"][0]["sha256"] is None, "known hashes are included")
G.hashing.cached = orig
fp.get_full_path = lambda folder, name: None

# ---------------------------------------------------------------- the folder pattern
day = datetime.datetime(2026, 10, 23, 14, 5)
check(G.folder_prefix("{project}/{character}/{date}/", "img", e, day) == "Lighthouses/Aurelia/2026-10-23/img", "the pattern's folders, then the name")
check(G.folder_prefix("", "img", e, day) == "img", "no pattern: just the name")
check(G.folder_prefix("{project}/{tag}", "", G.entry(project="P"), day) == "P/ComfyUI", "an empty placeholder's folder drops out; no name: ComfyUI")
check(G.folder_prefix("../../{project}/C:/x", "a", G.entry(project='Bad<>:"|?*Name'), day) == "BadName/C/x/a", "no climbing out, no drive letters, no characters Windows refuses")
check(G.folder_prefix("{model}/{year}-{month}/{rating}", "a", G.entry(prompt=GRAPH, rating=4), day) == "sample_xl_base/2026-10/4/a", "{model} {year} {month} {rating}")
check(G.folder_prefix("{unknown}/x", "a", e, day) == "{unknown}/x/a", "an unknown placeholder stays as typed")
check(G.folder_prefix("{characters}", "a", G.entry(characters="A, B"), day) == "A & B/a", "{characters}: all of them")

# ---------------------------------------------------------------- the node
node = G.GalleryInfo()
extra = {"workflow": {"nodes": []}}
images = object()
out = node.run(images, tags="dusk", rating=3, folder_pattern="{tag}", filename="x", prompt=GRAPH, extra_pnginfo=extra)
check(out[0] is images, "images pass through unchanged")
check(out[1] == "dusk/x", "filename_prefix from the pattern")
check(extra["mlgallery"]["tags"] == ["dusk"] and extra["mlgallery"]["rating"] == 3 and "workflow" in extra, "the entry joins the metadata the save node writes")
check(node.run(images, extra_pnginfo=None)[0] is images, "no metadata dict (ComfyUI started with --disable-metadata): still passes through")
types_ = G.GalleryInfo.INPUT_TYPES()
check(set(types_["optional"]) >= {"albums", "tags", "characters", "project", "rating", "favourite", "note", "folder_pattern", "filename", "workflow_name"},
      "every field is an input (each can be wired from another node)")
check(types_["hidden"] == {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"} and G.GalleryInfo.RETURN_TYPES == ("IMAGE", "STRING"), "hidden inputs and outputs")
check("MLGalleryInfo" in G.NODE_CLASS_MAPPINGS, "registered as MLGalleryInfo (the Gallery looks for this name)")

# the save node writes it: as ComfyUI's Save Image does, every extra_pnginfo key becomes a text chunk
try:
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    import tempfile
    info = PngInfo()
    for k, v in extra.items():
        info.add_text(k, json.dumps(v))
    path = os.path.join(tempfile.mkdtemp(), "saved.png")
    Image.new("RGB", (8, 8)).save(path, pnginfo=info)
    from smf import imagemeta
    with open(path, "rb") as f:
        text = imagemeta.read(f.read())["text"]
    check(json.loads(text["mlgallery"])["tags"] == ["dusk"], "the entry reads back from a saved PNG")
except ImportError:
    print("skip: Pillow not installed")

print(f"\n{'all passed' if not check.failed else f'{check.failed} failed'}")
sys.exit(1 if check.failed else 0)
