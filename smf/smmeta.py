"""Stability Matrix sidecar files.

Stability Matrix's Checkpoint Manager treats a model as "connected" when a
`<stem>.cm-info.json` (its ConnectedModelInfo, serialized with PascalCase
property names) sits next to it, and shows `<stem>.preview.<ext>` as the
thumbnail. Writing these makes models fetched/identified here look exactly
like models downloaded through Stability Matrix itself.
"""
from __future__ import annotations

import datetime as _dt
import json
import os

from . import net

# Companion files written by Stability Matrix (.cm-info.json, .preview.*),
# LoRA Manager (.metadata.json, .webp, ...) and A1111/Forge (.civitai.info, .json, .txt)
PREVIEW_SUFFIXES = (
    ".preview.webp", ".preview.png", ".preview.jpeg", ".preview.jpg", ".webp", ".png", ".jpeg", ".jpg",
    ".gif", ".avif", ".preview.mp4", ".mp4", ".webm",
)
SIDECAR_SUFFIXES = (
    ".cm-info.json", ".metadata.json", ".civitai.info", ".json", ".txt", ".yaml",
) + PREVIEW_SUFFIXES


def find_preview(model_path: str) -> str | None:
    st = model_stem(model_path)
    for suf in PREVIEW_SUFFIXES:
        p = st + suf
        if os.path.isfile(p):
            return p
    return None


