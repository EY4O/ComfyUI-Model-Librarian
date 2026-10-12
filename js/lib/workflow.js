// "Workflow" tab: scan the open graph, resolve + download missing models,
// repoint moved files and swap oversized UNets for GGUF quants.
import { call, ctx, h, clear, fmtSize, toast, pill, spinner, copy } from "./util.js";
import { startDownload, onJobsChange } from "./downloads.js";

const MODEL_RE = /\.(safetensors|ckpt|pt|pt2|pth|bin|gguf|sft|onnx)$/i;
// LoRA Manager nodes name LoRAs without an extension: a `loras` list widget
// ({name, strength, active}) or <lora:name:strength> text.
const LM_NODE_RE = /\(LoraManager\)$/;
// pool/randomizer/cycler pick LoRAs at run time, so their lists aren't fixed references
const LM_SKIP = new Set(["Lora Pool (LoraManager)", "Lora Randomizer (LoraManager)", "Lora Cycler (LoraManager)"]);
const LM_SYNTAX_RE = /<lora:([^:>]+):[^:>]+(?::[^:>]+)?>/gi;
const LM_EXT_RE = /\.(safetensors|ckpt|pt|bin)$/i;
const refMap = new Map(); // key -> {node, widget, path, graph}
export const topLevelModels = new Map(); // basename(lower) -> declared model entry
const pending = new Map(); // jobId -> {kind: "repoint"|"swap", keys, value}

const FOLDERS = [
  "checkpoints", "loras", "diffusion_models", "text_encoders", "vae", "clip_vision", "controlnet",
  "upscale_models", "embeddings", "style_models", "ipadapter", "model_patches", "audio_encoders",
  "latent_upscale_models", "hypernetworks", "gligen", "sams", "ultralytics", "vae_approx",
];

// scope "open": the workflow on the canvas; "saved": every saved workflow on disk
const state = { items: [], cands: {}, open: {}, busy: false, root: null, swaps: {}, choice: {}, scope: "open", workflows: [], wfFilter: null, showWfs: true };
const saved = () => state.scope === "saved";
const itemKey = (it) => `${it.folder}|${it.value.toLowerCase()}`;

// ---------------------------------------------------------------- graph walk
function graphs(root) {
  const out = [root];
  const subs = root?.subgraphs ?? root?._subgraphs;
  if (subs?.values) for (const g of subs.values()) out.push(g);
  return out;
}

function visit(v, path, fn, depth = 0) {
  if (typeof v === "string") return fn(v, path);
  if (v && typeof v === "object" && depth < 3) {
    for (const [k, x] of Object.entries(v)) visit(x, [...path, k], fn, depth + 1);
  }
}

// -> LoRA names referenced by a LoRA Manager widget, or null if it isn't one
export function lmLoraNames(nodeType, widget, hasLorasWidget) {
  if (!LM_NODE_RE.test(nodeType || "") || LM_SKIP.has(nodeType)) return null;
  if (widget.name === "loras") {
    const v = Array.isArray(widget.value) ? widget.value : widget.value?.__value__;
    // LoRA Manager only loads (and validates) active entries
    return Array.isArray(v) ? v.filter((l) => l?.active && l.name).map((l) => String(l.name)) : [];
  }
  // nodes with a `loras` list keep a synced copy in their text widget; read the list only
  if (hasLorasWidget || typeof widget.value !== "string") return null;
  const names = [...widget.value.matchAll(LM_SYNTAX_RE)].map((m) => m[1].trim()).filter(Boolean);
  return names.length ? names : null; // otherwise scan it normally (e.g. ckpt_name)
}

