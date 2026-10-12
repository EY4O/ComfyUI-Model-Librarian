// "Library" tab: card gallery with CivitAI previews, folder tree, filters,
// and bulk "Fetch metadata" (hash -> CivitAI lookup).
import { call, ctx, h, clear, fmtSize, toast, pill, spinner, copy, familyBadge, apiUrl, debounce, lmRescan } from "./util.js";
import { startDownload } from "./downloads.js";

const TYPE_LABEL = {
  loras: "LORA", checkpoints: "CKPT", diffusion_models: "UNET", embeddings: "EMB", controlnet: "CN",
  text_encoders: "TE", vae: "VAE", upscale_models: "UPSC",
};
const state = {
  root: null, section: "loras", entries: [], folder: "", search: "", family: "", onlyMissing: false,
  shown: 0, job: null, blur: true, revealed: new Set(),
  onlyUnused: false, unused: null, usageInfo: null, // unused: Set of ids for the loaded section
  onlyUpdates: false, upd: null, // upd: the update-check job
  source: "", // "", "civitai", "hf", "none"
};
const sourceOf = (e) => (e.model_id ? "civitai" : e.hf ? "hf" : "none");
let jobTimer = null;
let updTimer = null;
let observer = null;

export function mount(root) {
  state.root = root;
  load();
}

async function load() {
  clear(state.root, h("div.smf-empty", spinner(), " Reading library…"));
  try {
    const res = await call(`/library?section=${state.section}`);
    state.entries = res.entries;
    state.roots = res.roots;
    state.blur = res.blur_nsfw;
    state.unused = null;
    if (state.onlyUnused) await loadUsage();
    render();
    pollJob();
    pollUpdates();
  } catch (e) {
    clear(state.root, h("div.smf-empty.err", "Failed: " + e.message));
  }
}

