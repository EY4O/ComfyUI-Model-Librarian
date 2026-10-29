"""Build the workflows in example_workflows/ (ComfyUI's Templates browser lists them under Model Librarian).

    python tools/example_workflows.py                          # write every workflow
    python tools/example_workflows.py --thumb NAME render.png  # its thumbnail (NAME.jpg) from a render

Each workflow is made here rather than saved from the editor, so a change to a node's inputs is one edit and
tests/test_example_workflows.py can check the files against the nodes. The model loaders carry their download links
(properties.models, as ComfyUI's own templates do): opened on a fresh install, ComfyUI and Model Librarian's Workflow
tab both offer to fetch them.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(REPO, "example_workflows")

CHECKPOINT = {"name": "Illustrious-XL-v2.0.safetensors", "directory": "checkpoints",
              "url": "https://huggingface.co/OnomaAIResearch/Illustrious-XL-v2.0/resolve/main/Illustrious-XL-v2.0.safetensors",
              "hash": "c2a1a3eaa13d4c107dc7e00c3fe830cab427aa026362740ea094745b3422a331", "hash_type": "SHA256"}
UPSCALER = {"name": "4x-AnimeSharp.safetensors", "directory": "upscale_models",
            "url": "https://huggingface.co/Kim2091/AnimeSharp/resolve/main/4x-AnimeSharp.safetensors",
            "hash": "7fc60054d291579acac4fb537efd91c80611cbd281ef8b90f434048cc1313b39", "hash_type": "SHA256"}

QUALITY = "masterpiece, best quality, very aesthetic, absurdres, "
NEGATIVE = ("lowres, worst quality, low quality, bad anatomy, bad hands, extra digits, fewer digits, blurry, "
            "jpeg artifacts, signature, watermark, username, text")

# (input sockets, output sockets) of each node used; a widget wired from another node is linked by its name
SOCKETS = {
    "CheckpointLoaderSimple": ([], [("MODEL", "MODEL"), ("CLIP", "CLIP"), ("VAE", "VAE")]),
    "CLIPTextEncode": ([("clip", "CLIP")], [("CONDITIONING", "CONDITIONING")]),
    "EmptyLatentImage": ([], [("LATENT", "LATENT")]),
    "KSampler": ([("model", "MODEL"), ("positive", "CONDITIONING"), ("negative", "CONDITIONING"), ("latent_image", "LATENT")],
                 [("LATENT", "LATENT")]),
    "VAEDecode": ([("samples", "LATENT"), ("vae", "VAE")], [("IMAGE", "IMAGE")]),
    "VAEEncode": ([("pixels", "IMAGE"), ("vae", "VAE")], [("LATENT", "LATENT")]),
    "UpscaleModelLoader": ([], [("UPSCALE_MODEL", "UPSCALE_MODEL")]),
    "ImageUpscaleWithModel": ([("upscale_model", "UPSCALE_MODEL"), ("image", "IMAGE")], [("IMAGE", "IMAGE")]),
    "ImageScaleBy": ([("image", "IMAGE")], [("IMAGE", "IMAGE")]),
    "SaveImage": ([("images", "IMAGE")], []),
    "PrimitiveStringMultiline": ([], [("STRING", "STRING")]),
    "MarkdownNote": ([], []),
    "MLCharacterSelect": ([("model", "MODEL"), ("clip", "CLIP"), ("before", "STRING"), ("after", "STRING")],
                          [("prompt", "STRING"), ("character", "STRING"), ("model", "MODEL"), ("clip", "CLIP")]),
    "MLGalleryInfo": ([("images", "IMAGE")], [("images", "IMAGE"), ("filename_prefix", "STRING")]),
}
WIDGET_TYPES = {"text": "STRING", "characters": "STRING", "filename_prefix": "STRING"}  # widgets wired from another node


class Graph:
    def __init__(self):
        self.nodes, self.links = [], []

    def node(self, ntype, pos, size, values, title=None, models=None, color=None):
        ins, outs = SOCKETS[ntype]
        n = {"id": len(self.nodes) + 1, "type": ntype, "pos": list(pos), "size": list(size), "flags": {}, "order": len(self.nodes),
             "mode": 0, "inputs": [{"name": k, "type": t, "link": None} for k, t in ins],
             "outputs": [{"name": k, "type": t, "links": []} for k, t in outs],
             "properties": {"Node name for S&R": ntype}}
        if values:  # (the editor leaves it out for a node without widgets)
            n["widgets_values"] = values
        if title:
            n["title"] = title
        if models:
            n["properties"]["models"] = models
        if color:
            n["color"], n["bgcolor"] = color
        self.nodes.append(n)
        return n

    def wire(self, a, out, b, inp):
        """a's output named out into b's input (or widget) named inp."""
        slot = next(i for i, o in enumerate(a["outputs"]) if o["name"] == out)
        target = next((i for i, x in enumerate(b["inputs"]) if x["name"] == inp), None)
        if target is None:  # a widget: it gets an input of its own
            b["inputs"].append({"name": inp, "type": WIDGET_TYPES[inp], "widget": {"name": inp}, "link": None})
            target = len(b["inputs"]) - 1
        lid = len(self.links) + 1
        kind = a["outputs"][slot]["type"]
        b["inputs"][target]["link"] = lid
        a["outputs"][slot]["links"].append(lid)
        self.links.append([lid, a["id"], slot, b["id"], target, kind])

    def json(self, scale=0.6, offset=(640, 40)):
        for n in self.nodes:  # (the editor writes slot_index on outputs in use)
            for i, o in enumerate(n["outputs"]):
                if o["links"]:
                    o["slot_index"] = i
        return {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, json.dumps(self.links))), "revision": 0,
                "last_node_id": len(self.nodes), "last_link_id": len(self.links), "nodes": self.nodes, "links": self.links,
                "groups": [], "config": {}, "extra": {"ds": {"scale": scale, "offset": list(offset)}}, "version": 0.4}


def character_select(g, pos, random=False):
    # character, outfit, include_character, include_series, include_appearance, include_outfit, lora_strength,
    # character_id, off_tags, random_character, random_outfit, seed (+ its control), character_view (the picker's panel)
    return g.node("MLCharacterSelect", pos, (340, 470),
                  ["", "", True, False, True, True, 1.0, "", "", random, random, 0, "randomize" if random else "fixed", ""])


def gallery_info(g, pos, albums="", tags="", project="", pattern=""):
    # albums, tags, characters, project, rating, favourite, note, folder_pattern, filename, workflow_name
    return g.node("MLGalleryInfo", pos, (320, 330), [albums, tags, "", project, 0, False, "", pattern, "ComfyUI", ""])


def text(g, pos, value, title):
    return g.node("PrimitiveStringMultiline", pos, (320, 120), [value], title=title)


def note(g, md):
    """In a column of its own on the left: Character Select grows to fit a character's tags, so nothing sits below it."""
    return g.node("MarkdownNote", (-600, 160), (560, 460), [md], title="How to use it", color=("#432", "#653"))


