// "Archive" tab: point it at a folder of generated images (subfolders included) and it
// writes _ml_archive/ inside it: a report grouped by prompt family, a CSV, every recipe,
// one workflow per prompt variant, and small WebP thumbnails that carry their image's
// workflow (drop one onto ComfyUI to get that exact image back).
import { call, h, clear, fmtSize, toast, pill, spinner, copy, apiUrl } from "./util.js";

const RECENT = "smf.archiveFolders";
const s = { root: null, folder: "", job: null, summary: null, timer: null, moves: null, plan: null, dest: "", destFor: "", showMove: false, opts: { recursive: true, thumbs: true, embed: true, grouping: "similar" } };

const recent = () => { try { return JSON.parse(localStorage.getItem(RECENT) || "[]"); } catch { return []; } };
function remember(folder) {
  try { localStorage.setItem(RECENT, JSON.stringify([folder, ...recent().filter((f) => f !== folder)].slice(0, 8))); } catch {}
}

export function mount(root) {
  s.root = root;
  s.folder = s.folder || recent()[0] || "";
  render();
  poll();
  if (s.folder && !s.summary) loadSummary(s.folder);
}

async function loadSummary(folder) {
  try {
    s.summary = (await call(`/archive/summary?folder=${encodeURIComponent(folder)}`)).summary;
  } catch { s.summary = null; }
  s.plan = null;
  render();
  if (s.summary) loadMoves(folder);
}

async function loadMoves(folder) {
  try {
    s.moves = await call(`/archive/moves?folder=${encodeURIComponent(folder)}`);
    if (!s.dest || s.destFor !== folder) Object.assign(s, { dest: s.moves.default_dest || "", destFor: folder });
  } catch { s.moves = null; }
  render();
}

// A thumbnail carries its image's recipe and workflow: open it in the Recipes tab.
async function openAsRecipe(url, file) {
  try {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const name = (file || "image").split("/").pop().replace(/\.[^.]+$/, "") + ".webp";
    await window.ModelLibrarian.openFile(new File([await res.blob()], name, { type: "image/webp" }));
  } catch (e) {
    toast("error", "Open as recipe", e.message, 6000);
  }
}

async function previewMove() {
  try {
    s.plan = await call("/archive/move-plan", { method: "POST", body: { folder: s.summary.folder, dest: s.dest } });
  } catch (e) {
    s.plan = null;
    toast("warn", "Move originals", e.message, 7000);
  }
  render();
}

const sameFolder = (a, b) => String(a || "").trim().replace(/^"|"$/g, "").replace(/[\\/]+$/, "").toLowerCase()
  === String(b || "").trim().replace(/^"|"$/g, "").replace(/[\\/]+$/, "").toLowerCase();

async function startMove() {
  const p = s.plan;
  if (!p?.count || s.moving) return;
  if (!confirm(`Move ${p.count} original file${p.count === 1 ? "" : "s"} (${fmtSize(p.bytes)}) to\n${p.dest}?\n\n` +
    "Subfolders are kept, the archive keeps listing them, and you can undo this afterwards.")) return;
  s.moving = true;
  render();
  try {
    s.job = await call("/archive/move", { method: "POST", body: { folder: s.summary.folder, dest: p.dest } });
    s.plan = null;
    render();
    poll();
  } catch (e) {
    toast("error", "Move originals", e.message, 7000);
  } finally {
    s.moving = false;
    render();
  }
}

async function undoMove(log) {
  if (!confirm(`Put back the ${log.count} file${log.count === 1 ? "" : "s"} moved to ${log.dest}?`)) return;
  try {
    s.job = await call("/archive/undo-move", { method: "POST", body: { folder: s.summary.folder, log: log.log } });
    render();
    poll();
  } catch (e) {
    toast("error", "Undo move", e.message, 7000);
  }
}

