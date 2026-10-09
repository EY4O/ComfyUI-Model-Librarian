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


def sidecars(model_path: str) -> list[str]:
    """Existing companion files that belong to this model (and should move with it)."""
    st = model_stem(model_path)
    out = []
    for suf in SIDECAR_SUFFIXES:
        p = st + suf
        if os.path.isfile(p):
            out.append(p)
    return out


def build_cm_info(meta: dict) -> dict:
    h = meta.get("hashes") or {}
    info = {
        "ModelId": meta.get("modelId"),
        "ModelName": meta.get("modelName") or "",
        "ModelDescription": "",
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
        "Hashes": {"SHA256": h.get("SHA256"), "CRC32": h.get("CRC32"), "BLAKE3": h.get("BLAKE3")},
        "TrainedWords": list(meta.get("trainedWords") or []),
        "ThumbnailImageUrl": meta.get("preview"),
    }
    return {k: v for k, v in info.items() if v is not None}


def write_cm_info(model_path: str, meta: dict, overwrite: bool = False) -> str | None:
    p = cm_info_path(model_path)
    if os.path.exists(p) and not overwrite:
        return None
    with open(p, "w", encoding="utf-8") as f:
        json.dump(build_cm_info(meta), f)
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
