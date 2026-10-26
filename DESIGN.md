---
name: Model Librarian
description: The Model Librarian suite's homepage, drawn as a ComfyUI workflow on the apps' own charcoal canvas.
colors:
  canvas: "#161616"
  canvas-glass: "rgba(22, 22, 22, 0.94)"
  grid: "#262626"
  node: "#242424"
  node-head: "#2e2e2e"
  panel-head: "#23262e"
  panel: "#1c1c1c"
  panel-glass: "rgba(28, 28, 28, 0.92)"
  shot-bg: "#111111"
  control: "#2c2c2c"
  control-hover: "#343434"
  track: "#333333"
  scroll: "#3a3a3a"
  line: "#363636"
  line-2: "#464646"
  line-hover: "#555555"
  text: "#ececec"
  text-2: "#cfcfcf"
  dim: "#a3a3a3"
  accent: "#2563eb"
  accent-hover: "#1d4fd0"
  on-accent: "#ffffff"
  selection: "rgba(37, 99, 235, 0.45)"
  link: "#8cb8ff"
  link-hover: "#b4d0ff"
  missing: "#f87171"
  missing-ink: "#fecaca"
  moved: "#fbbf24"
  ok: "#4ade80"
  w-model: "#c084fc"
  w-clip: "#fbbf24"
  w-vae: "#f87171"
  w-latent: "#f472b6"
  w-image: "#60a5fa"
  w-library: "#34d399"
  note: "#fbbf24"
typography:
  display:
    fontFamily: "Segoe UI Variable Display, Segoe UI Variable, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "clamp(2.5rem, 4.6vw, 4.25rem)"
    fontWeight: 650
    lineHeight: 1.02
    letterSpacing: "-0.03em"
  headline-section:
    fontFamily: "Segoe UI Variable Display, Segoe UI Variable, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "clamp(2rem, 3.4vw, 3rem)"
    fontWeight: 650
    lineHeight: 1.05
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Segoe UI Variable Display, Segoe UI Variable, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "clamp(1.875rem, 3vw, 2.625rem)"
    fontWeight: 650
    lineHeight: 1.08
    letterSpacing: "-0.025em"
  title-doc:
    fontFamily: "Segoe UI Variable Display, Segoe UI Variable, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.375rem"
    fontWeight: 650
    lineHeight: 1.25
    letterSpacing: "-0.01em"
  title:
    fontFamily: "Segoe UI Variable Text, Segoe UI Variable, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 600
    lineHeight: 1.2
  lead:
    fontFamily: "Segoe UI Variable Text, Segoe UI Variable, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.1875rem"
    fontWeight: 400
    lineHeight: 1.5
  body-large:
    fontFamily: "Segoe UI Variable Text, Segoe UI Variable, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 400
    lineHeight: 1.55
  body:
    fontFamily: "Segoe UI Variable Text, Segoe UI Variable, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "1rem"
    fontWeight: 400
    lineHeight: 1.55
  label:
    fontFamily: "Segoe UI Variable Text, Segoe UI Variable, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
  port:
    fontFamily: "Segoe UI Variable Text, Segoe UI Variable, Segoe UI, system-ui, -apple-system, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    letterSpacing: "0.02em"
  mono:
    fontFamily: "Cascadia Mono, JetBrains Mono, Consolas, ui-monospace, monospace"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: 1.4
rounded:
  code: "5px"
  widget: "7px"
  control: "8px"
  inset: "9px"
  node: "10px"
  group: "12px"
  pill: "999px"
spacing:
  2xs: "6px"
  xs: "8px"
  sm: "12px"
  md: "16px"
  lg: "24px"
  xl: "32px"
  2xl: "56px"
  section: "72px"
