// "Library" tab: card gallery with CivitAI previews, folder tree, filters,
// and bulk "Fetch metadata" (hash -> CivitAI lookup).
import { call, ctx, h, clear, fmtSize, toast, pill, spinner, copy, familyBadge, apiUrl, debounce, lmRescan } from "./util.js";
import { startDownload, onJobsChange } from "./downloads.js";
import { SORTS, sourceOf, filterEntries, sortEntries, stars, ago } from "./libview.js";

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
  sort: "folder", minRating: 0,
};
let jobTimer = null;
let updTimer = null;
// update downloads in flight: job id -> the old version's entry; finished ones can be archived
const updJobs = new Map();
const oldVersions = []; // [{id, name, size, section, newRel}]

let updDone = 0, updTimer2 = null;
onJobsChange((jobs, finished) => {
  for (const j of finished) {
    const old = updJobs.get(j.id);
    if (!old) continue;
    updJobs.delete(j.id);
    if (j.status !== "done") continue;
    if (!oldVersions.some((o) => o.id === old.id)) oldVersions.push({ ...old, newRel: j.rel });
    updDone++;
  }
  if (!updDone) return;
  // one notice and one reload for a batch of updates, once the last of them has finished
  clearTimeout(updTimer2);
  updTimer2 = setTimeout(() => {
    if (updJobs.size) return;
    const n = updDone;
    updDone = 0;
    const archive = ctx.status?.config?.archive_dir;
    toast("success", n > 1 ? `${n} models updated` : "Model updated", `New version${n > 1 ? "s" : ""} downloaded; the old one${n > 1 ? "s are" : " is"} kept.` +
      (archive ? " Library offers to move the old versions to the archive drive." : ""), 8000);
    if (state.root?.isConnected) load();
  }, 1200);
});
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
  return sortEntries(filterEntries(state.entries, state, { unused: state.unused, multiRoot: state.roots.length > 1 }), state.sort);
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
  const srcCount = { civitai: 0, hf: 0, none: 0, removed: 0 };
  for (const e of state.entries) {
    srcCount[sourceOf(e)]++;
    if (e.removed) srcCount.removed++;
  }
  const srcItem = (key, label) => h("div.smf-tree-item" + (state.source === key ? ".sel" : ""),
    { onclick: () => { state.source = key; refresh(); } }, label, h("span.smf-dim.small", ` ${key ? srcCount[key] : state.entries.length}`));
  clear(sideEl,
    h("div.smf-side-title", "Folders"),
    folderTree(),
    h("div.smf-side-title", "Source"),
    srcItem("", "All"), srcItem("civitai", "CivitAI"), srcCount.hf ? srcItem("hf", "🤗 HuggingFace") : null, srcItem("none", "Unknown"),
    srcCount.removed ? srcItem("removed", "⚠ Removed from source") : null,
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
  const src = apiUrl(`/preview/${e.id}?v=${Math.round(e.mtime)}` + (e.preview_video ? "" : "&w=448")); // a small thumbnail, not the full-size image
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
  return h("div.smf-card.clickable", { title: `${e.rel}\n${fmtSize(e.size)}\nBase: ${e.family || "unknown"} (${e.evidence || ""})\nClick for details and your notes`,
    onclick: () => modelDialog(e) },
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
        e.notes?.rating ? h("span.smf-chip.stars", { title: `Your rating: ${e.notes.rating}/5` }, stars(e.notes.rating).replace(/☆/g, "")) : null,
        e.notes?.note ? h("span.smf-chip.dim", { title: e.notes.note }, "📝") : null,
        e.use_count ? h("span.smf-chip.dim", { title: `Used in ${e.use_count} run${e.use_count > 1 ? "s" : ""}, last ${ago(e.last_used)}` }, `${e.use_count}×`) : null,
        e.update ? updateChip(e) : null,
        e.removed ? h("span.smf-chip.gone", { title: removedText(e) + "\nClick for details" }, "Removed") : null,
        e.hf ? h("span.smf-chip.hf", { title: `${e.hf.repo} on HuggingFace — click for license, tags and model card`, onclick: (ev) => { ev.stopPropagation(); hfDialog(e); } },
          "🤗 HF", e.hf.license_name || e.hf.license ? h("span.smf-dim", " · " + (e.hf.license_name || e.hf.license)) : null) : null,
        e.version ? h("span.smf-chip", e.version) : null,
        e.base_label ? h("span.smf-chip.dim", e.base_label) : null)),
    nsfwHidden ? h("div.smf-nsfw", { onclick: (ev) => { ev.stopPropagation(); state.revealed.add(e.id); renderGrid(); } }, "NSFW — click to show") : null);
}