async function start() {
  const folder = s.folder.trim().replace(/^"|"$/g, "");
  if (!folder) return toast("warn", "Archive", "Type or paste the folder with your images.");
  try {
    s.job = await call("/archive/start", { method: "POST", body: { folder, ...s.opts } });
    remember(folder);
    s.summary = null;
    render();
    poll();
  } catch (e) {
    toast("error", "Archive", e.message, 7000);
  }
}

async function poll() {
  clearTimeout(s.timer);
  if (s.polling) return; // one chain at a time (mount and a click can both start one)
  s.polling = true;
  try {
    const prev = s.job?.status;
    s.job = await call("/archive/status");
    if (s.job.status === "running") s.timer = setTimeout(poll, 1000);
    else if (prev === "running") {
      const r = s.job.result;
      if (s.job.status === "cancelled" && (r?.kind === "move" || r?.kind === "undo")) {
        toast("warn", r.kind === "move" ? "Move stopped" : "Undo stopped",
          r.kind === "move" ? `${r.moved} files were moved before it stopped; Undo puts them back.` : `${r.restored} files were put back before it stopped.`, 8000);
        loadSummary(s.job.folder);
      } else if (s.job.status === "done" && r?.kind === "move") {
        toast(r.failed_count ? "warn" : "success", "Originals moved", `${r.moved} files (${fmtSize(r.bytes)}) → ${r.dest}` +
          (r.failed_count ? ` · ${r.failed_count} couldn't be moved: ${r.failed[0].error}` : ""), 8000);
        loadSummary(s.job.folder);
      } else if (s.job.status === "done" && r?.kind === "undo") {
        toast(r.failed_count ? "warn" : "success", "Move undone", `${r.restored} files are back` +
          (r.failed_count ? ` · ${r.failed_count} couldn't be: ${r.failed[0].error}` : ""), 8000);
        loadSummary(s.job.folder);
      } else if (s.job.status === "done") {
        if (sameFolder(r.folder, s.folder)) { // the folder box may show another folder by now
          s.summary = r;
          loadMoves(r.folder);
        }
        toast("success", "Archive written", `${r.images} images · ${r.families} prompt families`, 6000);
      } else if (s.job.status === "error") toast("error", "Archive", s.job.error, 8000);
    }
  } catch {}
  s.polling = false;
  render();
}

function options() {
  const o = s.opts;
  const chk = (key, label, title, disabled = false) => h("label.smf-check", { title },
    h("input", { type: "checkbox", checked: o[key], disabled, onchange: (e) => { o[key] = e.target.checked; render(); } }), " ", label);
  return h("div.smf-row.wrap", { style: { gap: "14px" } },
    chk("recursive", "Include subfolders", "One archive for the folder and everything under it"),
    chk("thumbs", "Thumbnails", "A 512 px WebP of every image (about 20 KB each)"),
    chk("embed", "Put each image's workflow in its thumbnail", "Drop a thumbnail onto ComfyUI to load that exact image's workflow (about 50 KB each)", !o.thumbs),
    h("label.smf-check", "Group prompts: ",
      h("select.smf-select", { onchange: (e) => (o.grouping = e.target.value) },
        [["similar", "Similar (a few words changed)"], ["loose", "Loose"], ["exact", "Exact only"]].map(([v, l]) => h("option", { value: v, selected: o.grouping === v }, l)))));
}

function progress() {
  const j = s.job;
  const pct = j.total ? Math.round((100 * j.done) / j.total) : 0;
  const el = (Date.now() / 1000 - j.started) || 1;
  const fresh = Math.max(0, (j.done || 0) - (j.reused || 0));
  const left = j.total && fresh > 20 ? Math.round(((j.total - j.done) * el) / fresh) : null;
  return h("div.smf-archive-run",
    h("div.smf-row", spinner(), h("b", { style: { marginLeft: "6px" } },
      j.phase === "grouping" ? "Grouping prompts…" : j.phase === "writing" ? "Writing the archive…"
        : j.phase === "moving" ? `Moving ${j.done} of ${j.total} originals` : j.phase === "restoring" ? `Putting back ${j.done} of ${j.total} files`
        : `Reading ${j.done} of ${j.total || "…"} images`),
      left != null && j.phase === "reading" ? h("span.smf-dim.small", ` · about ${left > 90 ? Math.round(left / 60) + " min" : left + " s"} left`) : null,
      h("span.smf-spacer"), h("button.smf-btn.small", { onclick: () => call("/archive/cancel", { method: "POST" }).then(poll) }, "Cancel")),
    h("div.smf-bar", h("div", { style: { width: pct + "%" } })),
    j.current ? h("div.smf-dim.small", j.current) : null,
    j.reused ? h("div.smf-dim.small", `${j.reused} unchanged since the last run (not read again)`) : null);
}

