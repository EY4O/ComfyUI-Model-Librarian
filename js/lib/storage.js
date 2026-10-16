// "Storage" tab: SSD/HDD tiers. Models unused for N days are suggested for the
// archive drive (you approve); archived models stay usable under the same names
// and come back to the SSD after a workflow uses them.
import { call, ctx, h, clear, fmtSize, toast, pill, spinner, familyBadge, lmRescan } from "./util.js";
import { historySection } from "./storehist.js";

const s = { root: null, plan: null, job: null, selReady: new Set(), selArchived: new Set(), busy: false };
let jobTimer = null;

export function mount(root) {
  s.root = root;
  load();
}

async function load() {
  s.busy = true;
  render();
  try {
    s.plan = await call("/tiering/plan");
    s.selReady = new Set(s.plan.ready.map((x) => x.id));
    s.selArchived = new Set();
    s.job = await call("/tiering/job");
    if (s.job.status === "running") pollJob();
  } catch (e) {
    toast("error", "Storage", e.message);
  }
  s.busy = false;
  render();
}

async function start(kind, ids) {
  if (!ids.length) return;
  const items = (kind === "archive" ? s.plan.ready : s.plan.archived).filter((x) => ids.includes(x.id));
  const bytes = items.reduce((a, x) => a + x.size, 0);
  const msg = kind === "archive"
    ? `Move ${ids.length} model(s), ${fmtSize(bytes)}, to the archive drive?\n\nEach copy is verified before the SSD file is removed. They stay usable under the same names (loading is slower from the HDD) and come back to the SSD when a workflow uses them. Undo is in Organize → History.`
    : `Bring ${ids.length} model(s), ${fmtSize(bytes)}, back to the SSD?`;
  if (!confirm(msg)) return;
  try {
    s.job = await call(`/tiering/${kind}`, { method: "POST", body: { ids } });
    pollJob();
  } catch (e) {
    toast("warn", "Not started", e.message, 6000);
  }
  render();
}

async function pollJob() {
  clearTimeout(jobTimer);
  try {
    const prev = s.job?.status;
    s.job = await call("/tiering/job");
    if (s.job.status === "running") jobTimer = setTimeout(pollJob, 1000);
    else if (prev === "running") {
      const j = s.job;
      const fail = (j.results || []).filter((r) => !r.ok);
      toast(fail.length ? "warn" : "success", j.kind === "archive" ? "Archived" : "Restored",
        `${j.ok || 0} model(s)` + (fail.length ? ` · ${fail.length} skipped: ${fail[0].error}` : ""), 9000);
      lmRescan();
      try { await ctx.app.refreshComboInNodes?.(); } catch {}
      return load();
    }
  } catch {}
  render();
}

function days(t) {
  if (!t) return "never (since it was first seen)";
  const d = (Date.now() / 1000 - t) / 86400;
  return d < 1 ? "today" : `${Math.floor(d)} days ago`;
}

function table(items, sel, extra) {
  const all = items.length && items.every((x) => sel.has(x.id));
  return h("table.smf-table",
    h("tr",
      h("th", h("input", { type: "checkbox", checked: all, onchange: (e) => { items.forEach((x) => e.target.checked ? sel.add(x.id) : sel.delete(x.id)); render(); } })),
      h("th", "Model"), h("th", "Size"), h("th", "Last used"), h("th", "")),
    items.map((x) => h("tr",
      h("td", h("input", { type: "checkbox", checked: sel.has(x.id), onchange: (e) => { e.target.checked ? sel.add(x.id) : sel.delete(x.id); render(); } })),
      h("td", h("b", x.title || x.name), " ", x.family ? familyBadge(x.family) : null,
        x.reason === "goal" ? [" ", pill("for free-space goal", "warn", "Suggested because the SSD is below your free-space goal (least recently used first)")] : null,
        h("div.smf-dim.small", `${x.section} · ${x.rel}`)),
      h("td.small", fmtSize(x.size)),
      h("td.small.smf-dim", days(x.last_used)),
      h("td", extra?.(x)))));
}

// The SSD's free space against the goal (Settings → Storage tiers).
function goalLine(p) {
  const g = p.goal;
  if (!g) return null;
  if (!g.goal) return h("div.smf-dim.small", `SSD (${g.drive}): ${fmtSize(g.free)} free · set a free-space goal in Settings → Storage tiers to get suggestions when it runs low.`);
  const below = g.free < g.goal;
  return h("div.smf-toolbar",
    pill(`SSD ${fmtSize(g.free)} free`, below ? "bad" : "ok", g.drive), " ",
    h("span", `goal ${fmtSize(g.goal)}`),
    below
      ? h("span.smf-dim.small", g.reachable
        ? ` · archiving the suggestions below leaves ${fmtSize(g.after)} free${g.picked ? ` (${g.picked} added for the goal, least recently used first)` : ""}`
        : ` · even archiving every model not used in the last ${g.protect_days} days leaves ${fmtSize(g.after)} free — lower the goal or the protection period in Settings`)
      : h("span.smf-dim.small", " · met"));
}

