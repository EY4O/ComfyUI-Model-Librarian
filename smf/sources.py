"""Find download candidates for a missing model file.

Order of trust: workflow-embedded URL -> personal registry -> ComfyUI-Manager
model list -> HuggingFace (exact filename in repo tree) -> CivitAI search ->
CivArchive (only when nothing above found the file: copies of models removed
from CivitAI).
"""
from __future__ import annotations

import asyncio
import difflib
import glob
import json
import os
import re
import time
from urllib.parse import quote

from . import civarchive, config, net, registry
from .paths import canonical

PRECISION_TOKENS = {
    "fp16", "fp32", "bf16", "fp8", "e4m3fn", "e5m2", "scaled", "pruned", "ema", "emaonly", "noema",
    "fp8mixed", "mixed", "fp4", "nvfp4", "int4", "int8", "svdq", "safetensors", "full", "model", "v",
    "gguf", "comfy", "comfyui", "only", "unet", "diffusion", "f16", "f32",
}
_QUANT = re.compile(r"^(q\d(_k)?(_[sml0-9])?|iq\d\w*)$", re.I)
CONF_RANK = {"high": 0, "medium": 1, "low": 2}
SRC_RANK = {"workflow": 0, "registry": 1, "hash": 1, "template": 2, "manager": 2, "huggingface": 3, "civitai": 4, "civarchive": 5, "manual": 6}

CIVITAI_TYPES = {
    "loras": ["LORA", "LoCon", "DoRA"],
    "checkpoints": ["Checkpoint"],
    "embeddings": ["TextualInversion"],
    "vae": ["VAE"],
    "controlnet": ["Controlnet"],
    "upscale_models": ["Upscaler"],
    "hypernetworks": ["Hypernetwork"],
}


def basename(p: str) -> str:
    return p.replace("\\", "/").rsplit("/", 1)[-1]


def stem(p: str) -> str:
    b = basename(p)
    return b.rsplit(".", 1)[0] if "." in b else b


_QUANT_SUFFIX = re.compile(r"(?i)[-_.](?:I?Q\d(?:_K)?(?:_[A-Z0-9]{1,2})?|BF16|F16|F32)$")


def core_tokens(filename: str) -> list[str]:
    from urllib.parse import unquote
    st = _QUANT_SUFFIX.sub("", stem(unquote(filename)))
    toks = [t for t in re.split(r"(?:[\s_\-\(\)\[\]]|(?<!\d)\.|\.(?!\d))+", st) if t]
    out = [t for t in toks if t.lower() not in PRECISION_TOKENS and not _QUANT.match(t) and len(t) > 1]
    return out or toks


def hf_query_variants(filename: str) -> list[str]:
    toks = core_tokens(filename)
    variants = []
    for n in (3, 2, 1):
        if len(toks) >= n:
            q = "-".join(toks[:n])
            variants.append(q)
            # flux1 -> flux.1, wan2 -> wan2.? not guessable; only alpha+digit split
            dotted = re.sub(r"([a-zA-Z])(\d)", r"\1.\2", q, count=1)
            if dotted != q:
                variants.append(dotted)
    seen, out = set(), []
    for v in variants:
        if v.lower() not in seen and len(v) >= 3:
            seen.add(v.lower())
            out.append(v)
    return out[:4]


def _cand(source, url, filename, *, confidence, size=None, sha256=None, page_url=None, title=None,
          folder=None, gated=False, meta=None):
    return {
        "source": source, "url": url, "filename": filename, "confidence": confidence,
        "size": size, "sha256": (sha256 or "").lower() or None, "page_url": page_url,
        "title": title, "folder": folder, "gated": gated, "meta": meta,
    }


# ----------------------------------------------------------- Manager list
_manager_cache: dict | None = None
_manager_cache_t = 0.0


def _local_manager_lists() -> list[str]:
    try:
        import folder_paths
        roots = folder_paths.get_folder_paths("custom_nodes")
    except Exception:
        roots = []
    out = []
    for r in roots:
        out += glob.glob(os.path.join(r, "*anager*", "model-list.json"))
    return out


