// "Recipes" tab: Model Librarian's own recipe library (no LoRA Manager needed).
// Drop an image or paste a link (CivitAI image/post, or a direct image file) to
// read its generation data, save it as a recipe, download every model it used
// into the shared models folder, then fill the open workflow with it or
// open it as a new one. With LoRA Manager installed, saved recipes can also be
// mirrored into its recipe list.
import { call, ctx, h, clear, fmtSize, toast, pill, spinner, familyBadge, copy, apiUrl } from "./util.js";
import { startDownload, onJobsChange } from "./downloads.js";
import { fillWorkflow, buildApiGraph, resolved, loraSyntax, lmMetadata, stem } from "./recipe_apply.js";
import { parseStrengths } from "./compare.js";
import { openComparison, loadInNewTab } from "./compareComfy.js";

const r = {
  root: null, view: "library", list: null, filter: "", favOnly: false, url: "",
  busy: null, error: null, choices: null,
  d: null, // open recipe: { recipe, items, thumb, file, preview, savedId, lmSaved, tags, lmId }
  lmList: null, // LoRA Manager's own recipes (read-only here)
};
const queued = new Map(); // jobId -> plan item

onJobsChange((jobs, finished) => {
  let changed = false;
  for (const j of finished) {
    const it = queued.get(j.id);
    if (!it) continue;
    queued.delete(j.id);
    it.job = null;
    if (j.status === "done") {
      it.status = "present";
      it.local = it.comfy_name = it.download.rel;
      it.matched_by = "downloaded";
    } else it.note = j.error || "Download failed";
    changed = true;
  }
  if (changed) render();
});

export function mount(root) {
  r.root = root;
  if (!r.list) loadList();
  if (ctx.status?.lm_installed && !r.lmList) loadLm();
  render();
}

// Called for drops anywhere on the Model Librarian window. Must read the
// DataTransfer synchronously: it's emptied once the event handler returns.
export function canHandle(dt) {
  return !!pickFile(dt) || !!pickUrl(dt);
}

export function openFile(f) {
  return analyzeFile(f);
}

export function handleDrop(dt) {
  const f = pickFile(dt);
  if (f) return analyzeFile(f);
  const u = pickUrl(dt);
  if (u) {
    r.url = u;
    return analyzeUrl(u);
  }
}

const isVideoFile = (f) => /^video\//.test(f?.type || "") || /\.(mp4|m4v|mov|webm|mkv)$/i.test(f?.name || "");

