// "Organize" + "Duplicates" tabs.
import { call, ctx, h, clear, fmtSize, toast, pill, spinner, familyBadge, confPill, apiUrl, lmRescan } from "./util.js";

const o = { root: null, sections: new Set(["loras"]), mode: "loose", plan: null, busy: false, history: [], showUnknown: false };
const d = { root: null, sections: new Set(["loras", "checkpoints", "diffusion_models"]), status: null, selected: new Set() };
let dupTimer = null;

function sectionPicker(set, onchange) {
  const sections = ctx.status?.sections || {};
  return h("div.smf-row.wrap", Object.entries(sections).map(([k, label]) =>
    h("label.smf-check", h("input", { type: "checkbox", checked: set.has(k),
      onchange: (ev) => { ev.target.checked ? set.add(k) : set.delete(k); onchange?.(); } }), " ", label)));
}

// ================================================================ Organize
export function mountOrganize(root) {
  o.root = root;
  loadHistory().then(renderOrganize);
}

async function loadHistory() {
  try {
    o.history = (await call("/organize/history")).runs;
  } catch {
    o.history = [];
  }
}

async function buildPlan() {
  o.busy = true;
  o.plan = null;
  renderOrganize();
  try {
    o.plan = await call("/organize/plan", { method: "POST", body: { sections: [...o.sections], mode: o.mode } });
  } catch (e) {
    toast("error", "Plan failed", e.message);
  }
  o.busy = false;
  renderOrganize();
}

async function applyPlan() {
  const items = o.plan.moves.filter((m) => m.checked).map((m) => ({ id: m.id, to_rel: m.to_rel }));
  if (!items.length) return;
  if (!confirm(`Move ${items.length} model(s) (with their preview/metadata files)?\n\nYou can undo this afterwards.`)) return;
  o.busy = true;
  renderOrganize();
  try {
    const r = await call("/organize/apply", { method: "POST", body: { items } });
    toast(r.failed ? "warn" : "success", "Organized", `${r.moved} moved${r.failed ? `, ${r.failed} skipped` : ""}`, 6000);
    const failed = r.results.filter((x) => !x.ok);
    if (failed.length) console.warn("[SM Model Fetcher] skipped:", failed);
    o.lastResult = r;
    if (r.moved) lmRescan([...new Set(r.results.filter((x) => x.ok).map((x) => x.section))]);
    try { await ctx.app.refreshComboInNodes?.(); } catch {}
  } catch (e) {
    toast("error", "Move failed", e.message);
  }
  o.busy = false;
  await loadHistory();
  await buildPlan();
}

async function undo(runId) {
  if (!confirm("Undo this run and move the files back?")) return;
  let r;
  try {
    r = await call("/organize/undo", { method: "POST", body: { run_id: runId } });
  } catch (e) {
    return toast("warn", "Undo not run", e.message, 6000);
  }
  if (r.ok) toast("success", "Undone", `${r.restored} file(s) restored${r.failed.length ? `, ${r.failed.length} could not be restored` : ""}`);
  else toast("error", "Undo failed", r.error);
  if (r.restored) lmRescan(); // the log doesn't record sections; rescan all LM types
  try { await ctx.app.refreshComboInNodes?.(); } catch {}
  await loadHistory();
  o.plan = null;
  renderOrganize();
}

function setAll(pred) {
  o.plan.moves.forEach((m) => (m.checked = !m.conflict && pred(m)));
  renderOrganize();
}

