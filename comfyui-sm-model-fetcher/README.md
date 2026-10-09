# SM Model Fetcher for ComfyUI

A ComfyUI extension built around **Stability Matrix's shared model folders**. It has seven tabs:

| Tab | What it does |
|---|---|
| **Workflow** | Scans the open workflow (including subgraphs and rgthree Power Lora Loader) for model files that are missing, moved, or too big for your GPU. It finds sources in this order: URLs embedded in the workflow → your personal registry → ComfyUI-Manager's model list → HuggingFace (exact filename + SHA256) → CivitAI. Downloads land directly in `Data/Models/<type>`. |
| **Library** | A card gallery of your models with CivitAI preview images, base-model badges (IL / PONY / XL / FLUX / QWEN …), trigger words, a folder tree, search and filters. **Fetch metadata** hashes files that have no info and identifies them on CivitAI. |
| **Organize** | Sorts models into base-model folders (`Lora/Illustrious`, `Lora/Pony`, `DiffusionModels/Qwen` …). Has a *Loose files only* mode and a *Full review* mode that fixes misplaced files. You get a preview plan before anything moves, and one-click **Undo**. |
| **Duplicates** | Finds byte-identical copies (SHA256), even when they have different names. Extra copies go to `Data/Models/_duplicates` and are never deleted. |
| **Recipes** | Drop an image (or paste a CivitAI image link) to see the checkpoint and LoRAs it was made with, and their strengths. Saves it as a **LoRA Manager** recipe and downloads every model you're missing. Needs LoRA Manager. |
| **Registry** | Remembers where every model came from (file name → URL + SHA256). |
| **Settings** | API keys, VRAM, folder names, detection rules. |

It works alongside **Stability Matrix** and **LoRA Manager**. It reads their metadata, writes Stability Matrix's own `.cm-info.json` + `.preview.*` files (so models show as *connected* in SM's Checkpoint Manager), and moves every sidecar file together with its model.

## Install (Stability Matrix)

1. In Stability Matrix, go to **Packages → ComfyUI → ⋮ → Open in Explorer** and open the `custom_nodes` folder.
2. Unzip this folder there: `custom_nodes/comfyui-sm-model-fetcher/`.
3. Restart ComfyUI from Stability Matrix.
4. Click **Models** in the top toolbar, or go to **Extensions → SM Model Fetcher**.
5. In **Settings**, add your **CivitAI API key** (civitai.com → Account → API Keys). Add a **HuggingFace token** too if you use gated models like FLUX.1-dev.

There are no extra Python dependencies; it only uses what ComfyUI already ships (aiohttp, PyYAML). The 12 GB swaps need **ComfyUI-GGUF**, which you can install via ComfyUI-Manager.

## Using it with ComfyUI Desktop

Add a section to `%APPDATA%\ComfyUI\extra_models_config.yaml` that points at Stability Matrix's `Data/Models` folder (change the path to your install), then restart Desktop:

```yaml
stability_matrix:
  base_path: C:/StabilityMatrix/Data/Models
  checkpoints: StableDiffusion
  diffusion_models: DiffusionModels
  loras: |
    Lora
    LyCORIS
  text_encoders: TextEncoders
  clip_vision: ClipVision
  vae: VAE
  controlnet: ControlNet
  upscale_models: ESRGAN
  embeddings: Embeddings
  ipadapter: IpAdapter
```

The extension recognises any section whose paths look like `.../Models/<StableDiffusion|Lora|...>`, so the section name doesn't matter, though `stability_matrix` is clearest. Install the extension in `Documents\ComfyUI\custom_nodes`.

## Shared data across installs

When Stability Matrix's shared folders are detected, the registry, hash cache, undo history and settings live in `Data/Models/.sm_model_fetcher/`, so every ComfyUI package in Stability Matrix and ComfyUI Desktop share them. Each install's existing data is merged in the first time it starts; the old local copies stay in `ComfyUI/user/sm_model_fetcher/` as a backup. API keys always stay in each install's user folder and are never written to the shared folder. You can turn sharing off in **Settings → Shared data**.

## LoRA Manager

- The Workflow tab understands LoRA Manager's nodes. It reads the LoRA list of *Lora Loader*, *Lora Stacker* and *WanVideo Lora Select*, and `<lora:name:strength>` text in LoRA Manager's text nodes. Those nodes name LoRAs without an extension, so missing ones are downloaded under exactly that name (`Lora/<name>.safetensors`).
- **Recipes** builds on LoRA Manager's recipes rather than keeping its own. LoRA Manager reads the image's generation data (ComfyUI, A1111/Forge or CivitAI) and stores the recipe; this extension finds each model's exact file on CivitAI by version ID or hash and downloads it, SHA256-verified, into the matching base-model folder (`Lora/Illustrious/…`, `StableDiffusion/Pony/…`). That includes the checkpoint, which LoRA Manager's own import doesn't download. Models found only by searching the file name are never downloaded in bulk; check them and download each one yourself. Dropping an image on this window never loads it as a workflow.
- LoRA Manager has no file watcher, so after downloads, Organize, Undo and duplicate moves the extension asks it to rescan (`/api/lm/<type>/scan`). That way its loaders, and its check for missing LoRAs when you queue a prompt, see the files straight away.

## How it detects the base model (Organize / badges)

1. **CivitAI `baseModel`**, from Stability Matrix `.cm-info.json`, LoRA Manager `.metadata.json`, `.civitai.info`, or a hash lookup. **High** confidence.
2. **LoRA training metadata**: kohya's `ss_sd_model_name` (e.g. `illustriousXL_v01`), `modelspec.architecture` or `ss_base_model_version`. This is what separates Illustrious, Pony and NoobAI from plain SDXL.
3. **Tensor layout**: only the safetensors header is read, never the weights. It recognises SD1.5, SD2, SDXL, SD3, Flux, Flux.2, Chroma, Qwen-Image, Wan, HunyuanVideo, LTXV, Lumina, Z-Image, Anima, HiDream and more. **Medium** confidence.
4. **File name keywords**. **Low** confidence, so these moves start unchecked.

Rules for the folder layout:

- A model you already filed under a family folder is left alone when the evidence can't contradict it. For example, if the tensor layout says "SDXL" but the file sits in `Illustrious/`, it isn't moved.
- Custom sub-folders are kept underneath the family folder: `Characters/x` → `Illustrious/Characters/x`.

## Safety

- Downloads are verified against the source's SHA256 when it's available, and resume after interruptions.
- Credentials are only sent to their own service: the HuggingFace token never goes to CivitAI, and no token is sent to CDN redirect hosts. Keys are stored in `ComfyUI/user/sm_model_fetcher/config.json` and never sent to the browser. The env vars `CIVITAI_API_KEY` / `HF_TOKEN` also work.
- Moves never overwrite files. A model that ComfyUI currently has loaded is skipped rather than copied. Every run is logged and can be undone.
- Duplicates are quarantined, never deleted. Check `Data/Models/_duplicates` and delete it yourself when you're happy.

## Notes

- After moving models, open workflows show them as **Moved**. Use **Fix moved paths** to repoint them.
- Data files (registry, hash cache, undo log, settings) live in `Data/Models/.sm_model_fetcher/` when sharing is on, otherwise in `ComfyUI/user/sm_model_fetcher/`.
