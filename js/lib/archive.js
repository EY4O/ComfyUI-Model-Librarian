// "Archive" tab: point it at a folder of generated images (subfolders included) and it
// writes _ml_archive/ inside it: a report grouped by prompt family, a CSV, every recipe,
// one workflow per prompt variant, and small WebP thumbnails that carry their image's
// workflow (drop one onto ComfyUI to get that exact image back).
import { call, h, clear, fmtSize, toast, pill, spinner, copy, apiUrl } from "./util.js";

const RECENT = "smf.archiveFolders";
const s = { root: null, folder: "", job: null, summary: null, timer: null, opts: { recursive: true, thumbs: true, embed: true, grouping: "similar" } };

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
  render();
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
  try {
    const prev = s.job?.status;
    s.job = await call("/archive/status");
    if (s.job.status === "running") s.timer = setTimeout(poll, 1000);
    else if (prev === "running") {
      if (s.job.status === "done") {
        s.summary = s.job.result;
        toast("success", "Archive written", `${s.job.result.images} images · ${s.job.result.families} prompt families`, 6000);
      } else if (s.job.status === "error") toast("error", "Archive", s.job.error, 8000);
    }
  } catch {}
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
      j.phase === "grouping" ? "Grouping prompts…" : j.phase === "writing" ? "Writing the archive…" : `Reading ${j.done} of ${j.total || "…"} images`),
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
      pill(`${fmtSize(r.original_mb * 1024 ** 2)} of images → ${fmtSize(r.archive_mb * 1024 ** 2)} archive`, "ok")),
    h("div.smf-row.wrap",
      h("code.small", r.out_dir), " ",
      h("button.smf-btn.small", { onclick: () => copy(r.out_dir, "Folder copied") }, "Copy folder"),
      h("button.smf-btn.small", { onclick: () => copy(report, "Report path copied") }, "Copy report path"),
      h("span.smf-dim.small", ` · written ${new Date(r.finished * 1000).toLocaleString()}`)),
    h("div.smf-dim.small", { style: { margin: "4px 0 10px" } },
      "report.md has every family, variant and image; images.csv opens in a spreadsheet. Drop any thumbnail from thumbs\\ onto ComfyUI to load that image's workflow."),
    h("div.smf-archive-grid", (r.top || []).map((f) => h("div.smf-archive-fam",
      h("div.smf-archive-thumbs", f.thumbs.map((t) => h("img", { src: thumb(t), loading: "lazy", alt: "" }))),
      h("div.smf-archive-prompt", { title: f.base }, f.base || "(empty prompt)"),
      h("div.smf-dim.small", `${f.id} · ${f.count} image${f.count === 1 ? "" : "s"} · ${f.variants} variant${f.variants === 1 ? "" : "s"}`)))),
    r.families > (r.top || []).length ? h("div.smf-dim.small", `…and ${r.families - r.top.length} more families in report.md`) : null);
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
      h("code", "_ml_archive"), " inside it — a report grouped by prompt (similar prompts become variants of one family), a CSV, every recipe, a workflow per prompt variant and small thumbnails that carry their image's workflow. Only that folder is written; your images aren't touched."),
    h("div.smf-row", list, input,
      h("button.smf-btn.primary", { onclick: start, disabled: running }, s.summary && s.summary.folder === s.folder.trim() ? "Update archive" : "Archive this folder")),
    options(),
    running ? progress() : null,
    s.job?.status === "error" ? h("div.err", s.job.error) : null,
    s.job?.status === "cancelled" ? h("div.smf-dim", "Stopped. What was read is kept; running it again carries on.") : null,
    !running && s.summary ? results(s.summary) : null,
    !running && !s.summary && s.folder ? h("div.smf-empty", "No archive for this folder yet.") : null);
}
