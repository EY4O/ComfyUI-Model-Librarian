"""HuggingFace details for models that came from HuggingFace.

A file is linked to its repo through the download registry (its URL is
huggingface.co/<owner>/<repo>/resolve/<rev>/<path>). For each repo we keep the
license, base model, tags, task, likes/downloads, gating and the start of its
model card, cached for a week in the shared data folder (hf_meta.json).
Fetched after a HuggingFace download and during Library → Fetch metadata.
"""
from __future__ import annotations

import re
import time

from . import config, net, registry

CACHE = "hf_meta.json"
TTL = 7 * 24 * 3600
CARD_CHARS = 2500
_URL = re.compile(r"^https://(?:www\.)?huggingface\.co/(?!datasets/|spaces/)([^/]+/[^/]+)/(?:resolve|blob|raw)/([^/]+)/(.+?)(?:\?.*)?$")
_NOISE_TAGS = ("license:", "region:", "endpoints_compatible", "autotrain_compatible", "has_space", "deploy:", "base_model:")


def _merge(shared, local):
    out = shared or {"repos": {}}
    for repo, d in (local.get("repos") or {}).items():
        if (d or {}).get("fetched", 0) > ((out["repos"].get(repo) or {}).get("fetched", 0)):
            out["repos"][repo] = d
    return out


config.register_merger(CACHE, _merge)


def repo_of(url: str | None) -> dict | None:
    """huggingface.co file URL -> {repo, rev, path}, or None."""
    m = _URL.match(url or "")
    if not m:
        return None
    return {"repo": m.group(1), "rev": m.group(2), "path": m.group(3)}


def link_for(name: str, sha256: str | None = None) -> dict | None:
    """The HuggingFace repo a model file was downloaded from, via the registry."""
    for e in (registry.lookup(name), registry.lookup_hash(sha256) if sha256 else None):
        if e:
            ln = repo_of(e.get("url"))
            if ln:
                return ln
    return None


def load() -> dict:
    return (config.read_json(CACHE, None) or {}).get("repos") or {}


def annotate(entries: list[dict]) -> list[dict]:
    """Adds `hf` (repo link + cached details) to library entries from HuggingFace."""
    cache = load()
    for e in entries:
        ln = link_for(e["name"], e.get("sha256"))
        if not ln:
            e.pop("hf", None)
            continue
        e["hf"] = {**ln, **(cache.get(ln["repo"]) or {})}
        if e["hf"].get("gone") and not e.get("removed"):
            e["removed"] = {"where": "HuggingFace", "what": "repo", "at": e["hf"].get("fetched")}
        if not e.get("page_url"):
            e["page_url"] = f"https://huggingface.co/{ln['repo']}"
    return entries


def _strip_front_matter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    text = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    return text.strip()


def readable(md: str) -> str:
    """Markdown a person can read as plain text: no images or HTML, links as their text."""
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)            # images (badges)
    md = re.sub(r"\[\s*\]\([^)]*\)", "", md)                # links left empty by that
    md = re.sub(r"\[([^\]]+)\]\((?:[^()]|\([^)]*\))*\)", r"\1", md)  # [text](url) -> text
    md = re.sub(r"<[^>]+>", "", md)
    md = re.sub(r"[ \t]+\n", "\n", md)
    return re.sub(r"\n{3,}", "\n\n", md).strip()


def parse(info: dict, card: str | None) -> dict:
    """HF /api/models/<repo> response (+ README text) -> what we keep."""
    cd = info.get("cardData") or {}
    tags = [t for t in info.get("tags") or [] if isinstance(t, str)]
    lic = cd.get("license") or next((t.split(":", 1)[1] for t in tags if t.startswith("license:")), None)
    base = cd.get("base_model")
    if isinstance(base, list):
        base = ", ".join(str(b) for b in base[:3])
    gated = info.get("gated")
    text = readable(_strip_front_matter(card)) if card else ""
    return {
        "license": lic, "license_name": cd.get("license_name"), "base_model": base,
        "pipeline": info.get("pipeline_tag"), "library": info.get("library_name"),
        "tags": [t for t in tags if not t.startswith(_NOISE_TAGS)][:24],
        "downloads": info.get("downloads"), "likes": info.get("likes"),
        "gated": gated if gated else False, "private": bool(info.get("private")),
        "author": info.get("author"), "updated": info.get("lastModified"),
        "card": text[:CARD_CHARS] or None,
        "card_truncated": len(text) > CARD_CHARS,
    }


async def _readme(repo: str) -> str | None:
    url = f"{net.HF_BASE}/{repo}/raw/main/README.md"
    try:
        async with net.session().get(url, headers=net.auth_headers(url)) as r:
            if r.status != 200:
                return None
            return (await r.text(errors="replace"))[:200_000]
    except Exception:
        return None


async def fetch(repo: str, force: bool = False) -> dict | None:
    """Details for one repo (cached for a week). None when HuggingFace says 404."""
    cached = load().get(repo)
    if cached and not force and time.time() - cached.get("fetched", 0) < TTL:
        return cached
    info = await net.get_json(f"{net.HF_BASE}/api/models/{repo}")
    if info is None:
        d = {"fetched": time.time(), "gone": True}
    else:
        d = {**parse(info, await _readme(repo)), "fetched": time.time()}
    config.update_json(CACHE, {"repos": {}}, lambda c: c.setdefault("repos", {}).__setitem__(repo, d))
    return d


async def fetch_missing(entries: list[dict], progress=None) -> int:
    """Fetches details for every linked repo not cached yet. -> repos fetched."""
    cache = load()
    repos = []
    for e in entries:
        ln = link_for(e["name"], e.get("sha256"))
        if ln and ln["repo"] not in repos and (ln["repo"] not in cache or time.time() - cache[ln["repo"]].get("fetched", 0) > TTL):
            repos.append(ln["repo"])
    n = 0
    for repo in repos:
        if progress:
            progress(repo)
        try:
            await fetch(repo, force=True)
            n += 1
        except Exception:
            continue
    return n