components:
  button:
    backgroundColor: "{colors.control}"
    textColor: "{colors.text}"
    typography: "{typography.title}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "40px"
  button-hover:
    backgroundColor: "{colors.control-hover}"
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-small:
    rounded: "{rounded.control}"
    padding: "0 11px"
    height: "32px"
  button-touch:
    height: "44px"
  media-toggle:
    backgroundColor: "{colors.panel-glass}"
    textColor: "{colors.text}"
    typography: "{typography.label}"
    rounded: "{rounded.control}"
    padding: "0 12px"
    height: "36px"
  media-toggle-hover:
    backgroundColor: "{colors.control}"
  pill-missing:
    textColor: "{colors.missing}"
    typography: "{typography.label}"
    rounded: "{rounded.pill}"
    padding: "0 9px"
    height: "22px"
  pill-moved:
    textColor: "{colors.moved}"
    rounded: "{rounded.pill}"
    padding: "0 9px"
    height: "22px"
  pill-ok:
    textColor: "{colors.ok}"
    rounded: "{rounded.pill}"
    padding: "0 9px"
    height: "22px"
  pill-quiet:
    textColor: "{colors.dim}"
    rounded: "{rounded.pill}"
    padding: "0 9px"
    height: "22px"
  node:
    backgroundColor: "{colors.node}"
    rounded: "{rounded.node}"
  node-head:
    backgroundColor: "{colors.node-head}"
    textColor: "{colors.text}"
    typography: "{typography.title}"
    padding: "0 12px"
    height: "36px"
  node-head-panel:
    backgroundColor: "{colors.panel-head}"
    textColor: "{colors.text}"
    typography: "{typography.title}"
    padding: "0 12px"
    height: "36px"
  node-body:
    padding: "10px 12px 12px"
  shot:
    backgroundColor: "{colors.shot-bg}"
  widget:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.dim}"
    typography: "{typography.label}"
    rounded: "{rounded.widget}"
    padding: "5px 10px"
    height: "30px"
  command:
    backgroundColor: "{colors.panel}"
    textColor: "{colors.text}"
    typography: "{typography.mono}"
    rounded: "{rounded.inset}"
    padding: "6px 6px 6px 14px"
  progress-track:
    backgroundColor: "{colors.track}"
    rounded: "{rounded.pill}"
    height: "4px"
  progress-fill:
    backgroundColor: "{colors.accent}"
    rounded: "{rounded.pill}"
    height: "4px"
  tab:
    textColor: "{colors.text-2}"
    rounded: "{rounded.control}"
    padding: "6px 12px"
  tab-hover:
    backgroundColor: "{colors.control}"
    textColor: "{colors.text}"
  tab-current:
    backgroundColor: "{colors.accent}"
    textColor: "{colors.on-accent}"
  group-frame:
    rounded: "{rounded.group}"
    padding: "16px"
---

# Design System: Model Librarian

## Overview

**Creative North Star: "The Workflow Canvas"**

The suite's web presence looks like the place its users already work: a ComfyUI graph on a charcoal canvas with a faint dot grid. Content lives in nodes (a darker title bar with a coloured dot, a body of ports and widget rows) and nodes are joined by wires that leave an output pin on the right and arrive at an input pin on the left. The world is inherited, not invented: Model Librarian Gallery's charcoal "Darkroom" neutrals, Segoe UI Variable, Model Librarian's blue for actions and its status pills.

Density is the apps' density: small labels, hairline borders, tight widget rows, generous space only between nodes. Colour is functional. Neutrals carry everything; blue means "do this"; red, amber and green mean model status; and the saturated slot colours belong to wires, pins and node dots, where they encode data type exactly as ComfyUI does. Real screenshots and recordings sit inside nodes as their bodies, so the product's own UI is the imagery.

The page is dark only, by decision: it mirrors the apps, which are dark, and declares `color-scheme: dark` with a canvas-coloured theme colour. There is no light theme to keep in step.

