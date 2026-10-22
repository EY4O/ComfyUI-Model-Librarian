// Tidy and Re-organize on the open ComfyUI canvas: reads the graph being shown (a subgraph when you're
// inside one), runs the layout (tidy.js / reorganize.js), writes the positions back and records one undo
// step (Ctrl+Z). Re-organize shows the new layout first, drawn over the canvas, to apply or cancel.
import { tidy, TITLE, SLOT } from "./tidy.js";
import { reorganize } from "./reorganize.js";

const rect = (r) => (r && r.length >= 4 ? [r[0], r[1], r[2], r[3]] : null);
const getLink = (graph, id) => (id == null ? null : graph.getLink?.(id) ?? (graph.links?.get ? graph.links.get(id) : graph.links?.[id]));

// A node's box is cached and refreshed when the canvas draws it: refresh it first (off-screen nodes
// may not have been drawn since they last moved or resized).
const refresh = (n, canvas) => { try { n.updateArea?.(canvas?.ctx); } catch {} };

function nodeBox(n) {
  const pos = n.pos || [0, 0], size = n.size || [0, 0];
  const b = rect(n.boundingRect) || [pos[0], pos[1] - TITLE, size[0] || 0, (size[1] || 0) + TITLE];
  return { x: b[0], y: b[1], w: b[2] || 0, h: b[3] || 0, dx: pos[0] - b[0], dy: pos[1] - b[1] };
}

function groupBox(g) {
  const b = rect(g._bounding) || rect(g.boundingRect) || [g.pos[0], g.pos[1], g.size[0], g.size[1]];
  return { x: b[0], y: b[1], w: b[2], h: b[3], pinned: !!(g.pinned || g.flags?.pinned) }; // a group pinned in ComfyUI stays put
}

function setGroup(g, b) {
  if (g._bounding && g._bounding.length >= 4) {
    g._bounding[0] = b.x; g._bounding[1] = b.y; g._bounding[2] = b.w; g._bounding[3] = b.h;
  } else {
    g.pos = [b.x, b.y];
    g.size = [b.w, b.h];
  }
}

// Set/Get nodes (KJNodes, Easy-Use): a value passed by name instead of a wire
function wireless(n) {
  const m = /^(?:easy )?(set|get)node$/i.exec(n.type || "");
  const name = m && n.widgets?.[0]?.value;
  return name ? { [m[1].toLowerCase() === "set" ? "sets" : "gets"]: String(name) } : {};
}

const selectedNodes = (canvas, nodes) => [...(canvas.selectedItems || Object.values(canvas.selected_nodes || {}))].filter((x) => nodes.includes(x));

// The layout for the graph on the canvas, without changing anything: -> {graph, nodes, groups, boxes, input, res}
// or null. mode "tidy" (compact: no distance limit) or "reorganize"; selectionOnly: just the selected nodes.
function plan(canvas, { selectionOnly = false, compact = false, mode = "tidy", sharedLoaders = false } = {}) {
  const graph = canvas.graph || canvas.getCurrentGraph?.();
  if (!graph) return null;
  const nodes = graph._nodes || graph.nodes || [];
  const groups = [...(graph._groups || graph.groups || [])]; // as they are now: a group deleted later can't shift the rest
  const selected = selectionOnly ? selectedNodes(canvas, nodes) : [];
  if (selectionOnly && selected.length < 2) return null;

  for (const n of nodes) refresh(n, canvas);
  const boxes = new Map(nodes.map((n) => [n.id, nodeBox(n)]));
  const input = {
    nodes: nodes.map((n) => {
      const b = boxes.get(n.id);
      return {
        id: n.id, x: b.x, y: b.y, w: b.w, h: b.h,
        pinned: !!(n.pinned || n.flags?.pinned), collapsed: !!n.flags?.collapsed,
        ...wireless(n),
        inputs: (n.inputs || []).map((inp, slot) => {
          const l = getLink(graph, inp.link);
          return l ? { slot, origin: l.origin_id, originSlot: l.origin_slot } : null;
        }).filter(Boolean),
      };
    }),
    groups: groups.map(groupBox),
    only: selectionOnly ? selected.map((n) => n.id) : null,
    compact,
    sharedLoaders,
  };
  const res = mode === "reorganize" ? reorganize(input) : tidy(input);
  return { graph, nodes, groups, boxes, input, res, count: input.only ? input.only.length : nodes.length };
}

