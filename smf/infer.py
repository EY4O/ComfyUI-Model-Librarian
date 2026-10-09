"""Work out which model folder a workflow widget value belongs to."""
from __future__ import annotations

from .paths import canonical

# (node_type, widget_name) -> folder. "*" matches any widget on that node.
KNOWN: dict[tuple[str, str], str] = {
    ("CheckpointLoaderSimple", "ckpt_name"): "checkpoints",
    ("CheckpointLoader", "ckpt_name"): "checkpoints",
    ("ImageOnlyCheckpointLoader", "ckpt_name"): "checkpoints",
    ("unCLIPCheckpointLoader", "ckpt_name"): "checkpoints",
    ("LoraLoader", "lora_name"): "loras",
    ("LoraLoaderModelOnly", "lora_name"): "loras",
    ("VAELoader", "vae_name"): "vae",
    ("UNETLoader", "unet_name"): "diffusion_models",
    ("UnetLoaderGGUF", "unet_name"): "diffusion_models",
    ("UnetLoaderGGUFAdvanced", "unet_name"): "diffusion_models",
    ("CLIPLoader", "*"): "text_encoders",
    ("DualCLIPLoader", "*"): "text_encoders",
    ("TripleCLIPLoader", "*"): "text_encoders",
    ("QuadrupleCLIPLoader", "*"): "text_encoders",
    ("CLIPLoaderGGUF", "*"): "text_encoders",
    ("DualCLIPLoaderGGUF", "*"): "text_encoders",
    ("TripleCLIPLoaderGGUF", "*"): "text_encoders",
    ("QuadrupleCLIPLoaderGGUF", "*"): "text_encoders",
    ("CLIPVisionLoader", "clip_name"): "clip_vision",
    ("ControlNetLoader", "control_net_name"): "controlnet",
    ("DiffControlNetLoader", "control_net_name"): "controlnet",
    ("UpscaleModelLoader", "model_name"): "upscale_models",
    ("LatentUpscaleModelLoader", "model_name"): "latent_upscale_models",
    ("StyleModelLoader", "style_model_name"): "style_models",
    ("GLIGENLoader", "gligen_name"): "gligen",
    ("HypernetworkLoader", "hypernetwork_name"): "hypernetworks",
    ("IPAdapterModelLoader", "ipadapter_file"): "ipadapter",
    ("ModelPatchLoader", "name"): "model_patches",
    ("AudioEncoderLoader", "audio_encoder_name"): "audio_encoders",
    ("PhotoMakerLoader", "photomaker_model_name"): "photomaker",
    ("UltralyticsDetectorProvider", "model_name"): "ultralytics",
    ("SAMLoader", "model_name"): "sams",
    # LoRA Manager (its LoRA nodes are handled separately: names have no extension)
    ("Checkpoint Loader (LoraManager)", "ckpt_name"): "checkpoints",
    ("Unet Loader (LoraManager)", "unet_name"): "diffusion_models",
}

# substring of widget name -> folder (checked in order)
HEURISTICS = [
    ("lora", "loras"),
    ("ckpt", "checkpoints"),
    ("checkpoint", "checkpoints"),
    ("clip_vision", "clip_vision"),
    ("vae", "vae"),
    ("unet", "diffusion_models"),
    ("diffusion", "diffusion_models"),
    ("clip", "text_encoders"),
    ("t5", "text_encoders"),
    ("text_encoder", "text_encoders"),
    ("control", "controlnet"),
    ("upscale", "upscale_models"),
    ("ipadapter", "ipadapter"),
    ("embedding", "embeddings"),
    ("style_model", "style_models"),
    ("sam", "sams"),
    ("bbox", "ultralytics"),
    ("segm", "ultralytics"),
]


def _combo_options(node_type: str, widget: str) -> list[str] | None:
    try:
        import nodes  # ComfyUI
    except ImportError:
        return None
    cls = nodes.NODE_CLASS_MAPPINGS.get(node_type)
    if cls is None:
        return None
    try:
        spec = cls.INPUT_TYPES()
    except Exception:
        return None
    for group in ("required", "optional"):
        inp = (spec.get(group) or {}).get(widget)
        if not inp:
            continue
        first = inp[0] if isinstance(inp, (list, tuple)) else None
        if isinstance(first, (list, tuple)):
            return [str(x) for x in first]
        if first == "COMBO" and len(inp) > 1 and isinstance(inp[1], dict):
            return [str(x) for x in inp[1].get("options", [])]
    return None


def _by_overlap(node_type: str, widget: str, inventory) -> str | None:
    opts = _combo_options(node_type, widget)
    if not opts:
        return None
    opts = {o for o in opts if o.lower() not in ("none", "")}
    if not opts:
        return None
    best, best_score = None, 0.0
    for folder, names in inventory.lists.items():
        if not names:
            continue
        inter = len(opts & names)
        if not inter:
            continue
        score = inter / len(opts)
        if score > best_score:
            best, best_score = folder, score
    return canonical(best) if best_score >= 0.5 else None


def infer_folder(node_type: str, widget: str, embedded_dir: str | None, inventory) -> tuple[str | None, str]:
    """-> (folder, how)"""
    if embedded_dir:
        return canonical(embedded_dir), "workflow"
    f = KNOWN.get((node_type, widget)) or KNOWN.get((node_type, "*"))
    if f:
        return f, "known-node"
    f = _by_overlap(node_type, widget, inventory)
    if f:
        return f, "node-options"
    w = (widget or "").lower() + " " + (node_type or "").lower()
    for needle, folder in HEURISTICS:
        if needle in w:
            return folder, "guess"
    return None, "unknown"