**Key Characteristics:**
- Charcoal canvas (dot grid every 24px) with flat grey nodes floating on a soft ambient shadow.
- Node anatomy: title bar with a coloured dot, optional tag or pill at the right, ports row, widget rows or a screenshot body.
- Wires coloured by ComfyUI slot type, drawn as horizontal-tangent bezier curves between same-typed pins.
- One action colour (blue) and three status colours (red, amber, green), never used decoratively.
- Every colour and radius the page uses is a named custom property on `:root`; components reference names, never literals.
- Segoe UI Variable throughout, with the Display optical size for headings. Dark only.

## Colors

A near-neutral charcoal ramp with one action blue, three status hues and a set of ComfyUI slot-type colours that live only on the graph.

### Primary
- **Librarian Blue** (accent): primary buttons, the current tab, download progress fills, and the base of the text selection tint (**Selection**, accent at 45%). It darkens to **Pressed Blue** (accent-hover) on hover. Darker than the apps' #3b82f6 so white labels pass AA.
- **On Accent** (on-accent): the white text on blue buttons, on the current tab and on selected text.
- **Link Blue** (link): inline links and the focus ring. Links lighten to **Link Hover** (link-hover) under the pointer.

### Secondary
- **Missing Red** (missing): Missing pills, the outline and 1px ring on a node whose model is absent. **Missing Ink** (missing-ink) colours the widget values inside a missing node.
- **Moved Amber** (moved): Moved pills and rating stars.
- **OK Green** (ok): OK pills, which replace Missing in place when a download finishes.

### Tertiary: slot types
- **MODEL Violet** (w-model), **CLIP Amber** (w-clip), **VAE Red** (w-vae), **LATENT Pink** (w-latent), **IMAGE Blue** (w-image), and the suite's own **LIBRARY Green** (w-library). They colour wires, pins, node title dots, feature-list ticks and install group frames. The KSampler's progress bar fills with LATENT Pink, since it is producing latents.
- **Note Amber** (note): the dot of ComfyUI's Note node, which holds the hero headline and the privacy document.
- Hue comes from classes, never inline styles: a port's pin takes its colour from a type class (`t-model` through `t-library`), a node's dot from its node class, a feature list's ticks from a hue class (`hue-image`, `hue-clip`, `hue-latent`, `hue-library`). Everywhere on the page a node's dot, and its feature list's ticks, are the type the node outputs (MODEL for the Workflow tab and the extension, LIBRARY for Library and Storage, IMAGE for Recipes and Gallery Info); the Gallery, which has no output, takes the type it receives.

### Neutral
- **Canvas** (canvas): page background, scrollbar track. **Canvas Glass** (canvas-glass, canvas at 94%) is the sticky bar (with blur) and the footer.
- **Grid Dot** (grid): the 1.2px dots of the canvas grid.
- **Node Grey** (node): node bodies; also the halo ring around pins and the base that group frames tint.
- **Title Bar Grey** (node-head): node title bars. **Panel Head** (panel-head) is the faintly blue title bar of the Model Librarian panel node, the one node that is the app itself.
- **Inset** (panel): widget rows, command fields, list rows inside a node, summary boxes, tables, code chips. **Panel Glass** (panel-glass, inset at 92%) sits over moving video under the media toggle.
- **Shot Black** (shot-bg): the backing behind a screenshot or video while it loads.
- **Control** (control): neutral buttons and tab hover; **Control Hover** (control-hover) for a hovered neutral button.
- **Track** (track): the unfilled part of progress bars. **Scroll** (scroll): the scrollbar thumb.
- **Hairline** (line), **Strong Hairline** (line-2) and **Hover Hairline** (line-hover): node, widget and row borders; button, command and quiet-pill borders and dashed placeholders; a hovered button's border.
- **Ink** (text), **Soft Ink** (text-2), **Dim** (dim): headings and values; body copy and lists; labels, ports, captions, meta.