// Write a plan's positions to the canvas (native reroute points follow the nodes their wire joins).
function applyPlan(canvas, { graph, nodes, groups, boxes, res }) {
  const deltas = new Map();
  for (const n of nodes) {
    const b = boxes.get(n.id), p = res.nodes.get(n.id);
    if (p) deltas.set(n.id, [p.x - b.x, p.y - b.y]);
  }
  for (const n of nodes) {
    const b = boxes.get(n.id), p = res.nodes.get(n.id);
    if (p && (p.x !== b.x || p.y !== b.y)) { n.pos = [p.x + b.dx, p.y + b.dy]; refresh(n, canvas); }
  }
  for (const g of res.groups) if (groups[g.index]) setGroup(groups[g.index], g);
  const reroutes = graph.reroutes instanceof Map ? [...graph.reroutes.values()] : [];
  for (const r of reroutes) {
    const ids = [...(r.linkIds || [])];
    const ds = ids.map((id) => getLink(graph, id)).filter(Boolean)
      .flatMap((l) => [deltas.get(l.origin_id), deltas.get(l.target_id)]).filter(Boolean);
    if (ds.length && r.pos) {
      const dx = ds.reduce((a, d) => a + d[0], 0) / ds.length, dy = ds.reduce((a, d) => a + d[1], 0) / ds.length;
      r.pos = [r.pos[0] + dx, r.pos[1] + dy];
    }
  }
  graph.change?.();
  canvas.setDirty?.(true, true);
}

// -> {moved, nodes}: lay out and write back in one go
export function tidyCanvas(canvas, opts = {}) {
  const p = plan(canvas, opts);
  if (!p) return { moved: 0, nodes: 0 };
  if (p.res.moved) applyPlan(canvas, p);
  return { moved: p.res.moved, nodes: p.count };
}

const captureUndo = (app) => {
  const tracker = app.extensionManager?.workflow?.activeWorkflow?.changeTracker;
  try {
    if (tracker?.captureCanvasState) tracker.captureCanvasState();
    else tracker?.checkState?.();
  } catch {}
};

const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;

// The Arrange menu (right-click on the canvas, the commands and the Workflow tab): each option named for what
// it does, with a hover hint. null is a separator.
export const ARRANGE = [
  { label: "Tidy in place", opts: {},
    hint: "Lines up and spaces the nodes roughly where they are: overlaps and big gaps gone, wires straightened. Ctrl+Z undoes it." },
  { label: "Tidy and pull in stragglers", opts: { compact: true },
    hint: "Like Tidy in place, but nodes far from what they connect to are brought in beside it." },
  null,
  { label: "Rebuild from connections", opts: { mode: "reorganize" },
    hint: "Lays the nodes out again from the wires, left to right, ignoring where they are now. Shows the new layout first, to apply or cancel." },
  { label: "Rebuild, shared models first", opts: { mode: "reorganize", sharedLoaders: true },
    hint: "Like Rebuild from connections, with the models several stages use (checkpoint, CLIP, VAE) kept together at the top-left." },
];
const arrangeName = ({ compact, mode, sharedLoaders }) => ARRANGE.find((a) => a && !!a.opts.compact === !!compact && (a.opts.mode || "tidy") === mode && !!a.opts.sharedLoaders === !!sharedLoaders)?.label || "Arrange";

// Tidy (or compact Tidy) with one undo step and a short summary; Re-organize shows its preview first. The undo
// step comes from ComfyUI's change tracker: it sees the new positions as one change, so Ctrl+Z puts everything back.
export function runTidy(app, toast, { selectionOnly = false, compact = false, mode = "tidy", sharedLoaders = false } = {}) {
  const canvas = app.canvas;
  if (!canvas) return;
  const name = arrangeName({ compact, mode, sharedLoaders });
  active?.cancel(); // a Rebuild preview still open would later apply over this
  const p = plan(canvas, { selectionOnly, compact, mode, sharedLoaders });
  if (!p || !p.count) return toast("info", name, selectionOnly ? "Select two or more nodes first." : "There's nothing to arrange here.", 3000);
  if (!p.res.moved) return toast("info", name, mode === "reorganize" ? "Already laid out." : "Already tidy.", 2500);
  if (mode === "reorganize") return preview(app, toast, p, name);
  applyPlan(canvas, p);
  captureUndo(app);
  toast("success", name, `${p.res.moved} of ${plural(p.count, "node")} moved · Ctrl+Z puts them back`, 4000);
}

