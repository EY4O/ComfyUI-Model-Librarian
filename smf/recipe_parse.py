"""Turn image metadata into a recipe (shared format, see docs/RECIPE_FORMAT.md).

Understands ComfyUI (API `prompt` graph, or the UI `workflow` when that's all
there is), A1111/Forge `parameters` (incl. Model/Lora hashes and Civitai
resources), NovelAI, InvokeAI, SwarmUI, Fooocus, Prompto share cards, and
Civitai's image API. Ported from Prompto's parsers (lib/pngmeta.js,
lib/civitai.js) and extended: hashes and Civitai version ids are kept, CLIP
strengths too, and LoRA stacks (rgthree, LoRA Manager, CR/Efficiency) count.
"""
from __future__ import annotations

import json
import math
import re

from . import imagemeta

def _loads(s):
    """json.loads, but NaN/Infinity (which ComfyUI writes into PNGs) become None:
    browsers can't parse them."""
    return json.loads(s, parse_constant=lambda _c: None)


def clean(o):
    """Replace non-finite floats with None, recursively."""
    if isinstance(o, float):
        return o if math.isfinite(o) else None
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    return o


SCHEMA = "recipe/1"


class NoMetadata(ValueError):
    pass


def empty() -> dict:
    return {
        "schema": SCHEMA, "id": None, "title": "", "created": None, "format": "",
        "source": {"url": None, "site": None, "filename": None, "image_id": None},
        "prompt": {"positive": "", "negative": ""},
        "settings": {"sampler": None, "scheduler": None, "sampler_raw": None, "steps": None, "cfg": None,
                     "seed": None, "width": None, "height": None, "denoise": None, "clip_skip": None},
        "model": None, "vae": None, "loras": [], "base_model": None,
        "tags": [], "notes": "", "comfy": None,
    }


def _ref(name=None, file=None, hash=None, version_id=None, model_id=None, **extra) -> dict:
    out = {"name": name or (_stem(file) if file else None), "file": file, "hash": (str(hash).lower() if hash else None),
           "civitai_version_id": _int(version_id), "civitai_model_id": _int(model_id)}
    out.update({k: v for k, v in extra.items() if v is not None})
    return out


def _lora(name=None, file=None, weight=1.0, clip_weight=None, **kw) -> dict:
    d = _ref(name, file, **kw)
    d["weight"] = _num(weight, 1.0)
    d["clip_weight"] = _num(clip_weight) if clip_weight is not None else None
    return d


# ---------------------------------------------------------------- helpers
def _num(v, default=None):
    try:
        f = float(v)
        return int(f) if f.is_integer() and not isinstance(v, float) and "." not in str(v) else f
    except (TypeError, ValueError):
        return default


def _int(v):
    try:
        return int(v) if v not in (None, "", 0, "0") else None
    except (TypeError, ValueError):
        return None


def _stem(p: str | None) -> str | None:
    if not p:
        return None
    b = str(p).replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(safetensors|ckpt|pt|pth|bin|gguf|sft)$", "", b, flags=re.I)


def _key(l: dict) -> str:
    return (l.get("hash") or "")[:10] or str(l.get("civitai_version_id") or "") or (_stem(l.get("file")) or l.get("name") or "").lower()


def _compatible(a: dict, b: dict) -> bool:
    """No conflicting version id or hash (hashes compare on the shorter prefix)."""
    if a.get("civitai_version_id") and b.get("civitai_version_id") and a["civitai_version_id"] != b["civitai_version_id"]:
        return False
    ha, hb = (a.get("hash") or "").lower(), (b.get("hash") or "").lower()
    n = min(len(ha), len(hb))
    return not (n and ha[:n] != hb[:n])


def _pair_resources(loras: list) -> list:
    """Civitai lists a LoRA twice: as a <lora:file:w> prompt tag and as a resource
    with only a display name + version id (or hash). A resource that matched
    nothing is folded into the one prompt-tag entry with the same strength."""
    out = [l for l in loras if l.get("_src") != "res"]
    for res in (l for l in loras if l.get("_src") == "res"):
        cands = [l for l in out if l.get("_src") == "tag" and _compatible(l, res)
                 and abs((l.get("weight") or 0) - (res.get("weight") or 0)) < 1e-6]
        if len(cands) == 1:
            tgt = cands[0]
            for k in ("civitai_version_id", "civitai_model_id", "hash", "version"):
                if res.get(k) and not tgt.get(k):
                    tgt[k] = res[k]
            if res.get("name") and res.get("name") != tgt.get("name") and not tgt.get("display_name"):
                tgt["display_name"] = res["name"]
        else:
            out.append(res)
    for l in out:
        l.pop("_src", None)
    return out


def _merge_lora(loras: list, new: dict) -> None:
    """Add or enrich: the same LoRA found by name, hash or version id merges."""
    nk = {_key(new), (_stem(new.get("file")) or "").lower(), (new.get("name") or "").lower()} - {""}
    for l in loras:
        lk = {_key(l), (_stem(l.get("file")) or "").lower(), (l.get("name") or "").lower()} - {""}
        if nk & lk or (new.get("civitai_version_id") and new["civitai_version_id"] == l.get("civitai_version_id")):
            for k, v in new.items():
                if v is not None and l.get(k) in (None, "", 1.0) and k not in ("weight", "_src"):
                    l[k] = v
            return
    loras.append(new)


