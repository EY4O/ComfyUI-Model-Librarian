"""Shared aiohttp session + host-aware auth headers."""
from __future__ import annotations

import asyncio
import os
from urllib.parse import urlparse

import aiohttp

from . import config

HF_BASE = os.environ.get("SMF_HF_BASE", "https://huggingface.co").rstrip("/")
CIVITAI_BASE = os.environ.get("SMF_CIVITAI_BASE", "https://civitai.com").rstrip("/")
MANAGER_LIST_URL = os.environ.get(
    "SMF_MANAGER_LIST_URL",
    "https://raw.githubusercontent.com/Comfy-Org/ComfyUI-Manager/main/model-list.json",
)
USER_AGENT = "ComfyUI-SM-Model-Fetcher/1.0"

_session: aiohttp.ClientSession | None = None


def session() -> aiohttp.ClientSession:
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(
            trust_env=True,  # honour HTTPS_PROXY etc.
            headers={"User-Agent": USER_AGENT},
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=20, sock_read=60),
        )
    return _session


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def is_hf(url: str) -> bool:
    # exact hosts only: CDN subdomains get signed URLs and must never see the token
    h = _host(url)
    return h == _host(HF_BASE) or h in ("huggingface.co", "hf.co")


def is_civitai(url: str) -> bool:
    h = _host(url)
    return h == _host(CIVITAI_BASE) or h in ("civitai.com", "civitai.green", "civitai.red")


def canonical_download_url(url: str) -> str:
    """CivitAI's API key authenticates downloads on civitai.com; civitai.red
    download links point at the same files (LoRA Manager rewrites them too)."""
    p = urlparse(url)
    if (p.hostname or "").lower() == "civitai.red" and p.path.startswith("/api/download/"):
        return p._replace(netloc="civitai.com").geturl()
    return url


def auth_headers(url: str, cfg: dict | None = None) -> dict:
    """Credentials are only ever attached to the service they belong to."""
    cfg = cfg or config.load()
    if is_hf(url) and cfg.get("hf_token"):
        return {"Authorization": f"Bearer {cfg['hf_token']}"}
    if is_civitai(url) and cfg.get("civitai_token"):
        return {"Authorization": f"Bearer {cfg['civitai_token']}"}
    return {}


RETRY_STATUS = (429, 502, 503, 504)
MAX_TRIES = 4


def _retry_delay(r, attempt: int) -> float:
    try:
        return min(30.0, max(0.5, float(r.headers.get("Retry-After", ""))))
    except ValueError:
        return min(30.0, 2.0 * 2 ** attempt)  # 2, 4, 8 s


async def _fetch_json(url: str, params, timeout: float):
    """-> (data, rel=next url). 404 -> (None, None). Rate limits / gateway errors
    are retried with backoff (Retry-After honoured) before giving up."""
    for attempt in range(MAX_TRIES):
        async with session().get(
            url, params=params, headers=auth_headers(url), timeout=aiohttp.ClientTimeout(total=timeout)
        ) as r:
            if r.status == 404:
                return None, None
            if r.status in RETRY_STATUS and attempt < MAX_TRIES - 1:
                delay = _retry_delay(r, attempt)
            else:
                r.raise_for_status()
                data = await r.json(content_type=None)
                try:
                    nxt = str(r.links.get("next", {}).get("url") or "") or None
                except Exception:
                    nxt = None
                return data, nxt
        await asyncio.sleep(delay)


async def get_json(url: str, params: dict | None = None, timeout: float = 30):
    return (await _fetch_json(url, params, timeout))[0]


async def get_json_with_links(url: str, params: dict | None = None, timeout: float = 30):
    """Like get_json but also returns the rel=next URL (HF pagination)."""
    return await _fetch_json(url, params, timeout)


async def close():
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None