def sampler(g, pos, seed_mode="randomize", denoise=1.0, steps=28):
    return g.node("KSampler", pos, (300, 262), [0, seed_mode, steps, 5.5, "euler_ancestral", "normal", denoise])


PICK = ("1. **Pick a character**: click the name on **Character Select**. Characters come from **+ Character** in "
        "Model Librarian for Chrome on a Danbooru, Gelbooru, Safebooru or e621 post, or from Model Librarian Gallery.\n")
FETCH = ("**Missing {what}?** Model Librarian shows a notice when the workflow opens: **Workflow → Find all sources → "
         "Download** fetches {them} from HuggingFace, SHA256-verified.\n")


def character_portrait() -> dict:
    g = Graph()
    ck = g.node("CheckpointLoaderSimple", (0, 160), (320, 100), [CHECKPOINT["name"]], models=[CHECKPOINT])
    before = text(g, (0, 320), QUALITY + "1girl, solo,", "Before the character")
    after = text(g, (0, 480), "upper body, smile, looking at viewer, outdoors, cherry blossoms, falling petals, blue sky, "
                              "depth of field", "After the character (the scene)")
    cs = character_select(g, (370, 160))
    pos = g.node("CLIPTextEncode", (760, 160), (320, 120), [""], title="Positive")
    neg = g.node("CLIPTextEncode", (760, 330), (320, 140), [NEGATIVE], title="Negative")
    lat = g.node("EmptyLatentImage", (760, 520), (320, 110), [832, 1216, 1])
    ks = sampler(g, (1120, 160))
    dec = g.node("VAEDecode", (1120, 470), (220, 50), [])
    gi = gallery_info(g, (1460, 160), albums="Characters", project="Character portraits", pattern="{project}/{character}")
    save = g.node("SaveImage", (1820, 160), (420, 640), ["ComfyUI"])
    note(g, "## Character portrait\n\n" + PICK +
         "2. **Run.** Its tags, its outfit and anything wired into *before* and *after* make the prompt. When the "
         "character has a LoRA linked, it loads through the model and clip wires.\n"
         "3. **Gallery Info** tags the picture with the character and saves it in *Character portraits*, in a folder for "
         "each character, for Model Librarian Gallery.\n\n" + FETCH.format(what="the checkpoint", them="Illustrious XL v2.0 (6.9 GB)"))
    g.wire(ck, "MODEL", cs, "model"); g.wire(ck, "CLIP", cs, "clip")
    g.wire(before, "STRING", cs, "before"); g.wire(after, "STRING", cs, "after")
    g.wire(cs, "clip", pos, "clip"); g.wire(cs, "prompt", pos, "text"); g.wire(cs, "clip", neg, "clip")
    g.wire(cs, "model", ks, "model"); g.wire(pos, "CONDITIONING", ks, "positive"); g.wire(neg, "CONDITIONING", ks, "negative")
    g.wire(lat, "LATENT", ks, "latent_image")
    g.wire(ks, "LATENT", dec, "samples"); g.wire(ck, "VAE", dec, "vae")
    g.wire(dec, "IMAGE", gi, "images"); g.wire(cs, "character", gi, "characters")
    g.wire(gi, "images", save, "images"); g.wire(gi, "filename_prefix", save, "filename_prefix")
    return g.json()