# A1111-style sampler names -> ComfyUI sampler + scheduler (from Prompto).
SAMPLERS = {
    "euler a": "euler_ancestral", "euler": "euler", "heun": "heun", "lms": "lms", "ddim": "ddim", "unipc": "uni_pc",
    "lcm": "lcm", "dpm2": "dpm_2", "dpm2 a": "dpm_2_ancestral", "dpm fast": "dpm_fast", "dpm adaptive": "dpm_adaptive",
    "dpm++ 2m": "dpmpp_2m", "dpm++ 2m sde": "dpmpp_2m_sde", "dpm++ 2s a": "dpmpp_2s_ancestral", "dpm++ sde": "dpmpp_sde",
    "dpm++ 3m sde": "dpmpp_3m_sde", "restart": "restart", "res multistep": "res_multistep", "er sde": "er_sde",
    "dpm++ 2m sde gpu": "dpmpp_2m_sde_gpu", "dpm++ 3m sde gpu": "dpmpp_3m_sde_gpu", "euler cfg++": "euler_cfg_pp",
}
SCHEDULERS = {"karras": "karras", "exponential": "exponential", "sgm uniform": "sgm_uniform", "simple": "simple",
              "normal": "normal", "beta": "beta", "align your steps": "align_your_steps", "ddim uniform": "ddim_uniform",
              "kl optimal": "kl_optimal", "linear quadratic": "linear_quadratic", "automatic": None}


def map_sampler(name, schedule_type=None) -> tuple[str | None, str | None]:
    s = str(name or "").strip()
    if not s:
        return None, (SCHEDULERS.get(str(schedule_type).lower()) if schedule_type else None)
    sched = None
    low = s.lower()
    for k, v in SCHEDULERS.items():
        if low.endswith(" " + k):
            sched, s = v, s[:-len(k) - 1]
            break
    if not sched and schedule_type:
        st = str(schedule_type).lower()
        sched = SCHEDULERS.get(st, st.replace(" ", "_"))
    samp = SAMPLERS.get(s.lower()) or (s if re.fullmatch(r"[a-z0-9_]+", s) else s.lower().replace("++", "pp").replace(" ", "_"))
    return samp, sched


_LORA_TAG = re.compile(r"<(?:lora|lyco):([^:>]+)(?::(-?[\d.]+))?(?::(-?[\d.]+))?>", re.I)


def _take_lora_tags(text: str, loras: list) -> str:
    def repl(m):
        _merge_lora(loras, _lora(file=m.group(1).strip(), weight=m.group(2) or 1, clip_weight=m.group(3), _src="tag"))
        return ""
    out = re.sub(_LORA_TAG.pattern + r",?\s*", repl, text or "", flags=re.I)  # the tag and the separator after it
    return re.sub(r"[ \t]{2,}", " ", re.sub(r"\s*,\s*(,\s*)+", ", ", out)).strip().strip(",").strip()


def _balanced(s: str, start: int) -> str | None:
    """The JSON object/array starting at s[start] (brace matching, string-aware)."""
    open_c = s[start]
    close_c = "}" if open_c == "{" else "]"
    depth, i, in_str, esc = 0, start, False, False
    while i < len(s):
        c = s[i]
        if in_str:
            esc = (c == "\\" and not esc)
            if c == '"' and not esc:
                in_str = False
        elif c == '"':
            in_str = True
        elif c == open_c:
            depth += 1
        elif c == close_c:
            depth -= 1
            if depth == 0:
                return s[start:i + 1]
        if c != "\\":
            esc = False
        i += 1
    return None


# ---------------------------------------------------------------- A1111 / Forge / Civitai text
def parse_a1111(text: str, pair: bool = True) -> dict:
    r = empty()
    r["format"] = "a1111"
    lines = text.strip().split("\n")
    idx = next((i for i, l in enumerate(lines) if re.match(r"^\s*Steps:\s*\d+", l)), -1)
    head = lines if idx == -1 else lines[:idx]
    neg_i = next((i for i, l in enumerate(head) if l.startswith("Negative prompt:")), -1)
    positive = "\n".join(head if neg_i == -1 else head[:neg_i]).strip()
    negative = "" if neg_i == -1 else re.sub(r"^Negative prompt:\s*", "", "\n".join(head[neg_i:])).strip()
    tail = "" if idx == -1 else ", ".join(lines[idx:])
    # JSON blobs first (they contain commas): Hashes, Civitai resources/metadata
    blobs = {}
    for key in ("Hashes", "Civitai resources", "Civitai metadata"):
        m = re.search(re.escape(key) + r":\s*([\[{])", tail)
        if m:
            raw = _balanced(tail, m.start(1))
            if raw:
                try:
                    blobs[key] = _loads(raw)
                except ValueError:
                    pass
                tail = tail[:m.start()] + tail[m.start(1) + len(raw):]
    kv = {}
    for m in re.finditer(r'([A-Za-z][\w /\-]*?):\s*("(?:\\.|[^"\\])*"|[^,]*)(?:,|$)', tail):
        v = m.group(2).strip()
        kv[m.group(1).strip()] = v[1:-1] if len(v) >= 2 and v[0] == '"' == v[-1] else v
    loras: list = []
    r["prompt"]["positive"] = _take_lora_tags(positive, loras)
    r["prompt"]["negative"] = negative
    s = r["settings"]
    s["sampler_raw"] = kv.get("Sampler")
    s["sampler"], s["scheduler"] = map_sampler(kv.get("Sampler"), kv.get("Schedule type"))
    s["steps"], s["cfg"], s["seed"] = _num(kv.get("Steps")), _num(kv.get("CFG scale")), _num(kv.get("Seed"))
    if "x" in kv.get("Size", ""):
        w, _, h = kv["Size"].partition("x")
        s["width"], s["height"] = _num(w), _num(h)
    s["denoise"] = _num(kv.get("Denoising strength"))
    s["clip_skip"] = _num(kv.get("Clip skip"))
    if kv.get("Model") or kv.get("Model hash"):
        r["model"] = _ref(name=kv.get("Model"), file=kv.get("Model"), hash=kv.get("Model hash"))
    if kv.get("VAE") or kv.get("VAE hash"):
        r["vae"] = _ref(name=kv.get("VAE"), file=kv.get("VAE"), hash=kv.get("VAE hash"))
    for pair in (kv.get("Lora hashes") or "").split(","):
        name, _, h = pair.partition(":")
        if name.strip() and h.strip():
            _merge_lora(loras, _lora(file=name.strip(), hash=h.strip()))
    hashes = blobs.get("Hashes") or {}
    if isinstance(hashes, dict):
        for k, h in hashes.items():
            if k == "model" and r["model"] is not None and not r["model"].get("hash"):
                r["model"]["hash"] = str(h).lower()
            elif k == "model" and r["model"] is None:
                r["model"] = _ref(hash=h)
            elif k.startswith("lora:"):
                _merge_lora(loras, _lora(file=k[5:], hash=h))
    for res in blobs.get("Civitai resources") or []:
        if not isinstance(res, dict):
            continue
        t = str(res.get("type", "")).lower()
        if t in ("checkpoint", "model"):
            m0 = r["model"] or _ref()
            m0["civitai_version_id"] = m0.get("civitai_version_id") or _int(res.get("modelVersionId"))
            m0["name"] = m0.get("name") or res.get("modelName")
            r["model"] = m0
        elif t in ("lora", "locon", "lycoris", "dora"):
            _merge_lora(loras, _lora(name=res.get("modelName"), weight=res.get("weight", 1),
                                     version_id=res.get("modelVersionId"), version=res.get("modelVersionName"), _src="res"))
    r["loras"] = _pair_resources(loras) if pair else loras
    return r


