"""Gallery Info: a node that tags what a workflow makes, for Model Librarian Gallery.

Put it just before the save node: images in, the same images out. When it runs it adds one `mlgallery`
entry to ComfyUI's shared metadata (extra_pnginfo), which every save node writes into the file with the
prompt and workflow: Save Image as a PNG text chunk, Save Video / Save WEBM as container tags, Video
Combine (Video Helper Suite) in both. The Gallery reads it to file the image under its albums, tags and
characters straight away. Its `filename_prefix` output, built from a folder pattern, saves each file
straight into its folder when wired into the save node's prefix.

The entry's format (v1) is written down in the Gallery's docs/PLAN.md; keep the two in step.
"""
from __future__ import annotations

import datetime
import re

from . import hashing, recipe_parse

VERSION = 1
CAPS = {"albums": 16, "tags": 64, "characters": 16}
TEXT_CAP, NOTE_CAP = 100, 2048
_BAD = re.compile(r'[<>:"|?*\x00-\x1f]')  # characters Windows refuses in a file or folder name


def split(v, cap: int) -> list[str]:
    """'a, b\\nc' or a list -> up to cap distinct, trimmed names."""
    items = v if isinstance(v, list) else re.split(r"[,\n]", v) if isinstance(v, str) else []
    out, seen = [], set()
    for x in items:
        x = str(x).strip()[:TEXT_CAP]
        if x and x.lower() not in seen:
            seen.add(x.lower())
            out.append(x)
    return out[:cap]


def _models(prompt) -> dict:
    """The checkpoint and LoRAs that ran (from the API graph), with hashes Model Librarian already knows."""
    try:
        rec = recipe_parse.parse_comfy_prompt(prompt) if isinstance(prompt, dict) else None
    except Exception:
        rec = None
    if not rec:
        return {"checkpoint": [], "loras": []}

    def sha(folder: str, name):
        try:
            import folder_paths
            full = folder_paths.get_full_path(folder, name) if name else None
        except Exception:
            full = None
        return hashing.cached(full) if full else None  # never hashes here: a run mustn't wait for that

    m = rec.get("model")
    ckpt = []
    if m and m.get("file"):
        folder = "diffusion_models" if m.get("type") == "unet" else "checkpoints"
        ckpt.append({"name": m["file"], "sha256": sha(folder, m["file"])})
    loras = [{"name": l["file"], "model": l.get("weight"), "clip": l.get("clip_weight"), "sha256": sha("loras", l["file"])}
             for l in rec.get("loras") or [] if l.get("file")]
    return {"checkpoint": ckpt, "loras": loras}


def entry(albums="", tags="", characters="", project="", rating=0, favourite=False, note="", prompt=None, workflow_name="", ml_version=None) -> dict:
    try:
        r = int(rating or 0)
    except (TypeError, ValueError):
        r = 0
    return {
        "v": VERSION,
        "albums": split(albums, CAPS["albums"]), "tags": split(tags, CAPS["tags"]), "characters": split(characters, CAPS["characters"]),
        "project": str(project or "").strip()[:TEXT_CAP],
        "rating": r if 1 <= r <= 5 else None,
        "favourite": bool(favourite),
        "note": str(note or "").strip()[:NOTE_CAP],
        "models": _models(prompt),
        "source": {"ml": ml_version, "workflow": str(workflow_name or "").strip()[:200] or None},
    }


def _segment(s: str) -> str:
    s = _BAD.sub("", s).replace("..", "").strip().strip(".").strip()
    return s[:80]