// ---------------------------------------------------------------- details + your notes
function modelDialog(e) {
  const close = () => box.remove();
  const n = { rating: e.notes?.rating || 0, note: e.notes?.note || "", tags: (e.notes?.tags || []).join(", ") };
  const save = async () => {
    try {
      const r = await call("/library/notes", { method: "POST", body: { id: e.id, rating: n.rating, note: n.note, tags: n.tags } });
      e.notes = r.notes && (r.notes.rating || r.notes.note || r.notes.tags?.length) ? r.notes : undefined;
      renderGrid();
      toast("success", "Saved", e.title || e.name, 1800);
    } catch (err) {
      toast("error", "Not saved", err.message);
    }
  };
  const starRow = h("div.smf-stars");
  const drawStars = () => clear(starRow, [1, 2, 3, 4, 5].map((i) => h("button.smf-star" + (i <= n.rating ? ".on" : ""), {
    title: `${i} star${i > 1 ? "s" : ""}`, onclick: () => { n.rating = n.rating === i ? 0 : i; drawStars(); save(); },
  }, i <= n.rating ? "★" : "☆")));
  drawStars();
  const row = (label, v) => (v ? h("div.smf-hf-row", h("span.smf-dim", label), h("span", v)) : null);
  const box = h("div.smf-hf-pop", { onclick: (ev) => ev.target === box && close() },
    h("div.smf-hf-card",
      h("div.smf-row", h("b", e.title || e.name.replace(/\.[^.]+$/, "")), e.version ? h("span.smf-dim", " " + e.version) : null,
        h("span.smf-spacer"),
        e.page_url ? h("a.smf-btn.small", { href: e.page_url, target: "_blank", rel: "noopener" }, e.model_id ? "CivitAI ↗" : "Page ↗") : null,
        e.hf ? h("button.smf-btn.small.ghost", { onclick: () => { close(); hfDialog(e); } }, "🤗 Details") : null,
        h("button.smf-btn.small.ghost", { onclick: close, title: "Close" }, "×")),
      row("File", e.rel), row("Size", fmtSize(e.size)), row("Base model", [e.base_label, e.family && e.family !== e.base_label ? `(${e.family})` : ""].filter(Boolean).join(" ")),
      row("Used", e.use_count ? `${e.use_count} run${e.use_count > 1 ? "s" : ""} · last ${ago(e.last_used)}` : "not in any run Model Librarian has seen"),
      e.trained_words?.length ? h("div.smf-hf-row", h("span.smf-dim", "Trigger words"),
        h("span", e.trained_words.join(", "), " ", h("button.smf-btn.small.ghost", { onclick: () => copy(e.trained_words.join(", "), "Trigger words copied") }, "Copy"))) : null,
      e.removed ? h("div.smf-warnline", removedText(e), " Your copy may be the only one you can get, so keep it — its details and preview stay next to the file.") : null,
      e.sha256 && (e.removed || !e.model_id) ? archiveBox(e) : null,
      h("div.smf-hf-row", h("span.smf-dim", "My rating"), starRow),
      h("div.smf-field", h("label", "My tags (comma separated)"),
        h("input.smf-input", { value: n.tags, placeholder: "e.g. portrait, keeper, test later", oninput: (ev) => (n.tags = ev.target.value), onchange: save })),
      h("div.smf-field", h("label", "My notes"),
        h("textarea.smf-input", { rows: 4, value: n.note, placeholder: "Best strength, what it's good at, prompts that work…", oninput: (ev) => (n.note = ev.target.value), onchange: save })),
      h("div.smf-dim.small", "Saved in the shared data folder, so every ComfyUI using this models folder sees them; they follow the model when it's moved.")));
  (state.root.closest(".smf-modal") || state.root).append(box); // survives the tab re-rendering
}

// ---------------------------------------------------------------- removed models + CivArchive
function removedText(e) {
  const r = e.removed;
  const when = r.at ? ` (noticed ${String(new Date(r.at * 1000).toISOString()).slice(0, 10)})` : "";
  return r.what === "version" ? `This version was removed from ${r.where}${when}.`
    : r.what === "repo" ? `This repository isn't on ${r.where} any more${when}.`
    : `This model was removed from ${r.where}${when}.`;
}

