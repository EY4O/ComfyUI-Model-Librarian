# SM Model Fetcher for ComfyUI

A model manager for ComfyUI built around **Stability Matrix's shared model folders**, designed to work alongside **LoRA Manager**. Open it from **Models** in the top toolbar (or **Extensions → SM Model Fetcher**).

| Tab | What it does |
|---|---|
| **Workflow** | Scans the open workflow (subgraphs, rgthree Power Lora Loader and LoRA Manager nodes included) for models that are missing, moved, or too big for your GPU. Finds sources in this order: URLs embedded in the workflow → your registry → ComfyUI-Manager's model list → HuggingFace (exact filename + SHA256) → CivitAI. Also accepts pasted CivitAI model pages and HuggingFace file pages. **Embed model sources** stores each model's download link + SHA256 in the workflow so people you share it with can fetch the exact files. |
| **Library** | Card gallery with CivitAI previews, base-model badges, trigger words, folder tree, search, size per base model, and an **Unused only** filter. **Fetch metadata** identifies files on CivitAI by hash; **Sync with LoRA Manager** copies metadata between LoRA Manager and Stability Matrix offline. |
| **Organize** | Sorts models into base-model folders (`Lora/Illustrious`, `Lora/Pony`, `DiffusionModels/Qwen` …) with a preview plan and one-click **Undo**. Saved workflows are repointed to the moved files automatically. |
| **Duplicates** | Finds byte-identical copies (SHA256) under any name. Either move extras to `Data/Models/_duplicates` (never deleted), or **replace them with hard links** so every path keeps working while the bytes are stored once. |
| **Recipes** | Drop an image (or paste a CivitAI image link) to see the checkpoint and LoRAs it was made with and their strengths. Saves it as a LoRA Manager recipe and downloads everything you're missing. **Copy LoRA syntax**, and **Open its workflow** for ComfyUI images. Needs LoRA Manager. |
| **Storage** | SSD/HDD tiers: models unused for a while are suggested for an archive drive (you approve), stay usable under the same names, and come back to the SSD after a workflow uses them. |
| **Registry** | Where every model came from (file name → URL + SHA256). |
| **Settings** | API keys, VRAM, behaviour, organizer folder names and rules, partial-download cleanup, shared data. |

## How it fits with Stability Matrix and LoRA Manager

| | Owns | SM Model Fetcher's part |
|---|---|---|
| **Stability Matrix** | The shared `Data/Models` folders, `.cm-info.json` + `.preview.*` sidecars | Downloads into SM's folders; writes SM's sidecars so models show as *connected* in SM's Checkpoint Manager; keeps its data next to the models so every SM package (and ComfyUI Desktop) shares it |
| **LoRA Manager** | Its LoRA library, `.metadata.json`, recipes, loader nodes | Understands LM's loader nodes; saves recipes through LM; asks LM to rescan after any download or move; syncs metadata with SM's sidecars |
| **SM Model Fetcher** | Missing-model resolution, base-model organizer, duplicates, VRAM advice | — |

## Install

**Stability Matrix:** Packages → ComfyUI → ⋮ → Open in Explorer → `custom_nodes`, put this folder there as `custom_nodes/comfyui-sm-model-fetcher/`, restart ComfyUI.

**ComfyUI Desktop:** put it in Desktop's `custom_nodes`, and add a section to Desktop's `extra_model_paths.yaml` that points at Stability Matrix's `Data/Models` folder (change the path), then restart:

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

Any section whose paths look like `.../Models/<StableDiffusion|Lora|...>` is recognised, whatever its name.

Then, in **Settings**, add your **CivitAI API key** (civitai.com → Account → API Keys) and a **HuggingFace token** if you use gated models like FLUX.1-dev. No extra Python packages are needed. GGUF swaps need **ComfyUI-GGUF** (install via ComfyUI-Manager).

## Shared data across installs

With Stability Matrix's folders detected, the registry, hash cache, undo history and settings live in `Data/Models/.sm_model_fetcher/`, shared by every ComfyUI that uses those folders. Several can run at once. Each install's earlier data is merged in on first start (the local copies stay as a backup). **API keys always stay in each install's own user folder.** Turn sharing off in **Settings → Shared data**.

## LoRA Manager integration