def random_character_batch() -> dict:
    g = Graph()
    ck = g.node("CheckpointLoaderSimple", (0, 160), (320, 100), [CHECKPOINT["name"]], models=[CHECKPOINT])
    before = text(g, (0, 320), QUALITY + "1girl, solo,", "Before the character")
    after = text(g, (0, 480), "cowboy shot, smile, looking at viewer, city street, night, neon lights, bokeh",
                 "After the character (the scene)")
    cs = character_select(g, (370, 160), random=True)
    pos = g.node("CLIPTextEncode", (760, 160), (320, 120), [""], title="Positive")
    neg = g.node("CLIPTextEncode", (760, 330), (320, 140), [NEGATIVE], title="Negative")
    lat = g.node("EmptyLatentImage", (760, 520), (320, 110), [832, 1216, 1])
    ks = sampler(g, (1120, 160))
    dec = g.node("VAEDecode", (1120, 470), (220, 50), [])
    gi = gallery_info(g, (1460, 160), albums="Characters", project="Random characters", pattern="{project}/{character}/{date}")
    save = g.node("SaveImage", (1820, 160), (420, 640), ["ComfyUI"])
    note(g, "## Random character batch\n\n"
         "1. **Set the run count** (next to **Run**) to how many pictures you want, say 8, and run. Each run picks one of "
         "your characters and one of its outfits at random, from Character Select's seed.\n"
         "2. **Gallery Info** saves each picture in *Random characters*, in a folder for each character and day, tagged "
         "with the character, so the batch arrives sorted in Model Librarian Gallery.\n\n"
         "Characters come from **+ Character** in Model Librarian for Chrome on a booru post, or from Model Librarian Gallery. "
         "Turn **random_character** off and click the name to pick one.\n\n"
         + FETCH.format(what="the checkpoint", them="Illustrious XL v2.0 (6.9 GB)"))
    g.wire(ck, "MODEL", cs, "model"); g.wire(ck, "CLIP", cs, "clip")
    g.wire(before, "STRING", cs, "before"); g.wire(after, "STRING", cs, "after")
    g.wire(cs, "clip", pos, "clip"); g.wire(cs, "prompt", pos, "text"); g.wire(cs, "clip", neg, "clip")
    g.wire(cs, "model", ks, "model"); g.wire(pos, "CONDITIONING", ks, "positive"); g.wire(neg, "CONDITIONING", ks, "negative")
    g.wire(lat, "LATENT", ks, "latent_image")
    g.wire(ks, "LATENT", dec, "samples"); g.wire(ck, "VAE", dec, "vae")
    g.wire(dec, "IMAGE", gi, "images"); g.wire(cs, "character", gi, "characters")
    g.wire(gi, "images", save, "images"); g.wire(gi, "filename_prefix", save, "filename_prefix")
    return g.json()


