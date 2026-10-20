"""Metadata bridge between LoRA Manager and Stability Matrix sidecars.

LoRA Manager keeps <stem>.metadata.json (with the raw CivitAI version data);
Stability Matrix keeps <stem>.cm-info.json + <stem>.preview.<ext>. Neither
reads the other's, so each fetches and hashes the same files again. This fills
each side from the other, offline:

  to_sm       LM has CivitAI data, SM has no .cm-info.json  -> write it
  sha_to_sm   SM .cm-info.json lacks SHA256, LM knows it      -> add it
  preview     no SM preview, LM has an image preview          -> copy it as <stem>.preview.<ext>
  to_lm       LM metadata has no CivitAI data, SM has it      -> fill it in
  new_lm      LoRA without LM metadata, SM has CivitAI data   -> create it, but only
              when the SHA256 is verified by our own hash cache (LoRA Manager trusts
              the sha256 in the file and won't re-hash)

LoRA Manager only re-reads changed metadata files on a full rebuild, which the
UI requests afterwards.
"""
from __future__ import annotations

import json
import os
import shutil

from . import busy, hashing, library, smmeta

LM_SECTIONS = ("loras", "checkpoints", "embeddings", "diffusion_models")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def _write(path: str, obj, indent=2) -> None:
    tmp = path + ".smf-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=indent, ensure_ascii=False)
    os.replace(tmp, path)


def _sm_preview(model_path: str) -> str | None:
    st = smmeta.model_stem(model_path)
    return next((st + s for s in smmeta.PREVIEW_SUFFIXES if s.startswith(".preview.") and os.path.isfile(st + s)), None)


def cm_meta_from_lm(lm: dict) -> dict:
    """LoRA Manager metadata -> the compact meta dict smmeta.build_cm_info takes."""
    civ = lm.get("civitai") or {}
    model = civ.get("model") or {}
    sha = (lm.get("sha256") or "").lower()
    files = [f for f in civ.get("files") or [] if isinstance(f, dict)]
    f = next((f for f in files if ((f.get("hashes") or {}).get("SHA256") or "").lower() == sha and sha), None) \
        or next((f for f in files if f.get("primary")), {})
    hashes = dict(f.get("hashes") or {}) if f and sha and ((f.get("hashes") or {}).get("SHA256") or "").lower() == sha else {}
    if sha:
        hashes["SHA256"] = sha.upper()
    img = next((i.get("url") for i in civ.get("images") or [] if isinstance(i, dict) and i.get("url")
                and i.get("type", "image") == "image"), None)
    creator = civ.get("creator") or model.get("creator") or {}
    return {
        "modelId": civ.get("modelId"), "modelName": model.get("name") or lm.get("model_name"),
        "nsfw": bool(model.get("nsfw")), "tags": model.get("tags") or lm.get("tags") or [],
        "type": model.get("type"), "creator": creator.get("username") if isinstance(creator, dict) else None,
        "versionId": civ.get("id"), "versionName": civ.get("name"),
        "baseModel": civ.get("baseModel") or lm.get("base_model"), "trainedWords": civ.get("trainedWords") or [],
        "fileName": f.get("name") if f else None, "fileId": f.get("id") if f else None,
        "hashes": hashes, "preview": img,
        "modelDescription": lm.get("modelDescription") or None, "versionDescription": civ.get("description") or None,
    }


def lm_civitai_from_cm(cm: dict) -> dict:
    """SM .cm-info.json -> the parts of a CivitAI model-version response LoRA Manager reads."""
    hashes = {k: v for k, v in (cm.get("Hashes") or {}).items() if v}
    out = {
        "id": cm.get("VersionId"), "modelId": cm.get("ModelId"), "name": cm.get("VersionName") or "",
        "baseModel": cm.get("BaseModel") or "", "trainedWords": list(cm.get("TrainedWords") or []),
        "model": {"name": cm.get("ModelName") or "", "type": cm.get("ModelType") or "", "nsfw": bool(cm.get("Nsfw")),
                  "tags": list(cm.get("Tags") or [])},
        "images": [{"url": cm["ThumbnailImageUrl"], "type": "image"}] if cm.get("ThumbnailImageUrl") else [],
        "files": [{"name": cm.get("RemoteFileName") or "", "id": cm.get("RemoteFileId"), "type": "Model",
                   "primary": True, "hashes": hashes}] if cm.get("RemoteFileName") or hashes else [],
    }
    if cm.get("AuthorUsername"):
        out["creator"] = {"username": cm["AuthorUsername"]}
    if cm.get("VersionDescription"):
        out["description"] = cm["VersionDescription"]
    return out


def _has_civitai(cm: dict | None) -> bool:
    return bool(cm and (cm.get("ModelId") or cm.get("VersionId")))


def _actions(e: dict) -> tuple[list[str], str | None]:
    """-> (actions, why something was skipped)"""
    p = e["path"]
    cm = smmeta.read_cm_info(p)
    lm = smmeta.read_lm_metadata(p)
    acts, skipped = [], None
    lm_civ = (lm or {}).get("civitai") or {}
    if lm and (lm_civ.get("id") or lm_civ.get("modelId")) and not cm:
        acts.append("to_sm")
    if cm and lm and not (cm.get("Hashes") or {}).get("SHA256") and lm.get("sha256"):
        acts.append("sha_to_sm")
    lm_prev = (lm or {}).get("preview_url") or ""
    if lm and not _sm_preview(p) and lm_prev.lower().endswith(_IMAGE_EXTS) and os.path.isfile(lm_prev):
        acts.append("preview")
    if lm and not (lm_civ.get("id") or lm_civ.get("modelId")) and _has_civitai(cm):
        acts.append("to_lm")
    if cm and lm and bool(cm.get("ModelDescription")) != bool(lm.get("modelDescription")):
        acts.append("description")  # one side has the model's description, the other doesn't
    if not lm and _has_civitai(cm) and e["section"] == "loras":
        cached = hashing.cached(p)
        cm_sha = ((cm.get("Hashes") or {}).get("SHA256") or "").lower()
        if cached and (not cm_sha or cm_sha == cached.lower()):
            acts.append("new_lm")
        else:
            skipped = "not hashed yet" if not cached else "SM's SHA256 doesn't match the file"
    return acts, skipped