// Once per session: say so when the SSD is below the free-space goal.
export async function checkGoal() {
  try {
    if (!ctx.status?.config?.archive_dir || !ctx.status?.config?.free_goal_gb) return;
    if (sessionStorage.getItem("smf-goal-told")) return;
    const p = await call("/tiering/plan");
    const g = p.goal;
    if (!g?.goal || g.free >= g.goal || !p.ready.length) return;
    sessionStorage.setItem("smf-goal-told", "1");
    toast("warn", "SSD below your free-space goal", `${fmtSize(g.free)} free (goal ${fmtSize(g.goal)}). Library → Storage suggests ${p.ready.length} model(s), ${fmtSize(p.ready_bytes)}.`, 12000);
  } catch {}
}

function render() {
  const root = s.root;
  if (!root || !root.isConnected) return;
  const p = s.plan;
  const intro = h("div.smf-help",
    "Keeps the SSD for models you use. Models unused for a while are suggested for an archive folder (e.g. an external HDD); ",
    "they stay usable under the same names (the first load is slower) and move back to the SSD after a workflow uses them.");
  if (s.busy && !p) return clear(root, intro, h("div.smf-empty", spinner(), " Checking…"));
  if (!p?.archive_dir) {
    return clear(root, intro, h("div.smf-empty", "Choose an archive folder in ", h("b", "Settings → Storage tiers"), " to start (for example ", h("code", "F:\\SMF-Archive"), ")."),
      historySection());
  }
  const j = s.job;
  const running = j?.status === "running";
  const sel = (items, set) => items.filter((x) => set.has(x.id));
  const readySel = sel(p.ready, s.selReady), archSel = sel(p.archived, s.selArchived);
  const bytes = (xs) => fmtSize(xs.reduce((a, x) => a + x.size, 0));
  clear(root,
    intro,
    h("div.smf-toolbar",
      h("span", "Archive: ", h("code", p.archive_dir), " "),
      p.connected ? pill(`connected · ${p.free != null ? fmtSize(p.free) + " free" : "?"}`, "ok") : pill("drive not connected", "bad"),
      h("span.smf-dim.small", ` · suggests models unused for ${p.after_days} days · `,
        p.restore_on_use ? "brings models back after use" : "automatic bring-back is off"),
      p.queued_restores ? pill(`${p.queued_restores} waiting to come back`, "warn", "Moves back to the SSD once the queue is idle") : null,
      h("span.smf-spacer"),
      h("button.smf-btn.small", { onclick: load, disabled: running }, "Refresh")),
    running ? h("div.smf-toolbar",
      h("div.smf-bar.inline", h("div", { style: { width: (j.total_bytes ? (100 * j.done_bytes) / j.total_bytes : 0) + "%" } })),
      h("span.smf-dim.small", `${j.kind === "archive" ? "Archiving" : "Restoring"} ${j.done}/${j.total} · ${fmtSize(j.done_bytes || 0)} of ${fmtSize(j.total_bytes || 0)} · ${j.current || ""}`)) : null,
    goalLine(p),
    h("h3", `Ready to archive — ${p.ready.length} model(s), ${fmtSize(p.ready_bytes)}`),
    p.ready.length
      ? [h("div.smf-toolbar", h("button.smf-btn.primary", { disabled: running || !p.connected || !readySel.length, onclick: () => start("archive", readySel.map((x) => x.id)) },
          `Move ${readySel.length} to the archive (${bytes(readySel)})`)),
        table(p.ready, s.selReady)]
      : h("div.smf-dim", `Nothing unused for ${p.after_days} days. Models never seen in a run count from when the extension first saw them.`),
    h("h3", { style: { marginTop: "16px" } }, `On the archive drive — ${p.archived.length} model(s), ${fmtSize(p.archived_bytes)}`),
    p.archived.length
      ? [h("div.smf-toolbar", h("button.smf-btn", { disabled: running || !p.connected || !archSel.length, onclick: () => start("restore", archSel.map((x) => x.id)) },
          `Bring ${archSel.length} back to the SSD (${bytes(archSel)})`)),
        table(p.archived, s.selArchived)]
      : h("div.smf-dim", "Nothing archived yet."),
    historySection());
}

// Background: automatic restores happen server-side; tell LoRA Manager and the user.
let since = Date.now() / 1000;
export function startEventPolling() {
  setInterval(async () => {
    if (!ctx.status?.config?.archive_dir) return;
    try {
      const r = await call(`/tiering/events?since=${since}`);
      since = r.now;
      const restored = r.events.filter((e) => e.kind === "restored" && e.auto);
      if (restored.length) {
        lmRescan([...new Set(restored.map((e) => e.section).filter(Boolean))]);
        toast("info", "Back on the SSD", restored.map((e) => e.name).join(", "), 6000);
      }
      const errs = r.events.filter((e) => e.kind === "error" && /after use/.test(e.error || ""));
      if (errs.length) toast("warn", "Couldn't bring back", `${errs[0].name}: ${errs[0].error}`, 8000);
    } catch {}
  }, 20000);
}
