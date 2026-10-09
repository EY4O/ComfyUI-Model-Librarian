// "Library" tab: card gallery with CivitAI previews, folder tree, filters,
// and bulk "Fetch metadata" (hash -> CivitAI lookup).
import { call, ctx, h, clear, fmtSize, toast, pill, spinner, copy, familyBadge, apiUrl, debounce } from "./util.js";

const TYPE_LABEL = {
  loras: "LORA", checkpoints: "CKPT", diffusion_models: "UNET", embeddings: "EMB", controlnet: "CN",
  text_encoders: "TE", vae: "VAE", upscale_models: "UPSC",
};
const state = {
  root: null, section: "loras", entries: [], folder: "", search: "", family: "", onlyMissing: false,
  shown: 0, job: null, blur: true, revealed: new Set(),
};
let jobTimer = null;
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
    render();
    pollJob();
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
    if (q) {
      const hay = `${e.name} ${e.title || ""} ${(e.trained_words || []).join(" ")} ${e.base_label || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
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
  const badges = {};
  for (const e of state.entries) {
    fams.set(e.family || "__unknown", (fams.get(e.family || "__unknown") || 0) + 1);
    if (e.family) badges[e.family] = e.badge;
  }
  clear(sideEl,
    h("div.smf-side-title", "Folders"),
    folderTree(),
    h("div.smf-side-title", "Base model"),
    h("div.smf-tree-item" + (!state.family ? ".sel" : ""), { onclick: () => { state.family = ""; refresh(); } }, "All"),
    [...fams.entries()].sort((a, b) => b[1] - a[1]).map(([f, n]) =>
      h("div.smf-tree-item" + (state.family === f ? ".sel" : ""), { onclick: () => { state.family = f; refresh(); } },
        familyBadge(f === "__unknown" ? null : f, f === "__unknown" ? "UNKN" : badges[f]), " ", f === "__unknown" ? "Unknown" : f,
        h("span.smf-dim.small", ` ${n}`))));
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
        e.version ? h("span.smf-chip", e.version) : null,
        e.base_label ? h("span.smf-chip.dim", e.base_label) : null)),
    nsfwHidden ? h("div.smf-nsfw", { onclick: (ev) => { ev.stopPropagation(); state.revealed.add(e.id); renderGrid(); } }, "NSFW — click to show") : null);
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
    notOnCivitai && !running ? h("span.smf-dim.small", { title: "Hash lookups found no match (private, renamed-and-retrained, or HuggingFace-only files)" }, `${notOnCivitai} not on CivitAI`) : null);
}

async function startIdentify() {
  if (!ctx.status?.config?.has_civitai_token) {
    toast("info", "Tip", "Add your CivitAI API key in Settings for the best results (some files need it).", 5000);
  }
  state.job = await call("/identify", { method: "POST", body: { sections: [state.section] } });
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
  sideEl = h("div.smf-lib-side");
  headEl = h("div.smf-lib-head");
  gridEl = h("div.smf-grid");
  clear(state.root,
    h("div.smf-toolbar", tabs),
    h("div.smf-toolbar", search, onlyMissing, h("button.smf-btn", { onclick: load }, "Reload")),
    h("div.smf-lib", sideEl, h("div.smf-lib-main", headEl, gridEl)));
  renderSide();
  renderGrid();
}
