// Tidy and Re-organize on the open ComfyUI canvas: reads the graph being shown (a subgraph when you're
// inside one), runs the layout (tidy.js / reorganize.js), writes the positions back and records one undo
// step (Ctrl+Z). Re-organize also shows a bar to keep the new layout or put the old one back.
import { tidy, TITLE } from "./tidy.js";
import { reorganize } from "./reorganize.js";

const rect = (r) => (r && r.length >= 4 ? [r[0], r[1], r[2], r[3]] : null);
const getLink = (graph, id) => (id == null ? null : graph.getLink?.(id) ?? (graph.links?.get ? graph.links.get(id) : graph.links?.[id]));

// A node's box is cached and refreshed when the canvas draws it: refresh it first (off-screen nodes
// may not have been drawn since they last moved or resized).
const refresh = (n, canvas) => { try { n.updateArea?.(canvas?.ctx); } catch {} };

function nodeBox(n) {
  const b = rect(n.boundingRect) || [n.pos[0], n.pos[1] - TITLE, n.size[0], n.size[1] + TITLE];
  return { x: b[0], y: b[1], w: b[2], h: b[3], dx: n.pos[0] - b[0], dy: n.pos[1] - b[1] };
}

function groupBox(g) {
  const b = rect(g._bounding) || rect(g.boundingRect) || [g.pos[0], g.pos[1], g.size[0], g.size[1]];
  return { x: b[0], y: b[1], w: b[2], h: b[3] };
}

function setGroup(g, b) {
  if (g._bounding && g._bounding.length >= 4) {
    g._bounding[0] = b.x; g._bounding[1] = b.y; g._bounding[2] = b.w; g._bounding[3] = b.h;
  } else {
    g.pos = [b.x, b.y];
    g.size = [b.w, b.h];
  }
}

// Everything a layout can change, to put it back exactly.
function snapshot(graph) {
  const nodes = graph._nodes || graph.nodes || [];
  const groups = graph._groups || graph.groups || [];
  const reroutes = graph.reroutes instanceof Map ? [...graph.reroutes.values()] : [];
  return {
    nodes: nodes.map((n) => [n, [n.pos[0], n.pos[1]]]),
    groups: groups.map((g) => [g, groupBox(g)]),
    reroutes: reroutes.filter((r) => r.pos).map((r) => [r, [r.pos[0], r.pos[1]]]),
  };
}

function restore(graph, snap, canvas) {
  for (const [n, p] of snap.nodes) { n.pos = [p[0], p[1]]; refresh(n, canvas); }
  for (const [g, b] of snap.groups) setGroup(g, b);
  for (const [r, p] of snap.reroutes) r.pos = [p[0], p[1]];
  graph.change?.();
  canvas.setDirty?.(true, true);
}

// -> {moved, nodes, snap} ; mode "tidy" (compact: no distance limit) or "reorganize";
// selectionOnly (Tidy): just the selected nodes (needs 2 or more)
// Set/Get nodes (KJNodes, Easy-Use): a value passed by name instead of a wire
function wireless(n) {
  const m = /^(?:easy )?(set|get)node$/i.exec(n.type || "");
  const name = m && n.widgets?.[0]?.value;
  return name ? { [m[1].toLowerCase() === "set" ? "sets" : "gets"]: String(name) } : {};
}

export function tidyCanvas(canvas, { selectionOnly = false, compact = false, mode = "tidy" } = {}) {
  const graph = canvas.graph || canvas.getCurrentGraph?.();
  if (!graph) return { moved: 0, nodes: 0 };
  const snap = snapshot(graph);
  const nodes = graph._nodes || graph.nodes || [];
  const groups = graph._groups || graph.groups || [];
  const selected = selectionOnly ? [...(canvas.selectedItems || Object.values(canvas.selected_nodes || {}))].filter((x) => nodes.includes(x)) : [];
  if (selectionOnly && selected.length < 2) return { moved: 0, nodes: 0 };

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
  };
  const res = mode === "reorganize" ? reorganize(input) : tidy(input);

  // native reroute points follow the nodes their wire joins
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
  return { moved: res.moved, nodes: input.only ? input.only.length : nodes.length, snap, graph };
}

const captureUndo = (app) => {
  const tracker = app.extensionManager?.workflow?.activeWorkflow?.changeTracker;
  try {
    if (tracker?.captureCanvasState) tracker.captureCanvasState();
    else tracker?.checkState?.();
  } catch {}
};

// Tidy (or compact Tidy, or Re-organize) with one undo step and a short summary. The undo step comes from
// ComfyUI's change tracker: it sees the new positions as one change, so Ctrl+Z puts everything back.
export function runTidy(app, toast, { selectionOnly = false, compact = false, mode = "tidy" } = {}) {
  const canvas = app.canvas;
  if (!canvas) return;
  const name = mode === "reorganize" ? "Re-organize" : compact ? "Compact tidy" : "Tidy";
  const r = tidyCanvas(canvas, { selectionOnly, compact, mode });
  if (!r.nodes) return toast("info", name, selectionOnly ? "Select two or more nodes to tidy them." : "There's nothing to arrange here.", 3000);
  if (!r.moved) return toast("info", name, mode === "reorganize" ? "Already laid out." : "Already tidy.", 2500);
  captureUndo(app);
  if (mode === "reorganize") return keepBar(app, r);
  toast("success", compact ? "Tidied (compact)" : "Tidied", `${r.moved} of ${r.nodes} node${r.nodes === 1 ? "" : "s"} moved · Ctrl+Z puts them back`, 4000);
}

// After Re-organize: keep the new layout, or put the old one back (Ctrl+Z works too).
let bar = null;
function keepBar(app, r) {
  bar?.remove();
  const close = () => { bar?.remove(); bar = null; };
  const btn = (label, primary, onclick) => {
    const b = document.createElement("button");
    b.textContent = label;
    b.className = "smf-btn" + (primary ? " primary" : "");
    b.onclick = onclick;
    return b;
  };
  bar = document.createElement("div");
  bar.className = "smf-keepbar";
  const text = document.createElement("span");
  text.textContent = `Re-organized ${r.moved} node${r.moved === 1 ? "" : "s"} from their connections.`;
  bar.append(text,
    btn("Keep", true, close),
    btn("Put back", false, () => { restore(r.graph, r.snap, app.canvas); captureUndo(app); close(); }));
  document.body.append(bar);
  setTimeout(() => { if (bar && bar.isConnected) close(); }, 30000); // keeping is the default
}