function filtered() {
  const q = state.search.toLowerCase();
  return state.entries.filter((e) => {
    if (state.folder) {
      const top = state.folder;
      const full = (state.roots.length > 1 ? e.root_name + "/" : "") + e.rel;
      if (!full.startsWith(top + "/")) return false;
    }
    if (state.family === "__unknown" && e.family) return false;
    if (state.family && state.family !== "__unknown" && e.family !== state.family) return false;
    if (state.onlyMissing && e.has_meta) return false;
    if (state.onlyUpdates && !e.update) return false;
    if (state.source && sourceOf(e) !== state.source) return false;
    if (state.onlyUnused && state.unused && !state.unused.has(e.id)) return false;
    if (q) {
      const hay = `${e.name} ${e.title || ""} ${(e.trained_words || []).join(" ")} ${e.base_label || ""} ${e.hf?.repo || ""} ${(e.hf?.tags || []).join(" ")}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

async function loadUsage() {
  try {
    const r = await call(`/library/usage?section=${state.section}`);
    state.unused = new Set(r.unused_ids);
    state.usageInfo = r;
  } catch (e) {
    state.onlyUnused = false;
    toast("error", "Usage check failed", e.message);
  }
}

function folderTree() {
  const counts = new Map();
  for (const e of state.entries) {
    const full = (state.roots.length > 1 ? e.root_name + "/" : "") + e.rel;
    const parts = full.split("/").slice(0, -1);
    for (let i = 1; i <= parts.length; i++) {
      const p = parts.slice(0, i).join("/");
      counts.set(p, (counts.get(p) || 0) + 1);
    }
  }
  const keys = [...counts.keys()].sort((a, b) => a.localeCompare(b));
  const item = (label, path, depth, n) => h("div.smf-tree-item" + (state.folder === path ? ".sel" : ""),
    { style: { paddingLeft: 8 + depth * 14 + "px" }, onclick: () => { state.folder = path; state.shown = 0; renderGrid(); renderSide(); } },
    "📁 ", label, h("span.smf-dim.small", ` ${n}`));
  return [
    item("All", "", 0, state.entries.length),
    keys.map((k) => item(k.split("/").pop(), k, k.split("/").length, counts.get(k))),
  ];
}

let sideEl, gridEl, headEl, sentinel;

function renderSide() {
  if (!sideEl) return;
  const fams = new Map();
  const bytes = new Map();
  const badges = {};
  let total = 0;
  for (const e of state.entries) {
    const f = e.family || "__unknown";
    fams.set(f, (fams.get(f) || 0) + 1);
    bytes.set(f, (bytes.get(f) || 0) + e.size);
    total += e.size;
    if (e.family) badges[e.family] = e.badge;
  }
  const srcCount = { civitai: 0, hf: 0, none: 0 };
  for (const e of state.entries) srcCount[sourceOf(e)]++;
  const srcItem = (key, label) => h("div.smf-tree-item" + (state.source === key ? ".sel" : ""),
    { onclick: () => { state.source = key; refresh(); } }, label, h("span.smf-dim.small", ` ${key ? srcCount[key] : state.entries.length}`));
  clear(sideEl,
    h("div.smf-side-title", "Folders"),
    folderTree(),
    h("div.smf-side-title", "Source"),
    srcItem("", "All"), srcItem("civitai", "CivitAI"), srcCount.hf ? srcItem("hf", "🤗 HuggingFace") : null, srcItem("none", "Unknown"),
    h("div.smf-side-title", "Base model"),
    h("div.smf-tree-item" + (!state.family ? ".sel" : ""), { onclick: () => { state.family = ""; refresh(); } },
      "All", h("span.smf-dim.small", ` ${fmtSize(total)}`)),
    [...fams.entries()].sort((a, b) => bytes.get(b[0]) - bytes.get(a[0])).map(([f, n]) =>
      h("div.smf-tree-item" + (state.family === f ? ".sel" : ""), { onclick: () => { state.family = f; refresh(); },
        title: `${n} model(s), ${fmtSize(bytes.get(f))}` },
        familyBadge(f === "__unknown" ? null : f, f === "__unknown" ? "UNKN" : badges[f]), " ", f === "__unknown" ? "Unknown" : f,
        h("span.smf-dim.small", ` ${n} · ${fmtSize(bytes.get(f))}`))));
}

function refresh() {
  state.shown = 0;
  renderSide();
  renderGrid();
}

function card(e) {
  const nsfwHidden = state.blur && e.nsfw && !state.revealed.has(e.id);
  const src = apiUrl(`/preview/${e.id}?v=${Math.round(e.mtime)}`);
  const media = e.has_preview
    ? e.preview_video
      ? h("video.smf-media", { src, muted: true, loop: true, autoplay: true, playsInline: true })
      : h("img.smf-media", { src, loading: "lazy", alt: "" })
    : h("div.smf-media.none", h("span", "NO PREVIEW"));
  if (nsfwHidden) media.classList.add("blur");
  const fetchBtn = h("button.smf-icon", {
    title: e.has_meta ? "Refresh metadata from CivitAI" : "Fetch metadata from CivitAI",
    onclick: async (ev) => {
      ev.stopPropagation();
      const btn = ev.currentTarget;
      btn.disabled = true;
      btn.replaceChildren(spinner());
      try {
        state.job = await call("/identify", { method: "POST", body: { sections: [state.section], ids: [e.id] } });
        if (state.job.status !== "running") toast("info", "Busy", "Another metadata fetch is already running.");
        pollJob();
      } catch (err) {
        toast("error", "Lookup failed", err.message);
      }
    },
  }, "⟳");
  return h("div.smf-card", { title: `${e.rel}\n${fmtSize(e.size)}\nBase: ${e.family || "unknown"} (${e.evidence || ""})` },
    media,
    h("div.smf-card-top",
      h("span.smf-type", TYPE_LABEL[e.section] || "MODEL"),
      familyBadge(e.family, e.badge),
      h("span.smf-spacer"),
      e.page_url ? h("a.smf-icon", { href: e.page_url, target: "_blank", rel: "noopener", title: "Open on CivitAI", onclick: (ev) => ev.stopPropagation() }, "🌐") : null,
      e.trained_words?.length ? h("button.smf-icon", { title: "Copy trigger words: " + e.trained_words.join(", "), onclick: (ev) => { ev.stopPropagation(); copy(e.trained_words.join(", "), "Trigger words copied"); } }, "✎") : null,
      h("button.smf-icon", { title: "Copy file name", onclick: (ev) => { ev.stopPropagation(); copy(e.rel, "File name copied"); } }, "⧉"),
      fetchBtn),
    h("div.smf-card-bottom",
      h("div.smf-card-title", e.title || e.name.replace(/\.[^.]+$/, "")),
      h("div.smf-row",
        e.archived ? h("span.smf-chip", { title: "On the archive drive — comes back to the SSD when a workflow uses it" }, "HDD") : null,
        e.update ? updateChip(e) : null,
        e.hf ? h("span.smf-chip.hf", { title: `${e.hf.repo} on HuggingFace — click for license, tags and model card`, onclick: (ev) => { ev.stopPropagation(); hfDialog(e); } },
          "🤗 HF", e.hf.license_name || e.hf.license ? h("span.smf-dim", " · " + (e.hf.license_name || e.hf.license)) : null) : null,
        e.version ? h("span.smf-chip", e.version) : null,
        e.base_label ? h("span.smf-chip.dim", e.base_label) : null)),
    nsfwHidden ? h("div.smf-nsfw", { onclick: (ev) => { ev.stopPropagation(); state.revealed.add(e.id); renderGrid(); } }, "NSFW — click to show") : null);
}

// ---------------------------------------------------------------- HuggingFace details
function hfDialog(e) {
  const close = () => box.remove();
  const body = h("div.smf-hf-body");
  const box = h("div.smf-hf-pop", { onclick: (ev) => ev.target === box && close() },
    h("div.smf-hf-card", h("div.smf-row",
      h("b", "🤗 ", e.hf.repo), h("span.smf-spacer"),
      h("button.smf-btn.small.ghost", { onclick: () => refreshHf(e, body) }, "Refresh"),
      h("a.smf-btn.small", { href: `https://huggingface.co/${e.hf.repo}`, target: "_blank", rel: "noopener" }, "Open on HuggingFace ↗"),
      h("button.smf-btn.small.ghost", { onclick: close, title: "Close" }, "×")), body));
  drawHf(e, body);
  state.root.append(box);
  if (!e.hf.fetched) refreshHf(e, body);
}