function results(r) {
  const thumb = (name) => apiUrl(`/archive/thumb?folder=${encodeURIComponent(r.folder)}&name=${name}`);
  const report = r.out_dir + (r.out_dir.includes("\\") ? "\\" : "/") + "report.md";
  return h("div",
    h("div.smf-row.wrap", { style: { gap: "6px", margin: "6px 0" } },
      pill(`${r.images} images`, "dim"), pill(`${r.with_meta} with generation data`, "ok"),
      pill(`${r.families} prompt families`, "src"), pill(`${r.variants} variants`, "dim"),
      r.no_meta ? pill(`${r.no_meta} without data`, "warn") : null,
      r.moved ? pill(`${r.moved} moved to another drive`, "src") : null,
      pill(`${fmtSize(r.original_mb * 1024 ** 2)} of images → ${fmtSize(r.archive_mb * 1024 ** 2)} archive`, "ok")),
    h("div.smf-row.wrap",
      h("code.small", r.out_dir), " ",
      h("button.smf-btn.small", { onclick: () => copy(r.out_dir, "Folder copied") }, "Copy folder"),
      h("button.smf-btn.small", { onclick: () => copy(report, "Report path copied") }, "Copy report path"),
      h("span.smf-dim.small", ` · written ${new Date(r.finished * 1000).toLocaleString()}`)),
    h("div.smf-dim.small", { style: { margin: "4px 0 10px" } },
      "report.md has every family, variant and image; images.csv opens in a spreadsheet. Drop any thumbnail from thumbs\\ onto ComfyUI to load that image's workflow, or click one here to open it as a recipe."),
    h("div.smf-archive-grid", (r.top || []).map((f) => h("div.smf-archive-fam",
      h("div.smf-archive-thumbs", f.thumbs.map((t, i) => h("img", { src: thumb(t), loading: "lazy", alt: "", title: `${(f.files || [])[i] || ""}\nClick to open as a recipe`,
        onclick: () => openAsRecipe(thumb(t), (f.files || [])[i]) }))),
      h("div.smf-archive-prompt", { title: f.base }, f.base || "(empty prompt)"),
      h("div.smf-dim.small", `${f.id} · ${f.count} image${f.count === 1 ? "" : "s"} · ${f.variants} variant${f.variants === 1 ? "" : "s"}`)))),
    r.families > (r.top || []).length ? h("div.smf-dim.small", `…and ${r.families - r.top.length} more families in report.md`) : null,
    moveSection());
}