function pickFile(dt) {
  return [...(dt?.files || [])].find((f) => /^image\//.test(f.type) || isVideoFile(f)) || null;
}

// A still from a video (for the recipe's thumbnail), made in the browser.
function videoThumb(file) {
  return new Promise((resolve) => {
    const v = document.createElement("video");
    const url = URL.createObjectURL(file);
    let done = false;
    const finish = (val) => { if (!done) { done = true; URL.revokeObjectURL(url); resolve(val); } };
    v.muted = true;
    v.preload = "auto";
    v.onloadeddata = () => { v.currentTime = Math.min(0.5, (v.duration || 1) / 3); };
    v.onseeked = () => {
      try {
        const k = Math.min(1, 512 / Math.max(v.videoWidth, v.videoHeight));
        const c = document.createElement("canvas");
        c.width = Math.round(v.videoWidth * k);
        c.height = Math.round(v.videoHeight * k);
        c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
        finish(c.toDataURL("image/webp", 0.85));
      } catch {
        finish(null);
      }
    };
    v.onerror = () => finish(null);
    setTimeout(() => finish(null), 10000);
    v.src = url;
  });
}

function pickUrl(dt) {
  const txt = dt?.getData?.("text/uri-list") || dt?.getData?.("text/plain") || "";
  return txt.split(/\r?\n/).map((l) => l.trim()).find((l) => /^https:\/\//.test(l)) || null;
}

async function loadList() {
  try {
    r.list = (await call("/recipes")).recipes;
  } catch (e) {
    r.list = [];
    toast("error", "Couldn't load recipes", e.message);
  }
  render();
}

// LoRA Manager's recipes, shown read-only under ours (newest 200).
async function loadLm() {
  try {
    const res = await ctx.api.fetchApi("/lm/recipes?page=1&page_size=200&sort_by=date");
    const data = res.ok ? await res.json() : null;
    r.lmList = Array.isArray(data?.items) ? data.items : [];
  } catch {
    r.lmList = [];
  }
  render();
}

const normTitle = (t) => String(t || "").trim().toLowerCase();

// LoRA Manager recipes that aren't copies of ours (mirrored ones carry our lm_id, older ones the same title)
function lmOnly() {
  const ids = new Set((r.list || []).map((x) => x.lm_id).filter(Boolean));
  const titles = new Set((r.list || []).map((x) => normTitle(x.title)));
  return (r.lmList || []).filter((x) => !ids.has(String(x.id)) && !titles.has(normTitle(x.title)));
}

async function blobToDataUrl(blob) {
  return new Promise((resolve) => {
    const fr = new FileReader();
    fr.onload = () => resolve(fr.result);
    fr.onerror = () => resolve(null);
    fr.readAsDataURL(blob);
  });
}

async function openLm(x) {
  closeDetail();
  r.busy = "Opening the LoRA Manager recipe…";
  render();
  try {
    const { recipe } = await call("/recipe/from-lm", { method: "POST", body: { item: x } });
    let thumb = null;
    try {
      const img = await fetch(`${ctx.api.api_base || ""}${x.file_url}`);
      if (img.ok) {
        // LoRA Manager serves previews as application/octet-stream; the server re-encodes them anyway
        const blob = await img.blob();
        thumb = await blobToDataUrl(blob.type.startsWith("image/") ? blob : new Blob([blob], { type: "image/webp" }));
      }
    } catch {}
    r.busy = null;
    return openExternal(recipe, { thumb, lmId: String(x.id) });
  } catch (e) {
    r.error = e.message;
  }
  r.busy = null;
  render();
}

function closeDetail() {
  if (r.d?.preview?.startsWith("blob:")) URL.revokeObjectURL(r.d.preview);
  Object.assign(r, { d: null, view: "library", error: null, busy: null, choices: null });
}

// ---------------------------------------------------------------- analyze
async function analyzeFile(f) {
  closeDetail();
  const video = isVideoFile(f);
  r.busy = video ? "Reading the video's generation data…" : "Reading generation data…";
  render();
  const fd = new FormData();
  fd.append("image", f);
  try {
    const res = await ctx.api.fetchApi("/sm-fetcher/recipe/analyze", { method: "POST", body: fd });
    const a = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(a.error || `HTTP ${res.status}`);
    if (video && !a.thumb) a.thumb = await videoThumb(f);
    openDraft(a, { file: f, preview: URL.createObjectURL(f), video });
  } catch (e) {
    r.error = e.message;
  }
  r.busy = null;
  render();
}

async function analyzeUrl(url) {
  url = (url || "").trim();
  if (!/^https:\/\//.test(url)) return toast("warn", "Invalid link", "Paste an https:// link to a CivitAI image or post, or to an image file.");
  closeDetail();
  r.url = url;
  r.busy = "Fetching the image and its generation data…";
  render();
  try {
    const a = await call("/recipe/analyze", { method: "POST", body: { url } });
    if (a.choices) {
      r.choices = a.choices;
      r.view = "choose";
    } else openDraft(a, {});
  } catch (e) {
    r.error = e.message;
  }
  r.busy = null;
  render();
}

function openDraft(a, extra) {
  r.d = { recipe: a.recipe, items: a.items || [], thumb: a.thumb, preview: extra.preview || a.thumb, file: extra.file || null,
    video: !!extra.video, savedId: null, lmSaved: false, tags: (a.recipe.tags || []).join(", ") };
  r.view = "detail";
}

// ComfyUI's /view link for an image in its output, temp or input folder
export const viewUrl = (im) => ctx.api.apiURL(`/view?${new URLSearchParams({ filename: im.filename, subfolder: im.subfolder || "", type: im.type || "output" })}`);

// An image a run just made, as a recipe ready to save: what made it (read from the image, or the run's own
// prompt and workflow), named after the workflow and the prompt. Saving can keep a full-size copy.
export async function openOutput(im, { workflowName } = {}) {
  closeDetail();
  r.busy = "Reading the image's generation data…";
  render();
  try {
    const a = await call("/recipe/from-output", { method: "POST", body: { filename: im.filename, subfolder: im.subfolder || "", type: im.type || "output", prompt_id: im.prompt_id || null } });
    const words = String(a.recipe.prompt?.positive || "").replace(/<[^>]*>|[()[\]{}]/g, " ").split(/[\s,]+/).filter(Boolean).slice(0, 6).join(" ");
    a.recipe.title = [workflowName, words].filter(Boolean).join(" · ") || a.recipe.title;
    if (workflowName && !(a.recipe.tags || []).includes(workflowName)) a.recipe.tags = [...(a.recipe.tags || []), workflowName];
    openDraft(a, { preview: viewUrl(im) });
    r.d.fromOutput = true;
    r.d.keepImage = im.type === "temp"; // a Preview Image's file goes when ComfyUI restarts: keep it by default
  } catch (e) {
    r.error = e.message;
  }
  r.busy = null;
  render();
}

// A recipe handed over by another extension (window.ModelLibrarian.openRecipe)
// or picked from LoRA Manager's recipes.
export async function openExternal(recipe, { thumb, lmId } = {}) {
  closeDetail();
  r.busy = "Checking which models are installed…";
  render();
  try {
    const res = await call("/recipe/plan", { method: "POST", body: { recipe } });
    const image = typeof thumb === "string" && /^(data:image\/|https:\/\/)/.test(thumb) ? thumb : null;
    openDraft({ recipe: res.recipe, items: res.items, thumb: image?.startsWith("data:image/") ? image : null }, { preview: image });
    if (lmId) r.d.lmId = lmId;
  } catch (e) {
    r.error = e.message;
  }
  r.busy = null;
  render();
}

async function openSaved(id) {
  closeDetail();
  r.busy = "Opening recipe…";
  render();
  try {
    const { recipe } = await call(`/recipes/${id}`);
    const v = (r.list || []).find((x) => x.id === id)?.thumb_v || 0;
    r.d = { recipe, items: [], thumb: null, preview: apiUrl(`/recipes/${id}/thumb?v=${v}`), file: null, savedId: id, lmSaved: false, tags: (recipe.tags || []).join(", ") };
    r.view = "detail";
    r.busy = "Checking which models are installed…";
    render();
    r.d.items = (await call("/recipe/plan", { method: "POST", body: { recipe } })).items;
  } catch (e) {
    r.error = e.message;
  }
  r.busy = null;
  render();
}

// ---------------------------------------------------------------- save / download
const tagList = (s) => s.split(",").map((t) => t.trim()).filter(Boolean);

async function save() {
  const d = r.d;
  d.recipe.tags = tagList(d.tags);
  if (d.lmId) d.recipe.lm_id = d.lmId; // a copy of a LoRA Manager recipe: don't mirror it back
  const { recipe, warning } = await call("/recipes", { method: "POST", body: { recipe: d.recipe, thumb: d.thumb, keep_image: !!d.keepImage } });
  if (warning) toast("warn", "Recipe", warning, 7000);
  d.recipe = recipe;
  d.savedId = recipe.id;
  r.list = null;
  loadList();
  if (!d.lmId && ctx.status?.lm_installed && ctx.status?.config?.recipes_mirror_lm) {
    try {
      const out = await mirrorToLm(d);
      d.lmSaved = true;
      if (out?.recipe_id) await patch({ lm_id: out.recipe_id });
    } catch (e) {
      toast("warn", "Saved, but not to LoRA Manager", e.message, 7000);
    }
  }
}

async function mirrorToLm(d) {
  const fd = new FormData();
  if (d.file) fd.append("image", d.file);
  else if (d.thumb) {
    fd.append("image_base64", d.thumb.split(",")[1]);
    fd.append("extension", ".webp");
  } else throw new Error("no image to give it");
  fd.append("name", d.recipe.title || "Imported recipe");
  fd.append("tags", JSON.stringify(d.recipe.tags || []));
  fd.append("metadata", JSON.stringify(lmMetadata(d.recipe)));
  const res = await ctx.api.fetchApi("/lm/recipes/save", { method: "POST", body: fd });
  const out = await res.json().catch(() => null);
  if (!res.ok || !out?.success) throw new Error(out?.error || `LoRA Manager: HTTP ${res.status}`);
  return out;
}

async function patch(fields) {
  const d = r.d;
  if (!d?.savedId) return;
  try {
    d.recipe = (await call(`/recipes/${d.savedId}`, { method: "PATCH", body: fields })).recipe;
    r.list = null;
    loadList();
  } catch (e) {
    toast("error", "Not saved", e.message);
  }
}

async function downloadItem(it) {
  const { confidence, dest, shared, ...payload } = it.download;
  // CivitAI calls UNet-only files "Checkpoint" too; the backend moves those to diffusion_models
  if (it.kind === "checkpoint") payload.auto_place = true;
  const job = await startDownload(payload);
  it.job = job.id;
  queued.set(job.id, it);
}

function missing(includeLow) {
  return (r.d?.items || []).filter((it) => it.status === "missing" && it.download && !it.job &&
    (includeLow || it.download.confidence !== "low"));
}

async function run({ doSave, doDownload }) {
  r.busy = doSave ? "Saving recipe…" : "Queueing downloads…";
  render();
  try {
    if (doSave && !r.d.savedId) await save();
    let n = 0;
    if (doDownload) for (const it of missing(false)) { await downloadItem(it); n++; }
    const parts = [];
    if (doSave) parts.push(`saved “${r.d.recipe.title}”${r.d.lmSaved ? " (also in LoRA Manager)" : ""}`);
    if (doDownload) parts.push(n ? `${n} download(s) queued` : "nothing to download");
    toast("success", "Recipe", parts.join(" · "), 5000);
  } catch (e) {
    toast("error", "Recipe failed", e.message, 8000);
  }
  r.busy = null;
  render();
}

// Fetch the picture again from the link the recipe was saved from (a broken or outdated one).
async function refreshPicture() {
  const d = r.d;
  r.busy = "Fetching the picture…";
  render();
  try {
    const { recipe } = await call(`/recipes/${d.savedId}/picture`, { method: "POST" });
    d.preview = apiUrl(`/recipes/${d.savedId}/thumb?v=${recipe.thumb_v}`);
    r.list = null;
    loadList();
    toast("success", "Recipe", "Picture refreshed", 3000);
  } catch (e) {
    toast("error", "Picture not refreshed", e.message, 7000);
  }
  r.busy = null;
  render();
}

async function remove() {
  const d = r.d;
  if (!confirm(`Delete the recipe “${d.recipe.title}”? (It's moved to recipes/_deleted, not erased.)`)) return;
  try {
    await call(`/recipes/${d.savedId}`, { method: "DELETE" });
    closeDetail();
    r.list = null;
    loadList();
  } catch (e) {
    toast("error", "Not deleted", e.message);
  }
}

// ---------------------------------------------------------------- apply
function closeWindow() {
  document.querySelector(".smf-close")?.click();
}

function fillCurrent() {
  const d = r.d;
  const graph = ctx.app?.graph;
  if (!graph) return toast("error", "No workflow", "Open a workflow in ComfyUI first.");
  const createNode = (type) => globalThis.LiteGraph?.createNode?.(type) || null;
  const res = fillWorkflow(graph, d.recipe, d.items, { createNode });
  if (!res.ok) return toast("warn", "Couldn't fill this workflow", res.error, 7000);
  toast(res.warnings.length ? "warn" : "success", "Recipe applied", [`Set: ${res.applied.join(", ")}`, ...res.warnings].join(" · "), 9000);
  if (!res.warnings.length) closeWindow();
}

async function openAsNew() {
  const d = r.d;
  const c = d.recipe.comfy || {};
  const name = (d.recipe.title || "recipe").replace(/[\\/:*?"<>|]+/g, "_");
  try {
    // in a new tab, without risking the open one (see loadInNewTab)
    if (c.workflow?.nodes) await loadInNewTab(ctx.app, () => ctx.app.loadGraphData(c.workflow, true, true, name), name);
    else if (c.prompt && ctx.app.loadApiJson) await loadInNewTab(ctx.app, () => ctx.app.loadApiJson(c.prompt, name), name);
    else {
      const g = buildApiGraph(d.recipe, d.items);
      if (!g) return toast("warn", "Can't build a workflow", "This recipe uses a UNet/diffusion model, which needs model-specific loaders. Use “Fill current workflow” on a workflow for that model instead.", 9000);
      if (!ctx.app.loadApiJson) return toast("error", "Can't open", "This ComfyUI version can't load API-format workflows.");
      await loadInNewTab(ctx.app, () => ctx.app.loadApiJson(g, name), name);
    }
    closeWindow();
  } catch (e) {
    toast("error", "Couldn't open the workflow", e.message);
  }
}

// The recipe's workflow with one of its LoRAs at several strengths, side by side (a new workflow).
async function compareRecipe() {
  const d = r.d, c = d.recipe.comfy || {}, cmp = d.compare;
  const strengths = parseStrengths(cmp.text);
  if (!strengths.length) return toast("warn", "Compare strengths", "Type the strengths to compare, like 0, 0.4, 0.7, 1.", 4000);
  const api = c.prompt && typeof c.prompt === "object" ? c.prompt : buildApiGraph(d.recipe, d.items);
  if (!api) return toast("warn", "Compare strengths", "This recipe has no ComfyUI workflow to copy, and its model needs model-specific loaders. Fill a workflow for that model, then use Compare strengths in the Workflow tab.", 9000);
  try {
    // the recipe's workflow names the LoRA as its creator had it; yours may be named differently
    const l = resolved(d.recipe, d.items).loras.find((x) => x.name === cmp.lora);
    await openComparison(ctx.app, toast, api, [cmp.lora, l?.orig].filter(Boolean), strengths, `${stem(cmp.lora)} strengths`,
      { rename: l?.installed ? cmp.lora : null });
    closeWindow();
  } catch (e) {
    toast("error", "Compare strengths", String(e.message || e), 6000);
  }
}

function compareRow(res) {
  const d = r.d;
  if (!d.compare) return null;
  const cmp = d.compare;
  return h("div.smf-actions.smf-compare",
    h("span.smf-dim.small", "LoRA"),
    h("select.smf-input", { style: { maxWidth: "260px" }, onchange: (e) => (cmp.lora = e.target.value) },
      res.loras.map((l) => h("option", { value: l.name, selected: l.name === cmp.lora }, l.stem + (l.installed ? "" : " (not installed)")))),
    h("span.smf-dim.small", "Strengths"),
    h("input.smf-input", { value: cmp.text, style: { width: "150px" }, oninput: (e) => (cmp.text = e.target.value), onkeydown: (e) => { if (e.key === "Enter") compareRecipe(); } }),
    h("button.smf-btn.small.primary", { onclick: compareRecipe }, "Build comparison"),
    h("span.smf-dim.small", "0 is without the LoRA. Opens as a new workflow."));
}

// ---------------------------------------------------------------- render
const KIND = { lora: "LORA", checkpoint: "CKPT", vae: "VAE" };

function statusCell(it) {
  if (it.job) return h("span", spinner(), " downloading");
  if (it.status === "present") return h("span", pill("Installed", it.matched_by === "similar name" ? "warn" : "ok", `Matched by ${it.matched_by}: ${it.comfy_name || it.local}`), " ",
    h("span.smf-dim.small", { title: it.comfy_name || it.local }, it.matched_by === "your link" || it.matched_by === "similar name" ? `${it.matched_by}: ${String(it.comfy_name || it.local).split(/[\\/]/).pop()}` : it.matched_by));
  if (it.status === "missing") {
    const c = it.download?.confidence;
    return h("span", pill("Missing", "bad"), c && c !== "high" ? [" ", pill(`${c} match`, "warn", "Found by searching the file name — check it's the right model")] : null);
  }
  return pill("Unavailable", "dim", it.note || "");
}

// ---------------------------------------------------------------- link by hand
const SECTIONS_FOR = { lora: ["loras"], checkpoint: ["checkpoints", "diffusion_models"], vae: [] };
const installed = {}; // kind -> [ComfyUI names]

async function installedNames(kind) {
  if (!installed[kind]) {
    const names = [];
    for (const s of SECTIONS_FOR[kind] || []) {
      try { names.push(...(await call(`/library?section=${s}`)).entries.map((e) => e.rel)); } catch {}
    }
    installed[kind] = names.sort((a, b) => a.localeCompare(b));
  }
  return installed[kind];
}

const norm = (s) => String(s || "").split(/[\\/]/).pop().replace(/\.[^.]+$/, "").toLowerCase().replace(/[^a-z0-9]/g, "");

async function linkFile(it, file) {
  try {
    const { item } = await call("/recipe/link", { method: "POST", body: { item: { ...it, edit: undefined }, file } });
    Object.assign(it, item, { edit: null });
    if (!file) { // matched through the link, so it never got a download planned: plan it now
      try { r.d.items = (await call("/recipe/plan", { method: "POST", body: { recipe: r.d.recipe } })).items; } catch {}
    }
    toast("success", file ? "Linked" : "Link removed", file ? `${it.name} → ${item.comfy_name}. Recipes naming it find it from now on.` : it.name, 5000);
  } catch (e) {
    toast("error", "Couldn't link it", e.message, 7000);
  }
  render();
}

async function linkUrl(it, url) {
  url = (url || "").trim();
  if (!/^https:\/\//.test(url)) return toast("warn", "Paste a link", "A CivitAI or HuggingFace page, or a direct https:// download link.");
  it.edit = "busy";
  render();
  try {
    const { item } = await call("/recipe/link-url", { method: "POST", body: { item: { ...it, edit: undefined }, url } });
    Object.assign(it, item, { edit: null });
  } catch (e) {
    it.edit = "url";
    toast("error", "Can't use that link", e.message, 8000);
  }
  render();
}

function editRow(it) {
  if (it.edit === "busy") return h("tr", h("td"), h("td", { colSpan: 5 }, h("span.smf-dim", spinner(), " Reading the link…")));
  if (it.edit === "url") {
    const inp = h("input.smf-input", { placeholder: "CivitAI or HuggingFace page, or a direct download link (https://)", style: { flex: 1 },
      onkeydown: (e) => e.key === "Enter" && linkUrl(it, inp.value) });
    setTimeout(() => inp.focus());
    return h("tr", h("td"), h("td", { colSpan: 5 }, h("div.smf-row", inp,
      h("button.smf-btn.small.primary", { onclick: () => linkUrl(it, inp.value) }, "Use link"),
      h("button.smf-btn.small.ghost", { onclick: () => { it.edit = null; render(); } }, "Cancel"))));
  }
  const listId = "smf-installed-" + it.kind;
  const list = h("datalist", { id: listId });
  const inp = h("input.smf-input", { list: listId, placeholder: `Start typing the name of your ${it.kind === "lora" ? "LoRA" : "model"} file…`, style: { flex: 1 },
    onkeydown: (e) => e.key === "Enter" && inp.value && linkFile(it, inp.value) });
  const sugg = h("div.smf-row.wrap.small");
  installedNames(it.kind).then((names) => {
    list.replaceChildren(...names.map((n) => h("option", { value: n })));
    // closest names first, as one-click choices
    const want = norm(it.name || it.file);
    const score = (n) => { const s = norm(n); return s === want ? 0 : s.includes(want) || want.includes(s) ? 1 : [...want].filter((c, i) => s[i] === c).length >= Math.min(4, want.length) ? 2 : 9; };
    const best = names.map((n) => [score(n), n]).filter(([sc]) => sc < 9).sort((a, b) => a[0] - b[0]).slice(0, 6);
    sugg.replaceChildren(...(best.length ? [h("span.smf-dim", "Close matches: "), ...best.map(([, n]) => h("button.smf-btn.small", { onclick: () => linkFile(it, n) }, n))] : []));
  });
  setTimeout(() => inp.focus());
  return h("tr", h("td"), h("td", { colSpan: 5 },
    h("div.smf-row", list, inp,
      h("button.smf-btn.small.primary", { onclick: () => inp.value && linkFile(it, inp.value) }, "Use this file"),
      h("button.smf-btn.small.ghost", { onclick: () => { it.edit = null; render(); } }, "Cancel")),
    sugg));
}

function linkButtons(it) {
  if (it.job || it.kind === "vae") return null;
  const pick = (label, title) => h("button.smf-btn.small.ghost", { title, onclick: () => { it.edit = "file"; render(); } }, label);
  if (it.status === "present") {
    if (it.matched_by === "your link") return h("button.smf-btn.small.ghost", { title: "Forget this link", onclick: () => linkFile(it, null) }, "Unlink");
    if (it.matched_by === "similar name") return pick("Not this one?", "Matched by a similar file name: pick the right file");
    return null;
  }
  const use = pick("Use my file…", "You already have it under another name: pick the file (remembered for next time)");
  if (it.download?.confidence === "high") return use; // found exactly: no need for another link
  return [use, h("button.smf-btn.small.ghost", { title: "Paste the page or download link where this model is", onclick: () => { it.edit = "url"; render(); } }, "Paste link…")];
}

function itemRow(it) {
  const row = itemMainRow(it);
  return it.edit ? [row, editRow(it)] : row;
}

function itemMainRow(it) {
  const d = it.download;
  return h("tr" + (it.status === "present" ? ".off" : ""),
    h("td", h("span.smf-type", KIND[it.kind] || it.kind)),
    h("td",
      h("div", h("b", it.name || stem(it.file)), it.version ? h("span.smf-dim", " — " + it.version) : null),
      it.base_model ? h("div.smf-dim.small", it.base_model) : null,
      it.note ? h("div.smf-warnline.small", it.note) : null),
    h("td", it.kind === "lora" && it.weight != null ? h("b", Number(it.weight).toFixed(2)) : h("span.smf-dim", "—")),
    h("td", statusCell(it)),
    h("td.small", d && it.status === "missing"
      ? [h("div", { title: d.dest }, d.shared ? pill("shared folder", "ok", "Your shared models folder") : pill("this install only", "warn", "This ComfyUI's own models folder, not the shared one"), " ", `${d.folder}/${d.rel}`),
        d.size ? h("div.smf-dim", fmtSize(d.size), d.sha256 ? " · sha256 verified" : "") : null,
        it.kind === "checkpoint" ? h("div.smf-dim", "→ diffusion_models instead if it turns out to be UNet-only") : null]
      : null),
    h("td",
      it.page_url ? h("a.smf-link", { href: it.page_url, target: "_blank", rel: "noopener" }, "page ↗") : null, " ",
      d && it.status === "missing" && !it.job
        ? h("button.smf-btn.small", { onclick: () => downloadItem(it).then(render).catch((e) => toast("error", "Download failed", e.message)) }, "Download")
        : null, " ", linkButtons(it)));
}

function settingsLine(s) {
  if (!s) return null;
  const bits = [
    s.steps != null && `Steps ${s.steps}`, (s.sampler_raw || s.sampler) && `Sampler ${s.sampler_raw || s.sampler}${s.scheduler && !s.sampler_raw ? " / " + s.scheduler : ""}`,
    s.cfg != null && `CFG ${s.cfg}`, s.seed != null && `Seed ${s.seed}`, s.width && s.height && `Size ${s.width}×${s.height}`,
    s.clip_skip && `Clip skip ${s.clip_skip}`, s.denoise != null && s.denoise !== 1 && `Denoise ${s.denoise}`,
  ].filter(Boolean);
  return bits.length ? h("div.smf-dim.small", bits.join(" · ")) : null;
}

function promptBox(label, text) {
  if (!text) return null;
  return h("div.smf-field",
    h("label", label, " ", h("button.smf-btn.small.ghost", { onclick: () => copy(text, `${label} copied`) }, "Copy")),
    h("div.smf-promptbox", text));
}

function importBar(compact) {
  const input = h("input", { type: "file", accept: "image/*,video/mp4,video/webm,video/quicktime,.mkv", style: { display: "none" },
    onchange: (e) => e.target.files[0] && analyzeFile(e.target.files[0]) });
  const url = h("input.smf-input", { placeholder: "…or paste a link: CivitAI image or post (civitai.com / .red / .green), or any image file", value: r.url,
    style: { flex: 1 }, oninput: (e) => (r.url = e.target.value), onkeydown: (e) => e.key === "Enter" && analyzeUrl(r.url) });
  return h("div",
    h("div.smf-drop" + (compact ? ".compact" : ""), { onclick: () => input.click() }, input,
      h("div", h("b", "Drop an image here"), " or click to choose one"),
      h("div.smf-dim.small", "PNG / JPEG / WebP from ComfyUI, A1111 / Forge, Fooocus, InvokeAI, SwarmUI, NovelAI or CivitAI — and MP4 / WebM videos saved by ComfyUI.")),
    h("div.smf-row", { style: { marginTop: "8px" } }, url, h("button.smf-btn", { onclick: () => analyzeUrl(r.url) }, "Import link")));
}

function recipeCard(x) {
  return h("div.smf-card.smf-recipe-card", { onclick: () => openSaved(x.id), title: x.title },
    x.has_thumb ? h("img.smf-media", { src: apiUrl(`/recipes/${x.id}/thumb?v=${x.thumb_v || 0}`), loading: "lazy", alt: "" }) : h("div.smf-media.none", "RECIPE"),
    x.media === "video" ? h("span.smf-video-badge", { title: "Made from a video" }, "▶") : null,
    h("div.smf-card-top",
      x.base_model ? familyBadge(null, x.base_model) : null, h("span.smf-spacer"),
      h("button.smf-icon.smf-fav" + (x.fav ? ".on" : ""), {
        title: x.fav ? "Unfavourite" : "Favourite",
        onclick: async (e) => {
          e.stopPropagation();
          x.fav = !x.fav;
          render();
          await call(`/recipes/${x.id}`, { method: "PATCH", body: { fav: x.fav } }).catch((er) => toast("error", "Not saved", er.message));
        },
      }, x.fav ? "★" : "☆")),
    h("div.smf-card-bottom",
      h("div.smf-card-title", x.title),
      h("div", x.model ? h("span.smf-chip", { title: x.model }, stem(x.model)) : null, " ",
        x.lora_count ? h("span.smf-chip.dim", `${x.lora_count} LoRA${x.lora_count > 1 ? "s" : ""}`) : null)));
}

function libraryView() {
  const f = r.filter.toLowerCase();
  const list = (r.list || []).filter((x) => (!r.favOnly || x.fav) &&
    (!f || [x.title, x.model, x.base_model, ...(x.tags || [])].some((v) => (v || "").toLowerCase().includes(f))));
  const lm = ctx.status?.lm_installed;
  return [
    h("div.smf-help",
      "Drop an image to see every model it was made with and the LoRA strengths. ",
      h("b", "Save"), " keeps it in your recipe library (shared by every ComfyUI using this models folder); ",
      h("b", "Download"), " fetches the checkpoint and LoRAs you're missing, already sorted by base model; ",
      h("b", "Fill current workflow"), " puts the prompt, settings and LoRAs into the workflow you have open.",
      lm ? h("span", " LoRA Manager is installed: ", ctx.status.config?.recipes_mirror_lm ? "new recipes are saved there too (see Settings)." : "mirroring to it is off (see Settings).") : null),
    importBar(!!(r.list && r.list.length)),
    h("div.smf-toolbar", { style: { marginTop: "12px" } },
      h("input.smf-input", { placeholder: "Filter by title, model, base model or tag…", value: r.filter, style: { flex: 1 },
        oninput: (e) => { r.filter = e.target.value; renderGrid(); } }),
      h("label.smf-check", h("input", { type: "checkbox", checked: r.favOnly, onchange: (e) => { r.favOnly = e.target.checked; render(); } }), " ★ only"),
      h("span.smf-dim", r.list ? `${r.list.length} recipe${r.list.length === 1 ? "" : "s"}` : ""),
      lm ? h("a.smf-link", { href: `${ctx.api.api_base || ""}/loras/recipes`, target: "_blank", rel: "noopener" }, "LoRA Manager recipes ↗") : null),
    r.list === null ? h("div.smf-empty", spinner(), " Loading recipes…")
      : !r.list.length ? h("div.smf-empty", "No saved recipes yet — drop an image above to make your first.")
        : h("div.smf-grid.smf-recipe-grid", list.length ? list.map(recipeCard) : h("div.smf-sentinel.smf-dim", "Nothing matches.")),
    lm ? lmSection(f) : null,
  ];
}

function lmSection(f) {
  if (r.lmList === null) return h("div.smf-dim.small", { style: { marginTop: "12px" } }, spinner(), " Reading LoRA Manager's recipes…");
  const all = lmOnly();
  if (!all.length) return null;
  const shown = all.filter((x) => !f || [x.title, x.base_model, ...(x.tags || [])].some((v) => String(v || "").toLowerCase().includes(f)));
  return h("div.smf-lm-section",
    h("h3", `In LoRA Manager — ${all.length} recipe${all.length === 1 ? "" : "s"}`,
      h("span.smf-dim.small", " · read-only here; open one to download its models, fill a workflow or save a copy")),
    h("div.smf-grid.smf-lm-grid", shown.length ? shown.map(lmCard) : h("div.smf-sentinel.smf-dim", "Nothing matches.")));
}

function lmCard(x) {
  const n = (x.loras || []).filter((l) => !l.exclude).length;
  return h("div.smf-card.smf-recipe-card", { onclick: () => openLm(x), title: x.title },
    x.file_url ? h("img.smf-media", { src: `${ctx.api.api_base || ""}${x.file_url}`, loading: "lazy", alt: "" }) : h("div.smf-media.none", "RECIPE"),
    h("div.smf-card-top", x.base_model ? familyBadge(null, x.base_model) : null, h("span.smf-spacer"), h("span.smf-chip.dim", "LoRA Manager")),
    h("div.smf-card-bottom",
      h("div.smf-card-title", x.title || "Untitled"),
      h("div", n ? h("span.smf-chip.dim", `${n} LoRA${n > 1 ? "s" : ""}`) : null)));
}

// re-render only the grid while typing in the filter (keeps the input's focus)
function renderGrid() {
  const grid = r.root?.querySelector(".smf-recipe-grid");
  if (!grid) return render();
  const tmp = h("div", libraryView());
  const next = tmp.querySelector(".smf-recipe-grid");
  if (next) grid.replaceWith(next);
  const lmGrid = r.root.querySelector(".smf-lm-grid"), lmNext = tmp.querySelector(".smf-lm-grid");
  if (lmGrid && lmNext) lmGrid.replaceWith(lmNext);
}

function chooseView() {
  return [
    h("div.smf-help", "That post has several images. Pick the one whose recipe you want (images without generation data are dimmed)."),
    h("div.smf-grid.smf-choose", r.choices.map((c) =>
      h("div.smf-card.smf-recipe-card" + (c.has_meta ? "" : ".off"), { onclick: () => analyzeUrl(c.url), title: c.has_meta ? c.url : "No generation data on CivitAI" },
        c.thumb ? h("img.smf-media", { src: c.thumb, loading: "lazy", alt: "", referrerPolicy: "no-referrer" }) : h("div.smf-media.none", "IMG"),
        c.has_meta ? null : h("div.smf-card-bottom", h("span.smf-chip.dim", "no recipe"))))),
    h("div.smf-toolbar", h("button.smf-btn.small", { onclick: () => { closeDetail(); render(); } }, "← Back to recipes")),
  ];
}

function detailView() {
  const d = r.d, rec = d.recipe, items = d.items;
  const need = missing(false).length;
  const needLow = missing(true).length - need;
  const res = resolved(rec, items);
  const src = rec.source || {};
  const saved = !!d.savedId;
  const field = (label, el) => h("div.smf-field", h("label", label), el);
  return [
    h("div.smf-recipe",
      d.preview && d.video ? h("video.smf-recipe-img", { src: d.preview, muted: true, loop: true, autoplay: true, playsInline: true })
        : d.preview ? h("img.smf-recipe-img", { src: d.preview, alt: "", onerror: (e) => e.target.remove() }) : null,
      h("div.smf-recipe-side",
        field("Recipe name", h("input.smf-input", { value: rec.title || "", oninput: (e) => (rec.title = e.target.value),
          onchange: () => patch({ title: rec.title }) })),
        field("Tags (comma separated)", h("input.smf-input", { value: d.tags, oninput: (e) => (d.tags = e.target.value),
          onchange: () => patch({ tags: tagList(d.tags) }) })),
        h("div.smf-row",
          rec.base_model ? h("span", "Base model: ", familyBadge(null, rec.base_model)) : null,
          rec.format ? pill(rec.format, "src", "Where the generation data came from") : null,
          src.url ? h("a.smf-link", { href: src.url, target: "_blank", rel: "noopener noreferrer" }, "source ↗") : null,
          saved && (rec.image || src.output) ? h("a.smf-link", { href: apiUrl(`/recipes/${d.savedId}/image`), target: "_blank", rel: "noopener",
            title: rec.image ? "The full-size copy kept with this recipe" : "The image in ComfyUI's output folder (while it's still there)" }, "full image ↗") : null),
        d.fromOutput && !saved ? h("label.smf-check", { title: "Otherwise the recipe keeps a 512 px picture and links to the image in ComfyUI's output folder" },
          h("input", { type: "checkbox", checked: !!d.keepImage, onchange: (e) => (d.keepImage = e.target.checked) }), " Keep a full-size copy of the image with the recipe") : null,
        promptBox("Prompt", rec.prompt?.positive),
        promptBox("Negative prompt", rec.prompt?.negative),
        settingsLine(rec.settings),
        h("div.smf-actions",
          saved
            ? h("span", pill("Saved", "ok"), d.lmSaved ? [" ", pill("also in LoRA Manager", "ok")] : null)
            : h("button.smf-btn.primary", { onclick: () => run({ doSave: true, doDownload: true }) },
              need ? `Save recipe & download ${need} missing` : "Save recipe"),
          !saved && need ? h("button.smf-btn", { onclick: () => run({ doSave: true, doDownload: false }) }, "Save only") : null,
          need ? h("button.smf-btn", { onclick: () => run({ doSave: false, doDownload: true }) }, saved ? `Download ${need} missing` : `Download ${need} missing only`) : null),
        needLow ? h("div.smf-dim.small", `${needLow} more found only by searching the file name — check them and use their Download button.`) : null,
        h("div.smf-actions",
          h("button.smf-btn", { title: "Put the prompt, settings, model and LoRAs into the workflow that's open (adds LoRA loaders if it needs more)", onclick: fillCurrent }, "Fill current workflow"),
          h("button.smf-btn", { title: rec.comfy?.workflow || rec.comfy?.prompt ? "Opens the ComfyUI workflow saved in the image" : "Builds a simple text-to-image workflow", onclick: openAsNew }, "Open as new workflow"),
          res.loras.length ? h("button.smf-btn.small", { title: "<lora:…> text for LoRA Manager's loader or A1111-style prompts", onclick: () => copy(loraSyntax(res.loras), "LoRA syntax copied") }, "Copy LoRA syntax") : null,
          res.loras.length ? h("button.smf-btn.small" + (d.compare ? ".primary" : ""), {
            title: "A new workflow with this recipe's workflow copied once per strength of one LoRA: same prompt and seed, side by side",
            onclick: () => { d.compare = d.compare ? null : { lora: (res.loras.find((l) => l.installed) || res.loras[0]).name, text: "0, 0.4, 0.7, 1" }; render(); },
          }, "Compare LoRA strengths…") : null,
          saved && src.url ? h("button.smf-btn.small.ghost", { title: "Fetch this recipe's picture again from its source link", onclick: refreshPicture }, "Refresh picture") : null,
          saved ? h("button.smf-btn.small.ghost", { onclick: remove }, "Delete") : null),
        compareRow(res))),
    items.length
      ? h("table.smf-table",
        h("tr", h("th", ""), h("th", "Model"), h("th", "Strength"), h("th", "Status"), h("th", "Saves to"), h("th", "")),
        items.map(itemRow))
      : h("div.smf-empty", "This recipe doesn't name any models."),
    h("div.smf-toolbar", { style: { marginTop: "10px" } },
      h("button.smf-btn.small", { onclick: () => { closeDetail(); render(); } }, "← Back to recipes")),
  ];
}

export function render() {
  const root = r.root;
  if (!root || !root.isConnected) return;
  if (r.busy) return clear(root, h("div.smf-empty", spinner(), " ", r.busy));
  const err = r.error ? h("div.smf-empty.err", r.error, " ", h("button.smf-btn.small", { onclick: () => { r.error = null; render(); } }, "OK")) : null;
  if (r.view === "detail" && r.d) return clear(root, err, ...detailView());
  if (r.view === "choose" && r.choices) return clear(root, err, ...chooseView());
  clear(root, err, ...libraryView());
}