async def _manager_index() -> dict:
    global _manager_cache, _manager_cache_t
    if _manager_cache is not None and time.time() - _manager_cache_t < 24 * 3600:
        return _manager_cache
    models = []
    cached = config.read_json("manager_model_list.json", None)
    if cached and time.time() - cached.get("_fetched", 0) < 24 * 3600:
        models = cached.get("models", [])
    else:
        try:
            data = await net.get_json(net.MANAGER_LIST_URL, timeout=20)
            if data and data.get("models"):
                models = data["models"]
                config.write_json("manager_model_list.json", {"_fetched": time.time(), "models": models})
        except Exception:
            models = (cached or {}).get("models", [])
    if not models:
        for p in _local_manager_lists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    models += json.load(f).get("models", [])
            except Exception:
                pass
    idx = {}
    for m in models:
        fn = m.get("filename")
        if fn and m.get("url", "").startswith("https://"):
            idx.setdefault(fn.lower(), m)
    _manager_cache, _manager_cache_t = idx, time.time()
    return idx


async def from_manager(filename: str) -> list[dict]:
    m = (await _manager_index()).get(basename(filename).lower())
    if not m:
        return []
    sp = m.get("save_path", "default")
    folder = canonical(sp) if sp and sp != "default" else canonical(m.get("type"))
    return [_cand("manager", m["url"], m["filename"], confidence="high", title=m.get("name"),
                  folder=folder, page_url=m.get("reference"))]


# ----------------------------------------------------------- HuggingFace
_tree_cache: dict[str, list] = {}


async def hf_search(query: str, limit: int = 8) -> list[dict]:
    try:
        res = await net.get_json(f"{net.HF_BASE}/api/models",
                                 params={"search": query, "limit": str(limit), "sort": "downloads",
                                         "direction": "-1"})
        return res or []
    except Exception:
        return []


async def hf_tree(repo: str) -> list[dict]:
    if repo in _tree_cache:
        return _tree_cache[repo]
    files: list[dict] = []
    url = f"{net.HF_BASE}/api/models/{repo}/tree/main"
    params = {"recursive": "true"}
    for _ in range(5):  # pagination guard
        try:
            data, nxt = await net.get_json_with_links(url, params=params)
        except Exception:
            return files  # transient error (429 etc.): don't cache a partial listing
        files += [f for f in (data or []) if f.get("type") == "file"]
        if not nxt:
            break
        url, params = nxt, None
    _tree_cache[repo] = files
    return files


def hf_file_url(repo: str, path: str) -> str:
    return f"{net.HF_BASE}/{repo}/resolve/main/{quote(path)}"


async def from_huggingface(filename: str) -> list[dict]:
    want = basename(filename).lower()
    repos: dict[str, dict] = {}
    for q in hf_query_variants(filename):
        for r in await hf_search(q):
            rid = r.get("id") or r.get("modelId")
            if rid and rid not in repos:
                repos[rid] = r
        if len(repos) >= 12:
            break
    repo_list = list(repos.items())[:10]
    trees = await asyncio.gather(*(hf_tree(rid) for rid, _ in repo_list))
    exact, near = [], []
    for (rid, info), files in zip(repo_list, trees):
        gated = bool(info.get("gated"))
        for f in files:
            name = basename(f["path"])
            lfs = f.get("lfs") or {}
            kw = dict(size=f.get("size") or lfs.get("size"), sha256=lfs.get("oid") or lfs.get("sha256"),
                      page_url=f"{net.HF_BASE}/{rid}", title=f"{rid}/{f['path']}", gated=gated)
            if name.lower() == want:
                exact.append(_cand("huggingface", hf_file_url(rid, f["path"]), name, confidence="high", **kw))
            elif name.lower().endswith((".safetensors", ".gguf", ".ckpt", ".pth", ".pt", ".sft", ".bin")):
                ratio = difflib.SequenceMatcher(None, name.lower(), want).ratio()
                if ratio >= 0.82:
                    c = _cand("huggingface", hf_file_url(rid, f["path"]), name, confidence="low", **kw)
                    c["_ratio"] = ratio
                    near.append(c)
    near.sort(key=lambda c: -c.pop("_ratio", 0))
    return exact[:5] + near[:3]


