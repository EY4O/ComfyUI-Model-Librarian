// Storage → History: free space per drive over time (one line per drive, the
// free-space goal as a reference line) and what the storage tiers moved each
// day (archived above the baseline, brought back below). Two charts, one axis each.
import { call, h, clear, fmtSize, spinner } from "./util.js";

const NS = "http://www.w3.org/2000/svg";
const DRIVE_COLORS = ["var(--viz-s1)", "var(--viz-s2)", "var(--viz-s3)"]; // fixed order, by drive
const DAY = 86400;

// ---------------------------------------------------------------- data (no DOM)
// samples [{t, drives: {label: {role, free, total}}}] -> [{label, role, points: [[t, free]]}] in drive order
export function seriesOf(samples, drives = []) {
  const order = drives.map((d) => d.label);
  const by = new Map();
  for (const s of samples || []) {
    for (const [label, d] of Object.entries(s.drives || {})) {
      if (!by.has(label)) by.set(label, { label, role: d.role, points: [] });
      by.get(label).points.push([s.t, d.free]);
    }
  }
  const rank = (l) => (order.includes(l) ? order.indexOf(l) : 99);
  return [...by.values()].sort((a, b) => rank(a.label) - rank(b.label) || a.label.localeCompare(b.label));
}

// moves [{day: "YYYY-MM-DD", archived, restored, archived_n, restored_n}] -> one entry per day of the range
export function dailyMoves(moves, days, now = Date.now() / 1000) {
  const by = new Map((moves || []).map((m) => [m.day, m]));
  const out = [];
  for (let i = days - 1; i >= 0; i--) {
    const d = new Date((now - i * DAY) * 1000);
    const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const m = by.get(key) || {};
    out.push({ day: key, t: Math.floor(d.setHours(12, 0, 0, 0) / 1000), archived: m.archived || 0, restored: m.restored || 0,
      archived_n: m.archived_n || 0, restored_n: m.restored_n || 0 });
  }
  return out;
}

// A round axis maximum (in bytes) with 4 even steps.
// (in GB, or TB from 1000 GB up, so the labels come out round)
export function niceMax(v) {
  if (!(v > 0)) return 1024 ** 3;
  const unit = v >= 1000 * 1024 ** 3 ? 1024 ** 4 : 1024 ** 3;
  const x = v / unit;
  const step = [1, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 10].map((m) => m * 10 ** Math.floor(Math.log10(x / 4))).find((s) => s * 4 >= x) || x / 4;
  return step * 4 * unit;
}

const gbLabel = (b) => {
  const g = b / 1024 ** 3;
  if (g < 1000) return `${Math.round(g)} GB`;
  const t = g / 1024;
  return `${Number.isInteger(Math.round(t * 100) / 100) ? Math.round(t) : t.toFixed(t < 10 ? 2 : 1).replace(/0$/, "")} TB`;
};
const dateLabel = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric" });

// ---------------------------------------------------------------- drawing
function svg(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) if (v != null) el.setAttribute(k, v);
  for (const k of kids.flat()) if (k != null) el.append(k);
  return el;
}

// a bar with a 4px rounded end away from the baseline
function barPath(x, w, y0, y1) {
  const r = Math.min(4, w / 2, Math.abs(y1 - y0));
  if (y1 < y0) return `M${x},${y0}V${y1 + r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 + r}V${y0}Z`;
  return `M${x},${y0}V${y1 - r}Q${x},${y1} ${x + r},${y1}H${x + w - r}Q${x + w},${y1} ${x + w},${y1 - r}V${y0}Z`;
}

function tooltip(wrap) {
  const tip = h("div.smf-viz-tip", { style: { display: "none" } });
  wrap.append(tip);
  return {
    show(x, y, kids) {
      clear(tip, kids);
      tip.style.display = "";
      const w = wrap.clientWidth;
      tip.style.left = Math.min(Math.max(x + 12, 0), w - tip.offsetWidth - 4) + "px";
      tip.style.top = Math.max(y - tip.offsetHeight - 8, 0) + "px";
    },
    hide() { tip.style.display = "none"; },
  };
}