function drawHf(e, body) {
  const d = e.hf;
  if (d.gone) return clear(body, h("div.smf-empty", "This repository isn't on HuggingFace any more (or it's private)."));
  if (!d.fetched) return clear(body, h("div.smf-empty", spinner(), " Fetching details…"));
  const n = (x) => (x == null ? "?" : Intl.NumberFormat().format(x));
  const row = (label, v) => (v ? h("div.smf-hf-row", h("span.smf-dim", label), h("span", v)) : null);
  clear(body,
    row("File", d.path),
    row("License", d.license_name || d.license),
    row("Base model", d.base_model),
    row("Task", [d.pipeline, d.library].filter(Boolean).join(" · ")),
    row("Popularity", `${n(d.likes)} likes · ${n(d.downloads)} downloads (last month)`),
    d.gated ? row("Access", d.gated === "manual" ? "gated — the author approves each request" : "gated — accept the license on the model page (and add a HuggingFace token in Settings)") : null,
    row("Updated", d.updated ? String(d.updated).slice(0, 10) : null),
    d.tags?.length ? h("div.smf-row.wrap", { style: { marginTop: "6px" } }, d.tags.map((t) => pill(t, "dim"))) : null,
    d.card ? h("div.smf-hf-readme", d.card, d.card_truncated ? h("div.smf-dim.small", "… the full model card is on HuggingFace.") : null)
      : h("div.smf-dim.small", { style: { marginTop: "8px" } }, "No model card."));
}

async function refreshHf(e, body) {
  clear(body, h("div.smf-empty", spinner(), " Fetching details…"));
  try {
    const r = await call("/hf/details", { method: "POST", body: { repo: e.hf.repo, force: true } });
    Object.assign(e.hf, r.details || {});
  } catch (err) {
    toast("error", "HuggingFace", err.message);
  }
  drawHf(e, body);
  renderGrid();
}

