---
version: 1
slug: "docs-index-html"
primary_target: "docs/index.html"
related_targets: ["docs/privacy.html"]
---

# Surface brief: librarian.eternalpose.io home

Mode: Persuade (suite homepage). Code-led (no image generation).

Audience and job: new ComfyUI users deciding whether to try the suite, and existing users looking for install steps and how the parts connect (equal weight, user's choice). Proof: real README screenshots and GIFs (sample data, labelled). User rejects: generic AI-startup look, walls of text before seeing the tools, a style unlike the apps.

Direction: pinned by the user (2026-10-26), replacing the rolled structures: the page is a ComfyUI-style workflow; scrolling down follows the wires from feature to feature.

## Direction contract

THESIS: The homepage is a workflow you scroll through. Each feature is a node wired to the next, and the first screen is the moment every ComfyUI user knows: a workflow with missing models, fixed in front of them. Refuses the hero-plus-feature-cards page.

OWN-WORLD: The apps' own world: charcoal canvas with a faint dot grid, nodes as #262626 bodies with darker title bars, 8px corners, hairline borders, Segoe UI Variable, ML blue #3b82f6 for actions, status pills (Missing red, Moved amber, OK green), base-model badge colours on tags. Wires use ComfyUI slot-type colours (MODEL purple, VAE red, LATENT pink, IMAGE blue, plus the suite's LIBRARY green), and every link joins slots of one type, as in ComfyUI (decided after the finish review, 2026-10-26).

STORY: See missing models resolve, learn the extension feeds it from CivitAI, the Library sorts it, recipes and storage keep it tidy, Gallery Info carries it into the Gallery, then install all three.

FIRST VIEWPORT: Left, a Note node with the headline, one line and the copyable install command. Right, a sample workflow: Load Checkpoint and LoRA Loader outlined red as Missing, wired to KSampler and Save Image, with Model Librarian's panel offering Watch it fetch them (a play icon: clearly the demo, never a real download). Nothing runs until the reader presses it (the button glows again and again until it's first played in that browser, remembered in localStorage, then once a visit); then both download at a steady pace over about ten seconds, each is verified (SHA256) and its loader node clears the red on its own, and KSampler runs to the picture.

FORM: user-pinned workflow canvas; position: pinned above the rolled list; seed key 12908012 (surface roll, superseded by the pin).

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