// One panel per drive, each on its own scale (a 4 TB archive drive would flatten
// a 1 TB SSD's line on a shared axis); the same time axis for all of them.
function freePanel(hist, s, i, width, tStart) {
  const color = DRIVE_COLORS[i] || DRIVE_COLORS[2];
  const W = width, H = 150, m = { l: 56, r: 120, t: 10, b: 22 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const t1 = hist.now;
  const goal = s.role === "models" ? hist.goal : null;
  const ymax = niceMax(Math.max(goal || 0, ...s.points.map((p) => p[1])) * 1.08);
  const x = (t) => m.l + ((t - tStart) / Math.max(1, t1 - tStart)) * pw;
  const y = (b) => m.t + ph - (b / ymax) * ph;
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": `Free space on ${s.label} over time` });
  for (let k = 0; k <= 4; k += 2) {
    const v = (ymax / 4) * k;
    root.append(svg("line", { x1: m.l, x2: m.l + pw, y1: y(v), y2: y(v), class: "smf-viz-grid" }),
      svg("text", { x: m.l - 6, y: y(v) + 4, "text-anchor": "end", class: "smf-viz-axis" }, gbLabel(v)));
  }
  const span = t1 - tStart, step = span > 60 * DAY ? 14 * DAY : span > 20 * DAY ? 7 * DAY : span > 4 * DAY ? DAY * 2 : DAY;
  for (let t = Math.ceil(tStart / step) * step; t <= t1; t += step) {
    root.append(svg("text", { x: x(t), y: H - 6, "text-anchor": "middle", class: "smf-viz-axis" }, dateLabel(t)));
  }
  if (goal) {
    root.append(svg("line", { x1: m.l, x2: m.l + pw, y1: y(goal), y2: y(goal), class: "smf-viz-ref" }),
      svg("text", { x: m.l + 4, y: y(goal) - 5, class: "smf-viz-axis" }, `free-space goal ${gbLabel(goal)}`));
  }
  const pts = s.points;
  root.append(svg("path", { d: pts.map((p, k) => `${k ? "L" : "M"}${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(""),
    fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }));
  const [lt, lf] = pts[pts.length - 1];
  root.append(svg("circle", { cx: x(lt), cy: y(lf), r: 4, fill: color, class: "smf-viz-ring" }),
    svg("text", { x: x(lt) + 9, y: y(lf) + 4, class: "smf-viz-label" }, `${fmtSize(lf)} free`));
  const cross = svg("line", { y1: m.t, y2: m.t + ph, class: "smf-viz-cross", visibility: "hidden" });
  const dot = svg("circle", { r: 4, fill: color, class: "smf-viz-ring", visibility: "hidden" });
  const hit = svg("rect", { x: m.l, y: m.t, width: pw, height: ph, fill: "transparent" });
  root.append(cross, dot, hit);
  const wrap = h("div.smf-viz-wrap", root);
  const tip = tooltip(wrap);
  hit.addEventListener("mousemove", (ev) => {
    const r = root.getBoundingClientRect();
    const t = tStart + ((((ev.clientX - r.left) / r.width) * W - m.l) / pw) * (t1 - tStart);
    const p = pts.reduce((a, q) => (Math.abs(q[0] - t) < Math.abs(a[0] - t) ? q : a), pts[0]);
    for (const [el, k] of [[cross, "x1"], [cross, "x2"], [dot, "cx"]]) el.setAttribute(k, x(p[0]));
    dot.setAttribute("cy", y(p[1]));
    cross.setAttribute("visibility", "visible");
    dot.setAttribute("visibility", "visible");
    tip.show((x(p[0]) / W) * r.width, ev.clientY - r.top, [
      h("div.smf-viz-tip-head", new Date(p[0] * 1000).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })),
      h("div.smf-viz-tip-row", h("span.smf-viz-sw", { style: { background: color } }), `${s.label} free`, h("b", fmtSize(p[1])))]);
  });
  hit.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); dot.setAttribute("visibility", "hidden"); tip.hide(); });
  return [h("div.smf-viz-legend", h("span", h("span.smf-viz-sw", { style: { background: color } }),
    h("b", s.label), ` ${s.role === "archive" ? "archive drive" : "models drive"}`)), wrap];
}

function freeChart(hist, width) {
  const series = seriesOf(hist.samples, hist.drives);
  const first = Math.min(...series.flatMap((s) => s.points.map((p) => p[0])), hist.now);
  const tStart = Math.max(hist.now - hist.days * DAY, first - DAY); // a new install: don't stretch two samples over 90 days of nothing
  return series.map((s, i) => freePanel(hist, s, i, width, tStart));
}

function movesChart(hist, width) {
  const days = dailyMoves(hist.moves, Math.min(hist.days, 60), hist.now);
  const W = width, H = 150, m = { l: 52, r: 120, t: 10, b: 22 };
  const pw = W - m.l - m.r, ph = H - m.t - m.b;
  const peak = Math.max(1, ...days.map((d) => Math.max(d.archived, d.restored)));
  const ymax = niceMax(peak); // each half (archived up, brought back down) runs 0..ymax
  const mid = m.t + ph / 2;
  const y = (b) => (b / ymax) * (ph / 2);
  const slot = pw / days.length, bw = Math.max(1, slot - 2); // 2px gap between bars
  const root = svg("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H, role: "img", "aria-label": "Gigabytes moved per day" });
  root.append(svg("line", { x1: m.l, x2: m.l + pw, y1: mid, y2: mid, class: "smf-viz-base" }),
    svg("text", { x: m.l - 6, y: m.t + 9, "text-anchor": "end", class: "smf-viz-axis" }, gbLabel(ymax)),
    svg("text", { x: m.l - 6, y: m.t + ph, "text-anchor": "end", class: "smf-viz-axis" }, gbLabel(ymax)),
    svg("text", { x: m.l + pw + 8, y: m.t + 12, class: "smf-viz-label" }, "to the archive ↑"),
    svg("text", { x: m.l + pw + 8, y: m.t + ph - 2, class: "smf-viz-label" }, "back to SSD ↓"));
  days.forEach((d, i) => {
    if (i % 14 === 0) root.append(svg("text", { x: m.l + i * slot + slot / 2, y: H - 5, "text-anchor": "middle", class: "smf-viz-axis" }, dateLabel(d.t)));
  });
  const wrap = h("div.smf-viz-wrap", root);
  const tip = tooltip(wrap);
  days.forEach((d, i) => {
    const bx = m.l + i * slot + 1;
    if (d.archived) root.append(svg("path", { d: barPath(bx, bw, mid - 1, mid - 1 - y(d.archived)), fill: "var(--viz-arch)" }));
    if (d.restored) root.append(svg("path", { d: barPath(bx, bw, mid + 1, mid + 1 + y(d.restored)), fill: "var(--viz-rest)" }));
    const hit = svg("rect", { x: m.l + i * slot, y: m.t, width: slot, height: ph, fill: "transparent" });
    hit.addEventListener("mousemove", (ev) => {
      const r = root.getBoundingClientRect();
      tip.show(ev.clientX - r.left, ev.clientY - r.top, [
        h("div.smf-viz-tip-head", new Date(d.t * 1000).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" })),
        h("div.smf-viz-tip-row", h("span.smf-viz-sw", { style: { background: "var(--viz-arch)" } }), "to the archive", h("b", d.archived ? `${fmtSize(d.archived)} · ${d.archived_n}` : "—")),
        h("div.smf-viz-tip-row", h("span.smf-viz-sw", { style: { background: "var(--viz-rest)" } }), "back to SSD", h("b", d.restored ? `${fmtSize(d.restored)} · ${d.restored_n}` : "—"))]);
    });
    hit.addEventListener("mouseleave", () => tip.hide());
    root.append(hit);
  });
  const total = (k) => days.reduce((a, d) => a + d[k], 0);
  return [h("div.smf-viz-legend",
    h("span", h("span.smf-viz-sw", { style: { background: "var(--viz-arch)" } }), `Archived · ${fmtSize(total("archived"))}`),
    h("span", h("span.smf-viz-sw", { style: { background: "var(--viz-rest)" } }), `Brought back · ${fmtSize(total("restored"))}`),
    h("span.smf-dim", `last ${days.length} days`)), wrap];
}

function tableView(hist) {
  const series = seriesOf(hist.samples, hist.drives);
  const perDay = new Map();
  for (const s of hist.samples) perDay.set(new Date(s.t * 1000).toDateString(), s); // the day's last sample
  const rows = [...perDay.values()].reverse().slice(0, 60);
  return h("details.smf-viz-table", h("summary", "Show as a table"),
    h("table.smf-table", h("tr", h("th", "Date"), series.map((s) => h("th", `${s.label} free`))),
      rows.map((r) => h("tr", h("td.small", dateLabel(r.t)), series.map((s) => h("td.small", r.drives[s.label] ? fmtSize(r.drives[s.label].free) : ""))))));
}

let cached = null;

export function historySection() {
  const box = h("div.smf-viz", h("div.smf-dim", spinner(), " Loading history…"));
  const draw = async () => {
    let hist;
    try {
      // the Storage tab re-renders every second during a move; the history changes every 6 hours
      if (!cached || Date.now() - cached.at > 60000) cached = { at: Date.now(), hist: await call("/storage/history?days=90") };
      hist = cached.hist;
    } catch (e) {
      return clear(box, h("span.err.small", e.message));
    }
    const width = Math.max(480, Math.min(1100, (box.clientWidth || 760) - 4));
    const enough = hist.samples.length >= 2;
    clear(box,
      h("div.smf-viz-title", "Free space"),
      enough ? freeChart(hist, width)
        : h("div.smf-dim.small", "Collecting: a sample is taken every 6 hours while ComfyUI runs, so the chart fills in over the next days. ",
          seriesOf(hist.samples, hist.drives).map((s) => h("span", ` ${s.label} ${s.role}: ${fmtSize(s.points[s.points.length - 1][1])} free.`))),
      hist.moves.length ? [h("div.smf-viz-title", "Moved by the storage tiers"), movesChart(hist, width)] : null,
      enough ? tableView(hist) : null);
  };
  setTimeout(draw, 30); // once the section is on the page, so its width can be measured
  return h("section.smf-history", h("h3", { style: { marginTop: "16px" } }, "History"), box);
}
