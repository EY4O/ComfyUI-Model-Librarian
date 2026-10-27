"""Character Select: a node that turns one of your characters into prompt tags (and loads its LoRA).

The characters are the shared list (characters.json, see charstore.py) the Chrome extension fills from booru posts.
The node's picker (js/lib/characters.js) sets `character` (its name) and `character_id`, the outfit, and the tags you
turned off (`off_tags`); here they're read back from the list at run time, so an edit to the character shows in the
next run. Outputs: the prompt, the character's name for Gallery Info's `characters`, and model / clip with the
character's LoRA applied when they're wired in and it has one.
"""
from __future__ import annotations

import json
import os
import re

from . import characters, charstore


def escape(tag: str, spaces: bool = True) -> str:
    """A booru tag as a ComfyUI prompt takes it: spaces for underscores, and brackets that aren't read as weights.
    (A LoRA's trigger word keeps its underscores: it's written as it was trained.)"""
    t = re.sub(r"\s+", " ", str(tag or "").replace("_", " ") if spaces else str(tag or "")).strip()
    return re.sub(r"(?<!\\)([()])", r"\\\1", t)


def resolve(cid: str = "", name: str = "") -> dict:
    """The character by id, else by name (any case), else by its booru tag. ValueError when it isn't in the list."""
    found = characters.load()["characters"]
    by = (lambda c: c.get("id") == cid, lambda c: (c.get("name") or "").lower() == str(name).strip().lower(),
          lambda c: charstore.norm(c.get("tag")) == charstore.norm(name))
    for test in by:
        c = next((c for c in found if test(c)), None)
        if c and (cid or name):
            return c
    if not str(name).strip() and not cid:
        raise ValueError("Character Select: pick a character (click the node's character)")
    raise ValueError(f"Character Select: {name or cid} isn't in your characters any more")


def build(c: dict, outfit: str = "", include_character=True, include_series=False, include_appearance=True, include_outfit=True,
          off_tags="", before="", after="", with_trigger=False) -> str:
    """The prompt: what comes before, the LoRA's trigger words (when it's loaded), the character's tag, its series, its
    appearance and the outfit's tags, then what comes after. Tags turned off on the node are left out; none twice."""
    off = {charstore.norm(t) for t in re.split(r"[,\n]", off_tags or "") if t.strip()}
    tags: list[tuple[str, bool]] = []  # (tag, written with spaces)
    if with_trigger:
        tags += [(str(w), False) for w in ((c.get("lora") or {}).get("trigger") or [])]
    if include_character and c.get("tag"):
        tags.append((c["tag"], True))
    if include_series and c.get("series"):
        tags.append((str(c["series"]).lower(), True))
    if include_appearance:
        tags += [(t, True) for t in c.get("appearance") or []]
    if include_outfit and outfit:
        tags += [(t, True) for t in (c.get("outfits") or {}).get(outfit) or []]
    seen, out = set(), []
    for t, spaces in tags:
        k = charstore.norm(t)
        if k and k not in seen and k not in off:
            seen.add(k)
            out.append(escape(t, spaces))
    return ", ".join(x for x in [str(before or "").strip().strip(","), ", ".join(out), str(after or "").strip().strip(",")] if x)


def _lora_file(name: str) -> str | None:
    """The character's LoRA as ComfyUI names it (by its path in the loras folder, else by its file name)."""
    import folder_paths
    if not name:
        return None
    have = folder_paths.get_filename_list("loras")
    if name in have:
        return name
    base = os.path.basename(str(name).replace("\\", "/")).lower()
    return next((n for n in have if os.path.basename(n.replace("\\", "/")).lower() == base), None)