// Zoom and scroll the canvas to show these x and y extents (default: every node in the shown graph). The
// canvas runs under ComfyUI's menu and side bar: keep clear of them, and of a bar at the bottom.
export function fitView(canvas, { xs, ys } = {}) {
  const ds = canvas?.ds;
  if (!ds) return;
  if (!xs) {
    xs = []; ys = [];
    for (const n of canvas.graph?._nodes ?? canvas.graph?.nodes ?? []) {
      refresh(n, canvas);
      const b = nodeBox(n);
      xs.push(b.x, b.x + b.w); ys.push(b.y, b.y + b.h);
    }
  }
  if (!xs.length) return;
  let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
  for (const v of xs) { x0 = Math.min(x0, v); x1 = Math.max(x1, v); }
  for (const v of ys) { y0 = Math.min(y0, v); y1 = Math.max(y1, v); }
  const el = canvas.canvas;
  const cw = el?.clientWidth || 1200, ch = el?.clientHeight || 800;
  const bx = x0 - 60, by = y0 - 60, bw = x1 - bx + 60, bh = y1 - by + 60;
  const M = { top: 90, bottom: 100, left: 70, right: 30 };
  const scale = Math.min(1, (cw - M.left - M.right) / bw, (ch - M.top - M.bottom) / bh);
  ds.scale = scale;
  ds.offset = [-bx + (M.left + (cw - M.left - M.right - bw * scale) / 2) / scale, -by + (M.top + (ch - M.top - M.bottom - bh * scale) / 2) / scale];
  canvas.setDirty?.(true, true);
}

// ---------------------------------------------------------------- Re-organize preview
// The new layout drawn over the dimmed canvas (boxes, wires and groups where they'd go; the nodes that move
// outlined), with a bar to apply it or cancel. Apply writes exactly what's shown.
let active = null;

function preview(app, toast, p, name) {
  active?.cancel();
  const canvas = app.canvas;
  const ds = canvas.ds;
  const view = { scale: ds.scale, offset: [ds.offset[0], ds.offset[1]] };
  const titles = new Map(p.nodes.map((n) => [n.id, n.getTitle?.() || n.title || n.type || ""]));
  const moved = new Set(p.input.nodes.filter((n) => { const q = p.res.nodes.get(n.id); return q.x !== n.x || q.y !== n.y; }).map((n) => n.id));
  const pos = new Map(p.input.nodes.map((n) => [n.id, { ...n, ...p.res.nodes.get(n.id) }])); // where each would go

  // show all of it: the new layout and where the moving nodes are now
  const shown = p.input.nodes.filter((n) => !p.input.only || p.input.only.includes(n.id));
  const xs = [], ys = [];
  for (const n of shown) {
    const q = p.res.nodes.get(n.id);
    xs.push(n.x, n.x + n.w, q.x, q.x + n.w);
    ys.push(n.y, n.y + n.h, q.y, q.y + n.h);
  }
  for (const g of p.res.groups) { xs.push(g.x, g.x + g.w); ys.push(g.y, g.y + g.h); }
  fitView(canvas, { xs, ys });

  // ComfyUI loads another workflow (or an undo step) into the same graph object with new node lists:
  // the plan is then for nodes that aren't on the canvas any more
  const stale = () => canvas.graph !== p.graph || (p.graph._nodes || p.graph.nodes) !== p.nodes;
  const prevDraw = canvas.onDrawForeground;
  const hook = function (ctx, area) {
    prevDraw?.call(this, ctx, area);
    if (active !== handle) return;
    if (stale()) return setTimeout(() => done(false), 0);
    drawPreview(ctx, canvas, p, { titles, moved, pos });
  };
  canvas.onDrawForeground = hook;

  const bar = document.createElement("div");
  bar.className = "smf-keepbar";
  const text = document.createElement("span");
  text.textContent = `${name}: ${plural(p.res.moved, "node")} would move.`;
  const btn = (label, primary, onclick) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.className = "smf-btn" + (primary ? " primary" : "");
    b.onclick = onclick;
    return b;
  };
  bar.append(text, btn("Apply", true, () => done(true)), btn("Cancel", false, () => done(false)));
  document.body.append(bar);
  document.body.classList.add("smf-previewing"); // fades the nodes' text boxes (page elements over the canvas)
  const onKey = (e) => { if (e.key === "Escape") { e.stopPropagation(); done(false); } };
  document.addEventListener("keydown", onKey, true);

  function done(apply) {
    if (active !== handle) return;
    active = null;
    if (canvas.onDrawForeground === hook) canvas.onDrawForeground = prevDraw; // not another extension's hook set since
    document.removeEventListener("keydown", onKey, true);
    bar.remove();
    document.body.classList.remove("smf-previewing");
    const gone = stale();
    if (apply && gone) {
      toast("warn", name, "The workflow changed while the preview was open: nothing was moved. Run it again.", 5000);
    } else if (apply) {
      applyPlan(canvas, p);
      captureUndo(app);
      toast("success", name, `${plural(p.res.moved, "node")} moved · Ctrl+Z puts them back`, 4000);
    } else if (!gone) { // the view goes back (not onto another workflow)
      ds.scale = view.scale;
      ds.offset = view.offset;
    }
    canvas.setDirty?.(true, true);
  }
  const handle = { cancel: () => done(false) };
  active = handle;
  canvas.setDirty?.(true, true);
}

