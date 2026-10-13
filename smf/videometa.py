"""Text metadata from video files (standard library only).

Where ComfyUI puts the workflow in a video:
* Save Video (MP4, through PyAV with use_metadata_tags): QuickTime metadata
  keys `prompt` and `workflow` (moov/meta: hdlr mdta, keys, ilst).
* Video Helper Suite (MP4 / WebM through ffmpeg): one `comment` holding
  {"prompt": ..., "workflow": ...} -- iTunes ©cmt in MP4, a COMMENT tag in WebM.
* Save WEBM: Matroska tags named after the keys.

read(path) -> {"format": "mp4" | "webm" | None, "text": {key: str}}; a
`comment` with prompt/workflow inside is unpacked into those keys. Only the
parts of the file that hold metadata are read, so large videos are fine.
"""
from __future__ import annotations

import json
import os
import struct

_ILST_NAMES = {b"\xa9cmt": "comment", b"\xa9nam": "title", b"\xa9too": "encoder", b"desc": "description", b"\xa9des": "description"}
_CONTAINERS = {b"moov", b"udta", b"meta", b"ilst", b"trak", b"mdia"}
_MAX_BOX = 64 * 1024 * 1024  # metadata boxes are small; skip anything bigger without reading it


def _boxes(f, start: int, end: int):
    """Yield (type, payload_start, payload_end) for the boxes in [start, end)."""
    pos = start
    while pos + 8 <= end:
        f.seek(pos)
        head = f.read(8)
        if len(head) < 8:
            return
        size, kind = struct.unpack(">I4s", head)
        hdr = 8
        if size == 1:
            ext = f.read(8)
            if len(ext) < 8:
                return
            size = struct.unpack(">Q", ext)[0]
            hdr = 16
        elif size == 0:
            size = end - pos
        if size < hdr or pos + size > end:
            return
        yield kind, pos + hdr, pos + size
        pos += size


def _data_value(f, start: int, end: int) -> str | None:
    """The UTF-8 payload of the first 'data' box under an ilst item."""
    for kind, s, e in _boxes(f, start, end):
        if kind == b"data" and e - s >= 8 and e - s < _MAX_BOX:
            f.seek(s + 8)  # type (4) + locale (4)
            return f.read(e - s - 8).decode("utf-8", "replace").rstrip("\0")
    return None


def _mp4(f, size: int) -> dict:
    out: dict[str, str] = {}

    def walk(start, end, depth=0, keys=None):
        for kind, s, e in _boxes(f, start, end):
            if kind == b"meta":
                # ISO 'meta' is a full box (4 bytes version/flags); QuickTime's isn't
                f.seek(s)
                first = f.read(12)
                known = (b"hdlr", b"keys", b"ilst")
                inner = s if first[4:8] in known else s + 4 if first[8:12] in known else s
                local_keys = None
                for k2, s2, e2 in _boxes(f, inner, e):
                    if k2 == b"keys" and e2 - s2 < _MAX_BOX:
                        f.seek(s2 + 4)
                        count = struct.unpack(">I", f.read(4))[0]
                        local_keys, p = [], s2 + 8
                        for _ in range(min(count, 1024)):
                            f.seek(p)
                            ksize, _ns = struct.unpack(">I4s", f.read(8))
                            local_keys.append(f.read(max(0, ksize - 8)).decode("utf-8", "replace"))
                            p += ksize
                for k2, s2, e2 in _boxes(f, inner, e):
                    if k2 == b"ilst":
                        for item, s3, e3 in _boxes(f, s2, e2):
                            if local_keys is not None and item[:1] == b"\0":
                                idx = struct.unpack(">I", item)[0]
                                name = local_keys[idx - 1] if 0 < idx <= len(local_keys) else None
                            elif item == b"----":
                                name = None
                                for k4, s4, e4 in _boxes(f, s3, e3):
                                    if k4 == b"name" and e4 - s4 > 4:
                                        f.seek(s4 + 4)
                                        name = f.read(e4 - s4 - 4).decode("utf-8", "replace")
                            else:
                                name = _ILST_NAMES.get(item)
                            if name:
                                v = _data_value(f, s3, e3)
                                if v:
                                    out.setdefault(name, v)
            elif kind in _CONTAINERS and depth < 4:
                walk(s, e, depth + 1)

    walk(0, size)
    return out


# ---------------------------------------------------------------- Matroska / WebM
_SIMPLE_TAG, _TAG_NAME, _TAG_STRING = b"\x67\xc8", b"\x45\xa3", b"\x44\x87"


def _vint(buf: bytes, i: int):
    """EBML variable-size integer at buf[i] -> (value, length)."""
    if i >= len(buf):
        return None, 0
    b = buf[i]
    for n in range(8):
        if b & (0x80 >> n):
            v = b & (0xFF >> (n + 1))
            if i + n >= len(buf):
                return None, 0
            for k in range(1, n + 1):
                v = (v << 8) | buf[i + k]
            return v, n + 1
    return None, 0


def _mkv_tags(buf: bytes) -> dict:
    out: dict[str, str] = {}
    i = 0
    while True:
        i = buf.find(_SIMPLE_TAG, i)
        if i < 0:
            return out
        size, n = _vint(buf, i + 2)
        if size is None or size > 32 * 1024 * 1024:
            i += 2
            continue
        body = buf[i + 2 + n:i + 2 + n + size]
        name = val = None
        j = 0
        while j + 3 <= len(body):
            eid = body[j:j + 2]
            sz, m = _vint(body, j + 2)
            if sz is None:
                break
            data = body[j + 2 + m:j + 2 + m + sz]
            if eid == _TAG_NAME:
                name = data.decode("utf-8", "replace")
            elif eid == _TAG_STRING:
                val = data.decode("utf-8", "replace")
            j += 2 + m + sz
        if name and val:
            out.setdefault(name.lower(), val)
        i += 2 + n + max(size, 1)


def _unpack(text: dict) -> dict:
    """Video Helper Suite's comment holds {"prompt": ..., "workflow": ...}."""
    for key in ("comment", "description"):
        raw = text.get(key)
        if isinstance(raw, str) and raw.lstrip().startswith("{"):
            try:
                d = json.loads(raw, parse_constant=lambda _c: None)
            except ValueError:
                continue
            if isinstance(d, dict):
                for k in ("prompt", "workflow"):
                    if k in d and k not in text:
                        text[k] = d[k] if isinstance(d[k], str) else json.dumps(d[k])
    return text


def read(path: str) -> dict:
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        head = f.read(16)
        if head[4:8] in (b"ftyp", b"moov", b"mdat", b"free", b"wide"):
            return {"format": "mp4", "text": _unpack(_mp4(f, size))}
        if head[:4] == b"\x1a\x45\xdf\xa3":
            # tags sit near the start (ffmpeg writes them in the header) or at the end
            chunk = 16 * 1024 * 1024
            f.seek(0)
            buf = f.read(chunk)
            if size > chunk:
                f.seek(max(chunk, size - chunk))
                buf += f.read(chunk)
            return {"format": "webm", "text": _unpack(_mkv_tags(buf))}
    return {"format": None, "text": {}}


VIDEO_EXTS = (".mp4", ".m4v", ".mov", ".webm", ".mkv")


def is_video(filename: str | None, content_type: str | None = None) -> bool:
    return bool((content_type or "").startswith("video/") or (filename or "").lower().endswith(VIDEO_EXTS))