- **Workflow scan:** reads the LoRA lists of *Lora Loader*, *Lora Stacker* and *WanVideo Lora Select*, and `<lora:name:strength>` text in LM's text nodes. Missing LoRAs are saved under exactly the name the node uses.
- **Recipes:** LM reads the image (ComfyUI, A1111/Forge or CivitAI metadata) and stores the recipe. This extension finds each model's exact CivitAI file by version ID or hash and downloads it, SHA256-verified, into the matching base-model folder — including the checkpoint, which LM's own import doesn't download. A "checkpoint" that turns out to be UNet-only goes to `DiffusionModels`. Models found only by file-name search are never bulk-downloaded. Dropping an image on this window never loads it over your open workflow.
- **Metadata sync** (Library → Sync with LoRA Manager): fills SM's `.cm-info.json` and preview from LM's metadata and vice versa, with no API calls. A new LM entry is only created when its SHA256 is verified by this extension's own hash cache, because LM trusts that value.
- **Rescans:** LM has no file watcher, so it's asked to rescan after downloads, moves, undo and syncs.

## Base-model detection (Organize / badges)

1. **CivitAI `baseModel`** from SM/LM/`.civitai.info` metadata or a hash lookup — high confidence.
2. **LoRA training metadata** (`ss_sd_model_name`, `modelspec.architecture`, `ss_base_model_version`) — separates Illustrious, Pony and NoobAI from plain SDXL.
3. **Tensor layout** from the safetensors header (weights are never loaded) — SD1.5/2/XL/3, Flux, Flux.2, Chroma, Qwen-Image, Wan, HunyuanVideo, LTXV, Lumina, Z-Image, Anima, HiDream and more — medium confidence.
4. **File name** — low confidence; these moves start unchecked.

Models already filed under a family folder stay put when the evidence can't contradict it, and custom sub-folders are kept (`Characters/x` → `Illustrious/Characters/x`).

## SSD / HDD storage tiers

Set an archive folder (e.g. on an external HDD) in **Settings → Storage tiers**.

- **Usage tracking:** every queued prompt records which models it actually loads (plain loaders, LoRA Manager lists and `<lora:…>` text, rgthree rows). Models never seen in a run count from when the extension first saw them, so nothing is suggested on day one.
- **Archiving (you approve):** the **Storage** tab lists models unused for N days (60 by default) for the model types you choose. Each one is copied to `<archive>/<SM folder>/<same path>`, the copy's SHA256 is verified, its sidecars move with it, and only then is the SSD file removed. Runs appear in Organize → History, so they can be undone. Nothing moves while the drive is unplugged or a model is loaded.
- **Still usable:** the archive folders are added to ComfyUI's model folders at startup, so archived models keep their exact names — workflows don't change, they just load more slowly from the HDD. For LoRA Manager, use **Add archive folders to LoRA Manager** once (then restart ComfyUI).
- **Coming back:** after a prompt uses an archived model, it's copied back to the SSD once the queue is idle (verified, sidecars included), and LoRA Manager is told to rescan. If ComfyUI still has the HDD copy open, removing it is retried later; the SSD copy wins in ComfyUI's lists meanwhile. You can also bring models back by hand in the Storage tab.

Usage data lives in the shared data folder, so every ComfyUI with this extension contributes to it.

## VRAM advice

Models bigger than your VRAM budget, and text encoders over half of it, get **Find smaller version**: fp8 versions (load in the same node; the workflow is repointed after download) and GGUF quants (UNets swap to *Unet Loader (GGUF)* automatically; GGUF text encoders need *CLIPLoader (GGUF)*). The biggest one that fits is recommended.

## Safety

- Downloads are SHA256-verified when the source publishes a hash, resume after interruptions, and survive restarts (**Retry** in the download tray).
- Credentials only go to their own service — never to CDN redirect hosts — and are never sent to the browser. `CIVITAI_API_KEY` / `HF_TOKEN` env vars work too.
- Moves never overwrite files; a model ComfyUI has loaded is skipped. Every run can be undone. Moving files and metadata fetches / duplicate scans never run at the same time.
- Duplicates are quarantined or hard-linked, never deleted. Hard links are only made when size, modification time and sampled bytes still match the scan.
- Saved workflows are backed up before they're repointed (`ComfyUI/user/sm_model_fetcher/workflow_backups/`).
