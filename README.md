<p align="center"><img src="docs/images/icon.png" width="112" alt="Model Librarian"></p>

<h1 align="center">ComfyUI Model Librarian</h1>

<p align="center"><b>Every model in its place — found, fetched, sorted and kept in sync across Stability Matrix and LoRA Manager.</b></p>

<p align="center">
  <a href="https://github.com/EY4O/comfyui-model-librarian/blob/main/LICENSE"><img src="https://img.shields.io/github/license/EY4O/comfyui-model-librarian?color=blue" alt="License"></a>
  <a href="https://github.com/EY4O/comfyui-model-librarian/commits/main"><img src="https://img.shields.io/github/last-commit/EY4O/comfyui-model-librarian?color=green&logo=github" alt="Last commit"></a>
  <a href="https://registry.comfy.org/nodes/comfyui-model-librarian"><img src="https://img.shields.io/badge/Comfy%20Registry-comfyui--model--librarian-6c47ff" alt="Comfy Registry"></a>
  <a href="https://ko-fi.com/looneth"><img src="https://img.shields.io/badge/Ko--fi-Support-FF813F?logo=ko-fi&logoColor=white" alt="Support on Ko-fi"></a>
</p>

A model manager for ComfyUI built around **Stability Matrix's shared model folders** and designed to work hand in hand with **[LoRA Manager](https://github.com/willmiao/ComfyUI-Lora-Manager)**. It finds and downloads whatever a workflow is missing, files your models by base model, turns images into recipes, keeps the SSD for the models you actually use — and makes Stability Matrix and LoRA Manager share what they know. Open it from **Models** in the ComfyUI toolbar.

![Library](docs/images/library.png)

> **⚠ CivitAI downloads and metadata lookups** need your CivitAI API key (civitai.com → Account settings → API Keys). Add it in **Settings** — it's stored server-side and never sent to the browser. Gated HuggingFace models (e.g. FLUX.1-dev) need a HuggingFace token too.

---

## ✨ Key Features

- 🔍 **Missing-model finder** — scans the open workflow (subgraphs, rgthree and LoRA Manager nodes included) and finds sources in order of trust: links embedded in the workflow → your download history → ComfyUI-Manager's list → HuggingFace → CivitAI. Downloads are SHA256-verified, resume after interruptions and survive restarts.
- 🩺 **Workflow health** — checks every saved workflow (and subgraph blueprint) at once: which ones are missing models, which models moved, and one click to find and download them all. Saved files keep working without edits.
- 🖼️ **Library** — a gallery of your models with CivitAI previews, base-model badges, trigger words, search, size per base model and an **Unused** filter. Models from HuggingFace show their license, tags and model card.
- ⬆️ **Update alerts** — a daily check for newer CivitAI versions of every model type, with a badge on the card, an **Updates only** filter and a one-click download that keeps the version you have.
- 🗂️ **Base-model organizer** — sorts models into `Illustrious/`, `Pony/`, `Flux/`, `Qwen/` … using CivitAI data, LoRA training metadata and the tensor layout itself. Preview first, undo anytime, and saved workflows are repointed automatically.
- 🧬 **Recipes from images** — drop an image or paste a link (CivitAI image or post, or any image file) to see its prompt, settings, checkpoint and LoRAs with their strengths. Save it to your recipe library, download everything you're missing, then fill the open workflow with it or open it as a new one. Reads ComfyUI, A1111/Forge, CivitAI, Fooocus, InvokeAI, SwarmUI and NovelAI images; no LoRA Manager needed (with LM installed, recipes are saved there too).
- 🔗 **Stability Matrix ↔ LoRA Manager** — understands LM's loader nodes, writes SM's own metadata so models show as *connected*, syncs metadata between the two offline, and tells LM to rescan after every change.
- 💾 **SSD / HDD storage tiers** — models unused for a while are suggested for an archive drive, stay usable under the same names, and come back to the SSD after a workflow uses them. Set a free-space goal and the least recently used models are suggested whenever the SSD runs low.
- ♻️ **Duplicates** — finds byte-identical copies under any name; quarantine them or replace them with hard links so every path keeps working.
- 🎛️ **VRAM advice** — models too big for your GPU get fp8 and GGUF alternatives, with one-click download and swap.
- 🤝 **Shared across installs** — every ComfyUI package in Stability Matrix (and ComfyUI Desktop) shares one registry, hash cache, history and usage data.

## 📸 Screenshots

| | |
|---|---|
| ![Workflow](docs/images/workflow.png) **Workflow** — missing, moved and too-big models with sources and smaller versions | ![Recipes](docs/images/recipes.png) **Recipes** — every model an image used, with strengths, ready to download and apply |
| ![Organize](docs/images/organize.png) **Organize** — base-model sorting with evidence and confidence | ![Storage](docs/images/storage.png) **Storage** — archive what you don't use, keep it usable |

<sub>Screenshots use sample data.</sub>

---

## 📦 Installation