// ---------------------------------------------------------------- update alerts
function updateChip(e) {
  const u = e.update;
  const more = u.newer_count > 1 ? ` (${u.newer_count} newer versions)` : "";
  return h("span.smf-chip.upd", {
    title: `Newer on CivitAI: ${u.name}${more}${u.published ? " · " + String(u.published).slice(0, 10) : ""}\nClick to download it next to this file (this version is kept).`,
    onclick: (ev) => { ev.stopPropagation(); getUpdate(e); },
  }, "⬆ ", u.name,
  h("span.smf-chip-x", { title: `Don't show ${u.name} again`, onclick: (ev) => { ev.stopPropagation(); dismissUpdate(e); } }, "×"));
}

async function getUpdate(e) {
  const u = e.update;
  try {
    const r = await call("/updates/candidate", { method: "POST", body: { id: e.id, version_id: u.id, version_name: u.name } });
    if (!confirm(`Download ${u.model_name || e.title || e.name} ${u.name}?\n\nSaves as ${r.folder}/${r.rel}${r.candidate.size ? ` (${fmtSize(r.candidate.size)})` : ""}.\nThe version you have (${e.version || e.name}) is kept.`)) return;
    const c = r.candidate;
    await startDownload({ url: c.url, folder: r.folder, rel: r.rel, sha256: c.sha256, size: c.size, source: c.source || "civitai",
      page_url: c.page_url || u.page_url, title: c.title, meta: c.meta });
    toast("info", "Download queued", r.rel, 3000);
  } catch (err) {
    toast("error", "Couldn't get the update", err.message, 8000);
  }
}

async function dismissUpdate(e) {
  try {
    await call("/updates/dismiss", { method: "POST", body: { model_id: e.update.model_id, version_id: e.update.id } });
    delete e.update;
    renderGrid();
  } catch (err) {
    toast("error", "Not saved", err.message);
  }
}

async function startUpdateCheck() {
  if (!ctx.status?.config?.has_civitai_token) toast("info", "Tip", "A CivitAI API key in Settings helps with models that need sign-in.", 5000);
  try {
    state.upd = await call("/updates/check", { method: "POST", body: { force: true } });
  } catch (e) {
    return toast("error", "Can't check now", e.message);
  }
  renderHead(filtered().length);
  pollUpdates();
}

async function pollUpdates() {
  clearTimeout(updTimer);
  try {
    const prev = state.upd?.status;
    state.upd = await call("/updates");
    renderHead(filtered().length);
    if (state.upd.status === "running") updTimer = setTimeout(pollUpdates, 1000);
    else if (prev === "running" && state.upd.status === "done") load();
  } catch {}
}

// Once a day, a minute after ComfyUI opens (Settings → check_updates): look for newer
// versions in the background and say so when there are some.
export async function autoCheckUpdates() {
  try {
    if (ctx.status?.config?.check_updates === false) return;
    let st = await call("/updates");
    if (st.status === "running" || !st.stale) return;
    st = await call("/updates/check", { method: "POST", body: {} });
    while (st.status === "running") {
      await new Promise((r) => setTimeout(r, 3000));
      st = await call("/updates");
    }
    if (st.status === "done" && st.updates) {
      toast("info", "Model updates", `${st.updates} of your models have a newer version on CivitAI — Models → Library → Updates only.`, 10000);
    }
  } catch {}
}

function renderGrid() {
  if (!gridEl) return;
  const list = filtered();
  if (!state.shown) state.shown = 120;
  observer?.disconnect();
  clear(gridEl, list.slice(0, state.shown).map(card));
  if (!list.length) gridEl.append(h("div.smf-empty", "No models match."));
  if (list.length > state.shown) {
    sentinel = h("div.smf-sentinel", spinner());
    gridEl.append(sentinel);
    observer = new IntersectionObserver((ents) => {
      if (ents.some((x) => x.isIntersecting)) {
        state.shown += 120;
        renderGrid();
      }
    }, { root: gridEl.closest(".smf-lib-main"), rootMargin: "600px" });
    observer.observe(sentinel);
  }
  renderHead(list.length);
}