// CivArchive keeps track of copies of files CivitAI no longer has (only asked for those)
function archiveBox(e) {
  const out = h("div.smf-archive");
  const show = async () => {
    clear(out, h("span.smf-dim.small", spinner(), " Asking CivArchive…"));
    let r;
    try {
      r = await call("/civarchive/lookup", { method: "POST", body: { sha256: e.sha256 } });
    } catch (err) {
      return clear(out, h("span.err.small", err.message));
    }
    const rec = r.record;
    if (!rec) return clear(out, h("span.smf-dim.small", "CivArchive doesn't list this file. ", h("a.smf-link", { href: r.page_url, target: "_blank", rel: "noopener" }, "Check on CivArchive ↗")));
    const live = rec.files.filter((c) => c.live);
    clear(out,
      h("div.smf-row", h("b.small", `CivArchive: ${live.length} live cop${live.length === 1 ? "y" : "ies"} of ${rec.files.length} known`), h("span.smf-spacer"),
        h("a.smf-btn.small", { href: rec.page_url, target: "_blank", rel: "noopener" }, "Open on CivArchive ↗")),
      rec.meta?.modelName ? h("div.smf-dim.small", [rec.meta.modelName, rec.meta.versionName, rec.meta.baseModel].filter(Boolean).join(" · ")) : null,
      rec.files.slice(0, 8).map((c) => h("div.smf-row.small",
        pill(c.live ? "live" : "gone", c.live ? "ok" : "dim"), " ", h("span", c.host), " ",
        c.live ? h("a.smf-link", { href: c.url, target: "_blank", rel: "noopener", title: c.url }, (c.filename || "file") + " ↗") : h("span.smf-dim", c.filename || ""))),
      h("div.smf-dim.small", "Share… in the Workflow tab uses a live copy as the download link for this model."));
  };
  clear(out, h("button.smf-btn.small", { onclick: show, title: "CivArchive tracks copies of models CivitAI no longer has (by SHA256)" }, "Find copies on CivArchive"));
  return out;
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
  (state.root.closest(".smf-modal") || state.root).append(box); // survives the tab re-rendering
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
    title: `Newer on CivitAI: ${u.name}${more}${u.published ? " · " + String(u.published).slice(0, 10) : ""}\nClick to compare it with yours and download it next to this file (this version is kept).`,
    onclick: (ev) => { ev.stopPropagation(); compareDialog(e); },
  }, "⬆ ", u.name,
  h("span.smf-chip-x", { title: `Don't show ${u.name} again`, onclick: (ev) => { ev.stopPropagation(); dismissUpdate(e); } }, "×"));
}

const updCandidate = (e) => call("/updates/candidate", { method: "POST", body: { id: e.id, version_id: e.update.id, version_name: e.update.name } });

async function queueUpdate(e, r) {
  const c = r.candidate;
  const job = await startDownload({ url: c.url, folder: r.folder, rel: r.rel, sha256: c.sha256, size: c.size, source: c.source || "civitai",
    page_url: c.page_url || e.update.page_url, title: c.title, meta: c.meta });
  updJobs.set(job.id, { id: e.id, name: e.name, size: e.size, section: e.section });
}

async function getUpdate(e, { ask = true } = {}) {
  const u = e.update;
  try {
    const r = await updCandidate(e);
    if (ask && !confirm(`Download ${u.model_name || e.title || e.name} ${u.name}?\n\nSaves as ${r.folder}/${r.rel}${r.candidate.size ? ` (${fmtSize(r.candidate.size)})` : ""}.\nThe version you have (${e.version || e.name}) is kept.`)) return;
    await queueUpdate(e, r);
    toast("info", "Download queued", r.rel, 3000);
  } catch (err) {
    toast("error", "Couldn't get the update", err.message, 8000);
  }
}