# ---------------------------------------------------------------- ComfyUI (API prompt graph)
_TEXT_KEYS = ("text", "text_g", "prompt", "positive", "t5xxl", "clip_l", "text_l", "string", "value", "wildcard_text", "populated_text")
_COND_KEYS = ("conditioning", "conditioning_1", "conditioning_to", "conditioning_from", "conditioning_2")
_SAMPLER_RE = re.compile(r"KSampler|SamplerCustom|Sampler \(|sampler", re.I)


def _is_link(v) -> bool:
    return isinstance(v, list) and len(v) == 2 and isinstance(v[1], int) and isinstance(v[0], (str, int))


def _node(g: dict, ref):
    return g.get(str(ref[0])) if _is_link(ref) else None


_ALIASES = {"sampler_name": ("sampler_name", "sampler"), "scheduler": ("scheduler", "scheduler_name"),
            "seed": ("seed", "noise_seed", "seed_value"), "noise_seed": ("noise_seed", "seed"), "cfg": ("cfg", "cfg_scale")}


def _scalar(g: dict, v, keys=("value", "seed", "noise_seed", "int", "number", "float", "steps", "cfg", "text", "string"),
            depth=0, want: str | None = None):
    """A literal value, following links to primitive/seed/text/parameter nodes.
    `want` is the input being resolved (e.g. "steps"): a linked node with an input
    of that name wins, then the input at the linked output's position (parameter
    nodes such as Image Saver's pass their inputs straight through), then `keys`."""
    if not _is_link(v):
        return v
    n = _node(g, v)
    if not n or depth > 4:
        return None
    inp = n.get("inputs") or {}
    for k in _ALIASES.get(want, (want,)) if want else ():
        if k in inp:
            return _scalar(g, inp[k], keys, depth + 1, want)
    vals = [x for k, x in inp.items() if not k.startswith("_")]
    slot = v[1]
    if slot > 0 and slot < len(vals):
        return _scalar(g, vals[slot], keys, depth + 1, want)
    for k in keys:
        if k in inp:
            return _scalar(g, inp[k], keys, depth + 1, want)
    return _scalar(g, vals[0], keys, depth + 1, want) if vals and want else None


_PART_KEY = re.compile(r"^(?:string|text)_?(?:[a-z]|\d+)$")


def _text_value(g: dict, v, depth=0) -> str | None:
    """A string input's value, following links through text and string-building
    nodes (StringConcatenate's string_a + string_b, text_a/text_b, text1/text2…)."""
    if isinstance(v, str):
        return v
    if not _is_link(v) or depth > 8:
        return None
    n = _node(g, v)
    if not n:
        return None
    inp = {str(k).lower(): x for k, x in (n.get("inputs") or {}).items()}  # some nodes say "Text"
    for k in ("populated_text", "text", "string", "value", "prompt", "text_g", "wildcard_text"):
        if isinstance(inp.get(k), str) and (k != "wildcard_text" or not isinstance(inp.get("populated_text"), str)):
            return inp[k]
    parts = [k for k in inp if _PART_KEY.match(k)]
    if parts:
        sep = inp.get("delimiter", inp.get("separator", " "))
        sep = sep if isinstance(sep, str) else " "
        vals = [t for t in (_text_value(g, inp[k], depth + 1) for k in parts) if t]
        return sep.join(vals) if vals else None
    for k in ("populated_text", "text", "string", "value", "prompt"):
        if _is_link(inp.get(k)):
            t = _text_value(g, inp[k], depth + 1)
            if t is not None:
                return t
    return None