def gallery_info_starter() -> dict:
    g = Graph()
    ck = g.node("CheckpointLoaderSimple", (0, 160), (320, 100), [CHECKPOINT["name"]], models=[CHECKPOINT])
    pos = g.node("CLIPTextEncode", (370, 160), (360, 160), [QUALITY + "scenery, no humans, lighthouse, cliff, ocean, waves, "
                                                            "sunset, orange sky, clouds, birds, wide shot"], title="Positive")
    neg = g.node("CLIPTextEncode", (370, 370), (360, 140), [NEGATIVE], title="Negative")
    lat = g.node("EmptyLatentImage", (370, 560), (360, 110), [1216, 832, 1])
    ks = sampler(g, (780, 160))
    dec = g.node("VAEDecode", (780, 470), (220, 50), [])
    gi = gallery_info(g, (1120, 160), albums="Scenery", tags="lighthouse, sunset", project="My project",
                      pattern="{project}/{date}")
    save = g.node("SaveImage", (1480, 160), (560, 420), ["ComfyUI"])
    note(g, "## Gallery Info starter\n\n"
         "**Gallery Info** goes just before the save node. What you fill in rides along in the picture for Model Librarian "
         "Gallery: albums, tags, characters, a project, a rating, favourite and a note.\n\n"
         "- **folder_pattern** saves into folders: wire *filename_prefix* into the save node (as here). Try "
         "*{project}/{album}/{date}*, or leave it empty for no folders.\n"
         "- Your own rating and favourite in the Gallery win over the node's.\n\n"
         + FETCH.format(what="the checkpoint", them="Illustrious XL v2.0 (6.9 GB)"))
    g.wire(ck, "CLIP", pos, "clip"); g.wire(ck, "CLIP", neg, "clip")
    g.wire(ck, "MODEL", ks, "model"); g.wire(pos, "CONDITIONING", ks, "positive"); g.wire(neg, "CONDITIONING", ks, "negative")
    g.wire(lat, "LATENT", ks, "latent_image")
    g.wire(ks, "LATENT", dec, "samples"); g.wire(ck, "VAE", dec, "vae")
    g.wire(dec, "IMAGE", gi, "images")
    g.wire(gi, "images", save, "images"); g.wire(gi, "filename_prefix", save, "filename_prefix")
    return g.json()