def read_lm_metadata(model_path: str) -> dict | None:
    """LoRA Manager's <stem>.metadata.json"""
    try:
        with open(model_stem(model_path) + ".metadata.json", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def read_civitai_info(model_path: str) -> dict | None:
    """A1111 Civitai Helper / Forge <stem>.civitai.info (raw model-version JSON)."""
    try:
        with open(model_stem(model_path) + ".civitai.info", "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def merged_info(model_path: str) -> dict:
    """Best-known metadata from any tool's sidecar files."""
    out: dict = {}
    cm = read_cm_info(model_path)
    if cm:
        out.update({
            "title": cm.get("ModelName"), "version": cm.get("VersionName"), "base": cm.get("BaseModel"),
            "model_id": cm.get("ModelId"), "version_id": cm.get("VersionId"),
            "trained_words": cm.get("TrainedWords") or [], "sha256": (cm.get("Hashes") or {}).get("SHA256"),
            "type": cm.get("ModelType"), "source": "Stability Matrix", "nsfw": cm.get("Nsfw"),
        })
    lm = read_lm_metadata(model_path)
    if lm:
        civ = lm.get("civitai") or {}
        model = civ.get("model") or {}
        out.setdefault("title", lm.get("model_name") or model.get("name"))
        out.setdefault("version", civ.get("name"))
        out.setdefault("base", lm.get("base_model") or civ.get("baseModel"))
        out.setdefault("model_id", civ.get("modelId"))
        out.setdefault("version_id", civ.get("id"))
        if not out.get("trained_words"):
            out["trained_words"] = civ.get("trainedWords") or []
        out.setdefault("sha256", lm.get("sha256"))
        out.setdefault("source", "LoRA Manager")
        out.setdefault("type", model.get("type"))
        if (lm.get("preview_nsfw_level") or 0) >= 4:
            out["nsfw"] = True
        if lm.get("favorite"):
            out["favorite"] = True
    ci = read_civitai_info(model_path)
    if ci:
        out.setdefault("title", (ci.get("model") or {}).get("name"))
        out.setdefault("version", ci.get("name"))
        out.setdefault("base", ci.get("baseModel"))
        out.setdefault("model_id", ci.get("modelId"))
        out.setdefault("version_id", ci.get("id"))
        if not out.get("trained_words"):
            out["trained_words"] = ci.get("trainedWords") or []
        out.setdefault("source", "civitai.info")
    return {k: v for k, v in out.items() if v not in (None, "")}


def model_stem(path: str) -> str:
    return os.path.splitext(path)[0]


def cm_info_path(model_path: str) -> str:
    return model_stem(model_path) + ".cm-info.json"


def read_cm_info(model_path: str) -> dict | None:
    try:
        with open(cm_info_path(model_path), "r", encoding="utf-8-sig") as f:
            return json.load(f)
    except Exception:
        return None


def stem_shared(model_path: str) -> bool:
    """Another model file uses the same stem (foo.safetensors + foo.gguf), so
    stem-named sidecars could belong to either."""
    from .paths import MODEL_EXTS
    st, me = model_stem(model_path), os.path.normcase(os.path.abspath(model_path))
    return any(os.path.isfile(st + e) and os.path.normcase(os.path.abspath(st + e)) != me for e in MODEL_EXTS)


def _owns(sidecar: str, model_path: str) -> bool:
    """For a shared stem: does this sidecar provably describe this model file?"""
    try:
        if sidecar.endswith(".metadata.json"):  # LoRA Manager records the exact file
            with open(sidecar, "r", encoding="utf-8") as f:
                fp = json.load(f).get("file_path") or ""
            return os.path.normcase(os.path.abspath(fp)) == os.path.normcase(os.path.abspath(model_path))
        if sidecar.endswith(".cm-info.json"):
            from . import hashing
            sha = ((read_cm_info(model_path) or {}).get("Hashes") or {}).get("SHA256") or ""
            mine = hashing.cached(model_path) or ""
            return bool(sha and mine) and sha.lower() == mine.lower()
    except Exception:
        pass
    return False


def sidecars(model_path: str) -> list[str]:
    """Existing companion files that belong to this model (and should move with it).
    When another model shares the stem, only sidecars that identify this exact
    file move; previews and the rest stay with the other model."""
    st = model_stem(model_path)
    shared = stem_shared(model_path)
    out = []
    for suf in SIDECAR_SUFFIXES:
        p = st + suf
        if os.path.isfile(p) and (not shared or _owns(p, model_path)):
            out.append(p)
    return out


def descriptions(model_path: str) -> dict:
    """The model's and the version's descriptions (HTML) from whichever sidecar has them."""
    cm = read_cm_info(model_path) or {}
    lm = read_lm_metadata(model_path) or {}
    ci = read_civitai_info(model_path) or {}
    return {
        "model": cm.get("ModelDescription") or lm.get("modelDescription") or None,
        "version": cm.get("VersionDescription") or (lm.get("civitai") or {}).get("description") or ci.get("description") or None,
    }


def save_descriptions(model_path: str, model_html: str | None, version_html: str | None) -> bool:
    """Writes them into the .cm-info.json next to the model (only when it exists and they're missing there)."""
    p = cm_info_path(model_path)
    cm = read_cm_info(model_path)
    if not isinstance(cm, dict):
        return False
    changed = False
    for key, val in (("ModelDescription", model_html), ("VersionDescription", version_html)):
        if val and not cm.get(key):
            cm[key] = val
            changed = True
    if changed:
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(cm, f)
        os.replace(tmp, p)
    return changed


def build_cm_info(meta: dict) -> dict:
    h = meta.get("hashes") or {}
    info = {
        "ModelId": meta.get("modelId"),
        "ModelName": meta.get("modelName") or "",
        "ModelDescription": meta.get("modelDescription") or "",
        "VersionDescription": meta.get("versionDescription") or None,  # not SM's; kept so it follows the file
        "Nsfw": bool(meta.get("nsfw")),
        "Tags": list(meta.get("tags") or []),
        "ModelType": meta.get("type") or "Unknown",
        "VersionId": meta.get("versionId"),
        "VersionName": meta.get("versionName") or "",
        "AuthorUsername": meta.get("creator"),
        "BaseModel": meta.get("baseModel"),
        "RemoteFileName": meta.get("fileName"),
        "RemoteFileId": meta.get("fileId"),
        "ImportedAt": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "Hashes": {k: v for k, v in (("SHA256", h.get("SHA256")), ("CRC32", h.get("CRC32")),
                                     ("BLAKE3", h.get("BLAKE3"))) if v},
        "TrainedWords": list(meta.get("trainedWords") or []),
        "ThumbnailImageUrl": meta.get("preview"),
    }
    return {k: v for k, v in info.items() if v is not None}


def write_cm_info(model_path: str, meta: dict, overwrite: bool = False) -> str | None:
    """Write SM's .cm-info.json. With overwrite, merge into an existing file:
    fresh CivitAI values win, but fields we don't produce (or produce empty, like
    ModelDescription) and the original ImportedAt are kept."""
    p = cm_info_path(model_path)
    cur = read_cm_info(model_path) if os.path.exists(p) else None
    if os.path.exists(p) and not overwrite:
        return None
    info = build_cm_info(meta)
    if isinstance(cur, dict):
        merged = dict(cur)
        for k, v in info.items():
            if v in ("", [], {}, None) or (k == "ImportedAt" and cur.get(k)):
                continue
            if k == "Hashes":
                v = {**(cur.get(k) or {}), **{a: b for a, b in v.items() if b}}
            merged[k] = v
        info = merged
    tmp = p + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(info, f)
    os.replace(tmp, p)
    return p


async def download_preview(model_path: str, url: str | None) -> str | None:
    if not url:
        return None
    st = model_stem(model_path)
    if find_preview(model_path):
        return None
    ext = os.path.splitext(url.split("?")[0])[1].lower().lstrip(".") or "jpeg"
    if ext not in ("png", "jpeg", "jpg", "webp"):
        ext = "jpeg"
    dest = f"{st}.preview.{ext}"
    try:
        async with net.session().get(url) as r:
            if r.status != 200 or not r.headers.get("Content-Type", "image").startswith("image"):
                return None
            data = await r.read()
        with open(dest, "wb") as f:
            f.write(data)
        return dest
    except Exception:
        return None