// Optional: once archived, the originals can go to another drive; the archive keeps listing them.
function moveSection() {
  const logs = s.moves?.logs || [];
  const p = s.plan;
  const skipped = p ? [p.changed && `${p.changed} changed since the archive was written (run it again first)`,
    p.recent && `${p.recent} changed in the last 10 minutes`, p.conflicts && `${p.conflicts} already at the destination`].filter(Boolean) : [];
  const when = (n) => `${n.slice(0, 4)}-${n.slice(4, 6)}-${n.slice(6, 8)} ${n.slice(9, 11)}:${n.slice(11, 13)}`;
  return h("div.smf-archive-move",
    h("div.smf-row", h("button.smf-btn.small", { onclick: () => { s.showMove = !s.showMove; render(); } },
      (s.showMove ? "▾ " : "▸ ") + "Move the originals to another drive…"),
      logs.length ? h("span.smf-dim.small", ` ${logs.length} move${logs.length === 1 ? "" : "s"} can be undone`) : null),
    s.showMove ? h("div.smf-archive-movebox",
      h("div.smf-dim.small", "Frees space here: archived files move to the folder below (same subfolders, times kept) and stay listed in this archive with their thumbnails. Every move is logged and can be undone. Files changed in the last 10 minutes are left alone."),
      h("div.smf-row", h("input.smf-input", { value: s.dest, style: { flex: 1 }, placeholder: "e.g. R:\\ComfyUI-Archive\\outputs\\Text2Img",
        oninput: (e) => { s.dest = e.target.value; if (s.plan) { s.plan = null; s.root.querySelector(".smf-archive-plan")?.remove(); } },
        onkeydown: (e) => e.key === "Enter" && previewMove() }),
        h("button.smf-btn", { onclick: previewMove }, "Check")),
      !s.moves?.default_dest ? h("div.smf-dim.small", "Tip: set an archive drive in Settings and this fills in by itself.") : null,
      p ? h("div.smf-archive-plan",
        h("div", p.count ? h("b", `${p.count} file${p.count === 1 ? "" : "s"}, ${fmtSize(p.bytes)}`) : h("b", "Nothing to move"),
          p.count ? ` → ${p.dest}` : "", p.without_meta ? h("span.smf-dim.small", ` (${p.without_meta} without generation data)`) : null),
        skipped.length ? h("div.smf-dim.small", "Left in place: " + skipped.join(" · ")) : null,
        p.sample?.length ? h("div.smf-dim.small", p.sample.join(", ") + (p.count > p.sample.length ? ", …" : "")) : null,
        p.count ? h("div", h("button.smf-btn.primary", { onclick: startMove, disabled: s.moving }, `Move ${p.count} file${p.count === 1 ? "" : "s"}`)) : null) : null,
      logs.map((l) => h("div.smf-row.small", h("span.smf-dim", `${when(l.log)} · ${l.count} files (${fmtSize(l.bytes)}) → `),
        h("code", l.dest), h("span.smf-spacer"), h("button.smf-btn.small", { onclick: () => undoMove(l) }, "Undo")))) : null);
}

function render() {
  const root = s.root;
  if (!root || !root.isConnected) return;
  const running = s.job?.status === "running";
  const list = h("datalist", { id: "smf-archive-recent" }, recent().map((f) => h("option", { value: f })));
  const input = h("input.smf-input", { list: "smf-archive-recent", value: s.folder, style: { flex: 1 }, disabled: running,
    placeholder: "Folder with your images, e.g. E:\\StabilityMatrix\\Data\\Images\\Text2Img",
    oninput: (e) => (s.folder = e.target.value), onchange: (e) => loadSummary(e.target.value.trim()),
    onkeydown: (e) => e.key === "Enter" && start() });
  clear(root,
    h("div.smf-help", "Keep what made every image without keeping the images: point this at a folder and it writes ",
      h("code", "_ml_archive"), " inside it — a report grouped by prompt (similar prompts become variants of one family), a CSV, every recipe, a workflow per prompt variant and small thumbnails that carry their image's workflow. Only that folder is written; your images aren't touched unless you choose to move them to another drive afterwards."),
    h("div.smf-row", list, input,
      h("button.smf-btn.primary", { onclick: start, disabled: running }, s.summary && s.summary.folder === s.folder.trim() ? "Update archive" : "Archive this folder")),
    options(),
    running ? progress() : null,
    s.job?.status === "error" ? h("div.err", s.job.error) : null,
    s.job?.status === "cancelled" && !["move", "undo"].includes(s.job.result?.kind) ? h("div.smf-dim", "Stopped. What was read is kept; running it again carries on.") : null,
    !running && s.summary ? results(s.summary) : null,
    !running && !s.summary && s.folder ? h("div.smf-empty", "No archive for this folder yet.") : null);
}