class CharacterSelect:
    """One of your characters as prompt tags, its name for Gallery Info, and its LoRA."""

    CATEGORY = "Model Librarian"
    FUNCTION = "run"
    RETURN_TYPES = ("STRING", "STRING", "MODEL", "CLIP")
    RETURN_NAMES = ("prompt", "character", "model", "clip")
    OUTPUT_TOOLTIPS = ("The character's tags (with what's wired into before / after) for a text encoder.",
                       "The character's name: wire it into Gallery Info's characters.",
                       "The model with the character's LoRA (the model wired in, unchanged, when it has none).",
                       "The CLIP with the character's LoRA.")
    DESCRIPTION = ("Picks one of your characters (the ones the Model Librarian Chrome extension adds from Danbooru and other boorus) "
                   "and writes its tags as a prompt: its tag, appearance and an outfit, with any tag turned off left out. "
                   "Wire model and clip through it to load the character's LoRA.")

    @classmethod
    def INPUT_TYPES(cls):
        on = lambda tip, d=True: ("BOOLEAN", {"default": d, "tooltip": tip})  # noqa: E731
        return {
            "required": {
                "character": ("STRING", {"default": "", "tooltip": "The character (click the node's picture or name to pick one)."}),
                "outfit": ("STRING", {"default": "", "tooltip": "One of the character's outfits (empty: none)."}),
                "include_character": on("Its booru tag, e.g. aurelia \\(lighthouse tales\\)."),
                "include_series": on("Its series, e.g. lighthouse tales.", False),
                "include_appearance": on("Its appearance tags: hair, eyes and the like."),
                "include_outfit": on("The outfit's tags."),
                "lora_strength": ("FLOAT", {"default": 1.0, "min": -10.0, "max": 10.0, "step": 0.05,
                                            "tooltip": "The character's LoRA strength, when model and clip are wired in and it has a LoRA."}),
                "character_id": ("STRING", {"default": "", "tooltip": "Set by the picker."}),
                "off_tags": ("STRING", {"default": "", "tooltip": "Tags turned off on the node, separated by commas (set by clicking them)."}),
            },
            "optional": {
                "model": ("MODEL", {"tooltip": "Wire the model through to load the character's LoRA."}),
                "clip": ("CLIP", {"tooltip": "Wire CLIP through to load the character's LoRA."}),
                "before": ("STRING", {"forceInput": True, "tooltip": "Text put before the character's tags (quality tags, say)."}),
                "after": ("STRING", {"forceInput": True, "tooltip": "Text put after them (the scene, say)."}),
            },
        }

    @classmethod
    def IS_CHANGED(cls, character="", character_id="", **_):
        """The character as it is in the list now: an edit there runs the node again."""
        try:
            return json.dumps(resolve(character_id, character), sort_keys=True)
        except ValueError:
            return ""

    @classmethod
    def VALIDATE_INPUTS(cls, character="", character_id="", **_):
        try:
            resolve(character_id, character)
            return True
        except ValueError as ex:
            return str(ex)

    def run(self, character, outfit, include_character, include_series, include_appearance, include_outfit, lora_strength,
            character_id="", off_tags="", model=None, clip=None, before="", after=""):
        c = resolve(character_id, character)
        if outfit and outfit not in (c.get("outfits") or {}):
            raise ValueError(f"Character Select: {c.get('name')} has no outfit named {outfit} "
                             f"({', '.join(c.get('outfits') or {}) or 'none'})")
        lora = (c.get("lora") or {}).get("name")
        loaded = False
        if lora and (model is not None or clip is not None) and lora_strength:
            fname = _lora_file(lora)
            if not fname:
                raise ValueError(f"Character Select: {c.get('name')}'s LoRA {lora} isn't in your loras folder")
            import nodes
            model, clip = nodes.LoraLoader().load_lora(model, clip, fname, lora_strength, lora_strength)
            loaded = True
        prompt = build(c, outfit, include_character, include_series, include_appearance, include_outfit, off_tags, before, after, with_trigger=loaded)
        return (prompt, c.get("name") or "", model, clip)


NODE_CLASS_MAPPINGS = {"MLCharacterSelect": CharacterSelect}
NODE_DISPLAY_NAME_MAPPINGS = {"MLCharacterSelect": "Character Select (Model Librarian)"}