def _trace_text(g: dict, ref, role: str, depth=0) -> tuple[str | None, str | None]:
    """Follow a conditioning link back to the node holding the prompt text."""
    n = _node(g, ref)
    if not n or depth > 10:
        return None, None
    inp = n.get("inputs") or {}
    for k in _TEXT_KEYS:
        v = inp.get(k)
        if isinstance(v, str):
            return v, str(ref[0])
        # a linked "positive" is conditioning passing through (Wan, ControlNet), not text
        if _is_link(v) and k in _TEXT_KEYS[:7] and k != "positive":
            t = _text_value(g, v)
            if isinstance(t, str):
                return t, str(ref[0])
    for k in (role,) + _COND_KEYS:
        if _is_link(inp.get(k)):
            t, nid = _trace_text(g, inp[k], role, depth + 1)
            if t is not None:
                return t, nid
    return None, None


def _find_sampler(g: dict):
    cands = [(k, n) for k, n in g.items() if isinstance(n, dict) and (
        _SAMPLER_RE.search(str(n.get("class_type", ""))) and any(x in (n.get("inputs") or {}) for x in ("positive", "guider", "sampler", "steps"))
    )]
    if not cands:
        return None, None

    def order(kn):
        k, _ = kn
        try:
            return (0, int(k))
        except ValueError:
            return (1, k)
    return sorted(cands, key=order)[0]


def _loader(g: dict, ref, depth=0, seen=None):
    """Trace a MODEL link back to its loader node."""
    seen = seen or set()
    n = _node(g, ref)
    if not n or depth > 20 or str(ref[0]) in seen:
        return None
    seen.add(str(ref[0]))
    inp = n.get("inputs") or {}
    for k in ("ckpt_name", "unet_name", "model_path"):
        if isinstance(inp.get(k), str):
            return n
    for k in ("model", "unet", "model1"):
        if _is_link(inp.get(k)):
            hit = _loader(g, inp[k], depth + 1, seen)
            if hit:
                return hit
    return None


def _graph_loras(g: dict, loras: list) -> None:
    for n in g.values():
        if not isinstance(n, dict):
            continue
        ct = str(n.get("class_type", ""))
        inp = n.get("inputs") or {}
        if "lora" not in ct.lower() and not any(k.startswith("lora_name") for k in inp):
            continue
        if isinstance(inp.get("lora_name"), str) and inp["lora_name"].lower() != "none":
            _merge_lora(loras, _lora(file=inp["lora_name"], weight=_scalar(g, inp.get("strength_model", inp.get("strength", 1))),
                                     clip_weight=_scalar(g, inp.get("strength_clip")) if "strength_clip" in inp else None))
        lst = inp.get("loras")
        lst = lst.get("__value__") if isinstance(lst, dict) else lst
        if isinstance(lst, list):  # LoRA Manager loader / stacker
            for e in lst:
                if isinstance(e, dict) and e.get("active", True) and e.get("name"):
                    _merge_lora(loras, _lora(file=e["name"], weight=e.get("strength", 1), clip_weight=e.get("clipStrength")))
        for k, v in inp.items():
            if isinstance(v, dict) and isinstance(v.get("lora"), str) and v.get("on", True) and v["lora"].lower() != "none":
                _merge_lora(loras, _lora(file=v["lora"], weight=v.get("strength", 1), clip_weight=v.get("strengthTwo")))  # rgthree
            m = re.fullmatch(r"lora_name_(\d+)", k)
            if m and isinstance(v, str) and v.lower() != "none":
                i = m.group(1)
                if str(inp.get(f"switch_{i}", "On")).lower() in ("off", "false"):
                    continue
                w = inp.get(f"model_weight_{i}", inp.get(f"lora_wt_{i}", inp.get(f"strength_{i}", 1)))
                _merge_lora(loras, _lora(file=v, weight=w, clip_weight=inp.get(f"clip_weight_{i}", inp.get(f"clip_str_{i}"))))


