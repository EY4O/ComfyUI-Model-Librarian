"""Read generation metadata embedded in image files (standard library only).

- PNG:  tEXt / zTXt / iTXt chunks (ComfyUI `prompt` + `workflow`, A1111
        `parameters`, NovelAI `Comment`, InvokeAI `invokeai_metadata`, …)
- JPEG: EXIF UserComment / ImageDescription (APP1), COM segments, XMP
- WebP: EXIF / XMP chunks

`read(data)` -> {"format": "png"|"jpeg"|"webp"|None, "text": {key: str}}
EXIF fields appear as text["UserComment"], text["ImageDescription"],
text["XPComment"]; JPEG comments as text["Comment"]; XMP as text["XMP"].
"""
from __future__ import annotations

import struct
import zlib

PNG_SIG = b"\x89PNG\r\n\x1a\n"
MAX_TEXT = 32 * 1024 * 1024  # a single metadata value; workflows can be large


def read(data: bytes) -> dict:
    if data[:8] == PNG_SIG:
        return {"format": "png", "text": _png(data)}
    if data[:2] == b"\xff\xd8":
        return {"format": "jpeg", "text": _jpeg(data)}
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return {"format": "webp", "text": _webp(data)}
    return {"format": None, "text": {}}


# ---------------------------------------------------------------- PNG
def _latin1(b: bytes) -> str:
    return b.decode("latin-1", "replace")


def _png(data: bytes) -> dict:
    out: dict[str, str] = {}
    pos = 8
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        pos += 12 + length
        try:
            if ctype == b"tEXt":
                k, _, v = body.partition(b"\0")
                out.setdefault(_latin1(k), _latin1(v))
            elif ctype == b"zTXt":
                k, _, rest = body.partition(b"\0")
                out.setdefault(_latin1(k), _latin1(zlib.decompress(rest[1:], bufsize=MAX_TEXT)))
            elif ctype == b"iTXt":
                k, _, rest = body.partition(b"\0")
                compressed, rest = rest[0], rest[2:]          # flag, method
                _lang, _, rest = rest.partition(b"\0")
                _tkey, _, text = rest.partition(b"\0")
                if compressed:
                    text = zlib.decompress(text, bufsize=MAX_TEXT)
                out.setdefault(_latin1(k), text.decode("utf-8", "replace"))
            elif ctype == b"eXIf":
                out.update({k: v for k, v in _exif(body).items() if k not in out})
            elif ctype == b"IEND":
                break
        except (zlib.error, IndexError, ValueError):
            continue
    return out


# ---------------------------------------------------------------- EXIF (TIFF)
_EXIF_IFD, _USER_COMMENT, _IMAGE_DESC, _XP_COMMENT = 0x8769, 0x9286, 0x010E, 0x9C9C
_TYPE_SIZE = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 7: 1, 9: 4, 10: 8}


def _decode_user_comment(raw: bytes) -> str:
    head, body = raw[:8], raw[8:]
    if head.startswith(b"UNICODE"):
        # A1111/piexif write UTF-16 big-endian; some tools write little-endian.
        enc = "utf-16-le" if body[1:2] == b"\0" and body[:1] != b"\0" else "utf-16-be"
        return body.decode(enc, "replace").rstrip("\0")
    if head.startswith(b"ASCII") or head == b"\0" * 8:
        return body.decode("utf-8", "replace").rstrip("\0")
    return raw.decode("utf-8", "replace").rstrip("\0")


def _exif(tiff: bytes) -> dict:
    if tiff[:6] == b"Exif\0\0":
        tiff = tiff[6:]
    if len(tiff) < 8 or tiff[:2] not in (b"II", b"MM"):
        return {}
    e = "<" if tiff[:2] == b"II" else ">"
    out: dict[str, str] = {}

    def entries(off: int):
        if off + 2 > len(tiff):
            return
        (n,) = struct.unpack(e + "H", tiff[off:off + 2])
        for i in range(min(n, 512)):
            p = off + 2 + 12 * i
            if p + 12 > len(tiff):
                return
            tag, typ, count = struct.unpack(e + "HHI", tiff[p:p + 8])
            size = _TYPE_SIZE.get(typ, 1) * count
            value = tiff[p + 8:p + 12] if size <= 4 else None
            if value is None:
                (voff,) = struct.unpack(e + "I", tiff[p + 8:p + 12])
                value = tiff[voff:voff + size]
            yield tag, typ, value[:size]

    try:
        (ifd0,) = struct.unpack(e + "I", tiff[4:8])
        exif_ifd = None
        for tag, typ, value in entries(ifd0):
            if tag == _EXIF_IFD:
                (exif_ifd,) = struct.unpack(e + "I", value[:4])
                continue
            if tag == _XP_COMMENT:
                out["XPComment"] = value.decode("utf-16-le", "replace").rstrip("\0")
                continue
            if typ != 2 or not 0x0100 <= tag <= 0x0110:
                continue
            text = value.decode("utf-8", "replace").rstrip("\0")
            # ComfyUI's animated WebP/AVIF: Model (0x0110) = "prompt:{...}", then Make,
            # ImageDescription, ... = "workflow:{...}" and any other extra keys
            key, sep, rest = text.partition(":")
            if sep and key.isidentifier() and rest.lstrip()[:1] in ("{", "["):
                out.setdefault(key, rest)
            elif tag == _IMAGE_DESC:
                out["ImageDescription"] = text
        if exif_ifd:
            for tag, typ, value in entries(exif_ifd):
                if tag == _USER_COMMENT:
                    out["UserComment"] = _decode_user_comment(value)
    except (struct.error, IndexError):
        pass
    return {k: v for k, v in out.items() if v.strip()}


# ---------------------------------------------------------------- JPEG
_XMP_NS = b"http://ns.adobe.com/xap/1.0/\0"


def _jpeg(data: bytes) -> dict:
    out: dict[str, str] = {}
    pos = 2
    while pos + 4 <= len(data):
        if data[pos] != 0xFF:
            break
        marker = data[pos + 1]
        if marker in (0xD9, 0xDA):  # end of image / start of scan: no more metadata
            break
        if marker == 0x01 or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        (length,) = struct.unpack(">H", data[pos + 2:pos + 4])
        seg = data[pos + 4:pos + 2 + length]
        pos += 2 + length
        if marker == 0xE1 and seg.startswith(b"Exif\0\0"):
            out.update({k: v for k, v in _exif(seg).items() if k not in out})
        elif marker == 0xE1 and seg.startswith(_XMP_NS):
            out.setdefault("XMP", seg[len(_XMP_NS):].decode("utf-8", "replace"))
        elif marker == 0xFE:
            out.setdefault("Comment", seg.decode("utf-8", "replace").rstrip("\0"))
    return out


# ---------------------------------------------------------------- WebP
def _webp(data: bytes) -> dict:
    out: dict[str, str] = {}
    pos = 12
    while pos + 8 <= len(data):
        fourcc = data[pos:pos + 4]
        (size,) = struct.unpack("<I", data[pos + 4:pos + 8])
        body = data[pos + 8:pos + 8 + size]
        pos += 8 + size + (size & 1)
        if fourcc == b"EXIF":
            out.update({k: v for k, v in _exif(body).items() if k not in out})
        elif fourcc == b"XMP ":
            out.setdefault("XMP", body.decode("utf-8", "replace"))
    return out
