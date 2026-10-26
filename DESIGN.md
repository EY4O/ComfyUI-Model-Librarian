---
name: Model Librarian
description: The Model Librarian suite's homepage, drawn as a ComfyUI workflow on the apps' own charcoal canvas.
colors:
  canvas: "#161616"
  grid: "#262626"
  node: "#242424"
  node-head: "#2e2e2e"
  panel: "#1c1c1c"
  control: "#2c2c2c"
  line: "#363636"
  line-2: "#464646"
  text: "#ececec"
  text-2: "#cfcfcf"
  dim: "#a3a3a3"
  accent: "#2563eb"
  accent-hover: "#1d4fd0"
  link: "#8cb8ff"
  missing: "#f87171"
  missing-ink: "#fecaca"
  moved: "#fbbf24"
  ok: "#4ade80"
  wire-model: "#c084fc"
  wire-clip: "#fbbf24"
  wire-vae: "#f87171"
  wire-latent: "#f472b6"
  wire-image: "#60a5fa"
  wire-library: "#34d399"
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
  button-primary:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
    rounded: "{rounded.control}"
    padding: "0 16px"
    height: "40px"
  button-primary-hover:
    backgroundColor: "{colors.accent-hover}"
  button-small:
    rounded: "{rounded.control}"
    padding: "0 11px"
    height: "32px"
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
  node-body:
    padding: "10px 12px 12px"
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
  tab:
    textColor: "{colors.text-2}"
    rounded: "{rounded.control}"
    padding: "6px 12px"
  tab-hover:
    backgroundColor: "{colors.control}"
    textColor: "{colors.text}"
  tab-current:
    backgroundColor: "{colors.accent}"
    textColor: "#ffffff"
  group-frame:
    backgroundColor: "{colors.node}"
    rounded: "{rounded.group}"
    padding: "16px"
---

# Design System: Model Librarian

## Overview

**Creative North Star: "The Workflow Canvas"**

The suite's web presence looks like the place its users already work: a ComfyUI graph on a charcoal canvas with a faint dot grid. Content lives in nodes (a darker title bar with a coloured dot, a body of ports and widget rows) and nodes are joined by wires that leave an output pin on the right and arrive at an input pin on the left. The world is inherited, not invented: Model Librarian Gallery's charcoal "Darkroom" neutrals, Segoe UI Variable, Model Librarian's blue for actions and its status pills.

Density is the apps' density: small labels, hairline borders, tight widget rows, generous space only between nodes. Colour is functional. Neutrals carry everything; blue means "do this"; red, amber and green mean model status; and the saturated slot colours belong to wires, pins and node dots, where they encode data type exactly as ComfyUI does. Real screenshots and recordings sit inside nodes as their bodies, so the product's own UI is the imagery.

**Key Characteristics:**
- Charcoal canvas (dot grid every 24px) with flat grey nodes floating on a soft ambient shadow.
- Node anatomy: title bar with type-coloured dot, optional tag or pill at the right, ports row, widget rows or a screenshot body.
- Wires coloured by ComfyUI slot type, drawn as horizontal-tangent bezier curves between same-typed pins.
- One action colour (blue) and three status colours (red, amber, green), never used decoratively.
- Segoe UI Variable throughout, with the Display optical size for headings.

## Colors

A near-neutral charcoal ramp with one action blue, three status hues and a set of ComfyUI slot-type colours that live only on the graph.

### Primary
- **Librarian Blue** (accent): primary buttons, the current tab, download progress fills, text selection tint. White text on it; it darkens to **Pressed Blue** (accent-hover) on hover. This is darker than the apps' #3b82f6 so white labels pass AA.
- **Link Blue** (link): inline links and the focus ring (2px outline, 2px offset). Hover lightens toward #b4d0ff.

### Secondary
- **Missing Red** (missing): Missing pills, the outline and 1px ring on a node whose model is absent. **Missing Ink** (missing-ink) colours the widget values inside a missing node.
- **Moved Amber** (moved): Moved pills and rating stars.
- **OK Green** (ok): OK pills and the default tick colour in feature lists.

