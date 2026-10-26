"""CivArchive (civarchive.com): a fallback for models CivitAI doesn't have.

Only asked when CivitAI has no match: a model removed from CivitAI, or a file
it never had. CivArchive hosts nothing itself; it indexes every known copy of a
file by SHA256 (CivitAI re-uploads, HuggingFace mirrors, other hosts) and
tracks whether each copy is still live, along with the CivitAI details it saw.
It has no public API, so we read the JSON its pages embed for the browser
(Next.js __NEXT_DATA__). Results are cached in the shared data folder
(civarchive.json). Live copies on CivitAI or HuggingFace become download
candidates (SHA256-verified like any download); copies elsewhere are only
offered as links to open in the browser.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from urllib.parse import quote, urlparse

from . import config, net

BASE = "https://civarchive.com"
CACHE = "civarchive.json"
TTL = 3 * 24 * 3600
TTL_MISS = 24 * 3600
CACHE_V = 2  # bumped when parse() changes, so older cached records are fetched again
MAX_PAGE = 4 * 1024 * 1024
DOWNLOAD_HOSTS = ("civitai.com", "civitai.red", "civitai.green", "huggingface.co")
_SHA = re.compile(r"^[a-f0-9]{64}$")
_NEXT = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
_FOLDER = {"LORA": "loras", "LOCON": "loras", "DORA": "loras", "CHECKPOINT": "checkpoints",
           "TEXTUALINVERSION": "embeddings", "VAE": "vae", "CONTROLNET": "controlnet", "UPSCALER": "upscale_models",
           "TEXTENCODER": "text_encoders"}


def _merge(shared, local):
    out = shared or {"files": {}}
    for sha, d in (local.get("files") or {}).items():
        if (d or {}).get("fetched", 0) > ((out["files"].get(sha) or {}).get("fetched", 0)):
            out["files"][sha] = d
    return out


config.register_merger(CACHE, _merge)


def enabled() -> bool:
    return bool(config.load().get("use_civarchive", True))


def page_url(sha256: str) -> str:
    return f"{BASE}/sha256/{sha256.lower()}"


def search_url(name: str) -> str:
    return f"{BASE}/search?q={quote(_stem(name))}&rating=all&kind=file"


def _stem(name: str) -> str:
    base = str(name).replace("\\", "/").rsplit("/", 1)[-1]
    return os.path.splitext(base)[0] if "." in base else base


def load() -> dict:
    return (config.read_json(CACHE, None) or {}).get("files") or {}


def page_data(html: str) -> dict | None:
    """The page's props (pageProps) from its embedded Next.js data."""
    m = _NEXT.search(html or "")
    if not m:
        return None
    try:
        d = json.loads(m.group(1))
    except ValueError:
        return None
    return ((d.get("props") or {}).get("pageProps")) if isinstance(d, dict) else None


async def _page(path: str) -> dict | None:
    """GET a CivArchive page -> its pageProps; None on 404. Other errors raise."""
    url = BASE + path
    async with net.session().get(url, headers={"Accept": "text/html"}) as r:
        if r.status == 404:
            return None
        r.raise_for_status()
        raw = b""
        while len(raw) < MAX_PAGE:
            chunk = await r.content.read(MAX_PAGE - len(raw))
            if not chunk:
                break
            raw += chunk
    pp = page_data(raw.decode("utf-8", errors="replace"))
    if pp is None:  # a bot check or an error page: not an answer, so don't cache it as "not listed"
        raise RuntimeError("CivArchive returned a page without data")
    return pp


def _host(url: str) -> str:
    return (urlparse(url or "").hostname or "").lower().removeprefix("www.")


def _sfw(img: dict) -> bool:
    lvl = img.get("nsfwLevel")
    return (lvl is None or lvl <= 1) and not img.get("is_nsfw")


