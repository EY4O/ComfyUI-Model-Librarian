"""Detect which base-model family a model file belongs to.

Evidence, strongest first:
  1. CivitAI `baseModel` (from Stability Matrix's .cm-info.json sidecar, or a
     live hash lookup)                                    -> confidence "high"
  2. Training metadata inside LoRA safetensors (kohya `ss_sd_model_name`,
     `ss_base_model_version`, `modelspec.architecture`)    -> "high"/"medium"
  3. Tensor layout in the safetensors header (no weights are loaded; only the
     JSON header is read)                                  -> "medium"
  4. File-name keywords                                    -> "low"
"""
from __future__ import annotations

import json
import os
import re
import struct

# Family -> default folder name. Users can rename folders in Settings.
FAMILIES = [
    "Illustrious", "NoobAI", "Pony", "SDXL", "SD1.5", "SD2", "SD3", "Flux", "Flux Kontext", "Flux.2",
    "Chroma", "Krea 2", "Qwen", "Wan", "HunyuanVideo", "LTXV", "Lumina", "Z-Image", "Anima", "HiDream",
    "AuraFlow", "PixArt", "Kolors", "Cosmos", "SVD", "Stable Cascade", "Mochi", "CogVideoX",
]

# Ordered regex rules applied to CivitAI baseModel strings, kohya model names and
# file names. First match wins, so specific rules come before generic ones.
TEXT_RULES: list[tuple[str, str]] = [
    (r"illustrious|\bilxl\b|illu(?:strious)?[-_ ]?xl", "Illustrious"),
    (r"noob", "NoobAI"),
    (r"pony|pdxl", "Pony"),
    (r"kontext", "Flux Kontext"),
    (r"flux[\s._-]*2", "Flux.2"),
    (r"chroma", "Chroma"),
    (r"krea[\s._-]*2|\bk2\b", "Krea 2"),
    (r"flux|krea", "Flux"),
    (r"qwen", "Qwen"),
    (r"\bwan\b|wan[\s._-]*2|wan2[12]|wan[\s_-]?video", "Wan"),
    (r"hunyuan", "HunyuanVideo"),
    (r"\bltx", "LTXV"),
    (r"z[\s._-]?image", "Z-Image"),
    (r"lumina", "Lumina"),
    (r"\banima\b|anima[\s._-]", "Anima"),
    (r"hidream", "HiDream"),
    (r"aura[\s_-]?flow", "AuraFlow"),
    (r"pixart", "PixArt"),
    (r"kolors", "Kolors"),
    (r"cosmos", "Cosmos"),
    (r"stable[\s_-]?cascade|wuerstchen", "Stable Cascade"),
    (r"\bsvd\b|stable[\s_-]?video", "SVD"),
    (r"mochi", "Mochi"),
    (r"cogvideo", "CogVideoX"),
    (r"sd[\s_-]?3|stable[\s_-]?diffusion[\s_-]?3", "SD3"),
    (r"sd[\s_-]?xl|sdxl|\bxl\b|_xl|xl_", "SDXL"),
    (r"sd[\s_-]?2(\.\d)?\b|sd_v2|v2-1|768-v", "SD2"),
    (r"sd[\s_-]?1(\.[45])?\b|sd_v1|sd15|v1-5", "SD1.5"),
]
_TEXT_RULES_C = [(re.compile(p, re.I), f) for p, f in TEXT_RULES]

# modelspec.architecture prefixes (Stability's model spec, written by
# kohya / OneTrainer / ai-toolkit)
ARCH_RULES = [
    (r"stable-diffusion-xl", "SDXL"),
    (r"stable-diffusion-v1", "SD1.5"),
    (r"stable-diffusion-v2", "SD2"),
    (r"stable-diffusion-3", "SD3"),
    (r"flux-1-kontext|flux\.1-kontext", "Flux Kontext"),
    (r"flux-?2|flux\.2", "Flux.2"),
    (r"flux|chroma", "Flux"),
    (r"qwen", "Qwen"),
    (r"wan", "Wan"),
    (r"hunyuan-video|hunyuanvideo", "HunyuanVideo"),
    (r"lumina", "Lumina"),
    (r"z-?image", "Z-Image"),
    (r"anima", "Anima"),
    (r"hidream", "HiDream"),
    (r"ltx", "LTXV"),
]
_ARCH_C = [(re.compile(p, re.I), f) for p, f in ARCH_RULES]

