# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Static HTML/CSS (no build step), published by GitHub Pages from this repository's `docs/` folder at librarian.eternalpose.io (DNS: a CNAME at Namecheap, like linemark., voyage. and xiv.eternalpose.io). Design notes in the repository root are not served.

## Users

Two audiences, equally (user's choice, 2026-10-26):

- **New ComfyUI users deciding whether to try the suite**, arriving from Reddit (r/comfyui, r/StableDiffusion), a CivitAI article, the Comfy Registry or the Chrome Web Store listing. They need to see what it does and that it is trustworthy, then how to install it.
- **Existing users** who already run Model Librarian and want install steps, updates, and how the three parts connect.

Most run ComfyUI on Windows with an NVIDIA GPU, often through Stability Matrix or Comfy Desktop, with large model folders (hundreds of GB) and many LoRAs from CivitAI.

## Product Purpose

The Model Librarian suite keeps AI models and what they make in order, on the user's own PC. librarian.eternalpose.io is the suite's homepage: one place that explains the three parts, how they work together, and how to install each, and that hosts the privacy policy the browser stores require.

## Positioning

A model manager built around a shared models folder that works alongside LoRA Manager rather than replacing it, with a browser extension and a gallery that hand work between each other: a CivitAI click lands the right file in the right ComfyUI folder, and every generation can be traced back to the models and workflow that made it. Free, open source, local, made by one maker (Looneth).

## Operating Context

- **Model Librarian** (ComfyUI custom nodes, EY4O/ComfyUI-Model-Librarian, v1.23.0): opened from **Library** in the ComfyUI toolbar. Installed from the Comfy Registry (`comfy node install comfyui-model-librarian`) or ComfyUI-Manager. CivitAI downloads need the user's CivitAI API key, stored in Model Librarian's Settings.
- **Model Librarian for Chrome** (Chrome/Edge extension, EY4O/Chrome-Model-Librarian, v0.6.1): a panel on CivitAI, HuggingFace and CivArchive pages; needs Model Librarian 1.15+ in the ComfyUI it downloads into. Not yet on the Chrome Web Store or Edge Add-ons (submission planned for the 3 Nov 2026 suite launch); until then installed with Load unpacked.
- **Model Librarian Gallery** (Windows app, EY4O/Model-Librarian-Gallery, v1.8.1): a portable folder from GitHub Releases; indexes AI generations, photos and illustrations where they are. Its exe is unsigned, so Windows SmartScreen warns on first run.
- How they connect: the Gallery Info node (ML 1.22) tags images as they're made; Open in ComfyUI (ML 1.23) sends a Gallery file's workflow back; Save as recipe puts it in Model Librarian's recipes; the extension (0.6) saves pictures from art sites into the Gallery's New downloads.

## Capabilities and Constraints

- Everything runs on the user's computer. The extension talks only to the user's own ComfyUI (127.0.0.1/localhost, or an address they set) and to CivitAI's public API without cookies; nothing goes to the developer. No analytics anywhere.
- Every Comfy Registry version of Model Librarian is currently marked "Flagged" (reason unknown, as of 2026-10-26). Don't promise Registry or ComfyUI-Manager installs beyond what works.
- Site scope (user's choice, 2026-10-26): one suite page plus `privacy.html`. The READMEs remain the detailed documentation.
- Contact: iamlooneth@gmail.com (business email) and GitHub issues/Discussions. The user's personal email must never appear.

## Brand Commitments

- Names: "Model Librarian" (the ComfyUI part and the suite), "Model Librarian for Chrome", "Model Librarian Gallery". Maker: Looneth. Part of eternalpose.io, which links here.
- Existing assets: the bookcase app icon (`docs/images/icon.png`, also the extension's and Registry's icon).
- Support: Ko-fi (ko-fi.com/looneth) on every project.

## Evidence on Hand

- README screenshots and GIFs made with sample data: `docs/images/` here (library, workflow, recipes, organize, storage, missing-models.gif, recipe.gif, updates.gif and more), the extension's `docs/images/` (panel-best, image-panel, badges, popup, hf-panel), and the Gallery's `docs/images/` (hero, viewer, stats, character, selection).
- Numbers as of 26 Oct 2026: 3 GitHub stars and 42 Registry downloads for Model Librarian; 23 Gallery release downloads. Too small to show as social proof.
- No testimonials, reviews or user counts exist; do not invent any.

## Product Principles

1. Show the real thing: every claim is backed by a real screenshot or demo of the actual UI, labelled as sample data.
2. Local and honest: say plainly what runs where, what each part needs, and what isn't finished (store listings, unsigned exe).
3. One suite, three doors: a visitor can start from any part and see how it connects to the other two.
4. Install in a minute: the path from "I want this" to working is short and copy-pasteable for each part.

## Accessibility & Inclusion

WCAG AA contrast, full keyboard use, prefers-reduced-motion honoured, readable at 200% zoom and on phones.