# ----------------------------------------------------------- CivitAI
def access_note(version: dict) -> str | None:
    """When CivitAI wants more than an API key for this version: paid (for a while, or for good) or early access."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)

    def later(iso):
        try:
            t = _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
            return t if t > now else None
        except (TypeError, ValueError):
            return None
    pa = version.get("paidAccess") or {}
    if pa.get("permanent"):
        return "A paid model on CivitAI: the download needs a purchase there"
    until = later(pa.get("endsAt")) if pa else None
    if until:
        return f"Paid early access on CivitAI until {until:%d %b %Y}: until then the download needs a purchase there"
    ea = later(version.get("earlyAccessEndsAt"))
    if ea:
        return f"Early access on CivitAI until {ea:%d %b %Y}: until then the download may need a purchase there"
    return None


def access_until(version: dict) -> str | None:
    """When a paid-for-now or early-access version becomes free (ISO time), or None."""
    import datetime as _dt
    now = _dt.datetime.now(_dt.timezone.utc)
    pa = version.get("paidAccess") or {}
    for iso in ([] if pa.get("permanent") else [pa.get("endsAt")]) + [version.get("earlyAccessEndsAt")]:
        try:
            if iso and _dt.datetime.fromisoformat(str(iso).replace("Z", "+00:00")) > now:
                return str(iso)
        except ValueError:
            continue
    return None


def civitai_meta(model: dict, version: dict, file: dict) -> dict:
    """Compact metadata later used to write Stability Matrix .cm-info.json files."""
    imgs = version.get("images") or []
    allow_nsfw = config.load().get("nsfw_previews")
    def _sfw(i):
        lvl = i.get("nsfwLevel")
        flag = i.get("nsfw")
        if isinstance(flag, str):
            flag = flag not in ("None", "", "false", "False")
        return (lvl is None or lvl <= 1) and not flag

    preview = next((i.get("url") for i in imgs
                    if i.get("type", "image") == "image" and (allow_nsfw or _sfw(i))), None)
    return {
        "modelId": model.get("id") or version.get("modelId"),
        "modelName": model.get("name"),
        "nsfw": bool(model.get("nsfw")),
        "tags": model.get("tags") or [],
        "type": model.get("type"),
        "creator": (model.get("creator") or {}).get("username"),
        "versionId": version.get("id"),
        "versionName": version.get("name"),
        "baseModel": version.get("baseModel"),
        "trainedWords": version.get("trainedWords") or [],
        "fileName": file.get("name"),
        "fileId": file.get("id"),
        "hashes": file.get("hashes") or {},
        "preview": preview,
        "versionDescription": version.get("description") or None,  # "about this version" (HTML)
        "access": access_note(version),
        "accessUntil": access_until(version),
        "nsfwLevel": version.get("nsfwLevel"),
    }


def _civ_file_cand(model, version, file, confidence):
    size = file.get("sizeKB") or file.get("sizeKb")
    url = file.get("downloadUrl") or version.get("downloadUrl")
    mid = model.get("id") or version.get("modelId")
    return _cand(
        "civitai", url, file.get("name"), confidence=confidence,
        size=int(size * 1024) if size else None,
        sha256=(file.get("hashes") or {}).get("SHA256"),
        page_url=f"{net.CIVITAI_BASE}/models/{mid}?modelVersionId={version.get('id')}",
        title=f"{model.get('name')} — {version.get('name')} ({version.get('baseModel')})",
        folder={"LORA": "loras", "LoCon": "loras", "DoRA": "loras", "Checkpoint": "checkpoints",
                "TextualInversion": "embeddings", "VAE": "vae", "Controlnet": "controlnet",
                "Upscaler": "upscale_models"}.get(model.get("type")),
        meta=civitai_meta(model, version, file),
    )


_model_desc: dict[int, str] = {}


async def model_description(model_id) -> str | None:
    """The model page's description (HTML). The model-versions answer doesn't carry it, so it's one more
    request, remembered for the session."""
    try:
        mid = int(model_id)
    except (TypeError, ValueError):
        return None
    if mid not in _model_desc:
        m = await net.get_json(f"{net.CIVITAI_BASE}/api/v1/models/{mid}")
        _model_desc[mid] = (m or {}).get("description") or ""
    return _model_desc[mid] or None


async def with_description(meta: dict | None) -> dict | None:
    """meta plus the model's description, when CivitAI has one (never fails the caller)."""
    if meta and meta.get("modelId") and not meta.get("modelDescription"):
        try:
            d = await model_description(meta["modelId"])
            if d:
                meta = {**meta, "modelDescription": d}
        except Exception:
            pass
    return meta