### Option 1: **ComfyUI-Manager** (Recommended)

1. Open **ComfyUI** → **Manager** → **Custom Nodes Manager**.
2. Search for `Model Librarian`.
3. Click **Install** and restart ComfyUI.

### Option 2: **Comfy CLI**

```bash
comfy node install comfyui-model-librarian
```

### Option 3: **Manual Installation**

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/EY4O/comfyui-model-librarian.git
```

No extra Python packages are needed. GGUF swaps use **ComfyUI-GGUF**, and LoRA Manager is optional — both available from ComfyUI-Manager.

<details>
<summary><b>Using it with Stability Matrix / ComfyUI Desktop</b></summary>

**Stability Matrix** packages are detected automatically (its `extra_model_paths.yaml` or symlinked model folders).

**ComfyUI Desktop** needs a section in its `extra_model_paths.yaml` pointing at Stability Matrix's models folder (change the path), then a restart:

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
</details>

## 🚀 Getting Started

1. **Settings** → add your CivitAI API key (and HuggingFace token).
2. Open a workflow — missing models show up as a notice; **Workflow → Find all sources → Download**.
3. **Library → Fetch metadata** to identify your existing models on CivitAI (previews, trigger words, base models).
4. **Organize → Build plan** to sort them into base-model folders.
5. Optional: set an archive folder in **Settings → Storage tiers** to start tiering.

---

## 📖 How It Works

<details>
<summary><b>🔗 Working with Stability Matrix and LoRA Manager</b></summary>

| | Owns | Model Librarian's part |
|---|---|---|
| **Stability Matrix** | Shared `Data/Models` folders, `.cm-info.json` + `.preview.*` sidecars | Downloads into SM's folders; writes SM's sidecars so models show as *connected* in its Checkpoint Manager; keeps its own data next to the models so every package shares it |
| **LoRA Manager** | LoRA library, `.metadata.json`, recipes, loader nodes | Reads LM's loader nodes (LoRA lists and `<lora:name:strength>` text); fills them when applying a recipe; mirrors saved recipes into LM's recipe list (optional); asks LM to rescan after downloads and moves; syncs metadata with SM's sidecars |

**Metadata sync** (Library → Sync with LoRA Manager) fills SM's `.cm-info.json` and preview from LM's metadata and vice versa, without any API calls. A new LM entry is only created when its SHA256 is verified, because LoRA Manager trusts that value.
</details>

<details>
<summary><b>🗂️ How the base model is detected</b></summary>

1. **CivitAI `baseModel`** — from SM / LM / `.civitai.info` metadata or a hash lookup. High confidence.
2. **LoRA training metadata** — `ss_sd_model_name`, `modelspec.architecture`, `ss_base_model_version`. This separates Illustrious, Pony and NoobAI from plain SDXL.
3. **Tensor layout** — read from the safetensors header (weights are never loaded): SD1.5/2/XL/3, Flux, Flux.2, Chroma, Qwen-Image, Wan, HunyuanVideo, LTXV, Lumina, Z-Image, Anima, HiDream and more. Medium confidence.
4. **File name** — low confidence; these moves start unchecked.

Models already in a matching family folder are left alone, and custom sub-folders are kept (`Characters/x` → `Illustrious/Characters/x`).
</details>

<details>
<summary><b>💾 SSD / HDD storage tiers</b></summary>

- **Usage tracking** — every queued prompt records which models it loads. Models never seen in a run count from when they were first seen, so nothing is suggested on day one.
- **Archiving (you approve)** — the Storage tab lists models unused for N days (60 by default). Each is copied to `<archive>/<SM folder>/<same path>`, the copy's SHA256 is verified, sidecars move with it, and only then is the SSD file removed. Runs can be undone from Organize → History.
- **Still usable** — archive folders are registered with ComfyUI, so archived models keep their exact names; workflows don't change, they just load more slowly. Use **Settings → Add archive folders to LoRA Manager** once so LM's loaders see them.
- **Coming back** — after a prompt uses an archived model, it's copied back to the SSD once the queue is idle. A different file is never deleted.
- **Free-space goal** — **Settings → Storage tiers → Keep free on the SSD**: when the drive holding your Stability Matrix models has less free space than that, the Storage tab also suggests the least recently used models (oldest first) until archiving them would meet the goal, marked *for free-space goal*. Models used in the last 14 days (adjustable) are never suggested. If the goal can't be reached that way, it says so. You get one notice per session while the SSD is below the goal.
</details>

<details>
<summary><b>🤗 HuggingFace details</b></summary>

Models downloaded from HuggingFace (through Model Librarian, so their source is known) get a **🤗 HF** chip in the Library with their license. Click it for the base model, task, likes and downloads, gating, tags and the start of the model card, cleaned up for reading, with a link to the repository. Details are fetched after the download and by **Fetch metadata**, cached for a week in the shared data folder, and can be refreshed from the popup. The Library's **Source** filter separates CivitAI, HuggingFace and unknown models.
</details>

<details>
<summary><b>🩺 Workflow health and update alerts</b></summary>

**Workflow → All saved workflows** reads every workflow and subgraph blueprint in ComfyUI's user folder, without opening them. Models are found in loader widgets, rgthree and LoRA Manager nodes, subgraphs and the sources embedded in a workflow; their folders come from each node's own inputs. The list shows the workflows that need something first; click one to see just its models, or **Open** it. **Find all sources** and **Download all** work as for the open workflow, and downloads keep the file name the workflows use, so they work without edits. **Fix moved paths** repoints saved files when exactly one file with that name exists (each file is backed up first). Models a node offers itself (frame-interpolation models it downloads on first use) aren't counted as missing.

**Update alerts**: once a day (Settings → Behaviour), and from **Library → Check for updates**, each model with CivitAI metadata is looked up once per CivitAI model and cached for a day. A newer version counts only for the same base model and the same variant: a low-noise file isn't offered the high-noise version, and 4-step isn't an update of 8-step. Older copies kept next to a newer one aren't flagged. The ⬆ chip on a card downloads the new version next to the old one (with a version suffix if the author reused the file name); its × hides that version.
</details>

<details>
<summary><b>🧬 Recipes</b></summary>

Model Librarian reads the generation data itself — PNG text chunks, JPEG/WebP EXIF, ComfyUI graphs (including Flux-style custom samplers, rgthree and LoRA Manager loaders), A1111/Forge text with its hashes, CivitAI's image API, Fooocus, InvokeAI, SwarmUI and NovelAI. A CivitAI post link shows its images to choose from.

- **Library** — saved recipes live in the shared data folder (`recipes/`), so every ComfyUI using your Stability Matrix folders sees them. Filter, favourite, rename, tag; deleting moves them to `recipes/_deleted/`.
- **Download** — each model's exact CivitAI file is found by version ID or hash and saved into the matching base-model folder. "Checkpoints" that turn out to be UNet-only go to `DiffusionModels`. Models found only by file-name search are never bulk-downloaded.
- **Fill current workflow** — sets the prompts, seed, steps, CFG, sampler, scheduler, size, clip skip, model and LoRAs in the workflow that's open. LoRA Manager's loader gets the whole list; plain LoRA loaders are filled in order, extra ones are added to the chain, and unused ones are bypassed.
- **Open as new workflow** — opens the ComfyUI workflow saved in the image, or builds a simple text-to-image workflow for checkpoint models.
- **LoRA Manager** — with it installed, new recipes are also saved to LM's recipe list (**Settings → Behaviour**).
- **Prompto** — recipes captured with the [Prompto](https://github.com/EY4O/prompto) Chrome extension keep their model hashes and Civitai version ids. When one is loaded into ComfyUI with [ComfyUI-Prompto](https://github.com/EY4O/ComfyUI-Prompto) and its models aren't installed, **Get them with Model Librarian** opens it here. Prompto's share cards carry the recipe too, so dropping one here finds the exact files.

The format is documented in **[docs/RECIPE_FORMAT.md](docs/RECIPE_FORMAT.md)**. Dropping an image on the window never replaces your open workflow.
</details>

<details>
<summary><b>🛡️ Safety</b></summary>

- Downloads are verified against the source's SHA256 and resume after interruptions; credentials only go to their own service, never to CDN redirect hosts.
- Moves never overwrite; a model ComfyUI has loaded is skipped; every run can be undone; moves never run alongside metadata fetches or duplicate scans.
- Duplicates are quarantined or hard-linked, never deleted — hard links only when size, timestamp and sampled bytes still match.
- Saved workflows are backed up before they're repointed. API keys stay in each install's user folder, never in the shared data folder.
</details>

<details>
<summary><b>🤝 Shared data</b></summary>

With Stability Matrix's folders detected, the registry, hash cache, undo history, usage data, recipes and settings live in `Data/Models/.sm_model_fetcher/`, shared by every ComfyUI that uses those folders (several can run at once). Turn it off in **Settings → Shared data**.

*Formerly **SM Model Fetcher** — internal names are unchanged, so existing data carries over.*
</details>

---

## 🧪 Development

Tests, the safe installer and the publishing workflow are described in **[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)**.

## 🤝 Contributing

Issues and pull requests are welcome — please run the test suite before opening a PR.

## 🙏 Credits

- [Stability Matrix](https://github.com/LykosAI/StabilityMatrix) — shared model folders and the `.cm-info.json` format
- [LoRA Manager](https://github.com/willmiao/ComfyUI-Lora-Manager) — recipes, metadata and loader nodes this integrates with
- [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) and city96's GGUF quantizations
- [ComfyUI-Manager](https://github.com/Comfy-Org/ComfyUI-Manager)'s model list, and the CivitAI and HuggingFace APIs

## ☕ Support

If Model Librarian saves you time (or disk space), you can support its development:

[![Support me on Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/looneth)

## 📄 License

[MIT](LICENSE)