### Named Rules
**The Slot Colour Rule.** Wire colour is the ComfyUI slot type of the pins it joins, and a wire only ever joins an output and an input of the same type. Never colour a wire by section, brand or mood.

**The Status Is Not Decoration Rule.** Red, amber and green mean Missing, Moved and OK. They appear only where a model's state is being shown. A status pill in a node's title bar keeps its status colour; only plain tags there go Dim.

**The One Action Colour Rule.** Blue fills only the next action (primary button, current tab) and download progress. Neutral buttons stay grey.

**The Named Colour Rule.** Every colour on the page is a `:root` custom property. A new colour is a new named token, not a literal in a rule or an inline style.

**The Derived Group Rule.** An install group frame has one hue, its part's wire token (Model Librarian is w-model, Chrome is w-image, Gallery is w-library). Its border is that hue at 55% over transparent, its body that hue mixed 7% into Node Grey, its header 22% into Node Grey (`color-mix(in srgb, …)`). Those three colours are derived, never separate tokens.

## Typography

**Display Font:** Segoe UI Variable Display (with Segoe UI, system-ui fallback)
**Body Font:** Segoe UI Variable Text (with Segoe UI, system-ui fallback)
**Label/Mono Font:** Cascadia Mono (with JetBrains Mono, Consolas) for install commands and code

**Character:** The Windows apps' own face, so the page reads as part of the suite rather than a marketing site. Headings use the Display optical size at weight 650 with tight negative tracking; everything inside nodes is the Text size at small, app-like sizes.

### Hierarchy
- **Display** (650, clamp 2.5 to 4.25rem, 1.02): the single hero headline in the Note node; 2.375rem on phones.
- **Headline Section** (650, clamp 2 to 3rem, 1.05): a page section that holds groups (Install).
- **Headline** (650, clamp 1.875 to 2.625rem, 1.08): each step's heading beside its node; the privacy page title uses a close variant (clamp 2 to 2.75rem).
- **Title Doc** (650, 1.375rem, 1.25): headings inside a long document node.
- **Title** (600, 0.9375rem, 1.2): node titles, list-row names; button text uses this size at weight 500.
- **Lead** (400, 1.1875rem, 1.5, max 34ch): the hero sentence.
- **Body Large** (400, 1.0625rem, max 46ch beside a node, 60ch for section intros): step copy.
- **Body** (400, 1rem, 1.55, max 68ch in documents).
- **Label** (500, 0.8125rem): pills, widget rows, tags, captions, meta lines, the media toggle; sizes in tabular numerals.
- **Port** (400, 0.75rem, +0.02em): port labels. Outputs are UPPERCASE type names (MODEL, IMAGE), inputs are lowercase slot names (model, samples), as ComfyUI writes them.

### Named Rules
**The App Voice Rule.** Inside a node, type is app-sized (0.75 to 0.9375rem). Large type exists only outside nodes or in the Note node's headline.

## Layout

Pages are a column of steps on the canvas, max 1320px wide with 32px side padding (16px on phones). Each step is a two-column grid, node and text at 7:5 (alternating to 5:7), 56px gap, 72px vertical padding; the hero uses 5:7 and fills the first viewport. The hero graph is a two-column grid of nodes (24px row gap, 64px column gap) so wires have room to curve. Install is a three-column row of group frames, 24px gap. Long documents sit in a single Note node, max 760px.

Spacing steps observed: 6, 8, 12, 16, 24, 32, 56, 72px; node bodies pad 10-12px, widget rows 5px 10px with 6px between rows.

Responsive: at 960px steps, hero and install collapse to one column (node first) at 36px gap; at 720px the bar hides button text and the brand name, node tags hide, the hero graph stacks into a single chain, and wires tighten their curve. Where a single column puts text between two wired nodes, the wire is masked around the text rather than crossing it. Wide screenshots swap to purpose-made narrow crops below 720px (`picture` with a media-matched source; the recipe video swaps its source and poster the same way).