async def civitai_by_hash(sha256: str) -> dict | None:
    """-> candidate (with meta), or None when CivitAI says 404. Other errors raise."""
    v = await net.get_json(f"{net.CIVITAI_BASE}/api/v1/model-versions/by-hash/{sha256}")
    if not v or "files" not in v:
        return None
    model = dict(v.get("model") or {})
    model.setdefault("id", v.get("modelId"))
    sha = sha256.lower()  # a full SHA256, or a short hash (AutoV2...) from image metadata
    f = next((f for f in v["files"] if _hash_matches(f, sha)), None)
    f = f or next((f for f in v["files"] if f.get("primary")), v["files"][0] if v["files"] else None)
    if not f:
        return None
    c = _civ_file_cand(model, v, f, "high")
    if not _hash_matches(f, sha):
        # don't record another file's hashes
        c["meta"]["hashes"] = {"SHA256": sha.upper()} if len(sha) == 64 else {}
        c["sha256"] = None
    return c


def _hash_matches(file: dict, want: str) -> bool:
    """want: a full SHA256 or a short CivitAI hash (AutoV2/AutoV3/CRC32...)."""
    want = (want or "").lower()
    return bool(want) and any(str(v).lower() == want for v in (file.get("hashes") or {}).values())


async def civitai_by_version(version_id, want_hash: str | None = None) -> dict | None:
    """-> candidate for a model version (the file matching want_hash, else the
    primary one), or None when CivitAI says 404. Other errors raise."""
    v = await net.get_json(f"{net.CIVITAI_BASE}/api/v1/model-versions/{int(version_id)}")
    if not v or not v.get("files"):
        return None
    model = dict(v.get("model") or {})
    model.setdefault("id", v.get("modelId"))
    files = v["files"]
    f = next((f for f in files if _hash_matches(f, want_hash)), None) \
        or next((f for f in files if f.get("primary")), files[0])
    return _civ_file_cand(model, v, f, "high")


async def from_civitai(filename: str, folder: str | None) -> list[dict]:
    want = basename(filename).lower()
    want_stem = stem(want)
    toks = core_tokens(filename)
    queries = []
    for n in (4, 2):
        q = " ".join(toks[:n])
        if q and q not in queries:
            queries.append(q)
    exact, loose = [], []
    seen = set()
    for q in queries:
        params = [("query", q), ("limit", "10"), ("nsfw", "true")]
        params += [("types", t) for t in CIVITAI_TYPES.get(canonical(folder) or "", [])]
        try:
            res = await net.get_json(f"{net.CIVITAI_BASE}/api/v1/models", params=params)
        except Exception:
            continue
        for m in (res or {}).get("items", []):
            for v in m.get("modelVersions", []):
                for f in v.get("files", []):
                    key = (v.get("id"), f.get("id"))
                    if key in seen:
                        continue
                    seen.add(key)
                    name = (f.get("name") or "").lower()
                    if name == want:
                        exact.append(_civ_file_cand(m, v, f, "high"))
                    elif stem(name) and (stem(name) in want_stem or want_stem in stem(name)):
                        loose.append(_civ_file_cand(m, v, f, "medium"))
            if not exact and not loose and m.get("modelVersions"):
                v = m["modelVersions"][0]
                f = next((f for f in v.get("files", []) if f.get("primary")), None)
                if f and len(loose) < 3:
                    loose.append(_civ_file_cand(m, v, f, "low"))
        if exact:
            break
    return exact[:5] + loose[:4]


# ----------------------------------------------------------- pasted links
_CIV_MODEL = re.compile(r"/models/(\d+)")
_CIV_DOWNLOAD = re.compile(r"/api/download/models/(\d+)")
_HF_FILE = re.compile(r"^/([^/]+/[^/]+)/(?:blob|resolve)/([^/]+)/(.+)$")