BASE_VERSION = {  # kohya ss_base_model_version
    "sdxl_base_v1-0": "SDXL", "sdxl_base_v0-9": "SDXL", "sd_v1": "SD1.5", "sd_v2": "SD2",
    "sd_v2_768_v": "SD2", "sd3": "SD3", "flux1": "Flux", "chroma": "Chroma", "lumina2": "Lumina",
}


def from_text(s: str | None, extra_rules: list[tuple[str, str]] | None = None) -> str | None:
    if not s:
        return None
    for pat, fam in extra_rules or []:
        try:
            if re.search(pat, s, re.I):
                return fam
        except re.error:
            continue
    for rx, fam in _TEXT_RULES_C:
        if rx.search(s):
            return fam
    return None


# ------------------------------------------------------------------ header
def read_safetensors_header(path: str, max_header: int = 64 * 1024 * 1024) -> dict | None:
    try:
        with open(path, "rb") as f:
            raw = f.read(8)
            if len(raw) < 8:
                return None
            n = struct.unpack("<Q", raw)[0]
            if n <= 0 or n > max_header:
                return None
            return json.loads(f.read(n))
    except Exception:
        return None


_PREFIXES = ("model.diffusion_model.", "diffusion_model.", "transformer.", "base_model.model.",
             "model.", "unet.", "net.")


def _strip(k: str) -> str:
    for p in _PREFIXES:
        if k.startswith(p):
            return k[len(p):]
    return k


def _shape(header: dict, key_pred) -> list | None:
    for k, v in header.items():
        if k != "__metadata__" and key_pred(k) and isinstance(v, dict):
            return v.get("shape")
    return None


def from_header_keys(header: dict, is_lora: bool) -> str | None:
    keys = [k for k in header if k != "__metadata__"]
    if not keys:
        return None
    ks = [_strip(k) for k in keys]
    joined = "\n".join(ks)
    has = lambda s: s in joined  # noqa: E731

    # --- DiT families
    if has("txtfusion.projector"):
        return "Krea 2"
    if has("llm_adapter."):
        return "Anima"
    if has("joint_blocks."):
        return "SD3"
    if has("txt_in.individual_token_refiner"):
        return "HunyuanVideo"
    if has("double_stream_modulation_img"):
        return "Flux.2"
    if has("distilled_guidance_layer"):
        return "Chroma"
    if has("double_blocks") or has("single_blocks") or has("single_transformer_blocks"):
        return "Flux"
    if has("img_mod") and has("txt_mod") or has("img_mlp") and has("txt_mlp") or has("txt_norm.weight"):
        return "Qwen"
    if has("cap_embedder") or (has("noise_refiner") and has("context_refiner")) or \
            (has("layers.") and has("attention.to_q") and has("adaLN_modulation")):
        shp = _shape(header, lambda k: k.endswith("cap_embedder.1.weight")) or \
            _shape(header, lambda k: "attention.to_q" in k and ("lora_B" in k or "lora_up" in k or k.endswith("to_q.weight")))
        dim = shp[0] if shp else None
        return "Lumina" if dim == 2304 else "Z-Image"
    if has("patchify_proj") or (has("adaln_single") and has("caption_projection") and not has("t_block")):
        return "LTXV"
    if has("t_block.1") or (has("adaln_single") and has("pos_embed")):
        return "PixArt"
    if has("caption_projection.0.linear") or has("double_stream_blocks") and has("single_stream_blocks"):
        return "HiDream"
    if has("double_layers.") and has("attn.w1q"):
        return "AuraFlow"
    if has("blocks.") and has(".mlp.layer1"):
        return "Anima" if is_lora else "Cosmos"
    if has("head.modulation") or (has("blocks.") and has("cross_attn") and has(".ffn.")) or has("patch_embedding"):
        return "Wan"
    if has("clf.1.weight") or has("clip_mapper"):
        return "Stable Cascade"
    if has("t5_yproj"):
        return "Mochi"

    # --- UNet families (SD1/2/XL) — use cross-attention context width
    ctx = _shape(header, lambda k: ("attn2" in k) and ("to_k" in k) and
                 any(t in k for t in ("lora_down", "lora_A", "lora.down", ".weight")) and
                 "lora_up" not in k and "lora_B" not in k)
    if ctx and len(ctx) >= 2:
        width = ctx[1]
        if width == 2048:
            return "SDXL"
        if width == 768:
            return "SD1.5"
        if width == 1024:
            return "SD2"
        if width == 1280:
            return "SDXL"  # refiner
    if has("lora_te2_") or has("conditioner.embedders.1") or has("label_emb.0.0") or \
            has("lora_unet_input_blocks") or has("text_encoder_2"):
        return "SDXL"
    if has("lora_te_text_model") or has("cond_stage_model.transformer.text_model"):
        return "SD1.5"
    if has("cond_stage_model.model.transformer"):
        return "SD2"
    if has("input_blocks.0.0.weight") or has("lora_unet_down_blocks"):
        return "SD1.5"
    return None


