// Tidy on the open ComfyUI canvas: reads the graph being shown (a subgraph when you're inside one),
// runs the layout from tidy.js, writes the positions back and records one undo step (Ctrl+Z).
import { tidy, TITLE } from "./tidy.js";

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

// -> {moved, nodes} ; selectionOnly: just the selected nodes (needs 2 or more)
export function tidyCanvas(canvas, { selectionOnly = false } = {}) {
  const graph = canvas.graph || canvas.getCurrentGraph?.();
  if (!graph) return { moved: 0, nodes: 0 };
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
        inputs: (n.inputs || []).map((inp, slot) => {
          const l = getLink(graph, inp.link);
          return l ? { slot, origin: l.origin_id, originSlot: l.origin_slot } : null;
        }).filter(Boolean),
      };
    }),
    groups: groups.map(groupBox),
    only: selectionOnly ? selected.map((n) => n.id) : null,
  };
  const res = tidy(input);

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
  return { moved: res.moved, nodes: input.only ? input.only.length : nodes.length };
}

// Tidy with one undo step and a short summary. The undo step comes from ComfyUI's change tracker:
// it sees the new positions as one change, so Ctrl+Z puts everything back.
export function runTidy(app, toast, { selectionOnly = false } = {}) {
  const canvas = app.canvas;
  if (!canvas) return;
  const tracker = app.extensionManager?.workflow?.activeWorkflow?.changeTracker;
  const r = tidyCanvas(canvas, { selectionOnly });
  if (!r.nodes) return toast("info", "Tidy", selectionOnly ? "Select two or more nodes to tidy them." : "There's nothing to tidy here.", 3000);
  if (!r.moved) return toast("info", "Tidy", "Already tidy.", 2500);
  try {
    if (tracker?.captureCanvasState) tracker.captureCanvasState();
    else tracker?.checkState?.();
  } catch {}
  toast("success", "Tidied", `${r.moved} of ${r.nodes} node${r.nodes === 1 ? "" : "s"} moved · Ctrl+Z puts them back`, 4000);
}