function renderHead(n) {
  if (!headEl) return;
  const missingMeta = state.entries.filter((e) => !e.has_meta && !e.lookup_failed).length;
  const notOnCivitai = state.entries.filter((e) => e.lookup_failed).length;
  const j = state.job;
  const running = j?.status === "running";
  const u = state.upd;
  const checking = u?.status === "running";
  const nUpd = state.entries.filter((e) => e.update).length;
  clear(headEl,
    h("span.smf-dim", `${n} of ${state.entries.length}`),
    h("span.smf-spacer"),
    running
      ? h("div.smf-jobinline",
        h("div.smf-bar.inline", h("div", { style: { width: (j.total ? (100 * j.done) / j.total : 0) + "%" } })),
        h("span.smf-dim.small", `${j.done}/${j.total} · found ${j.found} · ${j.current || ""}`),
        h("button.smf-btn.small.ghost", { onclick: () => call("/identify/cancel", { method: "POST" }).then(pollJob) }, "Stop"))
      : h("button.smf-btn" + (missingMeta ? ".primary" : ""), {
        onclick: startIdentify,
        title: "Hashes files without metadata and looks them up on CivitAI (uses your API key). Writes .cm-info.json + preview next to each model.",
      }, missingMeta ? `Fetch metadata (${missingMeta})` : "All identified ✓"),
    ctx.status?.lm_installed && BRIDGE_SECTIONS.has(state.section) && !running
      ? h("button.smf-btn", { onclick: syncWithLM, title: "Copy metadata between LoRA Manager (.metadata.json) and Stability Matrix (.cm-info.json + preview) — offline, no API calls" }, "Sync with LoRA Manager")
      : null,
    notOnCivitai && !running ? h("span.smf-dim.small", { title: "Hash lookups found no match (private, renamed-and-retrained, or HuggingFace-only files)" }, `${notOnCivitai} not on CivitAI`) : null,
    checking
      ? h("div.smf-jobinline",
        h("div.smf-bar.inline", h("div", { style: { width: (u.total ? (100 * u.done) / u.total : 0) + "%" } })),
        h("span.smf-dim.small", `Checking for updates ${u.done}/${u.total}`),
        h("button.smf-btn.small.ghost", { onclick: () => call("/updates/cancel", { method: "POST" }).then(pollUpdates) }, "Stop"))
      : h("button.smf-btn", {
        onclick: startUpdateCheck,
        title: "Ask CivitAI for newer versions of every model with CivitAI metadata (all model types)" + (u?.last_check ? `\nLast checked ${new Date(u.last_check * 1000).toLocaleString()}` : ""),
      }, nUpd ? `Check for updates · ${nUpd} here` : "Check for updates"));
}

const BRIDGE_SECTIONS = new Set(["loras", "checkpoints", "embeddings", "diffusion_models"]);
const BRIDGE_LABELS = {
  to_sm: "Stability Matrix info written from LoRA Manager",
  sha_to_sm: "SHA256 added to Stability Matrix info",
  preview: "previews copied for Stability Matrix",
  to_lm: "LoRA Manager entries filled in from Stability Matrix",
  new_lm: "LoRA Manager entries created (hash verified)",
};

async function syncWithLM() {
  let plan;
  try {
    plan = await call("/bridge/plan", { method: "POST", body: { sections: [state.section] } });
  } catch (e) {
    return toast("error", "Sync failed", e.message);
  }
  const lines = Object.entries(plan.counts).map(([k, n]) => `• ${n} ${BRIDGE_LABELS[k] || k}`);
  const skipped = plan.skipped.length ? `\n\n${plan.skipped.length} skipped (not hashed yet — run Fetch metadata first).` : "";
  if (!plan.items.length) return toast("info", "Already in sync", `Nothing to copy between LoRA Manager and Stability Matrix.${skipped}`, 6000);
  if (!confirm(`Sync ${plan.items.length} model(s):\n\n${lines.join("\n")}${skipped}\n\nOnly missing information is added; nothing is deleted.`)) return;
  try {
    const r = await call("/bridge/apply", { method: "POST", body: { ids: plan.items.map((i) => i.id) } });
    const done = Object.entries(r.counts).map(([k, n]) => `${n} ${BRIDGE_LABELS[k] || k}`).join(" · ");
    toast(r.failed ? "warn" : "success", "Synced", done + (r.failed ? ` · ${r.failed} failed` : ""), 8000);
    if (r.lm_sections.length) lmRescan(r.lm_sections, { full: true });
    load();
  } catch (e) {
    toast("error", "Sync failed", e.message, 8000);
  }
}