def from_lora_metadata(meta: dict, extra_rules=None) -> tuple[str | None, str | None]:
    """-> (family, evidence)"""
    if not meta:
        return None, None
    name = meta.get("ss_sd_model_name") or meta.get("ss_base_model_name") or ""
    fam = from_text(os.path.basename(name), extra_rules) if name else None
    if fam and fam not in ("SDXL", "SD1.5", "SD2"):
        return fam, f"trained on {os.path.basename(name)}"
    arch = meta.get("modelspec.architecture") or ""
    for rx, f in _ARCH_C:
        if rx.search(arch):
            # SDXL arch + a recognizable base name (Illustrious/Pony/Noob) wins above
            return (fam or f), f"modelspec {arch}" + (f", trained on {os.path.basename(name)}" if name else "")
    bv = (meta.get("ss_base_model_version") or "").lower()
    for k, f in BASE_VERSION.items():
        if bv.startswith(k):
            return (fam or f), f"ss_base_model_version {bv}"
    if fam:
        return fam, f"trained on {os.path.basename(name)}"
    # ai-toolkit and others sometimes store a JSON 'training_info' / 'name'
    for key in ("name", "modelspec.title", "training_info"):
        f = from_text(str(meta.get(key) or ""), extra_rules)
        if f:
            return f, f"metadata {key}"
    return None, None


def detect(path: str, *, kind: str, cm_info: dict | None = None, civitai_base: str | None = None,
           extra_rules: list[tuple[str, str]] | None = None) -> dict:
    """-> {family, confidence, evidence}. family None = unknown."""
    base = cm_info.get("BaseModel") if cm_info else None
    for src, label in ((civitai_base, "CivitAI"), (base, "Stability Matrix metadata (CivitAI)")):
        if src:
            fam = from_text(src, extra_rules)
            if fam:
                return {"family": fam, "confidence": "high", "evidence": f"{label}: {src}"}

    header = read_safetensors_header(path) if path.lower().endswith((".safetensors", ".sft")) else None
    is_lora = kind in ("loras", "lycoris")
    if header:
        meta = header.get("__metadata__") or {}
        if is_lora or meta.get("ss_sd_model_name") or meta.get("modelspec.architecture"):
            fam, ev = from_lora_metadata(meta, extra_rules)
            if fam:
                strong = ev.startswith("trained on") or "trained on" in ev
                return {"family": fam, "confidence": "high" if strong else "medium", "evidence": ev}
        fam = from_header_keys(header, is_lora)
        if fam:
            # Architecture can't tell Illustrious/Pony/NoobAI apart from SDXL; peek at the name
            if fam == "SDXL":
                nf = from_text(os.path.basename(path), extra_rules)
                if nf in ("Illustrious", "Pony", "NoobAI"):
                    return {"family": nf, "confidence": "medium",
                            "evidence": "SDXL architecture + file name"}
            return {"family": fam, "confidence": "medium", "evidence": "tensor layout"}

    fam = from_text(os.path.basename(path), extra_rules)
    if fam:
        return {"family": fam, "confidence": "low", "evidence": "file name"}
    return {"family": None, "confidence": None, "evidence": "no evidence"}
