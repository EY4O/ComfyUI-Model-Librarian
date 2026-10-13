# Development

The repository root is the extension (that's how ComfyUI-Manager and the Comfy Registry install it).

```
__init__.py, pyproject.toml   extension entry point and registry metadata
smf/                          Python backend (routes, downloads, library, organizer, tiers …)
js/                           frontend (ComfyUI extension UI)
tests/                        test suites (fake ComfyUI installs, local HTTP servers, no network)
tools/install.py              installs/updates the extension into local ComfyUI installs
tools/make-icon.py            draws the logo (docs/images/icon.png, js/assets/logo-64.png)
docs/                         this file, README images
backups/                      copies of installs replaced by the installer (git-ignored)
```

`tests/`, `tools/` and `docs/` are excluded from the registry package (`.comfyignore`).

## Install into your own ComfyUI installs

Change code here, never in an installed copy, then run:

```
python tools/install.py "<ComfyUI folder or custom_nodes folder>" [more targets…]
```

The installer copies only the extension files and records a SHA256 manifest. If an installed copy was edited in place since, it stops and lists the changes instead of overwriting them (copy the fixes here first, or pass `--force`; the old copy is backed up to `backups/` either way). An install under the old folder name (`comfyui-sm-model-fetcher`) is retired the same way. `--dry-run` shows what would happen. Restart ComfyUI afterwards.

## Tests

Needs a Python with aiohttp and PyYAML (any ComfyUI venv) and Node 20+:

```
<ComfyUI venv>/Scripts/python.exe tests/run_all.py
```

| Suite | Covers |
|---|---|
| `test_shared.py` | shared data folder, migration, cross-process locking, hash cache, LoRA Manager name matching |
| `test_fixes.py` | cm-info merge, sidecar ownership, operation lock, not-found expiry, rate-limit retry |
| `test_bridge.py` | LoRA Manager ↔ Stability Matrix metadata sync |
| `test_workflows.py` | saved-workflow repair, embedding model sources (through the HTTP route), the all-workflows health check (widget names from node inputs, subgraphs, LoRA Manager, node-provided models) |
| `test_hfmeta.py` | HuggingFace details: repo links from the registry, license/tags/model card parsing and clean-up, caching, the Fetch metadata pass, the details route |
| `test_updates.py` | update alerts: newer same-base, same-variant CivitAI versions, caching, dismissals, kept older copies, the candidate route |
| `test_dedupe_usage.py` | hard-link dedupe safety, unused-models report |
| `test_recipes.py` | recipe planning against mocked CivitAI |
| `test_recipe_parse.py` | image metadata (PNG/JPEG/WebP) from every supported generator, the shared `tests/fixtures/recipe1.json` cases (also run by Prompto), CivitAI items, planning, link analysis, recipe store, analyze and plan routes |
| `test_downloads_vram.py` | UNet relocation, download persistence/retry, partial cleanup, pasted links, VRAM advice |
| `test_tiering.py` | SSD/HDD tiers: usage tracking, suggestions, the free-space goal, verified archive/restore, restore after use, in-use cleanup, undo |
| `test_desktop.py` | ComfyUI Desktop folder-key handling |
| `test_lm.mjs` | LoRA Manager widget parsing (frontend) |
| `test_recipe_apply.mjs` | filling a workflow with a recipe (adding LoRA loaders), building a txt2img graph, LoRA Manager mirror metadata |

## The logo

`docs/images/icon.png` (README header and Registry listing) and `js/assets/logo-64.png` (window header and toolbar button) are drawn by a script rather than edited by hand:

```
python tools/make-icon.py
```

It needs Pillow and NumPy, and shares Prompto's holographic gradient, orb and tile so the two tools match. Change the drawing there and rerun it; both files are rewritten.

## README screenshots and GIFs

`tools/readme_media/` runs the real UI (`js/`) against a scripted fake backend (`ext/scripts/api.js`) with abstract sample previews, drives headless Edge through each walkthrough and writes the PNGs and GIFs to `docs/images/`:

```
<ComfyUI venv>/Scripts/python.exe tools/readme_media/make_media.py                  # everything
<ComfyUI venv>/Scripts/python.exe tools/readme_media/make_media.py recipe updates   # some scenes
```

Scenes: `workflow`, `health`, `recipe`, `updates`, `stills`. Add `--backdrop http://127.0.0.1:8188/` to recapture the ComfyUI page shown behind the window. When the UI changes, update the fake backend so the scenes still run; `sheet.py <gif> <png>` makes a contact sheet for checking a GIF.

## Publishing to the Comfy Registry

`.github/workflows/publish.yml` publishes whenever `pyproject.toml` changes on `main` (or when run by hand from the Actions tab). To release:

1. Bump `version` in `pyproject.toml`.
2. Commit and push to `main`.

One-time setup:

- `[tool.comfy] PublisherId` in `pyproject.toml` must match your publisher on [registry.comfy.org](https://registry.comfy.org).
- Add the publisher's API key as a repository secret named `REGISTRY_ACCESS_TOKEN` (Settings → Secrets and variables → Actions). Without it the workflow skips publishing with a notice.
