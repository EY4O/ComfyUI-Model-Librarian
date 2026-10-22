# Recipe format (`recipe/1`)

A recipe is everything needed to remake an image: the prompts, the sampler
settings and the exact models (checkpoint, LoRAs, VAE) it used. Model Librarian
stores one JSON file per recipe in `<shared data>/recipes/<id>.json`, with an
optional `<id>.webp` thumbnail. The same shape is meant to be shared with
[Prompto](https://github.com/EY4O/prompto), so a recipe captured in one can be
used in the other.

Readers should ignore keys they don't know. Writers should keep keys they don't
understand when they rewrite a file.

## Example

```json
{
  "schema": "recipe/1",
  "id": "3f9c0a1b2d4e",
  "title": "Lighthouse at dusk",
  "created": 1791836800.0,
  "format": "civitai",
  "source": { "url": "https://civitai.com/images/555", "site": "civitai", "filename": null, "image_id": 555 },
  "prompt": { "positive": "a lighthouse on a cliff at dusk, watercolor", "negative": "blurry, lowres" },
  "settings": {
    "sampler": "euler_ancestral", "scheduler": "karras", "sampler_raw": "Euler a Karras",
    "steps": 28, "cfg": 5.0, "seed": 81723, "width": 832, "height": 1216,
    "denoise": null, "clip_skip": 2
  },
  "model": {
    "name": "Illustrious XL", "file": "illustriousXL_v20", "type": "checkpoint",
    "hash": "1a2b3c4d5e", "civitai_version_id": 999, "civitai_model_id": null
  },
  "vae": null,
  "loras": [
    {
      "name": "watercolor_v3", "file": "watercolor_v3", "display_name": "Watercolor Wash", "version": "v3",
      "hash": "aaaa1111bb", "civitai_version_id": 111, "civitai_model_id": null,
      "weight": 0.8, "clip_weight": null
    }
  ],
  "base_model": "Illustrious",
  "tags": ["watercolor"],
  "notes": "",
  "fav": false,
  "comfy": null
}
```

## Fields

| Key | Type | Meaning |
|---|---|---|
| `schema` | string | Always `"recipe/1"` for this version. |
| `id` | string \| null | 12 lowercase hex characters once saved; `null` in a draft. |
| `title` | string | Display name. |
| `created`, `updated` | number | Unix time in seconds. |
| `format` | string | Where the data came from: `comfyui`, `comfyui-workflow`, `a1111`, `civitai`, `novelai`, `invokeai`, `swarmui`, `fooocus`. |
| `source` | object | `url` (page the image came from), `site`, `filename` (dropped file), `image_id` (site's id). Any of them may be `null`. A recipe saved from a ComfyUI run adds `output`: `{filename, subfolder, type}`, the image in ComfyUI's `output` (or `temp`) folder. |
| `image` | string | Optional. The full-size copy kept with the recipe (`<id>.png`, next to its JSON), when you chose to keep one. |
| `prompt` | object | `positive` and `negative` text. LoRA tags (`<lora:…>`) are removed from the text and listed in `loras`. |
| `settings` | object | `sampler` and `scheduler` use **ComfyUI names** (`dpmpp_2m`, `karras`); `sampler_raw` keeps the original label (`DPM++ 2M Karras`). `clip_skip` is positive (2 = ComfyUI's `stop_at_clip_layer: -2`). Unknown values are `null`. |
| `model` | ref \| null | The checkpoint or diffusion model. Adds `type`: `checkpoint` or `unet`, and `downloadable: false` for models that can't be downloaded (e.g. NovelAI). |
| `vae` | ref \| null | A separate VAE, if one was used. |
| `loras` | ref[] | In the order they were applied. Each adds `weight` (model strength, may be negative) and `clip_weight` (`null` = same as `weight`). |
| `base_model` | string \| null | CivitAI's base model label (`Illustrious`, `SDXL 1.0`, `Flux.1 D`…). |
| `tags`, `notes`, `fav` | | User's own organisation. |
| `comfy` | object \| null | `prompt` (API graph) and/or `workflow` (UI graph) when the image was made in ComfyUI, so it can be reopened exactly. |

### Model references

```json
{ "name": "…", "file": "…", "hash": "…", "civitai_version_id": 0, "civitai_model_id": 0 }
```

- `file` is the file name as the generator saw it, with or without folders and
  extension (`Illustrious\\watercolor_v3.safetensors`, `watercolor_v3`).
  Match on the stem.
- `hash` is lowercase hex: a full SHA256, or a short form (AutoV2 = first 10
  characters of the SHA256; A1111's LoRA hashes are 12). Compare on the shorter
  prefix.
- `civitai_version_id` is the most reliable way to find the exact file.
- Any field may be `null`; a reference needs at least one of them.

## Finding the models

Model Librarian resolves each reference in this order: the SHA256 index of
local files → file stem under ComfyUI's model folders → CivitAI by version id →
CivitAI by hash → name search (shown, but never bulk-downloaded). LoRAs are
downloaded into the folder for their base model.

## From another extension

In the ComfyUI page, `window.ModelLibrarian.openRecipe(recipe, { thumb })` opens a recipe/1 object in
Model Librarian's Recipes tab, ready to download what's missing and fill the workflow. `thumb` is an
optional image (a `data:image/…` URL is also saved with the recipe). Partial recipes are fine:
missing keys are filled in. [ComfyUI-Prompto](https://github.com/EY4O/ComfyUI-Prompto) uses this when
a recipe's models aren't installed.

```js
if (window.ModelLibrarian?.openRecipe) {
  await window.ModelLibrarian.openRecipe({
    schema: "recipe/1",
    prompt: { positive: "a lighthouse", negative: "" },
    loras: [{ file: "watercolor_v3", hash: "aaaa1111bb", civitai_version_id: 111, weight: 0.8 }],
  });
}
```

Image files can carry a recipe too: a `recipe` text chunk (PNG) holding the JSON is read as is
(Prompto's share cards include one).

The other way, **Send to Prompto** queues a recipe for the Prompto Chrome extension through
ComfyUI-Prompto (0.8.1 or newer, which lists `"recipe"` in `GET /prompto/status` → `capture_kinds`):

```js
await api.fetchApi("/prompto/captures", { method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ kind: "recipe", source: "Model Librarian", title, recipe, thumb }) });
```

`recipe` is a recipe/1 object (without `comfy`, to stay well under the 4 MB capture limit) and `thumb`
an optional `data:image/…` URL. Prompto files it in its inbox with the model hashes and version ids.

## Test fixtures

`tests/fixtures/recipe1.json` lists metadata inputs with the recipe each must produce. The same file
is in [Prompto](https://github.com/EY4O/prompto) (same path), whose JavaScript parsers run every case
too, so the Python and JS readers agree. Change both copies together.

## HTTP API (Model Librarian)

All under ComfyUI's `/api/sm-fetcher`:

| Route | |
|---|---|
| `POST /recipe/analyze` | multipart `image`, or JSON `{"url": "…"}` → `{recipe, thumb, items}`; a CivitAI post link returns `{choices: [{url, thumb, has_meta}]}` instead. 422 when there's no generation data. |
| `POST /recipe/plan` | `{"recipe": {…}}` → `{items, recipe}`: each model's local match or download candidate, and the recipe filled out to the full shape. |
| `POST /recipe/link` | `{"item": {…}, "file": "Illustrious/x.safetensors"}` → `{item}` matched to that installed file; remembered by the item's name and hash (`model_links.json`). `"file": null` forgets the link. |
| `POST /recipe/link-url` | `{"item": {…}, "url": "https://…"}` → `{item}` with a planned download from that page or file link (CivitAI, HuggingFace or a direct link). |
| `GET /recipes` | Summaries, newest first. |
| `POST /recipes` | `{"recipe": {…}, "thumb": "data:image/webp;base64,…"}` → `{recipe}` with `id` and `created` set. |
| `GET` / `PATCH` / `DELETE /recipes/{id}` | Read; edit `title`, `tags`, `notes`, `fav`; delete (moved to `recipes/_deleted/`). |
| `GET /recipes/{id}/thumb` | The WebP thumbnail. |