def parse(pp: dict, sha256: str) -> dict | None:
    """A /sha256/<hash> page -> {sha256, files: [copies], meta, deleted}, or None if it isn't listed."""
    sha = sha256.lower()
    copies = []
    for f in pp.get("files") or []:
        url = str(f.get("url") or "")
        if not url.startswith("https://"):
            continue
        copies.append({
            "filename": f.get("filename"), "url": url, "source": f.get("source") or _host(url),
            "host": _host(url), "live": not f.get("deleted_at"), "version_id": str(f.get("model_version_id") or ""),
            "gated": bool(f.get("is_gated")), "paid": bool(f.get("is_paid")),
        })
    models = [m for m in pp.get("models") or [] if isinstance(m, dict)]
    if not copies and not models:
        return None
    meta, size, name = {}, None, None
    m = models[0] if models else {}
    v = m.get("version") or {}
    for mm in models:  # the version whose file has this hash, if listed
        vv = mm.get("version") or {}
        f = next((f for f in vv.get("files") or [] if str(f.get("sha256") or "").lower() == sha), None)
        if f:
            m, v = mm, vv
            size = int(f["size_kb"] * 1024) if f.get("size_kb") else None
            name = f.get("name")
            break
    if m:
        allow_nsfw = config.load().get("nsfw_previews")
        imgs = [i for i in v.get("images") or [] if i.get("type", "image") == "image" and (i.get("url") or i.get("image_url"))]
        prev = next((i.get("url") or i.get("image_url") for i in imgs if allow_nsfw or _sfw(i)), None)
        # only CivitAI's own ids (they go into .cm-info.json and drive update checks); a
        # model from another site has none, and CivArchive's own ids would point at the wrong model
        from_civitai = str(m.get("platform") or pp.get("platform") or "").lower() == "civitai"
        mid = v.get("civitai_model_id") or (from_civitai and (v.get("model_id") or m.get("id")))
        vid = v.get("civitai_model_version_id") or (from_civitai and v.get("id"))
        meta = {
            "modelId": int(mid) if str(mid or "").isdigit() else None,
            "modelName": m.get("name"), "nsfw": bool(m.get("is_nsfw")),
            "tags": [t if isinstance(t, str) else (t or {}).get("name") for t in m.get("tags") or []][:20],
            "type": m.get("type"), "creator": m.get("creator_username") or m.get("username"),
            "versionId": int(vid) if str(vid or "").isdigit() else None,
            "versionName": v.get("name"), "baseModel": v.get("base_model"),
            "trainedWords": [w for w in v.get("trigger") or [] if isinstance(w, str)],
            "fileName": name or (copies[0]["filename"] if copies else None),
            "hashes": {"SHA256": sha.upper()}, "preview": prev,
        }
        meta = {k: x for k, x in meta.items() if x not in (None, "", [])}
        meta.setdefault("hashes", {"SHA256": sha.upper()})
    deleted = bool(m.get("deleted_at") or v.get("deleted_at")) or any(
        c["source"] == "civitai" and not c["live"] for c in copies)
    if deleted:
        # CivArchive can still call the removed version's own CivitAI link live: it isn't
        removed = {str(x) for x in (v.get("civitai_model_version_id"), v.get("id"), meta.get("versionId")) if x}
        for c in copies:
            if c["source"] == "civitai" and c["version_id"] in removed:
                c["live"] = False
    return {"sha256": sha, "files": copies, "meta": meta, "size": size,
            "filename": name or (copies[0]["filename"] if copies else None),
            "deleted_on_civitai": deleted, "page_url": page_url(sha),
            "folder": _FOLDER.get(str(meta.get("type") or "").upper())}


async def by_hash(sha256: str, force: bool = False) -> dict | None:
    """What CivArchive knows about a file (cached). None if it isn't listed."""
    sha = (sha256 or "").lower()
    if not _SHA.match(sha):
        return None
    hit = load().get(sha)
    if hit and not force and hit.get("v") == CACHE_V and time.time() - hit.get("fetched", 0) < (TTL if hit.get("found") else TTL_MISS):
        return hit.get("rec")
    pp = await _page(f"/sha256/{sha}")
    rec = parse(pp, sha) if pp else None
    d = {"fetched": time.time(), "found": bool(rec), "rec": rec, "v": CACHE_V}
    await asyncio.to_thread(config.update_json, CACHE, {"files": {}}, lambda c: c.setdefault("files", {}).__setitem__(sha, d))
    return rec


def search_hits(pp: dict, filename: str) -> list[str]:
    """SHA256s of search results whose file name is exactly `filename`."""
    want = str(filename).replace("\\", "/").rsplit("/", 1)[-1].lower()
    out = []
    for r in ((pp or {}).get("data") or {}).get("results") or []:
        m = re.match(r"^/sha256/([a-f0-9]{64})$", str(r.get("url") or ""))
        if m and str(r.get("name") or "").lower() == want and m.group(1) not in out:
            out.append(m.group(1))
    return out


async def by_name(filename: str, limit: int = 3) -> list[dict]:
    """Files CivArchive lists under exactly this name."""
    pp = await _page(f"/search?q={quote(_stem(filename))}&rating=all&kind=file")
    out = []
    for sha in search_hits(pp, filename)[:limit]:
        try:
            rec = await by_hash(sha)
        except Exception:
            continue
        if rec:
            out.append(rec)
    return out


def best_url(rec: dict | None) -> str | None:
    """A live copy we can download (CivitAI first, then HuggingFace)."""
    live = [c for c in (rec or {}).get("files") or [] if c["live"] and not c["paid"] and c["host"] in DOWNLOAD_HOSTS]
    # a re-upload on CivitAI first, unless the model was removed there (its other copies may follow); then HuggingFace
    removed = (rec or {}).get("deleted_on_civitai")
    live.sort(key=lambda c: (1 if c["host"].startswith("civitai") else 0) if removed else (0 if c["host"].startswith("civitai") else 1))
    return live[0]["url"] if live else None


def candidates(rec: dict, filename: str, folder: str | None = None) -> list[dict]:
    """Download candidates (sources._cand shape) for a CivArchive record."""
    from .sources import _cand  # late import: sources imports this module
    meta = rec.get("meta") or {}
    title = " — ".join(x for x in (meta.get("modelName"), meta.get("versionName")) if x) or rec.get("filename") or filename
    if meta.get("baseModel"):
        title += f" ({meta['baseModel']})"
    out, seen = [], set()
    for c in rec.get("files") or []:
        if not c["live"] or c["paid"] or c["url"] in seen:
            continue
        seen.add(c["url"])
        direct = c["host"] in DOWNLOAD_HOSTS
        cand = _cand("civarchive", c["url"], rec.get("filename") or c["filename"] or filename,
                     confidence="high" if direct else "medium", size=rec.get("size"), sha256=rec["sha256"],
                     page_url=rec["page_url"], title=f"{title} · copy on {c['host']}",
                     folder=rec.get("folder") or folder, gated=c["gated"], meta=meta or None)
        cand["via"] = c["host"]
        if not direct:
            cand["link_only"] = True  # opened in the browser, not downloaded here
        out.append(cand)
    out.sort(key=lambda x: (bool(x.get("link_only")), 0 if str(x.get("via", "")).startswith("civitai") else 1))
    return out