def hires_character_portrait() -> dict:
    g = Graph()
    ck = g.node("CheckpointLoaderSimple", (0, 160), (320, 100), [CHECKPOINT["name"]], models=[CHECKPOINT])
    up = g.node("UpscaleModelLoader", (0, 300), (320, 60), [UPSCALER["name"]], models=[UPSCALER])
    before = text(g, (0, 400), QUALITY + "1girl, solo,", "Before the character")
    after = text(g, (0, 560), "portrait, close-up, smile, looking at viewer, night, starry sky, glowing particles, detailed eyes",
                 "After the character (the scene)")
    cs = character_select(g, (370, 160))
    pos = g.node("CLIPTextEncode", (760, 160), (320, 120), [""], title="Positive")
    neg = g.node("CLIPTextEncode", (760, 330), (320, 140), [NEGATIVE], title="Negative")
    lat = g.node("EmptyLatentImage", (760, 520), (320, 110), [832, 1216, 1])
    ks = sampler(g, (1120, 160), seed_mode="fixed")
    dec = g.node("VAEDecode", (1120, 470), (220, 50), [])
    big = g.node("ImageUpscaleWithModel", (1120, 570), (240, 50), [])
    half = g.node("ImageScaleBy", (1120, 670), (260, 82), ["lanczos", 0.375], title="Down to 1.5×")
    enc = g.node("VAEEncode", (1120, 800), (220, 50), [])
    ks2 = sampler(g, (1460, 160), seed_mode="fixed", denoise=0.4, steps=20)
    ks2["title"] = "KSampler (hires pass)"
    dec2 = g.node("VAEDecode", (1460, 470), (220, 50), [])
    gi = gallery_info(g, (1800, 160), albums="Characters", tags="hires", project="Character portraits",
                      pattern="{project}/{character}")
    save = g.node("SaveImage", (2160, 160), (420, 640), ["ComfyUI"])
    note(g, "## Hires character portrait\n\n" + PICK +
         "2. **Run.** The picture is made at 832×1216, enlarged with 4x-AnimeSharp, brought down to 1.5× (1248×1824) and "
         "sampled again at 0.4 denoise for the detail. The seed is fixed: change it for another picture, and only the hires "
         "pass runs again when you change its settings.\n"
         "3. **Gallery Info** saves it in *Character portraits*, in a folder for each character, tagged with the character.\n\n"
         + FETCH.format(what="its models", them="Illustrious XL v2.0 (6.9 GB) and 4x-AnimeSharp (33 MB)"))
    g.wire(ck, "MODEL", cs, "model"); g.wire(ck, "CLIP", cs, "clip")
    g.wire(before, "STRING", cs, "before"); g.wire(after, "STRING", cs, "after")
    g.wire(cs, "clip", pos, "clip"); g.wire(cs, "prompt", pos, "text"); g.wire(cs, "clip", neg, "clip")
    g.wire(cs, "model", ks, "model"); g.wire(pos, "CONDITIONING", ks, "positive"); g.wire(neg, "CONDITIONING", ks, "negative")
    g.wire(lat, "LATENT", ks, "latent_image")
    g.wire(ks, "LATENT", dec, "samples"); g.wire(ck, "VAE", dec, "vae")
    g.wire(up, "UPSCALE_MODEL", big, "upscale_model"); g.wire(dec, "IMAGE", big, "image")
    g.wire(big, "IMAGE", half, "image")
    g.wire(half, "IMAGE", enc, "pixels"); g.wire(ck, "VAE", enc, "vae")
    g.wire(cs, "model", ks2, "model"); g.wire(pos, "CONDITIONING", ks2, "positive"); g.wire(neg, "CONDITIONING", ks2, "negative")
    g.wire(enc, "LATENT", ks2, "latent_image")
    g.wire(ks2, "LATENT", dec2, "samples"); g.wire(ck, "VAE", dec2, "vae")
    g.wire(dec2, "IMAGE", gi, "images"); g.wire(cs, "character", gi, "characters")
    g.wire(gi, "images", save, "images"); g.wire(gi, "filename_prefix", save, "filename_prefix")
    return g.json(scale=0.5)


# file name (the title in the Templates browser) -> workflow
WORKFLOWS = {
    "Character Portrait": character_portrait,
    "Random Character Batch": random_character_batch,
    "Hires Character Portrait": hires_character_portrait,
    "Gallery Info Starter": gallery_info_starter,
}


def thumb(name: str, src: str) -> str:
    """example_workflows/<name>.jpg from a render: 512 px on its long side (the browser's cards are smaller)."""
    from PIL import Image

    if name not in WORKFLOWS:
        raise SystemExit(f"No workflow named {name} ({', '.join(WORKFLOWS)})")
    im = Image.open(src).convert("RGB")
    im.thumbnail((512, 512), Image.LANCZOS)
    dest = os.path.join(OUT, name + ".jpg")
    im.save(dest, "JPEG", quality=88, optimize=True, progressive=True)  # (no metadata: a JPEG from PIL carries none)
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--thumb", nargs=2, metavar=("NAME", "IMAGE"), help="make NAME.jpg from a render")
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    if a.thumb:
        print("wrote", thumb(*a.thumb))
        return
    for name, make in WORKFLOWS.items():
        with open(os.path.join(OUT, name + ".json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(make(), f, indent=2, ensure_ascii=False)
            f.write("\n")
        print("wrote", f"example_workflows/{name}.json")


if __name__ == "__main__":
    sys.exit(main())