export function collectRefs() {
  refMap.clear();
  const refs = [];
  const root = ctx.app.rootGraph ?? ctx.app.graph;
  if (!root) return refs;
  for (const g of graphs(root)) {
    const gid = g.id ?? "root";
    for (const node of g._nodes ?? g.nodes ?? []) {
      const emb = new Map();
      for (const m of node.properties?.models ?? []) {
        if (m?.name) emb.set(m.name.toLowerCase(), m);
      }
      const nodeType = node.type ?? node.comfyClass;
      const hasLoras = (node.widgets ?? []).some((w) => w.name === "loras");
      for (const w of node.widgets ?? []) {
        const lm = lmLoraNames(nodeType, w, hasLoras);
        if (lm) {
          lm.forEach((name, i) => {
            const key = `${gid}:${node.id}:${w.name}:lm${i}`;
            refMap.set(key, { node, widget: w, path: [], graph: g, lm: true });
            const base = name.split(/[\\/]/).pop().replace(LM_EXT_RE, "").toLowerCase();
            const e = topLevelModels.get(base + ".safetensors") ?? null;
            refs.push({
              key, node_type: nodeType, widget: w.name, value: name, lm: true,
              embedded: e ? { url: e.url, directory: e.directory, hash: e.hash, hash_type: e.hash_type } : null,
            });
          });
          continue;
        }
        visit(w.value, [], (val, path) => {
          if (!MODEL_RE.test(val)) return;
          const key = `${gid}:${node.id}:${w.name}:${path.join(".")}`;
          refMap.set(key, { node, widget: w, path, graph: g });
          const base = val.split(/[\\/]/).pop().toLowerCase();
          const e = emb.get(val.toLowerCase()) ?? emb.get(base) ?? topLevelModels.get(base) ?? null;
          refs.push({
            key,
            node_type: node.type ?? node.comfyClass,
            widget: path.length ? `${w.name}.${path[path.length - 1]}` : w.name,
            value: val,
            embedded: e ? { url: e.url, directory: e.directory, hash: e.hash, hash_type: e.hash_type } : null,
          });
        });
      }
    }
  }
  return refs;
}

function setRefValue(key, value) {
  const r = refMap.get(key);
  if (!r || r.lm) return false; // never overwrite a LoRA Manager `loras` list
  const { node, widget, path } = r;
  if (!path.length) {
    widget.value = value;
    try { widget.callback?.(value, ctx.app.canvas, node); } catch {}
  } else {
    let o = widget.value;
    for (const p of path.slice(0, -1)) o = o[p];
    o[path[path.length - 1]] = value;
  }
  node.setDirtyCanvas?.(true, true);
  return true;
}

function swapToGGUF(key, ggufName) {
  const r = refMap.get(key);
  if (!r) return false;
  const old = r.node;
  const g = old.graph ?? r.graph;
  const LG = window.LiteGraph ?? globalThis.LiteGraph;
  if (!LG?.createNode) throw new Error("LiteGraph not available");
  const nn = LG.createNode("UnetLoaderGGUF");
  if (!nn) throw new Error("UnetLoaderGGUF node not found — install ComfyUI-GGUF");
  g.beforeChange?.();
  nn.pos = [old.pos[0], old.pos[1]];
  g.add(nn);
  const w = nn.widgets?.find((x) => x.name === "unet_name");
  if (w) w.value = ggufName;
  const linkIds = [...(old.outputs?.[0]?.links ?? [])];
  for (const id of linkIds) {
    const l = g.links?.get ? g.links.get(id) : g.links?.[id];
    if (!l) continue;
    if (l.target_id === -20 && g.outputNode) {
      // link to a subgraph output slot
      g.outputNode.slots?.[l.target_slot]?.connect?.(nn.outputs[0], nn);
      continue;
    }
    const tgt = g.getNodeById(l.target_id);
    if (tgt) nn.connect(0, tgt, l.target_slot);
  }
  g.remove(old);
  g.afterChange?.();
  ctx.app.canvas?.setDirty?.(true, true);
  return true;
}

// ---------------------------------------------------------------- jobs hook
onJobsChange((jobs, finished) => {
  let changed = false;
  for (const j of finished) {
    const p = pending.get(j.id);
    if (!p) continue;
    pending.delete(j.id);
    if (j.status !== "done") continue;
    if (p.kind === "repoint") p.keys.forEach((k) => setRefValue(k, p.value));
    if (p.kind === "swap") {
      let n = 0;
      for (const k of p.keys) {
        try {
          if (refMap.get(k)?.node?.type === "UNETLoader" && swapToGGUF(k, p.value)) n++;
        } catch (e) {
          toast("warn", "Swap not applied", String(e.message || e), 8000);
        }
      }
      if (n) toast("success", "Swapped to GGUF", `${n} loader node(s) now use ${p.value}`, 5000);
    }
    changed = true;
  }
  if (finished.some((j) => j.status === "done") || changed) {
    setTimeout(() => state.root && scan(), 800);
  }
});