### Tertiary: slot types
- **MODEL Violet** (wire-model), **CLIP Amber** (wire-clip), **VAE Red** (wire-vae), **LATENT Pink** (wire-latent), **IMAGE Blue** (wire-image), and the suite's own **LIBRARY Green** (wire-library). They colour wires, pins, port labels' pins, node title dots, a node's feature-list ticks, and install group frames. A node's dot takes the colour of the type it mainly carries.

### Neutral
- **Canvas** (canvas): page background, sticky bar (at 94% opacity with blur) and footer.
- **Grid Dot** (grid): the 1.2px dots of the canvas grid.
- **Node Grey** (node): node bodies; also the halo ring around pins.
- **Title Bar Grey** (node-head): node title bars.
- **Inset** (panel): widget rows, command fields, list rows inside a node, summary boxes, code chips.
- **Control** (control): neutral buttons and tab hover.
- **Hairline** (line) and **Strong Hairline** (line-2): node, widget and row borders; button and command borders, quiet pills, dashed placeholders.
- **Ink** (text), **Soft Ink** (text-2), **Dim** (dim): headings and values; body copy and lists; labels, ports, captions, meta.

### Named Rules
**The Slot Colour Rule.** Wire colour is the ComfyUI slot type of the pins it joins, and a wire only ever joins an output and an input of the same type. Never colour a wire by section, brand or mood.

**The Status Is Not Decoration Rule.** Red, amber and green mean Missing, Moved and OK. They appear only where a model's state is being shown.

**The One Action Colour Rule.** Blue fills only the next action (primary button, current tab) and progress. Neutral buttons stay grey.

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
- **Title** (600, 0.9375rem, 1.2): node titles, list-row names, button text at weight 500.
- **Lead** (400, 1.1875rem, 1.5, max 34ch): the hero sentence.
- **Body Large** (400, 1.0625rem, max 46ch beside a node, 60ch for section intros): step copy.
- **Body** (400, 1rem, 1.55, max 68ch in documents).
- **Label** (500, 0.8125rem): pills, widget rows, tags, captions, meta lines; sizes in tabular numerals.
- **Port** (400, 0.75rem, +0.02em): port labels. Outputs are UPPERCASE type names (MODEL, IMAGE), inputs are lowercase slot names (model, samples), as ComfyUI writes them.

### Named Rules
**The App Voice Rule.** Inside a node, type is app-sized (0.75 to 0.9375rem). Large type exists only outside nodes or in the Note node's headline.

## Layout

Pages are a column of steps on the canvas, max 1320px wide with 32px side padding (16px on phones). Each step is a two-column grid, node and text at 7:5 (alternating to 5:7), 56px gap, 72px vertical padding; the hero uses 5:7 and fills the first viewport. The hero graph is a two-column grid of nodes (24px row gap, 64px column gap) so wires have room to curve. Install is a three-column row of group frames, 24px gap. Long documents sit in a single Note node, max 760px.

Spacing steps observed: 6, 8, 12, 16, 24, 32, 56, 72px; node bodies pad 10-12px, widget rows 5px 10px with 6px between rows.

Responsive: at 960px steps, hero and install collapse to one column (node first) at 36px gap; at 720px the bar hides button text and the brand name, node tags hide, the hero graph stacks into a single chain, and wires tighten their curve (tangent 36-44px instead of 70-160px). Where a single column puts text between two wired nodes, the wire is masked around the text with a 14px margin rather than crossing it.

## Elevation & Depth

Flat tonal layering with one shadow. The canvas is darkest, nodes sit one step lighter, title bars a step lighter still, and inset elements (widgets, commands, rows) drop back toward the canvas. Every node carries the same soft ambient shadow so it reads as floating above the grid; nothing else casts a shadow.

### Shadow Vocabulary
- **Node float** (`box-shadow: 0 18px 40px -22px rgba(0,0,0,0.9), 0 2px 6px rgba(0,0,0,0.35)`): every node.
- **Missing ring** (`box-shadow: 0 0 0 1px #f87171, 0 18px 40px -22px rgba(0,0,0,0.9)`): a node whose model is missing; it replaces the float.
- **Pin halo** (`box-shadow: 0 0 0 2px #242424`): separates a pin from the node edge it overhangs.

### Named Rules
**The One Float Rule.** Nodes float; their contents do not. Depth inside a node comes from the inset tone, never a second shadow.

## Shapes