function drawPreview(ctx, canvas, p, { titles, moved, pos }) {
  const s = canvas.ds.scale, off = canvas.ds.offset, el = canvas.canvas;
  const at = (id) => pos.get(id);
  const slotY = (n, i) => (n.collapsed ? n.h / 2 : TITLE + (i + 0.5) * SLOT);
  ctx.save();
  ctx.fillStyle = "rgba(12,12,16,0.9)"; // dim what's there now
  ctx.fillRect(-off[0], -off[1], (el?.clientWidth || 4000) / s, (el?.clientHeight || 4000) / s);
  ctx.lineWidth = 1.5 / s;
  for (const g of p.res.groups) {
    ctx.fillStyle = "rgba(150,100,210,0.14)";
    ctx.strokeStyle = "rgba(190,140,250,0.75)";
    ctx.beginPath(); ctx.roundRect(g.x, g.y, g.w, g.h, 6); ctx.fill(); ctx.stroke();
  }
  ctx.strokeStyle = "rgba(140,190,230,0.65)";
  ctx.lineWidth = 2 / s;
  for (const n of p.input.nodes) {
    for (const inp of n.inputs) {
      const a = at(inp.origin), b = at(n.id);
      if (!a || !b) continue;
      const x1 = a.x + a.w, y1 = a.y + slotY(a, inp.originSlot), x2 = b.x, y2 = b.y + slotY(b, inp.slot), k = Math.max(40, Math.abs(x2 - x1) / 2);
      ctx.beginPath(); ctx.moveTo(x1, y1); ctx.bezierCurveTo(x1 + k, y1, x2 - k, y2, x2, y2); ctx.stroke();
    }
  }
  ctx.font = "600 14px system-ui, sans-serif";
  ctx.textBaseline = "middle";
  for (const n of p.input.nodes) {
    const q = at(n.id);
    ctx.fillStyle = "rgba(38,42,50,0.96)";
    ctx.strokeStyle = moved.has(n.id) ? "#5fb3ff" : "rgba(255,255,255,0.3)";
    ctx.lineWidth = (moved.has(n.id) ? 2 : 1) / s;
    ctx.beginPath(); ctx.roundRect(q.x, q.y, q.w, q.h, 6); ctx.fill(); ctx.stroke();
    ctx.save();
    ctx.beginPath(); ctx.rect(q.x, q.y, q.w, Math.min(q.h, TITLE)); ctx.clip();
    ctx.fillStyle = "rgba(235,238,245,0.92)";
    ctx.fillText(titles.get(n.id), q.x + 10, q.y + Math.min(q.h, TITLE) / 2);
    ctx.restore();
  }
  for (const g of p.res.groups) {
    const t = p.groups[g.index]?.title;
    if (t) { ctx.fillStyle = "rgba(220,190,255,0.95)"; ctx.font = "600 18px system-ui, sans-serif"; ctx.fillText(t, g.x + 10, g.y + 18); }
  }
  ctx.restore();
}