async function startIdentify() {
  if (!ctx.status?.config?.has_civitai_token) {
    toast("info", "Tip", "Add your CivitAI API key in Settings for the best results (some files need it).", 5000);
  }
  try {
    state.job = await call("/identify", { method: "POST", body: { sections: [state.section] } });
  } catch (e) {
    return toast("warn", "Can't fetch metadata now", e.message, 6000);
  }
  renderHead(filtered().length);
  pollJob();
}

async function pollJob() {
  clearTimeout(jobTimer);
  try {
    const prev = state.job?.status;
    state.job = await call("/identify");
    renderHead(filtered().length);
    if (state.job.status === "running") jobTimer = setTimeout(pollJob, 1000);
    else if (prev === "running" && state.job.status === "done") {
      toast("success", "Metadata fetched", `Found ${state.job.found}, not on CivitAI ${state.job.not_found}`, 6000);
      load();
    }
  } catch {}
}

function render() {
  const sections = ctx.status?.sections || { loras: "LoRAs" };
  const tabs = h("div.smf-subtabs",
    Object.entries(sections).map(([k, label]) => h("button.smf-subtab" + (k === state.section ? ".sel" : ""),
      { onclick: () => { state.section = k; state.folder = ""; state.family = ""; load(); } }, label)));
  const search = h("input.smf-input", {
    placeholder: "Search name, title, trigger words…", value: state.search,
    oninput: debounce((ev) => { state.search = ev.target.value; state.shown = 0; renderGrid(); }, 150),
  });
  const onlyMissing = h("label.smf-check", h("input", { type: "checkbox", checked: state.onlyMissing,
    onchange: (ev) => { state.onlyMissing = ev.target.checked; state.shown = 0; renderGrid(); } }), " Missing info only");
  const onlyUnused = h("label.smf-check", {
    title: "Not referenced by any saved workflow in this ComfyUI, nor by a LoRA Manager recipe",
  }, h("input", { type: "checkbox", checked: state.onlyUnused,
    onchange: async (ev) => {
      state.onlyUnused = ev.target.checked;
      if (state.onlyUnused && !state.unused) await loadUsage();
      if (state.onlyUnused && state.usageInfo) {
        const unusedBytes = state.entries.filter((e) => state.unused.has(e.id)).reduce((a, e) => a + e.size, 0);
        toast("info", "Unused models", `${state.unused.size} model(s), ${fmtSize(unusedBytes)} — not in any of ${state.usageInfo.workflows} saved workflow(s) or ${state.usageInfo.recipes} recipe(s)`, 7000);
      }
      state.shown = 0;
      renderGrid();
    } }), " Unused only");
  const nUpd = state.entries.filter((e) => e.update).length;
  const onlyUpdates = h("label.smf-check", { title: "Models with a newer version on CivitAI for the same base model" },
    h("input", { type: "checkbox", checked: state.onlyUpdates, onchange: (ev) => { state.onlyUpdates = ev.target.checked; state.shown = 0; renderGrid(); } }),
    nUpd ? ` Updates only (${nUpd})` : " Updates only");
  sideEl = h("div.smf-lib-side");
  headEl = h("div.smf-lib-head");
  gridEl = h("div.smf-grid");
  clear(state.root,
    h("div.smf-toolbar", tabs),
    h("div.smf-toolbar", search, onlyMissing, onlyUnused, onlyUpdates, h("button.smf-btn", { onclick: load }, "Reload")),
    h("div.smf-lib", sideEl, h("div.smf-lib-main", headEl, gridEl)));
  renderSide();
  renderGrid();
}