def parse_comfy_prompt(graph) -> dict:
    g = _loads(graph) if isinstance(graph, str) else graph
    if not isinstance(g, dict):
        raise ValueError("not a ComfyUI prompt graph")
    r = empty()
    r["format"] = "comfyui"
    sid, sn = _find_sampler(g)
    si = (sn or {}).get("inputs") or {}
    pos_ref, neg_ref, cfg = si.get("positive"), si.get("negative"), si.get("cfg")
    guider = _node(g, si.get("guider"))
    if guider:  # SamplerCustomAdvanced -> CFGGuider / BasicGuider
        gi = guider.get("inputs") or {}
        pos_ref = gi.get("positive", gi.get("conditioning"))
        neg_ref = gi.get("negative")
        cfg = gi.get("cfg", cfg)
    s = r["settings"]
    if pos_ref is not None:
        r["prompt"]["positive"] = _trace_text(g, pos_ref, "positive")[0] or ""
    if neg_ref is not None:
        pos_id = _trace_text(g, pos_ref, "positive")[1] if pos_ref is not None else None
        t, nid = _trace_text(g, neg_ref, "negative")
        r["prompt"]["negative"] = (t or "") if nid != pos_id else ""
    if not r["prompt"]["positive"]:
        encs = [n for n in g.values() if isinstance(n, dict) and "CLIPTextEncode" in str(n.get("class_type", ""))]
        texts = [next((v for k in _TEXT_KEYS if isinstance(v := (e.get("inputs") or {}).get(k), str)), None) for e in encs]
        texts = [t for t in texts if t is not None]
        if texts:
            r["prompt"]["positive"] = texts[0]
            r["prompt"]["negative"] = texts[1] if len(texts) > 1 else ""

    def from_linked(key, link_key):
        n = _node(g, si.get(link_key))
        return _scalar(g, (n.get("inputs") or {}).get(key), want=key) if n else None
    s["seed"] = _scalar(g, si.get("seed", si.get("noise_seed")), want="seed") if ("seed" in si or "noise_seed" in si) else from_linked("noise_seed", "noise")
    s["steps"] = _scalar(g, si["steps"], want="steps") if "steps" in si else from_linked("steps", "sigmas")
    s["cfg"] = _scalar(g, cfg, want="cfg")
    sampler = si.get("sampler_name") if "sampler_name" in si else from_linked("sampler_name", "sampler")
    s["sampler"] = _scalar(g, sampler, ("sampler_name", "value", "string", "text"), want="sampler_name")
    s["scheduler"] = _scalar(g, si.get("scheduler"), ("scheduler", "value", "string", "text"), want="scheduler") if "scheduler" in si else from_linked("scheduler", "sigmas")
    s["denoise"] = _scalar(g, si["denoise"], want="denoise") if "denoise" in si else from_linked("denoise", "sigmas")
    lat = _node(g, si.get("latent_image"))
    for n in ([lat] if lat else []) + [n for n in g.values() if isinstance(n, dict)]:
        inp = (n or {}).get("inputs") or {}
        w, h = _scalar(g, inp.get("width"), want="width"), _scalar(g, inp.get("height"), want="height")
        if isinstance(w, (int, float)) and isinstance(h, (int, float)):
            s["width"], s["height"] = int(w), int(h)
            break
    model_ref = si.get("model") or ((guider or {}).get("inputs") or {}).get("model")
    ld = _loader(g, model_ref) if model_ref else None
    if not ld:
        ld = next((n for n in g.values() if isinstance(n, dict) and any(isinstance((n.get("inputs") or {}).get(k), str) for k in ("ckpt_name", "unet_name"))), None)
    if ld:
        inp = ld.get("inputs") or {}
        f = inp.get("ckpt_name") or inp.get("unet_name")
        r["model"] = _ref(file=f, type="unet" if "unet_name" in inp else "checkpoint")
    for n in g.values():
        inp = (n or {}).get("inputs") or {} if isinstance(n, dict) else {}
        if isinstance(inp.get("vae_name"), str) and not r["vae"]:
            r["vae"] = _ref(file=inp["vae_name"])
        if isinstance(inp.get("stop_at_clip_layer"), int) and inp["stop_at_clip_layer"] < -1:
            s["clip_skip"] = -inp["stop_at_clip_layer"]
    loras: list = []
    _graph_loras(g, loras)
    r["loras"] = loras
    r["comfy"] = {"prompt": g}
    return r


# ---------------------------------------------------------------- ComfyUI (UI workflow only)
_WIDGET_ORDER = {
    "KSampler": ["seed", None, "steps", "cfg", "sampler_name", "scheduler", "denoise"],
    "KSamplerAdvanced": [None, "seed", None, "steps", "cfg", "sampler_name", "scheduler"],
}


def parse_comfy_workflow(wf) -> dict:
    w = _loads(wf) if isinstance(wf, str) else wf
    nodes = {n.get("id"): n for n in (w or {}).get("nodes", []) if isinstance(n, dict)}
    links = {l[0]: l for l in (w or {}).get("links", []) if isinstance(l, list) and len(l) >= 5}
    r = empty()
    r["format"] = "comfyui-workflow"
    s = r["settings"]
    loras: list = []

    def text_of(link_id, depth=0):
        l = links.get(link_id)
        n = nodes.get(l[1]) if l else None
        if not n or depth > 8:
            return None
        wv = n.get("widgets_values") or []
        if "CLIPTextEncode" in str(n.get("type")) and wv and isinstance(wv[0], str):
            return wv[0]
        for i in n.get("inputs") or []:
            if i.get("link") is not None and i.get("type") == "CONDITIONING":
                t = text_of(i["link"], depth + 1)
                if t is not None:
                    return t
        return None

    for n in sorted(nodes.values(), key=lambda n: n.get("id") or 0):
        t, wv = str(n.get("type")), n.get("widgets_values") or []
        if n.get("mode") in (2, 4):  # muted / bypassed
            continue
        if t in _WIDGET_ORDER and s["steps"] is None:
            for k, v in zip(_WIDGET_ORDER[t], wv):
                if k:
                    s[k if k != "sampler_name" else "sampler"] = v
            for i in n.get("inputs") or []:
                if i.get("name") in ("positive", "negative") and i.get("link") is not None:
                    r["prompt"][i["name"]] = text_of(i["link"]) or ""
        elif t in ("CheckpointLoaderSimple", "CheckpointLoader|pysssss") and wv and not r["model"]:
            r["model"] = _ref(file=wv[0], type="checkpoint")
        elif t in ("UNETLoader", "UnetLoaderGGUF") and wv and not r["model"]:
            r["model"] = _ref(file=wv[0], type="unet")
        elif t == "VAELoader" and wv and not r["vae"]:
            r["vae"] = _ref(file=wv[0])
        elif t in ("LoraLoader", "LoraLoaderModelOnly") and wv and isinstance(wv[0], str):
            _merge_lora(loras, _lora(file=wv[0], weight=wv[1] if len(wv) > 1 else 1, clip_weight=wv[2] if len(wv) > 2 else None))
        elif t.startswith("EmptyLatentImage") or t == "EmptySD3LatentImage":
            if len(wv) >= 2:
                s["width"], s["height"] = wv[0], wv[1]
        for v in wv:  # rgthree rows / LoRA Manager lists
            if isinstance(v, dict) and isinstance(v.get("lora"), str) and v.get("on", True):
                _merge_lora(loras, _lora(file=v["lora"], weight=v.get("strength", 1), clip_weight=v.get("strengthTwo")))
            lst = v.get("__value__") if isinstance(v, dict) else v
            if isinstance(lst, list) and "LoraManager" in t:
                for e in lst:
                    if isinstance(e, dict) and e.get("active") and e.get("name"):
                        _merge_lora(loras, _lora(file=e["name"], weight=e.get("strength", 1), clip_weight=e.get("clipStrength")))
    r["loras"] = loras
    r["comfy"] = {"workflow": w}
    return r