def folder_prefix(pattern: str, filename: str, e: dict, now: datetime.datetime | None = None) -> str:
    """The save node's filename_prefix: the pattern's folders (placeholders filled in, cleaned), then the name.

    {project} {character} {characters} {album} {tag} {model} {rating} {date} {year} {month} {day}"""
    now = now or datetime.datetime.now()
    ckpt = (e.get("models") or {}).get("checkpoint") or []
    model = re.sub(r"\.(safetensors|ckpt|pt|pth|gguf|sft)$", "", ckpt[0]["name"].replace("\\", "/").split("/")[-1], flags=re.I) if ckpt else ""
    values = {
        "project": e.get("project") or "", "character": (e.get("characters") or [""])[0], "characters": " & ".join(e.get("characters") or []),
        "album": (e.get("albums") or [""])[0], "tag": (e.get("tags") or [""])[0], "model": model,
        "rating": str(e["rating"]) if e.get("rating") else "", "date": now.strftime("%Y-%m-%d"),
        "year": now.strftime("%Y"), "month": now.strftime("%m"), "day": now.strftime("%d"),
    }
    filled = re.sub(r"\{(\w+)\}", lambda m: values.get(m.group(1).lower(), m.group(0)), pattern or "")
    parts = [p for p in (_segment(x) for x in re.split(r"[\\/]+", filled)) if p]  # empty ones (an unset placeholder) drop out
    name = _segment(filename or "") or "ComfyUI"
    return "/".join(parts + [name])


class GalleryInfo:
    """Tag what this workflow makes for Model Librarian Gallery, and optionally pick the folder it's saved in."""

    CATEGORY = "Model Librarian"
    FUNCTION = "run"
    RETURN_TYPES = ("IMAGE", "STRING")
    RETURN_NAMES = ("images", "filename_prefix")
    DESCRIPTION = ("Adds albums, tags, characters, a project, rating and note to the files the next save node writes, for Model Librarian "
                   "Gallery. Place it just before the save node. filename_prefix: wire it into the save node's prefix to save into "
                   "folders from the pattern.")

    @classmethod
    def INPUT_TYPES(cls):
        text = lambda tip, **kw: ("STRING", {"default": "", "tooltip": tip, **kw})  # noqa: E731
        return {
            "required": {"images": ("IMAGE", {"tooltip": "Passed through unchanged: connect the save node after this one."})},
            "optional": {
                "albums": text("Albums to file it under, separated by commas."),
                "tags": text("Tags, separated by commas."),
                "characters": text("Characters in it, separated by commas: the Gallery counts them as confirmed."),
                "project": text("A project name."),
                "rating": ("INT", {"default": 0, "min": 0, "max": 5, "tooltip": "1 to 5 stars (0: none). Your own rating in the Gallery wins."}),
                "favourite": ("BOOLEAN", {"default": False, "tooltip": "Mark it as a favourite (your own choice in the Gallery wins)."}),
                "note": text("A note.", multiline=True),
                "folder_pattern": text("Folders for filename_prefix, e.g. {project}/{character}/{date}/ "
                                       "(also {album} {tag} {model} {rating} {year} {month} {day}). Empty: no folders."),
                "filename": ("STRING", {"default": "ComfyUI", "tooltip": "The file name after the folders (the save node adds the number)."}),
                "workflow_name": ("STRING", {"default": "", "tooltip": "Filled in with the open workflow's name when you queue."}),
            },
            "hidden": {"prompt": "PROMPT", "extra_pnginfo": "EXTRA_PNGINFO"},
        }

    def run(self, images, albums="", tags="", characters="", project="", rating=0, favourite=False, note="", folder_pattern="",
            filename="ComfyUI", workflow_name="", prompt=None, extra_pnginfo=None):
        e = entry(albums, tags, characters, project, rating, favourite, note, prompt, workflow_name, _ml_version())
        if isinstance(extra_pnginfo, dict):  # the same dict the save node reads, later in this run
            extra_pnginfo["mlgallery"] = e
        return (images, folder_prefix(folder_pattern, filename, e))


def _ml_version() -> str | None:
    try:  # a plain read, not tomllib: Python 3.10 doesn't have it
        import os
        with open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pyproject.toml"), encoding="utf-8") as f:
            m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


NODE_CLASS_MAPPINGS = {"MLGalleryInfo": GalleryInfo}
NODE_DISPLAY_NAME_MAPPINGS = {"MLGalleryInfo": "Gallery Info (Model Librarian)"}
