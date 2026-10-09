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

const state = { items: [], cands: {}, open: {}, busy: false, root: null, swaps: {}, choice: {} };
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
  const refs = collectRefs();
  const res = await call("/scan", { method: "POST", body: { refs } });
  state.items = res.items;
  state.budget = res.budget;
  state.smMode = res.sm_mode;
  render();
  return res.items;
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
    if (!it.lm && rel !== it.value) pending.set(job.id, { kind: "repoint", keys: it.refs, value: rel });
    toast("info", "Download queued", rel, 2500);
  } catch (e) {
    toast("error", "Download failed", e.message, 8000);
  }
}

async function manualUrl(it, url) {
  url = (url || "").trim();
  if (!/^https:\/\//.test(url)) return toast("warn", "Invalid URL", "Paste an https:// download link.");
  const cand = { url, source: "manual", filename: (it.search_name || it.value).split(/[\\/]/).pop() };
  await download(it, cand);
}

async function findAll() {
  const missing = state.items.filter((i) => i.status === "missing" && !Array.isArray(state.cands[itemKey(i)]));
  let idx = 0;
  const worker = async () => {
    while (idx < missing.length) await resolve(missing[idx++]);
  };
  await Promise.all([worker(), worker(), worker()]);
}

async function downloadAllHigh() {
  let n = 0;
  for (const it of state.items.filter((i) => i.status === "missing")) {
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
      body: { value: it.found_as || it.value, size: it.size, node_type: it.node_types[0] },
    });
  } catch (e) {
    state.swaps[k] = { error: e.message };
  }
  render();
}

async function downloadSwap(it, opt) {
  try {
    const job = await startDownload({
      url: opt.url, folder: "diffusion_models", rel: opt.filename, sha256: opt.sha256, size: opt.size,
      source: "huggingface", page_url: opt.page_url, title: `${opt.repo}/${opt.path}`,
    });
    const swappable = it.refs.filter((k) => refMap.get(k)?.node?.type === "UNETLoader");
    if (swappable.length) pending.set(job.id, { kind: "swap", keys: swappable, value: opt.filename });
    toast("info", "GGUF download queued", `${opt.filename} (${fmtSize(opt.size)})`, 3000);
  } catch (e) {
    toast("error", "Download failed", e.message, 8000);
  }
}

// ---------------------------------------------------------------- render
export function mount(root) {
  state.root = root;
  clear(root, h("div.smf-empty", spinner(), " Scanning workflow…"));
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
      if (c?.local && !it.lm) {
        actions.push(h("button.smf-btn.primary", {
          title: "Point this workflow at the copy you already have: " + c.local,
          onclick: () => { it.refs.forEach((r) => setRefValue(r, c.local)); toast("success", "Using local file", c.local, 3000); scan(); },
        }, "Use local file"));
      } else if (c) actions.push(h("button.smf-btn.primary", { onclick: () => download(it, c) }, "Download"));
    }
  }
  if (it.status === "elsewhere") {
    actions.push(h("button.smf-btn", { onclick: () => { it.refs.forEach((r) => setRefValue(r, it.found_as)); scan(); } }, "Repoint"));
  }
  if (it.too_big) {
    actions.push(h("button.smf-btn.warn", { onclick: () => findSwap(it) }, "Find GGUF"));
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
  if (it.too_big) {
    const gb = (b) => (b / 1024 ** 3).toFixed(1) + " GB";
    const head = h("div.smf-warnline", `⚠ ${gb(it.size)} model > ${gb(state.budget)} VRAM budget — it will spill into system RAM (slow).`);
    let inner = null;
    if (sw === "loading") inner = h("div.smf-dim", spinner(), " Looking for GGUF quantizations…");
    else if (sw?.error) inner = h("div.err", sw.error);
    else if (sw?.options) {
      if (!sw.options.length) inner = h("div.smf-dim", "No GGUF repo found on HuggingFace for this model.");
      else {
        const canSwap = it.node_types.includes("UNETLoader") && ctx.status?.gguf_installed;
        inner = h("div",
          sw.note ? h("div.smf-dim.small", sw.note) : null,
          !ctx.status?.gguf_installed ? h("div.smf-warnline", "ComfyUI-GGUF isn't installed — install it via ComfyUI-Manager to load .gguf files.") : null,
          h("table.smf-table",
            h("tr", h("th", "Quant"), h("th", "File"), h("th", "Size"), h("th", "")),
            sw.options.slice(0, 12).map((o) => h("tr" + (o.recommended ? ".rec" : ""),
              h("td", pill(o.quant, o.fits ? "ok" : "bad"), o.recommended ? pill("best fit", "ok") : null),
              h("td.small", o.filename),
              h("td", fmtSize(o.size)),
              h("td", h("button.smf-btn.small" + (o.recommended ? ".primary" : ""), { onclick: () => downloadSwap(it, o) },
                canSwap ? "Download & swap" : "Download"))))),
          h("div.smf-dim.small", "From ", h("a.smf-link", { href: sw.options[0].page_url, target: "_blank" }, sw.options[0].repo)));
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
        it.hint ? h("div.smf-warnline.small", it.hint) : null),
      it.status === "missing" && !it.lm ? folderSel : h("span.smf-dim.small", it.found_folder || it.folder || ""),
      h("div.smf-actions", actions)),
    it.status === "missing" ? h("div.smf-item-sub", dest) : null,
    body, swapBody);
}

export function render() {
  const root = state.root;
  if (!root) return;
  const items = state.items;
  const missing = items.filter((i) => i.status === "missing");
  const moved = items.filter((i) => i.status === "elsewhere");
  const big = items.filter((i) => i.too_big);
  const toolbar = h("div.smf-toolbar",
    h("div.smf-summary",
      pill(`${items.length} models`, "dim"), " ",
      missing.length ? pill(`${missing.length} missing`, "bad") : pill("nothing missing", "ok"), " ",
      moved.length ? pill(`${moved.length} moved`, "warn") : null, " ",
      big.length ? pill(`${big.length} too big for VRAM`, "warn") : null),
    h("div.smf-actions",
      h("button.smf-btn", { onclick: () => scan() }, "Rescan"),
      missing.length ? h("button.smf-btn", { onclick: findAll }, "Find all sources") : null,
      missing.length ? h("button.smf-btn.primary", { onclick: downloadAllHigh }, "Download all (high confidence)") : null,
      moved.length ? h("button.smf-btn", { onclick: fixMoved }, "Fix moved paths") : null,
      items.some((i) => i.status === "present" && !i.lm)
        ? h("button.smf-btn", { onclick: embedSources, title: "Store each model's download link + SHA256 in the workflow, so anyone you share it with can fetch the exact files" }, "Embed model sources")
        : null));
  const smNote = state.smMode === "none"
    ? h("div.smf-warnline", "Stability Matrix shared folders not detected — downloads go to ComfyUI's own models folder. (Is this ComfyUI launched from Stability Matrix?)")
    : null;
  const list = items.length
    ? items.map(itemRow)
    : h("div.smf-empty", "This workflow doesn't reference any model files.");
  clear(root, toolbar, smNote, h("div.smf-list", list));
}