# ---------------------------------------------------------------- other generators
def parse_novelai(comment, text: dict) -> dict:
    c = _loads(comment) if isinstance(comment, str) else comment
    r = empty()
    r["format"] = "novelai"
    r["prompt"]["positive"] = c.get("prompt") or text.get("Description") or ""
    r["prompt"]["negative"] = c.get("uc") or ""
    s = r["settings"]
    s["steps"], s["cfg"], s["seed"] = c.get("steps"), c.get("scale"), c.get("seed")
    s["width"], s["height"] = c.get("width"), c.get("height")
    s["sampler_raw"] = c.get("sampler")
    s["sampler"] = c.get("sampler")
    s["scheduler"] = c.get("noise_schedule")
    r["model"] = _ref(name=text.get("Source") or "NovelAI")  # NovelAI models aren't downloadable
    r["model"]["downloadable"] = False
    return r


def parse_invokeai(meta) -> dict:
    m = _loads(meta) if isinstance(meta, str) else meta
    r = empty()
    r["format"] = "invokeai"
    pp = m.get("positive_prompt")
    r["prompt"]["positive"] = pp if isinstance(pp, str) else ""
    r["prompt"]["negative"] = m.get("negative_prompt") or ""
    s = r["settings"]
    s["seed"], s["steps"], s["cfg"] = m.get("seed"), m.get("steps"), m.get("cfg_scale")
    s["width"], s["height"], s["scheduler"] = m.get("width"), m.get("height"), m.get("scheduler")
    mod = m.get("model") or {}
    if isinstance(mod, dict) and (mod.get("name") or mod.get("model_name")):
        r["model"] = _ref(name=mod.get("name") or mod.get("model_name"), hash=(mod.get("hash") or "").replace("blake3:", "") or None)
    loras: list = []
    for e in m.get("loras") or []:
        lm = e.get("model") or e.get("lora") or {}
        nm = lm.get("name") or lm.get("model_name")
        if nm:
            _merge_lora(loras, _lora(name=nm, file=nm, weight=e.get("weight", 1)))
    r["loras"] = loras
    return r


def parse_json_parameters(p: dict) -> dict | None:
    """SwarmUI (sui_image_params) and Fooocus write JSON into `parameters`."""
    if isinstance(p.get("sui_image_params"), dict):
        q = p["sui_image_params"]
        r = empty()
        r["format"] = "swarmui"
        r["prompt"]["positive"], r["prompt"]["negative"] = q.get("prompt") or "", q.get("negativeprompt") or ""
        s = r["settings"]
        s["seed"], s["steps"], s["cfg"] = q.get("seed"), q.get("steps"), q.get("cfgscale")
        s["width"], s["height"], s["sampler"], s["scheduler"] = q.get("width"), q.get("height"), q.get("sampler"), q.get("scheduler")
        if q.get("clipstopatlayer"):
            s["clip_skip"] = abs(int(q["clipstopatlayer"]))
        if q.get("model"):
            r["model"] = _ref(file=q["model"])
        if q.get("vae"):
            r["vae"] = _ref(file=q["vae"])
        loras: list = []
        weights = q.get("loraweights") or []
        for i, nm in enumerate(q.get("loras") or []):
            _merge_lora(loras, _lora(file=nm, weight=weights[i] if i < len(weights) else 1))
        r["loras"] = loras
        return r
    if any(k in p for k in ("Prompt", "prompt")) and any(k in p for k in ("Base Model", "base_model", "base_model_name", "Fooocus V2 Expansion", "fooocus_scheme")):
        r = empty()
        r["format"] = "fooocus"
        r["prompt"]["positive"] = p.get("Prompt", p.get("prompt", ""))
        r["prompt"]["negative"] = p.get("Negative Prompt", p.get("negative_prompt", ""))
        s = r["settings"]
        s["seed"], s["steps"] = _num(p.get("Seed", p.get("seed"))), _num(p.get("Steps", p.get("steps")))
        s["cfg"] = _num(p.get("Guidance Scale", p.get("guidance_scale")))
        s["sampler"], s["scheduler"] = p.get("Sampler", p.get("sampler")), p.get("Scheduler", p.get("scheduler"))
        res = str(p.get("Resolution", p.get("resolution", "")))
        m = re.search(r"(\d+)\D+(\d+)", res)
        if m:
            s["width"], s["height"] = int(m.group(1)), int(m.group(2))
        bm = p.get("Base Model", p.get("base_model", p.get("base_model_name")))
        if bm:
            r["model"] = _ref(file=bm, hash=p.get("Base Model Hash", p.get("base_model_hash")))
        loras: list = []
        for k, v in p.items():
            if re.fullmatch(r"LoRA \d+", k) and isinstance(v, str) and ":" in v:
                nm, _, w = v.rpartition(":")
                _merge_lora(loras, _lora(file=nm.strip(), weight=w.strip()))
        for e in p.get("loras") or []:
            if isinstance(e, (list, tuple)) and e:
                _merge_lora(loras, _lora(file=e[0], weight=e[1] if len(e) > 1 else 1, hash=e[2] if len(e) > 2 else None))
        r["loras"] = loras
        return r
    return None