**The Touch Target Rule.** Below 720px every button (small ones included), the media toggle, each top-bar tab, the brand link and each footer link is at least 44px tall. On desktop buttons stay 40px and small buttons 32px.

## Elevation & Depth

Flat tonal layering with one shadow. The canvas is darkest, nodes sit one step lighter, title bars a step lighter still, and inset elements (widgets, commands, rows) drop back toward the canvas. Every node carries the same soft ambient shadow so it reads as floating above the grid; nothing else casts a shadow. Two glass layers exist, both functional: the sticky bar (Canvas Glass with an 8px blur) and the media toggle over video (Panel Glass, no blur).

### Shadow Vocabulary
- **Node float** (`--shadow-node`: `0 18px 40px -22px rgba(0,0,0,0.9), 0 2px 6px rgba(0,0,0,0.35)`): every node.
- **Missing ring** (`0 0 0 1px` Missing Red, then `--shadow-node-soft`: `0 18px 40px -22px rgba(0,0,0,0.9)`): a node whose model is missing; it replaces the float.
- **Pin halo** (`0 0 0 2px` Node Grey): separates a pin from the node edge it overhangs.

### Named Rules
**The One Float Rule.** Nodes float; their contents do not. Depth inside a node comes from the inset tone, never a second shadow.

## Shapes

Gently rounded on a closed, named scale, and nothing outside it: code chips and the panel node's app icon 5px (`--r-code`); widget rows, the brand logo and the focus ring 7px (`--r-widget`); buttons, tabs, list rows, the media toggle, the preview well and the scrollbar thumb 8px (`--r-control`); commands, summaries and tables 9px (`--r-inset`); nodes and the panel-shot 10px (`--radius`); group frames 12px (`--r-group`); pills and progress bars fully round (`--r-pill`). Pins and title dots are 10px circles. A node's title bar shares the node's top corners; a screenshot body is clipped to the bottom corners (node radius less the 1px border). Borders are 1px hairlines everywhere; the preview placeholder is dashed until its image arrives. Pins overhang the node edge by 6px on their side (inputs left, outputs right) so wires meet the border.

## Components

### Buttons
- **Shape:** gently rounded (8px), 40px tall, 1px border; 44px below 720px.
- **Neutral:** Control grey with Strong Hairline border and Ink text, weight 500 at 0.9375rem; hover to Control Hover with a Hover Hairline border.
- **Primary:** Librarian Blue fill and border, On Accent text; hover to Pressed Blue. Transitions 0.15s on background and border.
- **Small:** 32px tall, 11px padding, 0.875rem; used in the bar, inside commands and in group frames.
- **Focus:** 2px Link Blue outline, 2px offset, 7px corners (every focusable element).
- **Disabled:** 55% opacity. Icons are 16px stroked SVGs (1.8 stroke) with an 8px gap.

### Chips (status pills)
- **Style:** transparent, 22px tall, fully round, 1px border in the text colour, Label type.
- **State:** Missing (red), Moved (amber), OK (green), Quiet (dim text, Strong Hairline border) for neutral facts like a source name. A pill flips from Missing to OK in place when its download finishes, including when it sits in a node's title bar.

### Cards / Containers: the node
- **Corner Style:** 10px.
- **Background:** Node Grey body, Title Bar Grey head (36px min, 12px padding) with a 1px Hairline under it.
- **Title bar:** 10px dot in the node's hue, title in Title type, and an optional right-aligned Dim tag or status pill. The Model Librarian panel node swaps the dot for the 18px app icon on a Panel Head bar.
- **Body:** a ports row (inputs left, outputs right, pins overhanging the edge), then widget rows, list rows, or a screenshot clipped to the bottom corners over Shot Black.
- **Shadow Strategy:** Node float (see Elevation).