// ---------------------------------------------------------------- actions
export async function scan() {
  if (saved()) {
    const res = await call("/workflows/health");
    state.items = res.items;
    state.workflows = res.workflows;
    state.smMode = res.sm_mode;
    if (state.wfFilter && !res.workflows.some((w) => w.file === state.wfFilter)) state.wfFilter = null;
    render();
    return res.items;
  }
  const refs = collectRefs();
  const res = await call("/scan", { method: "POST", body: { refs } });
  state.items = res.items;
  state.budget = res.budget;
  state.smMode = res.sm_mode;
  render();
  return res.items;
}

function setScope(scope) {
  if (state.scope === scope) return;
  Object.assign(state, { scope, items: [], cands: {}, open: {}, swaps: {}, choice: {}, wfFilter: null });
  clear(state.root, h("div.smf-empty", spinner(), scope === "saved" ? " Checking every saved workflow…" : " Scanning workflow…"));
  scan().catch((e) => clear(state.root, h("div.smf-empty.err", "Scan failed: " + e.message)));
}

// Opens a saved workflow in ComfyUI (as itself, so saving writes back to the same file).
async function openSaved(w) {
  try {
    const res = await ctx.api.fetchApi(`/userdata/${encodeURIComponent(w.path)}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const wfObj = ctx.app.extensionManager?.workflow?.getWorkflowByPath?.(w.path);
    await ctx.app.loadGraphData(data, true, true, wfObj || w.path.split("/").pop());
    document.querySelector(".smf-close")?.click();
  } catch (e) {
    toast("error", "Couldn't open the workflow", e.message);
  }
}

// Saved workflows are fixed on disk: a moved model is repointed when exactly one
// file with its name exists (each changed file is backed up first).
async function fixSaved() {
  try {
    const r = await call("/workflows/scan", { method: "POST", body: { apply: true } });
    toast(r.fixes ? "success" : "info", "Saved workflows", r.fixes
      ? `${r.fixes} reference(s) repointed in ${r.fixed_files} workflow(s). Backups: ${r.backup_dir}`
      : "Nothing could be repointed automatically (names that match several files are left alone).", 8000);
  } catch (e) {
    toast("error", "Fix failed", e.message);
  }
  scan();
}

async function resolve(it) {
  const k = itemKey(it);
  state.cands[k] = "loading";
  state.open[k] = true;
  render();
  try {
    const { candidates } = await call("/resolve", {
      method: "POST",
      body: { value: it.search_name || it.value, folder: it.folder, embedded: it.embedded },
    });
    state.cands[k] = candidates;
    state.choice[k] = candidates.length ? 0 : -1;
  } catch (e) {
    state.cands[k] = { error: e.message };
  }
  render();
}

// Path in ComfyUI's own format (Windows lists use backslashes) so repointed widgets validate
function relFor(it, cand) {
  if (saved() && !it.lm) return it.value; // saved workflows name this file; keep its name so they work unchanged
  if (it.lm) {
    // LoRA Manager resolves by name, so save under exactly the name the node asks for
    const ext = (cand.filename || "").match(LM_EXT_RE)?.[0] || ".safetensors";
    return it.value.replace(/\\/g, "/") + ext;
  }
  const sep = ctx.status?.sep || "/";
  const parts = it.value.split(/[\\/]/);
  const want = parts.pop();
  const name = cand.filename && cand.filename.toLowerCase() !== want.toLowerCase() ? cand.filename : want;
  return [...parts, name].join(sep);
}

async function download(it, cand) {
  const folder = it.folder || cand.folder;
  if (!folder) {
    toast("warn", "Pick a folder", "Choose which model folder this file belongs in first.");
    return;
  }
  const rel = relFor(it, cand);
  try {
    const job = await startDownload({
      url: cand.url, folder, rel, sha256: cand.sha256, size: cand.size, source: cand.source,
      page_url: cand.page_url, title: cand.title, meta: cand.meta,
    });
    if (!saved() && !it.lm && rel !== it.value) pending.set(job.id, { kind: "repoint", keys: it.refs, value: rel });
    toast("info", "Download queued", rel, 2500);
  } catch (e) {
    toast("error", "Download failed", e.message, 8000);
  }
}

async function manualUrl(it, url) {
  url = (url || "").trim();
  if (!/^https:\/\//.test(url)) return toast("warn", "Invalid URL", "Paste an https:// download link.");
  let cand;
  try {
    // CivitAI model pages / HuggingFace file pages -> the real file, with SHA256 + metadata
    ({ candidate: cand } = await call("/resolve-url", { method: "POST", body: { url } }));
  } catch (e) {
    return toast("error", "Can't use that link", e.message, 8000);
  }
  if (cand.source === "manual") cand.filename = (it.search_name || it.value).split(/[\\/]/).pop();
  await download(it, cand);
}

async function findAll() {
  const missing = visibleItems().filter((i) => i.status === "missing" && !Array.isArray(state.cands[itemKey(i)]));
  let idx = 0;
  const worker = async () => {
    while (idx < missing.length) await resolve(missing[idx++]);
  };
  await Promise.all([worker(), worker(), worker()]);
}

async function downloadAllHigh() {
  let n = 0;
  for (const it of visibleItems().filter((i) => i.status === "missing")) {
    const c = state.cands[itemKey(it)];
    if (!Array.isArray(c)) continue;
    const best = c[state.choice[itemKey(it)] ?? 0];
    if (best && best.confidence === "high" && (it.folder || best.folder)) {
      await download(it, best);
      n++;
    }
  }
  if (!n) toast("info", "Nothing to download", "Find sources first; only high-confidence matches are auto-downloaded.");
}

function fixMoved() {
  let n = 0;
  for (const it of state.items.filter((i) => i.status === "elsewhere")) {
    it.refs.forEach((k) => setRefValue(k, it.found_as) && n++);
  }
  toast("success", "Paths fixed", `${n} widget(s) repointed`, 3000);
  scan();
}

// Write each model's source into its loader node (properties.models — what
// ComfyUI's own missing-models dialog reads), so shared workflows can fetch the
// exact files even without this extension.
async function embedSources() {
  const items = state.items.filter((i) => i.status === "present" && !i.lm && i.folder);
  if (!items.length) return toast("info", "Nothing to embed", "No installed models with a known folder in this workflow.");
  let sources;
  try {
    ({ sources } = await call("/workflows/sources", { method: "POST", body: { items: items.map((i) => ({ value: i.value, folder: i.folder })) } }));
  } catch (e) {
    return toast("error", "Embed failed", e.message);
  }
  const byValue = new Map(sources.filter((s) => s.url).map((s) => [s.value, s]));
  let nodes = 0;
  const done = new Set();
  for (const it of items) {
    const s = byValue.get(it.value);
    if (!s) continue;
    for (const key of it.refs) {
      const node = refMap.get(key)?.node;
      if (!node) continue;
      node.properties ??= {};
      const entry = { name: it.value, url: s.url, directory: s.directory, ...(s.hash ? { hash: s.hash, hash_type: "sha256" } : {}) };
      const list = (node.properties.models || []).filter((m) => m?.name !== it.value);
      node.properties.models = [...list, entry];
      nodes++;
      done.add(it.value);
    }
  }
  if (nodes) {
    ctx.app.graph?.change?.();
    ctx.app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.();
    ctx.app.canvas?.setDirty?.(true, true);
  }
  const unknown = items.length - done.size;
  toast(done.size ? "success" : "info", "Model sources embedded",
    `${done.size} model(s) in ${nodes} node(s)` + (unknown ? ` · ${unknown} without a known source (Library → Fetch metadata finds CivitAI ones)` : "") +
    (done.size ? " · save the workflow to keep them" : ""), 8000);
}

async function findSwap(it) {
  const k = itemKey(it);
  state.swaps[k] = "loading";
  render();
  try {
    state.swaps[k] = await call("/vram", {
      method: "POST",
      body: { value: it.found_as || it.value, size: it.size, node_type: it.node_types[0], node_types: it.node_types },
    });
  } catch (e) {
    state.swaps[k] = { error: e.message };
  }
  render();
}

async function downloadSwap(it, opt) {
  // fp8 loads in the same node: download next to the original and repoint.
  // GGUF UNets swap to Unet Loader (GGUF); GGUF text encoders are download-only.
  const folder = opt.kind === "fp8" ? (it.found_folder || it.folder || "diffusion_models")
    : it.big_kind === "text_encoder" ? "text_encoders" : "diffusion_models";
  try {
    const job = await startDownload({
      url: opt.url, folder, rel: opt.filename, sha256: opt.sha256, size: opt.size,
      source: "huggingface", page_url: opt.page_url, title: `${opt.repo}/${opt.path}`,
    });
    if (opt.action === "repoint") {
      const sep = ctx.status?.sep || "/";
      pending.set(job.id, { kind: "repoint", keys: it.refs.filter((k) => !refMap.get(k)?.lm), value: opt.filename.split("/").join(sep) });
    } else if (opt.action === "swap") {
      const swappable = it.refs.filter((k) => refMap.get(k)?.node?.type === "UNETLoader");
      if (swappable.length) pending.set(job.id, { kind: "swap", keys: swappable, value: opt.filename });
    }
    toast("info", `${opt.quant} download queued`, `${opt.filename} (${fmtSize(opt.size)})` +
      (opt.action === "download" ? " — load it with CLIPLoader (GGUF)" : ""), 4000);
  } catch (e) {
    toast("error", "Download failed", e.message, 8000);
  }
}

// ---------------------------------------------------------------- render
export function mount(root) {
  state.root = root;
  clear(root, h("div.smf-empty", spinner(), saved() ? " Checking every saved workflow…" : " Scanning workflow…"));
  scan().catch((e) => clear(root, h("div.smf-empty.err", "Scan failed: " + e.message)));
}

function statusPill(it) {
  if (it.status === "missing") return pill("Missing", "bad");
  if (it.status === "elsewhere") return pill("Moved", "warn", `Found as ${it.found_as}`);
  if (it.status === "invalid") return pill("Invalid", "bad", it.error);
  return pill("OK", "ok");
}

function candRow(it, c, i) {
  const k = itemKey(it);
  const selected = (state.choice[k] ?? 0) === i;
  return h("label.smf-cand" + (selected ? ".sel" : ""),
    h("input", { type: "radio", name: "c-" + k, checked: selected, onchange: () => { state.choice[k] = i; render(); } }),
    h("div.smf-cand-main",
      h("div",
        pill(c.source, "src"), " ", pill(c.confidence, c.confidence === "high" ? "ok" : c.confidence === "medium" ? "warn" : "bad"), " ",
        h("b", c.filename || "?"), " ",
        c.size ? h("span.smf-dim", fmtSize(c.size)) : null,
        c.local ? pill("already downloaded", "ok", "You have this file as " + c.local) : null,
        c.gated ? pill("gated", "warn", "Needs a HuggingFace token + accepted license") : null,
        c.sha256 ? pill("sha256", "dim", "Download will be verified") : null),
      c.title ? h("div.smf-dim.small", c.title) : null),
    c.page_url ? h("a.smf-link", { href: c.page_url, target: "_blank", rel: "noopener" }, "page ↗") : null
  );
}

function itemRow(it) {
  const k = itemKey(it);
  const cands = state.cands[k];
  const open = state.open[k];
  const dest = it.dest ? h("span.smf-dim.small", { title: it.dest },
    it.shared ? pill("SM shared", "ok", "Stability Matrix shared folder") : pill("ComfyUI only", "warn", "Not a Stability Matrix shared folder"),
    " ", it.dest) : null;

  const folderSel = h("select.smf-select", {
    onchange: (e) => { it.folder = e.target.value || null; state.cands[k] = undefined; render(); },
    title: `Detected by: ${it.how}`,
  }, h("option", { value: "" }, "— choose folder —"),
  FOLDERS.concat(it.folder && !FOLDERS.includes(it.folder) ? [it.folder] : []).map((f) => h("option", { value: f, selected: f === it.folder }, f)));

  const actions = [];
  if (it.status === "missing") {
    actions.push(h("button.smf-btn", { onclick: () => resolve(it), disabled: cands === "loading" }, Array.isArray(cands) ? "Search again" : "Find source"));
    if (Array.isArray(cands) && cands.length) {
      const c = cands[state.choice[k] ?? 0];
      // LoRA Manager refs live inside its `loras` list widget, so they can't be repointed
      if (c?.local && !it.lm && saved()) {
        actions.push(h("span.smf-dim.small", { title: c.local }, "You have it as ", h("b", c.local.split(/[\\/]/).pop()), " — open the workflow to use it"));
      } else if (c?.local && !it.lm) {
        actions.push(h("button.smf-btn.primary", {
          title: "Point this workflow at the copy you already have: " + c.local,
          onclick: () => { it.refs.forEach((r) => setRefValue(r, c.local)); toast("success", "Using local file", c.local, 3000); scan(); },
        }, "Use local file"));
      } else if (c) actions.push(h("button.smf-btn.primary", { onclick: () => download(it, c) }, "Download"));
    }
  }
  if (it.status === "elsewhere") {
    actions.push(saved()
      ? h("button.smf-btn", { onclick: fixSaved, title: "Repoint every saved workflow that uses it (backed up first)" }, "Repoint")
      : h("button.smf-btn", { onclick: () => { it.refs.forEach((r) => setRefValue(r, it.found_as)); scan(); } }, "Repoint"));
  }
  if (it.too_big && !saved()) {
    actions.push(h("button.smf-btn.warn", { onclick: () => findSwap(it) }, "Find smaller version"));
  }

  let body = null;
  if (open && it.status === "missing") {
    let list;
    if (cands === "loading") list = h("div.smf-dim", spinner(), " Searching registry, ComfyUI-Manager list, HuggingFace and CivitAI…");
    else if (cands?.error) list = h("div.err", cands.error);
    else if (Array.isArray(cands) && !cands.length) list = h("div.smf-dim", "No source found automatically. Paste a direct link below (CivitAI / HuggingFace).");
    else if (Array.isArray(cands)) list = cands.map((c, i) => candRow(it, c, i));
    const urlIn = h("input.smf-input", { placeholder: "…or paste a download URL (https://)", style: { flex: 1 } });
    body = h("div.smf-item-body", list,
      h("div.smf-row", urlIn, h("button.smf-btn", { onclick: () => manualUrl(it, urlIn.value) }, "Download URL")));
  }
  const sw = state.swaps[k];
  let swapBody = null;
  if (it.too_big && !saved()) {
    const gb = (b) => (b / 1024 ** 3).toFixed(1) + " GB";
    const head = h("div.smf-warnline", it.big_kind === "text_encoder"
      ? `⚠ ${gb(it.size)} text encoder — over half your ${gb(state.budget)} VRAM budget; an fp8 or GGUF version frees a lot of VRAM/RAM.`
      : `⚠ ${gb(it.size)} model > ${gb(state.budget)} VRAM budget — it will spill into system RAM (slow).`);
    let inner = null;
    if (sw === "loading") inner = h("div.smf-dim", spinner(), " Looking for fp8 and GGUF versions…");
    else if (sw?.error) inner = h("div.err", sw.error);
    else if (sw?.options) {
      if (!sw.options.length) inner = h("div.smf-dim", "No fp8 or GGUF version found on HuggingFace for this model.");
      else {
        const label = (o) => o.action === "repoint" ? "Download & use"
          : o.action === "swap" && it.node_types.includes("UNETLoader") && ctx.status?.gguf_installed ? "Download & swap" : "Download";
        inner = h("div",
          sw.note ? h("div.smf-dim.small", sw.note) : null,
          !ctx.status?.gguf_installed && sw.options.some((o) => o.kind === "gguf")
            ? h("div.smf-warnline", "ComfyUI-GGUF isn't installed — install it via ComfyUI-Manager to load .gguf files (fp8 works without it).") : null,
          h("table.smf-table",
            h("tr", h("th", "Quant"), h("th", "File"), h("th", "Size"), h("th", "")),
            sw.options.slice(0, 12).map((o) => h("tr" + (o.recommended ? ".rec" : ""),
              h("td", pill(o.quant, o.fits ? "ok" : "bad"), o.recommended ? pill("best fit", "ok") : null),
              h("td.small", o.filename, h("div.smf-dim", o.repo)),
              h("td", fmtSize(o.size)),
              h("td", h("button.smf-btn.small" + (o.recommended ? ".primary" : ""), { onclick: () => downloadSwap(it, o) },
                label(o)))))));
      }
    }
    swapBody = h("div.smf-item-body", head, inner);
  }

  return h("div.smf-item." + it.status,
    h("div.smf-item-head",
      statusPill(it),
      h("div.smf-item-title",
        h("b", { title: it.value, onclick: () => copy(it.value, "Filename copied"), style: { cursor: "copy" } }, it.value),
        it.lm ? h("span", " ", pill("LoRA Manager", "src", "Referenced by name from a LoRA Manager node")) : null,
        h("div.smf-dim.small",
          `${it.refs.length} ref${it.refs.length > 1 ? "s" : ""} · ${it.node_types.join(", ")}`,
          it.size ? ` · ${fmtSize(it.size)}` : "",
          it.status === "elsewhere" ? ` · found as ${it.found_as}` : ""),
        saved() && it.workflows ? usedIn(it) : null,
        it.hint ? h("div.smf-warnline.small", it.hint) : null),
      it.status === "missing" && !it.lm ? folderSel : h("span.smf-dim.small", it.found_folder || it.folder || ""),
      h("div.smf-actions", actions)),
    it.status === "missing" ? h("div.smf-item-sub", dest) : null,
    body, swapBody);
}

const wfName = (file) => file.split("/").pop().replace(/\.json$/i, "");
const wfByFile = (file) => state.workflows.find((w) => w.file === file);

function usedIn(it) {
  const list = it.workflows;
  const shown = list.slice(0, 4);
  return h("div.smf-dim.small", "Used in ",
    shown.map((f, i) => [i ? ", " : "", h("a.smf-link", { href: "#", title: f, onclick: (e) => { e.preventDefault(); state.wfFilter = f; render(); } }, wfName(f))]),
    list.length > shown.length ? ` and ${list.length - shown.length} more` : "");
}

function visibleItems() {
  return saved() && state.wfFilter ? state.items.filter((i) => i.workflows?.includes(state.wfFilter)) : state.items;
}

function workflowList() {
  const bad = state.workflows.filter((w) => w.missing || w.moved || w.error);
  const head = h("div.smf-row",
    h("b", `${state.workflows.length} saved workflow${state.workflows.length === 1 ? "" : "s"}`), " ",
    bad.length ? pill(`${bad.length} need attention`, "warn") : pill("all have their models", "ok"),
    h("span.smf-spacer"),
    state.workflows.length ? h("button.smf-btn.small.ghost", { onclick: () => { state.showWfs = !state.showWfs; render(); } }, state.showWfs ? "Hide list" : "Show list") : null);
  if (!state.showWfs) return h("div.smf-wflist", head);
  const row = (w) => h("div.smf-wfrow" + (state.wfFilter === w.file ? ".sel" : ""),
    h("a.smf-link", { href: "#", title: w.file, onclick: (e) => { e.preventDefault(); state.wfFilter = state.wfFilter === w.file ? null : w.file; render(); } }, wfName(w.file)),
    h("span.smf-dim.small", w.path.replace(/^workflows\//, "").replace(/[^/]+$/, "")),
    h("span.smf-spacer"),
    w.error ? pill("unreadable", "bad", w.error)
      : [w.missing ? pill(`${w.missing} missing`, "bad") : null, " ", w.moved ? pill(`${w.moved} moved`, "warn") : null,
        !w.missing && !w.moved ? pill(w.models ? `${w.models} models OK` : "no models", "ok") : null],
    w.user === "default" && !w.error ? h("button.smf-btn.small.ghost", { onclick: () => openSaved(w), title: "Open it in ComfyUI" }, "Open") : null);
  return h("div.smf-wflist", head, h("div.smf-wfrows", (bad.length ? bad : state.workflows).slice(0, 200).map(row)),
    bad.length && bad.length < state.workflows.length ? h("div.smf-dim.small", `${state.workflows.length - bad.length} more workflow(s) have everything they need.`) : null);
}

export function render() {
  const root = state.root;
  if (!root) return;
  const items = visibleItems();
  const missing = items.filter((i) => i.status === "missing");
  const moved = items.filter((i) => i.status === "elsewhere");
  const big = saved() ? [] : items.filter((i) => i.too_big);
  const scopeBar = h("div.smf-row.smf-scope",
    h("button.smf-tab" + (saved() ? "" : ".sel"), { onclick: () => setScope("open") }, "This workflow"),
    h("button.smf-tab" + (saved() ? ".sel" : ""), { onclick: () => setScope("saved"), title: "Check every saved workflow and subgraph blueprint for missing models" }, "All saved workflows"));
  const filterNote = saved() && state.wfFilter
    ? h("div.smf-row", "Showing models used by ", h("b", wfName(state.wfFilter)), " ",
      h("button.smf-btn.small.ghost", { onclick: () => { state.wfFilter = null; render(); } }, "Show all"),
      wfByFile(state.wfFilter)?.user === "default" ? h("button.smf-btn.small", { onclick: () => openSaved(wfByFile(state.wfFilter)) }, "Open it") : null)
    : null;
  const toolbar = h("div.smf-toolbar",
    h("div.smf-summary",
      pill(`${items.length} models`, "dim"), " ",
      missing.length ? pill(`${missing.length} missing`, "bad") : pill("nothing missing", "ok"), " ",
      moved.length ? pill(`${moved.length} moved`, "warn") : null, " ",
      big.length ? pill(`${big.length} too big for VRAM`, "warn") : null),
    h("div.smf-actions",
      h("button.smf-btn", { onclick: () => scan() }, saved() ? "Check again" : "Rescan"),
      missing.length ? h("button.smf-btn", { onclick: findAll }, "Find all sources") : null,
      missing.length ? h("button.smf-btn.primary", { onclick: downloadAllHigh }, "Download all (high confidence)") : null,
      moved.length ? h("button.smf-btn", { onclick: saved() ? fixSaved : fixMoved, title: saved() ? "Repoint saved workflows on disk (backed up first)" : "" }, "Fix moved paths") : null,
      !saved() && items.some((i) => i.status === "present" && !i.lm)
        ? h("button.smf-btn", { onclick: embedSources, title: "Store each model's download link + SHA256 in the workflow, so anyone you share it with can fetch the exact files" }, "Embed model sources")
        : null));
  const smNote = state.smMode === "none"
    ? h("div.smf-warnline", "Stability Matrix shared folders not detected — downloads go to ComfyUI's own models folder. (Is this ComfyUI launched from Stability Matrix?)")
    : null;
  // the saved view lists only what needs attention; installed models would be thousands of rows
  const shownItems = saved() ? items.filter((i) => i.status !== "present") : items;
  const list = shownItems.length
    ? shownItems.map(itemRow)
    : h("div.smf-empty", saved()
      ? (state.workflows.length ? "Every saved workflow has the models it needs." : "No saved workflows found in ComfyUI's user folder.")
      : "This workflow doesn't reference any model files.");
  clear(root, scopeBar, saved() ? workflowList() : null, filterNote, toolbar, smNote, h("div.smf-list", list));
}