async def from_url(url: str) -> dict:
    """A pasted link -> download candidate. Understands CivitAI model pages and
    download links (exact file, SHA256 and metadata) and HuggingFace file pages
    (/blob/ -> /resolve/, SHA256 from the repo listing). Anything else is
    downloaded as-is."""
    from urllib.parse import parse_qs, unquote, urlparse
    u = urlparse(url)
    host = (u.hostname or "").lower()
    if host in ("civitai.com", "civitai.red", "civitai.green", "www.civitai.com"):
        vid = (parse_qs(u.query).get("modelVersionId") or [None])[0]
        m = _CIV_DOWNLOAD.search(u.path)
        if m:
            vid = m.group(1)
        if not vid:
            mm = _CIV_MODEL.search(u.path)
            if mm:
                model = await net.get_json(f"{net.CIVITAI_BASE}/api/v1/models/{mm.group(1)}")
                versions = (model or {}).get("modelVersions") or []
                vid = versions[0].get("id") if versions else None
        if vid:
            c = await civitai_by_version(vid)
            if c:
                if m:
                    c["url"] = net.canonical_download_url(url)  # keep the exact file they linked
                    if u.query:  # ?type= / ?format= may pick a non-primary file: its hash is unknown
                        c["sha256"] = None
                        c["meta"]["hashes"] = {}
                return c
        raise ValueError("Couldn't find a downloadable version on that CivitAI page")
    if net.is_hf(url):
        m = _HF_FILE.match(u.path)
        if m:
            repo, rev, path = m.group(1), m.group(2), unquote(m.group(3))
            dl = f"{net.HF_BASE}/{repo}/resolve/{rev}/{quote(path)}"
            sha = size = None
            if rev == "main":
                f = next((f for f in await hf_tree(repo) if f.get("path") == path), None)
                if f:
                    lfs = f.get("lfs") or {}
                    sha, size = lfs.get("oid") or lfs.get("sha256"), f.get("size") or lfs.get("size")
            return _cand("huggingface", dl, basename(path), confidence="high", sha256=sha, size=size,
                         page_url=f"{net.HF_BASE}/{repo}", title=f"{repo}/{path}")
    return _cand("manual", url, basename(u.path) or "download", confidence="medium")


# ----------------------------------------------------------- CivArchive
async def from_civarchive(filename: str, folder: str | None, embedded: dict | None = None) -> list[dict]:
    """Copies CivArchive lists: by the workflow's embedded SHA256 when there is
    one, else by exact file name. Never raises (it's the last resort)."""
    try:
        sha = (embedded or {}).get("hash") if ((embedded or {}).get("hash_type") or "sha256").lower() == "sha256" else None
        recs = [r for r in [await civarchive.by_hash(sha)] if r] if sha else await civarchive.by_name(filename)
    except Exception:
        return []
    out = []
    for rec in recs:
        out += civarchive.candidates(rec, filename, folder)
    return out


# ----------------------------------------------------------- orchestrator
async def from_templates(filename: str) -> list[dict]:
    """ComfyUI's own workflow templates list the official link of every model they load."""
    from . import companions
    m = companions.template_model(filename)
    if not m:
        return []
    title = f"{m['name']} (ComfyUI's {m['template']} template)"
    try:
        c = await from_url(m["url"])  # HuggingFace: SHA256 and size from the repo listing
    except Exception:
        c = _cand("template", m["url"], m["name"], confidence="high")
    c.update(source="template", confidence="high", folder=m["folder"], title=title, filename=m["name"])
    return [c]


async def resolve(filename: str, folder: str | None, embedded: dict | None = None) -> list[dict]:
    cands: list[dict] = []
    if embedded and embedded.get("url", "").startswith("https://"):
        cands.append(_cand("workflow", embedded["url"], basename(filename), confidence="high",
                           folder=canonical(embedded.get("directory")) or folder))
    if embedded and embedded.get("hash") and (embedded.get("hash_type") or "sha256").lower() == "sha256":
        r = registry.lookup_hash(embedded["hash"])
        if r:
            cands.append(_cand("registry", r["url"], r["filename"], confidence="high", sha256=r.get("sha256"),
                               size=r.get("size"), page_url=r.get("page_url"), title=r.get("title")))
        try:
            c = await civitai_by_hash(embedded["hash"])
        except Exception:
            c = None
        if c:
            c["source"] = "hash"
            cands.append(c)
    r = registry.lookup(filename)
    if r:
        cands.append(_cand("registry", r["url"], r["filename"], confidence="high", sha256=r.get("sha256"),
                           size=r.get("size"), page_url=r.get("page_url"), title=r.get("title"),
                           folder=r.get("folder")))
    if not any(c["confidence"] == "high" for c in cands):
        cands += await from_templates(filename)
    if not any(c["confidence"] == "high" for c in cands):
        cands += await from_manager(filename)
    if not any(c["confidence"] == "high" for c in cands):
        hf, cv = await asyncio.gather(from_huggingface(filename), from_civitai(filename, folder))
        cands += hf + cv
    if not any(c["confidence"] == "high" for c in cands) and civarchive.enabled():
        cands += await from_civarchive(filename, folder, embedded)
    # dedupe by url, rank
    seen, out = set(), []
    for c in sorted(cands, key=lambda c: (CONF_RANK[c["confidence"]], SRC_RANK.get(c["source"], 9))):
        if c["url"] and c["url"] not in seen:
            seen.add(c["url"])
            out.append(c)
    return out[:10]
