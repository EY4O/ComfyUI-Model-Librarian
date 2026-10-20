# Brief: Model Librarian for Chrome

*Status: phases 1-4 built 2026-10-20 in the private repo EY4O/Chrome-Model-librarian (0.4.0, loaded unpacked) against Model Librarian 1.15.0, plus what came up on the way (best file for your PC, text encoders and VAEs from ComfyUI's templates). Not planned: the Chrome Web Store (the user doesn't intend to publish it). Drafted 2026-10-16.*

**What changed from the plan in Phase 1:** the extension talks to ComfyUI directly from its service worker. A `declarativeNetRequest` rule drops the `Origin` header on the extension's own requests to 127.0.0.1/localhost, so ComfyUI's origin check passes with no tab open (needed for Comfy Desktop, which has no browser tab); running the request inside an open ComfyUI tab is the fallback. No pairing code: ComfyUI's origin check already keeps websites out, and the existing Model Librarian routes are no more protected than these, so a token would add a setup step without adding safety. The address is found automatically (ports 8188, 8000, 8189) or set in the popup.

## Why

Stability Matrix's Chrome extension (about 10K users) puts **Download with Stability Matrix** on CivitAI model pages and hands the download to the desktop app via a deep link. It's the one thing keeping Stability Matrix in the loop now that Model Librarian downloads, sorts, verifies and tracks models inside ComfyUI. A Model Librarian extension replaces it and uses what Model Librarian knows about your library.

## Goal

One click on CivitAI (or HuggingFace, or CivArchive) downloads the exact file into the right ComfyUI folder — sorted by base model, SHA256-verified, with preview and metadata — and every model page tells you whether you already have it.

## Features

**Parity with Stability Matrix**
- A download button on CivitAI model pages (civitai.com, .red, .green), per version and per file (pruned / full / fp16…).
- Lands in the right folder for its type and base model (Organize's rules), with SHA256 check, resume, `.cm-info.json` and preview.
- Download progress in the extension's popup.

**Better**
- **Knows your library:** on model pages and listing cards, badges for *You have this* (by hash or version), *Newer version available*, *Removed from CivitAI*; the button becomes *Update* or *Already downloaded*.
- **Everything an image used:** on a CivitAI image or post, *Get all models* downloads the checkpoint and every LoRA at once, and can save it as a recipe (and send it to Prompto).
- **More sites:** HuggingFace file pages (with license and gating), CivArchive pages (live copies of removed models).
- **Queue and targets:** click as many downloads as you like, with or without ComfyUI open: they wait in the extension and start as soon as a ComfyUI is reachable. Choose which ComfyUI receives them (Stability Matrix's, the standalone one, a remote one over Tailscale).
- **Save for later:** bookmark a model into Model Librarian without downloading it.
- **Storage-aware:** warns when the SSD is below the free-space goal and offers the storage tiers.
- **Keys stay home:** CivitAI and HuggingFace keys live in Model Librarian only; the extension never holds them.

## How it fits together

```
CivitAI / HF / CivArchive page ── content script (buttons, badges)
            │
     extension service worker (queue, pairing, which ComfyUI)
            │
   ComfyUI tab bridge (content script on the ComfyUI page)   or   direct HTTP
            │
   Model Librarian routes in ComfyUI → existing downloader, Organize rules, updates, CivArchive
```

- **Talking to ComfyUI:** ComfyUI refuses requests to a local address (127.0.0.1) from another origin unless it's started with `--enable-cors-header`. So, like Prompto, the extension talks through an open ComfyUI tab (a small bridge script). Direct HTTP is used when allowed: a non-local address such as Tailscale, or ComfyUI started with the CORS flag.
- **Pairing:** a one-time code shown in Model Librarian's Settings links the extension. Requests carry the pairing token, so no other website can trigger downloads.
- **New Model Librarian routes (small):** `ext/hello` (pairing, version, free space), `ext/lookup` (batch: owned / update / removed for version ids and hashes), `ext/download` (version + file → planned download), `ext/jobs`. Everything else is reused: `civitai_by_version`, the downloader, `organize.folder_for`, `updates`, `civarchive`.
- **Reads pages through APIs, not markup:** model and version ids come from the page URL and CivitAI's API, so site redesigns don't break it.

## Phases

1. **Parity (MVP):** CivitAI model-page button → download into the right folder; a queue that waits while ComfyUI is closed and starts when it's reachable; popup with queue and progress; one ComfyUI; pairing; tab bridge. Loaded unpacked.
2. **Library-aware:** owned / update / removed badges on model pages and listing cards; *Get all models* from image and post pages, with save as recipe.
3. **More sources and targets:** HuggingFace and CivArchive buttons; several ComfyUIs; notifications.
4. **Bulk and extras:** download a CivitAI collection; save-for-later list; Prompto integration.

## Decisions

- **A separate extension**, its own repo (e.g. `EY4O/model-librarian-chrome`), drawing on Prompto's code rather than living inside Prompto:
  - CivitAI page handling: host-aware (civitai.com / .red / .green) page detection and API lookups from Prompto's `content/civitai.js`;
  - the ComfyUI tab bridge pattern from Prompto + ComfyUI-Prompto (here, Model Librarian ships the bridge script itself);
  - the shared `recipe/1` helpers (`lib/recipe1.js`) for *Get all models* and saving recipes.
  Shared pieces are copied in at first; if both extensions keep changing them, they can move to a small shared package later.
- **ComfyUI has to be running for downloads**, and a queue is enough: clicks are stored in the extension (`chrome.storage`) and sent the moment a paired ComfyUI is reachable (checked on a timer and whenever a ComfyUI tab opens). No background helper app.
- **Unpacked first** (Developer mode → Load unpacked). The Chrome Web Store, with its privacy policy and review, can come later. Edge loads the same build.

## Risks

- CivitAI page or API changes: lean on the API and keep the button code small.
- ComfyUI's origin rules may tighten: the tab bridge doesn't depend on them.
- Login-gated or early-access models need the CivitAI key in Model Librarian; the extension says so instead of failing silently.
- Downloads are always started by a click (no scraping), within CivitAI's API terms.
