# Development

The repository root is the extension (that's how ComfyUI-Manager and the Comfy Registry install it).

```
__init__.py, pyproject.toml   extension entry point and registry metadata
smf/                          Python backend (downloads, library, organizer, tiers, recipes …)
smf/routes/                   the HTTP API: one *_routes.py module per area, wired up in __init__.py
js/                           frontend (ComfyUI extension UI)
tests/                        test suites (fake ComfyUI installs, local HTTP servers, no network)
tools/install.py              installs/updates the extension into local ComfyUI installs
tools/make-icon.py            draws the logo (docs/images/icon.png, js/assets/logo-64.png)
tools/readme_media/           rebuilds the README screenshots and GIFs (also the UI smoke test's driver)
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
| `test_video.py` | recipes from videos written like ComfyUI does (Save Video MP4, Video Helper Suite comment, WebM tags, animated WebP), streamed uploads |
| `test_notes.py` | your ratings, notes and tags; use counts; the Library routes |
| `test_routes.py` | every API route registered once; the route package doesn't shadow the data modules |
| `test_ui.py` | UI smoke test: every README walkthrough runs against the real frontend in headless Edge (skipped without Edge) |
| `test_civarchive.py` | CivArchive fallback (only when CivitAI has nothing), removed models, Share's download list, leftover downloads and cut-short models |
| `test_links.py` | recipe models you have under another name: name / similar-name matching, links made by hand, pasted links |
| `test_history.py` | storage history samples, daily moves, version comparison |
| `test_thumbs.py` | small WebP thumbnails of large previews for the Library cards |
| `test_desktop_root.py` | the shared models folder without Stability Matrix: Comfy Desktop's default folder, missing SM-named folders skipped, a folder set by hand |
| `test_archive.py` | Archive: prompt families and diffs, report / CSV / recipes / workflows, WebP thumbnails carrying their workflow, incremental re-runs (synthetic images only) |
| `test_lm.mjs` | LoRA Manager widget parsing (frontend) |
| `test_storehist.mjs` | storage history chart data (frontend) |
| `test_share.mjs` | model links written into a saved copy of a workflow (frontend) |
| `test_libview.mjs` | Library filters and sorting (frontend) |
| `test_recipe_apply.mjs` | filling a workflow with a recipe (adding LoRA loaders), building a txt2img graph, LoRA Manager mirror metadata |

## Routes for the Chrome extension

The Model Librarian Chrome extension (a separate repo, `EY4O/Chrome-Model-librarian`) uses `smf/ext.py` through `smf/routes/ext_routes.py`:

| Route | Does |
|---|---|
| `GET /sm-fetcher/ext/hello` | Who's there: app name, version, models folder, free space, whether a CivitAI key is set, and (1.12.0+) `system`: the GPU, its VRAM and budget, the quantized formats this ComfyUI runs at full speed (`comfy.model_management.supports_*_compute`), the formats it loads (`comfy.quant_ops.QUANT_ALGOS`) and the GGUF / Nunchaku loaders |
| `POST /sm-fetcher/ext/lookup` | `{version_ids, hashes, model_ids}` -> `have` / `downloading` / `missing` for each; model ids (card badges) -> `have` / `update` / `missing` |
| `POST /sm-fetcher/ext/download` | `{version_id, file_id?, dry_run?}` -> planned like Recipes downloads (type folder, base-model subfolder), started with the downloader; never twice |
| `POST /sm-fetcher/ext/companions` | `{base_model, file_name}` -> the text encoders, VAE and CLIP vision a diffusion model needs (`smf/companions.py`: from ComfyUI's installed workflow templates, matched by base family and model file name), each with `have` / `alt` from the inventory |
| `POST /sm-fetcher/ext/companion-download` | `{base_model, file_name, name}` -> downloads one of those from the template's link (SHA256 from HuggingFace); anything not on the list is refused |
| `GET /sm-fetcher/ext/jobs?ids=` | Those downloads' progress |
| `GET /sm-fetcher/ext/model?id=` | A CivitAI model's versions and files, slimmed (the Library's "find a better fit") |
| `POST /sm-fetcher/ext/civarchive` | `{sha256}` -> yours, or CivArchive's live copies planned into the right folder (other hosts as links) |
| `POST /sm-fetcher/ext/download-url` | `{url, folder, dry_run?}` -> a HuggingFace file page into the folder picked (SHA256 from the repo; a same-named file in the folder counts as yours) |

Image and post pages use the Recipes routes (`/recipe/analyze`, `/recipes`) and `/download`.

The extension needs the version these routes first shipped in (1.11.0); raise `MIN_ML` in its `lib/comfy.js` if they change incompatibly. Tests: `tests/test_ext.py` (CivitAI faked).

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