// Every update shown in this section, after one confirmation with the total size.
async function getAllUpdates() {
  const list = state.entries.filter((e) => e.update);
  if (!list.length) return;
  const found = [];
  let failed = 0;
  toast("info", "Updates", `Looking up ${list.length} new version${list.length > 1 ? "s" : ""}…`, 3000);
  for (const e of list) {
    try { found.push([e, await updCandidate(e)]); } catch { failed++; }
  }
  if (!found.length) return toast("error", "Couldn't get the updates", "CivitAI didn't answer for any of them.", 8000);
  const bytes = found.reduce((a, [, r]) => a + (r.candidate.size || 0), 0);
  const lines = found.slice(0, 12).map(([e, r]) => `• ${e.title || e.name} → ${e.update.name}  (${r.rel})`);
  if (!confirm(`Download ${found.length} new version${found.length > 1 ? "s" : ""}${bytes ? `, ${fmtSize(bytes)} in total` : ""}?\n\n${lines.join("\n")}` +
    `${found.length > 12 ? `\n… and ${found.length - 12} more` : ""}${failed ? `\n\n${failed} couldn't be looked up and are skipped.` : ""}\n\nThe versions you have are kept.`)) return;
  let n = 0;
  for (const [e, r] of found) {
    try { await queueUpdate(e, r); n++; } catch (err) { toast("warn", "Not queued", `${e.name}: ${err.message}`, 6000); }
  }
  toast("info", "Downloads queued", `${n} update${n > 1 ? "s" : ""}`, 4000);
}

// After updates: move the versions they replaced to the archive drive (or keep them).
function oldVersionsBanner() {
  const here = oldVersions.filter((o) => state.entries.some((e) => e.id === o.id));
  if (!here.length) return null;
  const bytes = here.reduce((a, o) => a + (o.size || 0), 0);
  const archive = ctx.status?.config?.archive_dir;
  const clearThese = () => { for (const o of here) oldVersions.splice(oldVersions.indexOf(o), 1); renderGrid(); };
  return h("div.smf-oldbanner",
    h("span", `${here.length} model${here.length > 1 ? "s were" : " was"} updated. `,
      archive ? `Move the old version${here.length > 1 ? "s" : ""} (${fmtSize(bytes)}) to the archive drive?` : "The old versions are kept (set an archive folder in Settings → Storage tiers to move them off the SSD)."),
    h("span.smf-spacer"),
    archive ? h("button.smf-btn.small.primary", {
      title: here.map((o) => o.name).join("\n"),
      onclick: async () => {
        try {
          await call("/tiering/archive", { method: "POST", body: { ids: here.map((o) => o.id) } });
          toast("info", "Archiving", `${here.length} old version${here.length > 1 ? "s" : ""} — progress in the Storage tab. They stay usable from the HDD.`, 7000);
          clearThese();
        } catch (err) {
          toast("warn", "Not started", err.message, 7000);
        }
      },
    }, "Archive old versions") : null,
    h("button.smf-btn.small.ghost", { onclick: clearThese }, archive ? "Keep them" : "OK"));
}

// The version you have next to the newer one, before downloading it.
function compareDialog(e) {
  const u = e.update;
  const close = () => box.remove();
  const body = h("div", h("div.smf-empty", spinner(), " Asking CivitAI…"));
  const box = h("div.smf-hf-pop", { onclick: (ev) => ev.target === box && close() },
    h("div.smf-hf-card.smf-share-card",
      h("div.smf-row", h("b", e.title || e.name.replace(/\.[^.]+$/, "")), h("span.smf-dim", ` ${e.version || "yours"} → ${u.name}`), h("span.smf-spacer"),
        h("a.smf-btn.small", { href: u.page_url, target: "_blank", rel: "noopener" }, "CivitAI ↗"),
        h("button.smf-btn.small.ghost", { onclick: close, title: "Close" }, "×")),
      body));
  (state.root.closest(".smf-modal") || state.root).append(box); // survives the tab re-rendering
  call("/updates/compare", { method: "POST", body: { model_id: u.model_id, have: e.version_id, newer: u.id } })
    .then((r) => drawCompare(e, r, body, close))
    .catch((err) => clear(body, h("div.err", err.message), h("div.smf-toolbar",
      h("button.smf-btn.primary", { onclick: () => { close(); getUpdate(e); } }, `Download ${u.name} anyway`))));
}

function drawCompare(e, r, body, close) {
  const a = r.have, b = r.newer;
  const date = (v) => (v?.published ? String(v.published).slice(0, 10) : "?");
  const n = (x) => (x == null ? "?" : Intl.NumberFormat().format(x));
  const words = (v, other) => {
    const o = new Set((other?.trained_words || []).map((w) => w.toLowerCase()));
    return (v?.trained_words || []).length
      ? v.trained_words.map((w) => h("span.smf-chip" + (other && !o.has(w.toLowerCase()) ? ".upd" : ".dim"), { title: other && !o.has(w.toLowerCase()) ? "Only in this version" : "" }, w))
      : h("span.smf-dim", "none");
  };
  const imgs = (v) => h("div.smf-cmp-imgs", (v?.images || []).map((i) => h("img" + (i.nsfw && state.blur ? ".blur" : ""), { src: i.url, loading: "lazy", alt: "", referrerPolicy: "no-referrer" })),
    v?.hidden_images ? h("span.smf-dim.small", `${v.hidden_images} NSFW image(s) hidden (Settings → NSFW previews)`) : null);
  const row = (label, f) => [h("div.smf-dim.small", label), h("div", f(a, b)), h("div", f(b, a))];
  clear(body,
    h("div.smf-cmp",
      h("div"), h("b", "You have · " + (a?.name || e.version || "this file")), h("b", "Newer · " + b.name, b.early_access ? h("span", " ", pill("early access", "warn")) : null),
      row("Published", (v) => date(v)),
      row("Base model", (v) => v?.base_model || "?"),
      row("File", (v) => v ? [v.file || "?", h("div.smf-dim.small", [v.size ? fmtSize(v.size) : null, v.format].filter(Boolean).join(" · "))] : "?"),
      row("Popularity", (v) => v ? `${n(v.downloads)} downloads · ${n(v.likes)} likes` : "?"),
      row("Trigger words", (v, o) => words(v, o)),
      row("Samples", (v) => imgs(v))),
    a ? null : h("div.smf-dim.small", "CivitAI doesn't list your version any more, so only the newer one is shown."),
    b.description ? h("div.smf-field", h("label", `About ${b.name}`), h("div.smf-hf-readme", b.description)) : null,
    h("div.smf-toolbar",
      h("button.smf-btn.ghost", { onclick: () => { close(); dismissUpdate(e); }, title: `Don't show ${b.name} again for this model` }, "Hide this version"),
      h("button.smf-btn.primary", { onclick: () => { close(); getUpdate(e, { ask: false }); } },
        `Download ${b.name}` + (b.size ? ` (${fmtSize(b.size)})` : ""), h("span.smf-dim.small", " · yours is kept"))));
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

const SEEN_REMOVED = "smf.removedSeen";
function readSeenRemoved() {
  try { return JSON.parse(localStorage.getItem(SEEN_REMOVED) || "[]"); } catch { return []; }
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
      toast("info", "Model updates", `${st.updates} of your models have a newer version on CivitAI — open Library and tick Updates only.`, 10000);
    }
    const seen = new Set(readSeenRemoved());
    const fresh = (st.removed || []).filter((id) => !seen.has(id));
    if (st.status === "done" && fresh.length) {
      toast("warn", "Removed from CivitAI", `${fresh.length} of your models ${fresh.length === 1 ? "was" : "were"} removed from CivitAI — your copies may be the only ones left. Library → Source → Removed.`, 12000);
      try { localStorage.setItem(SEEN_REMOVED, JSON.stringify([...seen, ...fresh].slice(-2000))); } catch {}
    }
  } catch {}
}

function renderGrid() {
  if (!gridEl) return;
  const list = filtered();
  if (!state.shown) state.shown = 120;
  observer?.disconnect();
  clear(gridEl, list.slice(0, state.shown).map(card));
  const banner = oldVersionsBanner();
  if (banner) gridEl.prepend(banner);
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
      : [nUpd ? h("button.smf-btn.primary", { onclick: getAllUpdates, title: "Download the newer version of every model flagged in this section (the old ones are kept)" }, `Download all updates (${nUpd})`) : null,
        h("button.smf-btn", {
        onclick: startUpdateCheck,
        title: "Ask CivitAI for newer versions of every model with CivitAI metadata (all model types)" + (u?.last_check ? `\nLast checked ${new Date(u.last_check * 1000).toLocaleString()}` : ""),
      }, "Check for updates")]);
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
  const sortSel = h("select.smf-select", { title: "Sort", onchange: (ev) => { state.sort = ev.target.value; state.shown = 0; renderGrid(); } },
    Object.entries(SORTS).map(([k, label]) => h("option", { value: k, selected: state.sort === k }, label)));
  const ratingSel = h("select.smf-select", { title: "Your rating", onchange: (ev) => { state.minRating = Number(ev.target.value); state.shown = 0; renderGrid(); } },
    [0, 1, 2, 3, 4, 5].map((i) => h("option", { value: i, selected: state.minRating === i }, i ? `★ ${i}+` : "Any rating")));
  sideEl = h("div.smf-lib-side");
  headEl = h("div.smf-lib-head");
  gridEl = h("div.smf-grid");
  clear(state.root,
    h("div.smf-toolbar", tabs),
    h("div.smf-toolbar", search, sortSel, ratingSel, onlyMissing, onlyUnused, onlyUpdates, h("button.smf-btn", { onclick: load }, "Reload")),
    h("div.smf-lib", sideEl, h("div.smf-lib-main", headEl, gridEl)));
  renderSide();
  renderGrid();
}
