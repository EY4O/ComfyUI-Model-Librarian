# SM Model Fetcher — development

The extension itself is in [`comfyui-sm-model-fetcher/`](comfyui-sm-model-fetcher/README.md) (that folder is what gets installed into ComfyUI's `custom_nodes`).

```
comfyui-sm-model-fetcher/   the ComfyUI extension (Python backend in smf/, frontend in js/)
tests/                      test suites (fake ComfyUI installs, local HTTP servers, no network)
tools/install.py            installs/updates the extension into ComfyUI installs
backups/                    copies of installed versions replaced by the installer (git-ignored)
```

## Install or update an install

This folder is the single source of truth. Don't edit installed copies; change the code here and run:

```
python tools/install.py "<ComfyUI folder or custom_nodes folder>" [more targets…]
```

The installer records a SHA256 manifest in each install. If an installed copy was edited in place since, it stops and lists the changed files instead of overwriting them (copy the fixes here first, or pass `--force`; the old copy is backed up to `backups/` either way). `--dry-run` shows what would happen. Restart ComfyUI afterwards.

## Tests

Needs a Python with aiohttp and PyYAML (any ComfyUI venv) and Node 20+:

```
E:/StabilityMatrix/Data/Packages/Latest-ComfyUI/venv/Scripts/python.exe tests/run_all.py
```

| Suite | Covers |
|---|---|
| `test_shared.py` | shared data folder, migration, cross-process locking, hash cache, LoRA Manager name matching |
| `test_fixes.py` | cm-info merge, sidecar ownership, operation lock, not-found expiry, rate-limit retry |
| `test_bridge.py` | LoRA Manager ↔ Stability Matrix metadata sync |
| `test_workflows.py` | saved-workflow repair, embedding model sources (through the HTTP route) |
| `test_dedupe_usage.py` | hard-link dedupe safety, unused-models report |
| `test_recipes.py` | recipe planning against mocked CivitAI |
| `test_downloads_vram.py` | UNet relocation, download persistence/retry, partial cleanup, pasted links, VRAM advice |
| `test_desktop.py` | ComfyUI Desktop folder-key handling |
| `test_lm.mjs` | LoRA Manager widget parsing (frontend) |
