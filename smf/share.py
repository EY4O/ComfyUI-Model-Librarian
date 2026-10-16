"""Sharing a workflow with its download list.

For every model the open workflow uses, find a link someone else can download
the exact file from, its page and its SHA256: your download history first,
then the CivitAI version recorded next to the file, then CivitAI by hash, and
CivArchive only for files CivitAI doesn't have (removed models). The frontend
embeds the links in the workflow (ComfyUI's own `properties.models`, which its
missing-models dialog reads too) or copies them as a list to post.
"""
from __future__ import annotations

import asyncio
import os

from . import civarchive, hashing, net, paths, registry, smmeta, sources, updates


def _civ_page(mid, vid) -> str | None:
    if not mid:
        return None
    return f"{net.CIVITAI_BASE}/models/{mid}" + (f"?modelVersionId={vid}" if vid else "")


def _local(it: dict, inv: paths.Inventory) -> tuple[str | None, str | None]:
    """-> (full path, file name as found) of an installed model, or (None, None)."""
    val = it.get("value")
    if not isinstance(val, str) or not val:
        return None, None
    if it.get("lm"):
        state, folder, name = inv.find_lm(paths.strip_lm_ext(paths.norm_rel(val)))
    else:
        state, folder, name, _ = inv.find(val, paths.canonical(it.get("folder")))
    if state == "missing" or not name:
        return None, None
    fp = inv.full_path(folder, name)
    return (fp, name) if fp and os.path.isfile(fp) else (None, None)


async def source_for(it: dict, inv: paths.Inventory, removed: dict) -> dict:
    fp, found = _local(it, inv)
    folder = "loras" if it.get("lm") else paths.canonical(it.get("folder"))
    out = {"value": it.get("value"), "folder": folder, "lm": bool(it.get("lm")), "url": None, "page_url": None,
           "sha256": None, "size": None, "title": None, "base": None, "source": None, "removed": None,
           "file": os.path.basename(found) if found else None}
    if not fp:
        out["note"] = "not installed"
        return out
    out["size"] = os.path.getsize(fp)
    info = await asyncio.to_thread(smmeta.merged_info, fp)
    sha = (hashing.cached(fp) or info.get("sha256") or "").lower() or None
    if not sha:
        try:
            sha = await hashing.sha256_file(fp)
        except OSError:
            sha = None
    out.update(sha256=sha, title=info.get("title"), base=info.get("base"))
    mid, vid = info.get("model_id"), info.get("version_id")
    gone = removed.get(str(mid)) if mid else None
    if gone:
        out["removed"] = gone

    reg = registry.lookup(found) or registry.lookup(str(it.get("value"))) or (registry.lookup_hash(sha) if sha else None)
    if reg and str(reg.get("url", "")).startswith("https://") and not (sha and reg.get("sha256") and reg["sha256"].lower() != sha):
        out.update(url=reg["url"], page_url=reg.get("page_url") or _civ_page(mid, vid), source=reg.get("source"),
                   title=out["title"] or reg.get("title"))
    elif vid and not gone:
        # recorded by Stability Matrix / LoRA Manager / Model Librarian next to the file
        out.update(url=f"{net.CIVITAI_BASE}/api/download/models/{vid}", page_url=_civ_page(mid, vid), source="civitai")
    elif sha and not gone:
        try:
            c = await sources.civitai_by_hash(sha)
        except Exception:
            c = None
        if c and c.get("sha256") == sha:
            out.update(url=c["url"], page_url=c.get("page_url"), source="civitai", title=out["title"] or c.get("title"))
            registry.remember(found, c["url"], source="civitai", sha256=sha, size=out["size"], folder=folder,
                              page_url=c.get("page_url"), title=c.get("title"))
    dead = out["url"] and net.is_civitai(out["url"]) and gone
    if (not out["url"] or dead) and sha and civarchive.enabled():
        try:
            rec = await civarchive.by_hash(sha)
        except Exception:
            rec = None
        if rec:
            url = civarchive.best_url(rec)
            out.update(url=url, source="civarchive" if url else out["source"], archive_url=rec["page_url"],
                       page_url=out["page_url"] or rec["page_url"])
            if rec.get("deleted_on_civitai") and not out["removed"]:
                out["removed"] = {"where": "CivitAI", "what": "model"}
            meta = rec.get("meta") or {}
            out["title"] = out["title"] or " — ".join(x for x in (meta.get("modelName"), meta.get("versionName")) if x) or None
            out["base"] = out["base"] or meta.get("baseModel")
        elif dead:
            out["url"] = None
    if not out["url"]:
        out["note"] = "removed from CivitAI and no live copy known" if out["removed"] else "no known source"
    return out


async def sources_for(items: list[dict]) -> list[dict]:
    inv = await asyncio.to_thread(paths.Inventory)
    cache = updates.load()
    removed = {mid: {"where": "CivitAI", "what": "model", "at": rec.get("checked")}
               for mid, rec in (cache.get("models") or {}).items() if (rec or {}).get("gone")}
    out = []
    for it in items[:300]:
        if isinstance(it, dict):
            out.append(await source_for(it, inv, removed))
    return out


def markdown(rows: list[dict], title: str | None = None) -> str:
    """The list to post next to a shared workflow."""
    lines = [f"**Models for {title}**" if title else "**Models used**", ""]
    for r in rows:
        name = r.get("file") or r.get("value")
        bits = [f"`{name}`", f"→ `models/{r['folder']}`" if r.get("folder") else ""]
        if r.get("title"):
            bits.append(f"— {r['title']}" + (f" ({r['base']})" if r.get("base") else ""))
        if r.get("page_url"):
            bits.append(f"· [page]({r['page_url']})")
        elif r.get("url"):
            bits.append(f"· [download]({r['url']})")
        if r.get("archive_url") and r.get("archive_url") != r.get("page_url"):
            bits.append(f"· [CivArchive]({r['archive_url']})")
        if r.get("size"):
            bits.append(f"· {r['size'] / 1024 ** 3:.2f} GB" if r["size"] >= 1024 ** 3 else f"· {r['size'] / 1024 ** 2:.0f} MB")
        if r.get("removed"):
            bits.append("· removed from " + r["removed"].get("where", "CivitAI"))
        if r.get("sha256"):
            bits.append(f"· SHA256 `{r['sha256'][:10]}…`")
        lines.append("- " + " ".join(b for b in bits if b))
    return "\n".join(lines)