### Screenshot bodies
- **Shot:** the image or video fills the node body, clipped to the bottom corners.
- **Fade right:** a wide shot that runs past its node fades out over its last 18% (a mask from opaque at 82% to transparent), so the crop reads as deliberate.
- **Panel shot:** a screenshot that is itself a panel sits inset in the node (max 500px, 10px corners) with no Shot Black behind it, so its own edges show.

### Media toggle
A Pause / Play control over a looping video, bottom-right 12px in from the corner: 36px tall (44px on phones), 8px corners, Strong Hairline border, Panel Glass fill (Control on hover), Label type with a 16px icon. It reports its state with `aria-pressed`. It stays hidden where the video isn't autoplaying: with reduced motion the video shows native controls instead.

### Progress bars
A 4px track in Track grey, fully round, with a fully round fill: Librarian Blue for downloads, LATENT Pink for the sampler.

### Inputs / Fields: widget rows and commands
- **Widget row:** Inset background, Hairline border, 7px corners, 30px min height; key in Dim on the left, value in Ink at weight 500 on the right, truncated with an ellipsis.
- **Command field:** Inset background, Strong Hairline border, 9px corners; the command in Mono with a small Copy button at the right that reads "Copied" (or "Selected" when the clipboard is refused) for 1.6s. A visually hidden status region announces the same result to screen readers.

### Navigation
- **Bar:** sticky, 52px, Canvas Glass with an 8px backdrop blur and a Hairline bottom border; brand (26px icon, weight 600) then tabs, with Ko-fi and the primary action at the far right.
- **Tabs:** Soft Ink at 0.9375rem, 6px 12px, 8px corners; hover fills Control grey; the current page fills Librarian Blue with On Accent text, like the app's tab strip. Below 720px tabs are 44px tall at 0.875rem.

### Group frame
ComfyUI's group, coloured by the Derived Group Rule: 12px corners, a 1px border, a tinted body and a deeper-tinted header with the name in weight 600 and a 0.8125rem Soft Ink subtitle. Holds a command, an ordered list and small buttons pinned to the bottom.

### Wire
SVG paths, 2.5px round-capped stroke at 85% opacity, slot-coloured, a cubic bezier with horizontal tangents (out to the right, in from the left). Wires feeding a broken graph sit at 35% until it is fixed. Wires further down draw themselves (stroke-dashoffset, 1.1s, cubic-bezier(0.16, 1, 0.3, 1)) when their target node rises into view.

### Motion and reduced motion
Motion is limited to the wire draw, the sample image fading in (0.6s), scripted progress bars and the looping recipe video. With prefers-reduced-motion the wires are simply present, the image appears without a fade, the demo jumps to its end state and the video shows controls instead of autoplaying. Colour feedback (hover fills, pills turning OK) stays.

## Do's and Don'ts

### Do:
- **Do** put content in nodes with a title bar, a coloured dot and real ports, and join them with wires between same-typed pins.
- **Do** label outputs with UPPERCASE type names and inputs with lowercase slot names.
- **Do** use the real app screenshots and recordings as node bodies, labelled as sample data, with narrow crops for phones.
- **Do** keep blue for the next action and download progress, and red, amber, green for model status only.
- **Do** name every new colour and radius as a `:root` token, and set hues with classes.
- **Do** give every control a 44px target below 720px.
- **Do** honour prefers-reduced-motion: wires appear without drawing, demos jump to their end state, videos show controls instead of autoplaying.

### Don't:
- **Don't** colour a wire by anything but its ComfyUI slot type, or join two different types.
- **Don't** add a second shadow, glow or gradient inside a node; depth inside is tonal.
- **Don't** use the base-model badge colours on wires or dots; they belong to model tags inside the app screenshots.
- **Don't** fill neutral buttons with blue, or use status colours as decoration.
- **Don't** set large type inside a node, except the Note node's headline.
- **Don't** add a radius outside the named scale, a colour literal outside `:root`, or a hue in an inline style.
- **Don't** add a light theme; the page is dark like the apps.