function moveRow(m) {
  const target = h("select.smf-select", {
    onchange: (ev) => {
      const v = ev.target.value;
      if (v === "__custom") {
        const name = prompt("Folder name:", m.target_folder);
        if (!name) return renderOrganize();
        m.target_folder = name.replace(/[\\/:*?"<>|]/g, "").trim();
      } else m.target_folder = v;
      const parts = m.to_rel.split("/");
      parts[0] = m.target_folder;
      m.to_rel = parts.join("/");
      renderOrganize();
    },
  }, [...new Set([m.target_folder, ...o.plan.folders])].map((f) => h("option", { value: f, selected: f === m.target_folder }, f)),
  h("option", { value: "__custom" }, "Custom…"));
  return h("tr" + (m.checked ? "" : ".off"),
    h("td", h("input", { type: "checkbox", checked: m.checked, disabled: !!m.conflict, onchange: (ev) => { m.checked = ev.target.checked; renderSummary(); } })),
    h("td.thumb", m.has_preview ? h("img", { src: apiUrl(`/preview/${m.id}`), loading: "lazy" }) : null),
    h("td",
      h("div", h("b", m.title || m.name)),
      h("div.smf-dim.small", m.root_name + "/" + m.from_rel)),
    h("td", familyBadge(m.family, m.badge), " ", confPill(m.confidence), h("div.smf-dim.small", m.evidence)),
    h("td", "→ ", target, h("div.smf-dim.small", m.to_rel), m.conflict ? h("div.err.small", m.conflict) : null),
    h("td.small.smf-dim", m.reason));
}

let summaryEl;
function renderSummary() {
  if (!summaryEl || !o.plan) return;
  const n = o.plan.moves.filter((m) => m.checked).length;
  clear(summaryEl,
    pill(`${o.plan.moves.length} to sort`, "warn"), " ",
    pill(`${o.plan.already_sorted} already sorted`, "ok"), " ",
    o.plan.unknown.length ? pill(`${o.plan.unknown.length} unknown`, "dim") : null,
    h("span.smf-spacer"),
    h("button.smf-btn.small", { onclick: () => setAll(() => true) }, "All"),
    h("button.smf-btn.small", { onclick: () => setAll((m) => m.confidence === "high") }, "High only"),
    h("button.smf-btn.small", { onclick: () => setAll((m) => m.confidence !== "low") }, "High + medium"),
    h("button.smf-btn.small", { onclick: () => setAll(() => false) }, "None"),
    h("button.smf-btn.primary", { disabled: !n || o.busy, onclick: applyPlan }, `Move ${n} file${n === 1 ? "" : "s"}`));
}

function renderOrganize() {
  const root = o.root;
  if (!root) return;
  const modeSel = h("div.smf-row",
    h("label.smf-check", h("input", { type: "radio", name: "smf-mode", checked: o.mode === "loose", onchange: () => { o.mode = "loose"; } }),
      " Loose files only ", h("span.smf-dim.small", "(files sitting in the folder root)")),
    h("label.smf-check", h("input", { type: "radio", name: "smf-mode", checked: o.mode === "full", onchange: () => { o.mode = "full"; } }),
      " Full review ", h("span.smf-dim.small", "(re-check every subfolder, fix misplaced models)")));
  const intro = h("div.smf-help",
    "Sorts models into base-model folders (",
    h("code", "Lora/Illustrious"), ", ", h("code", "Lora/Pony"), ", ", h("code", "DiffusionModels/Qwen"),
    "…). Evidence used: CivitAI base model (from Stability Matrix / LoRA Manager metadata), LoRA training metadata, tensor layout, then file name. ",
    "Low-confidence guesses start unchecked. Custom sub-folders are kept underneath the family folder. Tip: run ",
    h("b", "Library → Fetch metadata"), " first for the most accurate results.");
  summaryEl = h("div.smf-toolbar");
  let body;
  if (o.busy) body = h("div.smf-empty", spinner(), " Working…");
  else if (!o.plan) body = h("div.smf-empty", "Choose folders and build a plan. Nothing moves until you confirm.");
  else if (!o.plan.moves.length) body = h("div.smf-empty", "Everything is already sorted 🎉");
  else body = h("table.smf-table.plan",
    h("tr", h("th", ""), h("th", ""), h("th", "Model"), h("th", "Detected"), h("th", "Target"), h("th", "Why")),
    o.plan.moves.map(moveRow));
  const unknown = o.plan?.unknown?.length
    ? h("details.smf-details", h("summary", `${o.plan.unknown.length} model(s) with unknown base model (left in place)`),
      h("div.smf-dim.small", o.plan.unknown.map((u) => h("div", u.rel))))
    : null;
  const hist = o.history.length
    ? h("details.smf-details", h("summary", "History / undo"),
      o.history.map((r) => h("div.smf-row",
        h("span", new Date(r.time * 1000).toLocaleString()), pill(r.kind, "dim"), h("span", `${r.count} model(s)`),
        h("button.smf-btn.small", { onclick: () => undo(r.id) }, "Undo"))))
    : null;
  clear(root,
    intro,
    h("div.smf-toolbar", sectionPicker(o.sections)),
    h("div.smf-toolbar", modeSel, h("span.smf-spacer"),
      h("button.smf-btn.primary", { onclick: buildPlan, disabled: o.busy }, "Build plan")),
    o.history.length ? h("div.smf-toolbar", h("span.smf-dim.small", "Last run: " + new Date(o.history[0].time * 1000).toLocaleString()),
      h("button.smf-btn.small", { onclick: () => undo(o.history[0].id) }, "Undo last run")) : null,
    o.plan ? summaryEl : null,
    h("div.smf-list", body, unknown, hist));
  renderSummary();
}

// ================================================================ Duplicates
export function mountDuplicates(root) {
  d.root = root;
  pollDup();
}

async function scanDup() {
  try {
    d.status = await call("/duplicates/scan", { method: "POST", body: { sections: [...d.sections] } });
  } catch (e) {
    return toast("warn", "Can't scan now", e.message, 6000);
  }
  renderDup();
  pollDup();
}

async function pollDup() {
  clearTimeout(dupTimer);
  try {
    const prev = d.status?.status;
    d.status = await call("/duplicates");
    if (d.status.status === "done" && prev !== "done") {
      d.selected = new Set(d.status.groups.flatMap((g) => g.duplicates.map((x) => x.id)));
    }
    renderDup();
    if (d.status.status === "running") dupTimer = setTimeout(pollDup, 1000);
  } catch {}
}

function swapKeep(g, dup) {
  g.duplicates = g.duplicates.filter((x) => x.id !== dup.id).concat([g.keep]);
  d.selected.delete(dup.id);
  d.selected.add(g.keep.id);
  g.keep = dup;
  renderDup();
}

async function quarantine() {
  const ids = [...d.selected];
  if (!ids.length) return;
  if (!confirm(`Move ${ids.length} duplicate file(s) to the _duplicates folder?\n\nNothing is deleted — check the folder and delete it yourself when you're happy. Undo is available in Organize → History.`)) return;
  let r;
  try {
    r = await call("/duplicates/quarantine", { method: "POST", body: { ids } });
  } catch (e) {
    return toast("warn", "Nothing moved", e.message, 6000);
  }
  toast("success", "Duplicates moved", `${r.moved} file(s) → ${r.quarantine || "_duplicates"}`, 8000);
  if (r.moved) lmRescan([...d.sections]);
  try { await ctx.app.refreshComboInNodes?.(); } catch {}
  scanDup();
}

function renderDup() {
  const root = d.root;
  if (!root) return;
  const s = d.status || { status: "idle" };
  let body;
  if (s.status === "running") {
    body = h("div.smf-empty",
      h("div", spinner(), ` ${s.phase === "hashing" ? "Hashing same-size files" : "Listing files"}… ${s.done}/${s.total}`),
      h("div.smf-bar", h("div", { style: { width: (s.total ? (100 * s.done) / s.total : 0) + "%" } })),
      h("div.smf-dim.small", s.current || ""));
  } else if (s.status === "done") {
    if (!s.groups.length) body = h("div.smf-empty", "No duplicates found 🎉");
    else {
      const sel = s.groups.flatMap((g) => g.duplicates).filter((x) => d.selected.has(x.id));
      const freed = sel.reduce((a, x) => a + x.size, 0);
      body = h("div",
        h("div.smf-toolbar",
          pill(`${s.groups.length} group(s)`, "warn"), " ", pill(`${fmtSize(s.wasted)} wasted`, "bad"),
          h("span.smf-spacer"),
          h("button.smf-btn.primary", { disabled: !sel.length, onclick: quarantine }, `Move ${sel.length} to _duplicates (frees ${fmtSize(freed)})`)),
        s.groups.map((g) => h("div.smf-dupgroup",
          h("div.smf-dim.small", `${fmtSize(g.size)} · sha256 ${g.sha256.slice(0, 12)}…`),
          h("div.smf-duprow.keep", pill("KEEP", "ok"), h("span", g.keep.root_name + "/" + g.keep.rel),
            g.keep.title ? h("span.smf-dim.small", " — " + g.keep.title) : null),
          g.duplicates.map((x) => h("div.smf-duprow",
            h("input", { type: "checkbox", checked: d.selected.has(x.id), onchange: (ev) => { ev.target.checked ? d.selected.add(x.id) : d.selected.delete(x.id); renderDup(); } }),
            h("span", x.root_name + "/" + x.rel),
            h("button.smf-btn.small.ghost", { onclick: () => swapKeep(g, x) }, "Keep this one instead"))))));
    }
  } else if (s.status === "error") body = h("div.smf-empty.err", s.error);
  else body = h("div.smf-empty", "Finds byte-identical copies (same SHA256), even under different names or in different folders. Only same-size files are hashed, so it's quick.");
  clear(root,
    h("div.smf-help", "Duplicates are moved to a ", h("code", "_duplicates"), " folder next to your shared Models folder — never deleted. ComfyUI and Stability Matrix ignore that folder."),
    h("div.smf-toolbar", sectionPicker(d.sections), h("span.smf-spacer"),
      h("button.smf-btn.primary", { onclick: scanDup, disabled: s.status === "running" }, "Scan for duplicates")),
    h("div.smf-list", body));
}