def _enrich(base: dict, extra: dict) -> dict:
    """Add hashes / Civitai ids / missing settings from a second source."""
    if extra.get("model"):
        if not base.get("model"):
            base["model"] = extra["model"]
        else:
            for k, v in extra["model"].items():
                if v is not None and not base["model"].get(k):
                    base["model"][k] = v
    for l in extra.get("loras") or []:
        _merge_lora(base["loras"], dict(l))
    for k, v in (extra.get("settings") or {}).items():
        if v is not None and base["settings"].get(k) is None:
            base["settings"][k] = v
    for k in ("positive", "negative"):
        if not base["prompt"][k] and extra["prompt"].get(k):
            base["prompt"][k] = extra["prompt"][k]
    return base


# ---------------------------------------------------------------- entry points
def from_text(text: dict) -> dict:
    """Recipe from metadata key/values (PNG chunks, EXIF fields)."""
    params = text.get("parameters") or text.get("UserComment") or ""
    pjson = None
    if params.lstrip().startswith("{"):
        try:
            pjson = _loads(params)
        except ValueError:
            pjson = None
    rec = None
    if text.get("recipe"):  # the shared format itself (e.g. Prompto share cards): exact model references
        try:
            r1 = _loads(text["recipe"])
            if isinstance(r1, dict) and r1.get("schema") == SCHEMA:
                rec = normalize(r1)
        except ValueError:
            rec = None
    if rec is None and text.get("prompt"):
        try:
            rec = parse_comfy_prompt(text["prompt"])
        except (ValueError, TypeError, AttributeError):
            rec = None
    elif rec is not None and text.get("prompt"):
        try:
            rec["comfy"] = {**(rec.get("comfy") or {}), "prompt": _loads(text["prompt"])}
        except ValueError:
            pass
    if rec is None and text.get("invokeai_metadata"):
        rec = parse_invokeai(text["invokeai_metadata"])
    if rec is None and pjson is not None:
        rec = parse_json_parameters(pjson)
    if rec is None and params and pjson is None:
        rec = parse_a1111(params)
    elif rec is not None and params and pjson is None and rec.get("format") != "prompto":
        rec = _enrich(rec, parse_a1111(params))  # e.g. ComfyUI saves that also write A1111 text with hashes
    if rec is None and text.get("Comment") and text.get("Software", "").startswith("NovelAI") or (
            rec is None and text.get("Comment", "").lstrip().startswith('{"prompt"')):
        try:
            rec = parse_novelai(text["Comment"], text)
        except ValueError:
            rec = None
    if rec is None and text.get("workflow"):
        try:
            rec = parse_comfy_workflow(text["workflow"])
        except (ValueError, TypeError):
            rec = None
    if rec is None:
        raise NoMetadata("No generation data found in this image (it may have been stripped when it was saved or shared).")
    if text.get("workflow"):
        try:
            rec.setdefault("comfy", None)
            rec["comfy"] = {**(rec["comfy"] or {}), "workflow": _loads(text["workflow"])}
        except ValueError:
            pass
    if text.get("prompto"):
        try:
            card = _loads(text["prompto"])
            rec["title"] = rec["title"] or ((card.get("recipe") or {}).get("title") or "")
            rec["format"] = "prompto+" + rec["format"]
        except ValueError:
            pass
    return rec


def normalize(r1: dict) -> dict:
    """A recipe/1 object from elsewhere, filled out to the full shape (non-finite numbers dropped)."""
    rec = empty()
    for k, v in r1.items():
        if k in ("prompt", "settings", "source") and isinstance(v, dict):
            rec[k].update(v)
        elif k in rec or k in ("display_name", "fav", "updated", "lm_id", "media"):
            rec[k] = v
    rec["loras"] = [l for l in (rec.get("loras") or []) if isinstance(l, dict)]
    rec["schema"] = SCHEMA
    rec["id"] = None  # whoever saves it gives it its own id
    rec["source"].pop("output", None)  # an image in someone else's ComfyUI output folder isn't ours
    return clean(rec)


def from_video(path: str, filename: str | None = None) -> dict:
    """Recipe from a video file's metadata (ComfyUI Save Video, Video Helper Suite, WebM)."""
    from . import videometa
    meta = videometa.read(path)
    if not meta["format"]:
        raise NoMetadata("Not an MP4, MOV or WebM video.")
    if not meta["text"]:
        raise NoMetadata("No generation data in this video (it may have been re-encoded or saved without metadata).")
    rec = from_text(meta["text"])
    rec["source"]["filename"] = filename
    if not rec["title"] and filename:
        rec["title"] = re.sub(r"\.[^.]+$", "", filename)
    rec["media"] = "video"
    return rec


def from_image(data: bytes, filename: str | None = None) -> dict:
    meta = imagemeta.read(data)
    if not meta["format"]:
        raise NoMetadata("Not a PNG, JPEG or WebP image.")
    rec = from_text(meta["text"])
    rec["source"]["filename"] = filename
    if not rec["title"] and filename:
        rec["title"] = re.sub(r"\.[^.]+$", "", filename)
    return rec