def plan(sections: list[str]) -> dict:
    items, skipped = [], []
    for s in sections:
        if s not in LM_SECTIONS:
            continue
        for e in library.build(s):
            acts, why = _actions(e)
            if acts:
                items.append({"id": e["id"], "name": e["name"], "section": s, "actions": acts})
            if why:
                skipped.append({"id": e["id"], "name": e["name"], "why": why})
    counts = {}
    for it in items:
        for a in it["actions"]:
            counts[a] = counts.get(a, 0) + 1
    return {"items": items, "counts": counts, "skipped": skipped}


def _apply_one(e: dict, acts: list[str]) -> list[str]:
    p = e["path"]
    done = []
    lm = smmeta.read_lm_metadata(p)
    cm = smmeta.read_cm_info(p)
    if "to_sm" in acts and lm:
        smmeta.write_cm_info(p, cm_meta_from_lm(lm))
        done.append("to_sm")
        cm = smmeta.read_cm_info(p)
    if "sha_to_sm" in acts and cm and lm:
        cm.setdefault("Hashes", {})["SHA256"] = lm["sha256"].upper()
        _write(smmeta.cm_info_path(p), cm, indent=None)
        done.append("sha_to_sm")
    if "preview" in acts and lm and not _sm_preview(p):
        src = lm["preview_url"]
        ext = os.path.splitext(src)[1].lower()
        shutil.copy2(src, smmeta.model_stem(p) + ".preview" + (".jpeg" if ext == ".jpg" else ext))
        done.append("preview")
    if "description" in acts and cm and lm:
        if cm.get("ModelDescription") and not lm.get("modelDescription"):
            lm = {**lm, "modelDescription": cm["ModelDescription"]}
            _write(smmeta.model_stem(p) + ".metadata.json", lm)
        elif lm.get("modelDescription") and not cm.get("ModelDescription"):
            smmeta.save_descriptions(p, lm["modelDescription"], (lm.get("civitai") or {}).get("description"))
            cm = smmeta.read_cm_info(p)
        done.append("description")
    if "to_lm" in acts and lm and _has_civitai(cm):
        lm = dict(lm)
        lm["civitai"] = {**(lm.get("civitai") or {}), **lm_civitai_from_cm(cm)}
        lm["model_name"] = cm.get("ModelName") or lm.get("model_name")
        lm["base_model"] = cm.get("BaseModel") or lm.get("base_model")
        lm["tags"] = list(cm.get("Tags") or lm.get("tags") or [])
        lm["from_civitai"] = True
        if not lm.get("preview_url"):
            prev = smmeta.find_preview(p)
            if prev:
                lm["preview_url"] = prev.replace("\\", "/")
        _write(smmeta.model_stem(p) + ".metadata.json", lm)
        done.append("to_lm")
    if "new_lm" in acts and not lm and _has_civitai(cm):
        sha = hashing.cached(p)
        if sha:
            st = os.stat(p)
            prev = smmeta.find_preview(p)
            _write(smmeta.model_stem(p) + ".metadata.json", {
                "file_name": os.path.splitext(os.path.basename(p))[0], "model_name": cm.get("ModelName") or "",
                "file_path": p.replace("\\", "/"), "size": st.st_size, "modified": st.st_mtime, "sha256": sha.lower(),
                "base_model": cm.get("BaseModel") or "", "preview_url": prev.replace("\\", "/") if prev else "",
                "preview_nsfw_level": 0, "notes": "", "from_civitai": True, "civitai": lm_civitai_from_cm(cm),
                "tags": list(cm.get("Tags") or []), "modelDescription": cm.get("ModelDescription") or "", "civitai_deleted": False,
                "favorite": False, "exclude": False, "db_checked": False, "skip_metadata_refresh": False,
                "metadata_source": None, "last_checked_at": 0, "hash_status": "completed", "usage_tips": "{}",
            })
            done.append("new_lm")
    return done


def apply(ids: list[str]) -> dict:
    with busy.operation("Syncing metadata"):
        results, sections = [], set()
        for fid in ids:
            e = library.get(fid)
            if not e or not os.path.exists(e["path"]):
                results.append({"id": fid, "ok": False, "error": "Unknown file (rescan)"})
                continue
            try:
                acts, _ = _actions(e)  # recompute: never act on a stale plan
                done = _apply_one(e, acts)
                results.append({"id": fid, "ok": True, "done": done})
                if any(a in done for a in ("to_lm", "new_lm")):
                    sections.add(e["section"])
            except Exception as ex:
                results.append({"id": fid, "ok": False, "error": str(ex)})
        counts = {}
        for r in results:
            for a in r.get("done", []):
                counts[a] = counts.get(a, 0) + 1
        return {"results": results, "counts": counts, "lm_sections": sorted(sections),
                "failed": sum(1 for r in results if not r["ok"])}