Gently rounded and consistent: nodes 10px, group frames 12px, buttons, tabs and rows 8px, commands 9px, widget rows 7px, code chips 5px, pills fully round. Pins and title dots are 10px circles. A node's title bar shares the node's top corners; a screenshot body is clipped to the bottom corners. Borders are 1px hairlines everywhere; the preview placeholder is dashed until its image arrives. Pins overhang the node edge by 6px on their side (inputs left, outputs right) so wires meet the border.

## Components

### Buttons
- **Shape:** gently rounded (8px), 40px tall, 1px border.
- **Neutral:** Control grey with Strong Hairline border and Ink text, weight 500 at 0.9375rem; hover lifts to #343434 with a #555 border.
- **Primary:** Librarian Blue fill and border, white text; hover to Pressed Blue. Transitions 0.15s on background and border.
- **Small:** 32px tall, 11px padding, 0.875rem; used in the bar, inside commands and in group frames.
- **Disabled:** 55% opacity. Icons are 16px stroked SVGs (1.8 stroke) with an 8px gap.

### Chips (status pills)
- **Style:** transparent, 22px tall, fully round, 1px border in the text colour, Label type.
- **State:** Missing (red), Moved (amber), OK (green), Quiet (dim text, Strong Hairline border) for neutral facts like a source name. A pill flips from Missing to OK in place when its download finishes.

### Cards / Containers: the node
- **Corner Style:** 10px.
- **Background:** Node Grey body, Title Bar Grey head (36px min, 12px padding) with a 1px Hairline under it.
- **Title bar:** 10px dot in the node's slot colour, title in Title type, and an optional right-aligned Dim tag or status pill. The Model Librarian panel node swaps the dot for the 18px app icon on a faintly blue head (#23262e).
- **Body:** a ports row (inputs left, outputs right, pins overhanging the edge), then widget rows, list rows, or a screenshot clipped to the bottom corners.
- **Shadow Strategy:** Node float (see Elevation).

### Inputs / Fields: widget rows and commands
- **Widget row:** Inset background, Hairline border, 7px corners, 30px min height; key in Dim on the left, value in Ink at weight 500 on the right, truncated with an ellipsis.
- **Command field:** Inset background, Strong Hairline border, 9px corners; the command in Mono with a small Copy button at the right that reads "Copied" for 1.6s.

### Navigation
- **Bar:** sticky, 52px, Canvas at 94% with an 8px backdrop blur and a Hairline bottom border; brand (26px icon, weight 600) then tabs, with Ko-fi and the primary action at the far right.
- **Tabs:** Soft Ink at 0.9375rem, 6px 12px, 8px corners; hover fills Control grey; the current page fills Librarian Blue with white text, like the app's tab strip.

### Group frame
ComfyUI's group: 12px corners, a 1px border of the group's slot colour at 55%, body tinted 7% toward that colour over Node Grey, header tinted 22% with the name in weight 600 and a 0.8125rem Soft Ink subtitle. Holds a command, an ordered list and small buttons.

### Wire
SVG paths, 2.5px round-capped stroke at 85% opacity, slot-coloured, a cubic bezier with horizontal tangents (out to the right, in from the left). Wires feeding a broken graph sit at 35% until it is fixed. Wires further down draw themselves (stroke-dashoffset, 1.1s, cubic-bezier(0.16, 1, 0.3, 1)) when their target node rises into view; with reduced motion they are simply present.

## Do's and Don'ts

### Do:
- **Do** put content in nodes with a title bar, a slot-coloured dot and real ports, and join them with wires between same-typed pins.
- **Do** label outputs with UPPERCASE type names and inputs with lowercase slot names.
- **Do** use the real app screenshots and recordings as node bodies, labelled as sample data.
- **Do** keep blue for the next action and progress, and red, amber, green for model status only.
- **Do** honour prefers-reduced-motion: wires appear without drawing, demos jump to their end state, videos show controls instead of autoplaying.

### Don't:
- **Don't** colour a wire by anything but its ComfyUI slot type, or join two different types.
- **Don't** add a second shadow, glow or gradient inside a node; depth inside is tonal.
- **Don't** use the base-model badge colours on wires or dots; they belong to model tags inside the app screenshots.
- **Don't** fill neutral buttons with blue, or use status colours as decoration.
- **Don't** set large type inside a node, except the Note node's headline.