def from_lm_recipe(item: dict) -> dict:
    """A LoRA Manager recipe (its stored JSON, as /api/lm/recipes lists it) -> recipe/1."""
    rec = empty()
    rec["format"] = "lora-manager"
    rec["title"] = str(item.get("title") or "")
    gp = item.get("gen_params") or {}
    rec["prompt"]["positive"] = str(gp.get("prompt") or "")
    rec["prompt"]["negative"] = str(gp.get("negative_prompt") or "")
    s = rec["settings"]
    s["sampler_raw"] = gp.get("sampler")
    s["sampler"], s["scheduler"] = map_sampler(gp.get("sampler"), gp.get("scheduler"))
    s["steps"], s["cfg"], s["seed"] = _num(gp.get("steps")), _num(gp.get("cfg_scale") or gp.get("cfg")), _num(gp.get("seed"))
    size = str(gp.get("size") or "")
    if "x" in size:
        w, _, h = size.partition("x")
        s["width"], s["height"] = _num(w), _num(h)
    s["clip_skip"], s["denoise"] = _num(gp.get("clip_skip")), _num(gp.get("denoising_strength"))
    ck = item.get("checkpoint") or {}
    if isinstance(ck, dict) and any(ck.get(k) for k in ("file_name", "name", "hash", "modelVersionId")):
        rec["model"] = _ref(name=ck.get("name") or ck.get("modelName"), file=ck.get("file_name") or None, hash=ck.get("hash") or None,
                            version_id=ck.get("modelVersionId") or ck.get("id"), type="checkpoint")
    for l in item.get("loras") or []:
        if not isinstance(l, dict) or l.get("exclude"):
            continue
        e = _lora(name=l.get("modelName") or None, file=l.get("file_name") or None, hash=l.get("hash") or None,
                  version_id=l.get("modelVersionId") or None, weight=l.get("strength", 1))
        if l.get("modelVersionName"):
            e["version"] = l["modelVersionName"]
        if l.get("modelName") and l.get("file_name"):
            e["display_name"] = l["modelName"]
        _merge_lora(rec["loras"], e)
    rec["base_model"] = item.get("base_model") or None
    rec["tags"] = [str(t) for t in item.get("tags") or [] if str(t).strip()]
    src = str(item.get("source_path") or "")
    rec["source"].update(url=src if src.startswith("http") else None, site="lora-manager")
    rec["created"] = item.get("created_date")
    rec["lm_id"] = item.get("id")
    return clean(rec)


def from_civitai_item(item: dict, page_url: str | None = None) -> dict:
    """Civitai's /api/v1/images item (withMeta) -> recipe, keeping version ids."""
    meta = item.get("meta") or {}
    m = meta.get("meta") if isinstance(meta.get("meta"), dict) else meta
    comfy = None
    try:
        c = _loads(m["comfy"]) if isinstance(m.get("comfy"), str) else m.get("comfy")
        if isinstance(c, dict) and c.get("prompt"):
            comfy = c
    except (ValueError, TypeError):
        comfy = None
    rec = parse_comfy_prompt(comfy["prompt"]) if comfy else empty()
    if comfy and comfy.get("workflow"):
        rec["comfy"]["workflow"] = comfy["workflow"]
    lines = [m.get("prompt") or ""]
    if m.get("negativePrompt"):
        lines.append("Negative prompt: " + m["negativePrompt"])
    a = parse_a1111("\n".join(lines))
    s = a["settings"]
    s["sampler_raw"] = m.get("sampler")
    s["sampler"], s["scheduler"] = map_sampler(m.get("sampler"), m.get("Schedule type") or m.get("scheduler"))
    s["steps"], s["cfg"], s["seed"] = _num(m.get("steps")), _num(m.get("cfgScale")), _num(m.get("seed"))
    if "x" in str(m.get("Size", "")):
        w, _, h = str(m["Size"]).partition("x")
        s["width"], s["height"] = _num(w), _num(h)
    # the generation size; the item's own size may be after an upscale
    s["width"] = s["width"] or _num(m.get("width")) or item.get("width")
    s["height"] = s["height"] or _num(m.get("height")) or item.get("height")
    s["denoise"], s["clip_skip"] = _num(m.get("Denoising strength") or m.get("denoise")), _num(m.get("clipSkip") or m.get("Clip skip"))
    if m.get("Model") or m.get("Model hash"):
        a["model"] = _ref(name=m.get("Model"), file=m.get("Model"), hash=m.get("Model hash"))
    for res in m.get("resources") or []:
        t = str(res.get("type", "")).lower()
        if t in ("model", "checkpoint"):
            mr = _ref(name=res.get("name"), hash=res.get("hash"))
            if a["model"]:
                for k, v in mr.items():
                    if v is not None and not a["model"].get(k):
                        a["model"][k] = v
            else:
                a["model"] = mr
        elif t in ("lora", "locon", "lycoris", "dora"):
            _merge_lora(a["loras"], _lora(name=res.get("name"), weight=res.get("weight", 1), hash=res.get("hash"), _src="res"))
    for res in m.get("civitaiResources") or []:
        t = str(res.get("type", "")).lower()
        if t in ("checkpoint", "model"):
            a["model"] = a["model"] or _ref()
            a["model"]["civitai_version_id"] = a["model"].get("civitai_version_id") or _int(res.get("modelVersionId"))
        elif t in ("lora", "locon", "lycoris", "dora"):
            _merge_lora(a["loras"], _lora(weight=res.get("weight", 1), version_id=res.get("modelVersionId"),
                                          version=res.get("modelVersionName"), _src="res"))
    for k, h in (m.get("hashes") or {}).items():
        if k == "model" and a["model"]:
            a["model"]["hash"] = a["model"].get("hash") or str(h).lower()
        elif k.startswith("lora:"):
            _merge_lora(a["loras"], _lora(file=k[5:], hash=h))
    a["loras"] = _pair_resources(a["loras"])
    rec = _enrich(rec, a) if comfy else a
    rec["format"] = "civitai"
    rec["base_model"] = item.get("baseModel") or m.get("baseModel")
    rec["source"].update(url=page_url or (f"https://civitai.com/images/{item['id']}" if item.get("id") else None),
                         site="civitai", image_id=item.get("id"))
    rec["title"] = rec["title"] or (f"CivitAI image {item['id']}" if item.get("id") else "CivitAI image")
    return rec
