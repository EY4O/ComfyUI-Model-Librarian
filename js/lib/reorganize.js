// Re-organize: lays a workflow out again from its connections, ignoring where nodes are now (a layered
// graph layout). Each node goes one column after what feeds it, columns are ordered so wires cross as
// little as possible, and nodes are placed so wires run as straight as possible. Groups stay blocks (laid
// out inside, then placed by what they connect to), disconnected pieces are laid out on their own and
// stacked, pinned nodes (and the groups holding them) don't move, and the workflow keeps its top-left
// corner. Set/Get nodes (wireless links) count as connected for the order, though no wire is drawn; a node
// with no connections at all (a note, a bypasser) keeps its place beside its nearest neighbour. Only
// positions change.
//
// Pure (no ComfyUI): same input and output as tidy() in tidy.js.
import { GRID, PAD, GROUP_TITLE, TITLE, SLOT } from "./tidy.js";

export const LAYER_GAP = 80;  // between columns
export const NODE_GAP = 30;   // between nodes in a column
export const PIECE_GAP = 120; // between disconnected pieces
const SWEEPS = 8;

const snap = (v) => Math.round(v / GRID) * GRID;
const inside = (outer, b, tol = 4) => b.x >= outer.x - tol && b.y >= outer.y - tol && b.x + b.w <= outer.x + outer.w + tol && b.y + b.h <= outer.y + outer.h + tol;
const centerIn = (g, b) => { const cx = b.x + b.w / 2, cy = b.y + b.h / 2; return cx >= g.x && cx <= g.x + g.w && cy >= g.y && cy <= g.y + g.h; };
const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const slotY = (n, i) => (n.collapsed ? n.h / 2 : TITLE + (i + 0.5) * SLOT);

/**
 * @param {{nodes: {id, x, y, w, h, pinned?, collapsed?, sets?, gets?, inputs?: {slot, origin, originSlot}[]}[], groups?: {x, y, w, h}[]}} graph
 *   sets / gets: the name of a Set node's value, or of the value a Get node reads
 *   `only`: lay out just these nodes, where they are (groups and the other nodes untouched)
 * @returns {{nodes: Map<id, {x, y}>, groups: {index, x, y, w, h}[], moved: number}}
 */
export function reorganize(graph) {
  const nodes = new Map(graph.nodes.map((n) => [n.id, { ...n }]));
  const only = graph.only && graph.only.length ? new Set(graph.only) : null;
  const groups = only ? [] : (graph.groups || []).map((g, i) => ({ ...g, index: i }));
  const byArea = [...groups].sort((a, b) => a.w * a.h - b.w * b.h);
  for (const g of groups) g.parent = byArea.find((p) => p !== g && p.w * p.h > g.w * g.h && inside(p, g)) || null;
  for (const n of nodes.values()) n.group = byArea.find((g) => centerIn(g, n)) || null;
  const within = (n, g) => { for (let p = n.group; p; p = p.parent) if (p === g) return true; return false; };
  const setters = new Map([...nodes.values()].filter((n) => n.sets != null).map((n) => [n.sets, n]));
  const groupWithin = (x, g) => { for (let p = x.parent; p; p = p.parent) if (p === g) return true; return false; };

  const shiftItem = (it, dx, dy) => {
    it.x += dx; it.y += dy;
    if (it.kind === "group") {
      for (const n of nodes.values()) if (within(n, it.g)) { n.x += dx; n.y += dy; }
      for (const x of groups) if (groupWithin(x, it.g)) { x.x += dx; x.y += dy; }
    }
  };

  for (const c of [...byArea, null]) {
    const items = [
      ...[...nodes.values()].filter((n) => n.group === c && (!only || only.has(n.id))).map((n) => ({ kind: "node", n, x: n.x, y: n.y, w: n.w, h: n.h, pinned: !!n.pinned })),
      // a group holding a pinned node stays where it is too
      ...groups.filter((g) => g.parent === c).map((g) => ({ kind: "group", g, x: g.x, y: g.y, w: g.w, h: g.h, pinned: [...nodes.values()].some((n) => n.pinned && within(n, g)) })),
    ];
    for (const it of items) { it.ox = it.x; it.oy = it.y; }
    if (!items.length) continue;
    const origin = { x: Math.min(...items.map((i) => i.x)), y: Math.min(...items.map((i) => i.y)) };
    // the item of this container holding node n, and where node n's slot sits relative to that item's top
    const holder = (n) => items.find((it) => (it.kind === "node" ? it.n === n : within(n, it.g))) || null;
    const port = (it, n, slot) => (it.kind === "node" ? slotY(n, slot) : n.y - it.y + slotY(n, slot));
    const edges = [];
    for (const n of nodes.values()) {
      for (const inp of n.inputs || []) {
        const o = nodes.get(inp.origin);
        if (!o) continue;
        const a = holder(o), b = holder(n);
        if (!a || !b || a === b) continue;
        edges.push({ from: a, to: b, fromY: port(a, o, inp.originSlot), toY: port(b, n, inp.slot), key: inp.slot });
      }
      const o = n.gets != null ? setters.get(n.gets) : null; // a wireless link: orders the layout, no wire drawn
      const a = o && holder(o), b = holder(n);
      if (a && b && a !== b) edges.push({ from: a, to: b, fromY: 0, toY: 0, key: -1, virtual: true });
    }
    const fixed = items.filter((i) => i.pinned);
    const linked = new Set(edges.flatMap((e) => [e.from, e.to]));
    let free = items.filter((i) => !i.pinned);
    // loose items (nothing in or out: notes, bypassers) stay beside their nearest neighbour, placed after
    const loose = free.some((i) => linked.has(i)) ? free.filter((i) => !linked.has(i)) : [];
    free = free.filter((i) => !loose.includes(i));
    const pieces = components(free, edges);
    let cursorY = origin.y;
    for (const piece of pieces) {
      const pe = edges.filter((e) => piece.includes(e.from) && piece.includes(e.to));
      const pos = layered(piece, pe);
      // the piece starts at the container's top-left, below the pieces already placed, clear of pinned nodes
      let dy = cursorY;
      const dx = origin.x;
      for (let guard = 0; guard <= fixed.length; guard++) {
        const hit = fixed.find((f) => piece.some((it) => overlaps({ x: pos.get(it).x + dx, y: pos.get(it).y + dy, w: it.w, h: it.h }, f)));
        if (!hit) break;
        dy = hit.y + hit.h + NODE_GAP;
      }
      let bottom = dy;
      for (const it of piece) {
        const p = pos.get(it);
        shiftItem(it, snap(p.x + dx) - it.x, snap(p.y + dy) - it.y);
        bottom = Math.max(bottom, it.y + it.h);
      }
      cursorY = snap(bottom + PIECE_GAP);
    }
    const placed = items.filter((i) => !loose.includes(i));
    const gap = (a, b) => Math.max(0, a.ox - (b.ox + b.w), b.ox - (a.ox + a.w)) + Math.max(0, a.oy - (b.oy + b.h), b.oy - (a.oy + a.h));
    for (const it of [...loose].sort((a, b) => a.oy - b.oy || a.ox - b.ox)) {
      const anchor = free.reduce((best, f) => (!best || gap(it, f) < gap(it, best) ? f : best), null);
      const x = snap(anchor.x + it.ox - anchor.ox);
      let y = snap(anchor.y + it.oy - anchor.oy);
      for (let guard = 0; guard <= placed.length; guard++) {
        const hit = placed.find((p) => overlaps({ x, y, w: it.w, h: it.h }, p));
        if (!hit) break;
        y = snap(hit.y + hit.h + NODE_GAP);
      }
      shiftItem(it, x - it.x, y - it.y);
      placed.push(it);
    }
    for (const it of items) {
      if (it.kind === "node") { it.n.x = it.x; it.n.y = it.y; } else { it.g.x = it.x; it.g.y = it.y; }
    }
    if (c) {
      const x0 = Math.min(...items.map((i) => i.x)) - PAD, y0 = Math.min(...items.map((i) => i.y)) - GROUP_TITLE;
      const x1 = Math.max(...items.map((i) => i.x + i.w)) + PAD, y1 = Math.max(...items.map((i) => i.y + i.h)) + PAD;
      Object.assign(c, { x: x0, y: y0, w: x1 - x0, h: y1 - y0 });
    }
  }

  const out = new Map();
  let moved = 0;
  for (const o of graph.nodes) {
    const n = nodes.get(o.id);
    out.set(o.id, { x: n.x, y: n.y });
    if (n.x !== o.x || n.y !== o.y) moved++;
  }
  return { nodes: out, groups: groups.map((g) => ({ index: g.index, x: g.x, y: g.y, w: g.w, h: g.h })), moved };
}

// Connected pieces (wires in either direction), biggest first; within a piece, items keep their original order.
function components(items, edges) {
  const adj = new Map(items.map((i) => [i, []]));
  for (const e of edges) {
    if (adj.has(e.from) && adj.has(e.to)) { adj.get(e.from).push(e.to); adj.get(e.to).push(e.from); }
  }
  const seen = new Set(), out = [];
  const order = [...items].sort((a, b) => a.y - b.y || a.x - b.x);
  for (const start of order) {
    if (seen.has(start)) continue;
    const piece = [], stack = [start];
    seen.add(start);
    while (stack.length) {
      const it = stack.pop();
      piece.push(it);
      for (const nb of adj.get(it)) if (!seen.has(nb)) { seen.add(nb); stack.push(nb); }
    }
    out.push(piece);
  }
  return out.sort((a, b) => b.length - a.length || Math.min(...a.map((i) => i.y)) - Math.min(...b.map((i) => i.y)));
}

// One connected piece -> Map(item -> {x, y}) relative to (0, 0).
function layered(items, edges) {
  if (items.length === 1) return new Map([[items[0], { x: 0, y: 0 }]]);
  // ---- columns: longest path from the start; a node that nothing feeds sits just before what it feeds
  const preds = new Map(items.map((i) => [i, []])), succs = new Map(items.map((i) => [i, []]));
  for (const e of edges) { preds.get(e.to).push(e); succs.get(e.from).push(e); }
  const layer = new Map();
  const state = new Map(); // cycles (not in a valid workflow, but never hang): a back edge is ignored
  const depth = (it) => {
    if (layer.has(it)) return layer.get(it);
    if (state.get(it) === "visiting") return -1;
    state.set(it, "visiting");
    let d = 0;
    for (const e of preds.get(it)) { const p = depth(e.from); if (p >= 0) d = Math.max(d, p + 1); }
    state.set(it, "done");
    layer.set(it, d);
    return d;
  };
  for (const it of items) depth(it);
  // then each node moves right to just before the first node it feeds (loaders sit by what they feed, and a
  // branch that only feeds the end isn't left far out at the start); wireless links don't pull a Set node
  const byLayer = [...items].sort((a, b) => layer.get(b) - layer.get(a));
  for (let pass = 0; pass < 3; pass++) {
    for (const it of byLayer) {
      const out = succs.get(it).filter((e) => !e.virtual);
      if (!out.length) continue;
      const first = Math.min(...out.map((e) => layer.get(e.to)));
      if (first - 1 > layer.get(it)) layer.set(it, first - 1);
    }
  }
  // ---- long wires get invisible waypoints in the columns they cross (so they can run straight)
  const all = [...items];
  const links = [];
  for (const e of edges) {
    if (e.virtual) continue; // no wire to route
    let a = e.from, fromY = e.fromY;
    const la = layer.get(e.from), lb = layer.get(e.to);
    if (lb <= la) continue; // a back edge from a cycle
    for (let l = la + 1; l < lb; l++) {
      const d = { kind: "dummy", w: 0, h: 0 };
      layer.set(d, l);
      all.push(d);
      links.push({ from: a, to: d, fromY, toY: 0, key: e.key });
      a = d; fromY = 0;
    }
    links.push({ from: a, to: e.to, fromY, toY: e.toY, key: e.key });
  }
  const L = Math.max(...all.map((i) => layer.get(i)));
  const cols = Array.from({ length: L + 1 }, () => []);
  for (const it of all) cols[layer.get(it)].push(it);
  const inL = new Map(all.map((i) => [i, []])), outL = new Map(all.map((i) => [i, []]));
  for (const k of links) { inL.get(k.to).push(k); outL.get(k.from).push(k); }

  // ---- order in each column: start from where things were, then barycenter sweeps (ports included)
  for (const col of cols) col.sort((a, b) => (a.y ?? 0) - (b.y ?? 0));
  const index = new Map();
  const reindex = () => cols.forEach((col) => col.forEach((it, i) => index.set(it, i)));
  reindex();
  const bary = (it, side) => {
    const ks = side === "in" ? inL.get(it) : outL.get(it);
    if (!ks.length) return null;
    return ks.reduce((s, k) => s + index.get(side === "in" ? k.from : k.to) + (side === "in" ? k.fromY : k.toY) / 10000, 0) / ks.length;
  };
  const crossings = () => {
    let c = 0;
    for (const k1 of links) for (const k2 of links) {
      if (k1 === k2 || layer.get(k1.from) !== layer.get(k2.from)) continue;
      const a = index.get(k1.from) - index.get(k2.from) + (k1.fromY - k2.fromY) / 10000;
      const b = index.get(k1.to) - index.get(k2.to) + (k1.toY - k2.toY) / 10000;
      if (a * b < 0) c++;
    }
    return c / 2;
  };
  let best = cols.map((c) => [...c]), bestX = crossings();
  for (let s = 0; s < SWEEPS; s++) {
    const down = s % 2 === 0;
    const seq = down ? cols.slice(1) : cols.slice(0, -1).reverse();
    for (const col of seq) {
      const keyed = col.map((it, i) => ({ it, k: bary(it, down ? "in" : "out") ?? i }));
      keyed.sort((a, b) => a.k - b.k);
      col.splice(0, col.length, ...keyed.map((x) => x.it));
      col.forEach((it, i) => index.set(it, i));
    }
    const x = crossings();
    if (x < bestX) { bestX = x; best = cols.map((c) => [...c]); }
  }
  best.forEach((c, i) => cols[i].splice(0, cols[i].length, ...c));
  reindex();

  // ---- y: straight wires, packed without overlaps (least squares per column, alternating directions)
  const y = new Map(all.map((it) => [it, 0]));
  const pack = (col, want) => {
    // y[i+1] >= y[i] + h[i] + gap ; minimize sum (y - want)^2  -> isotonic regression (pool adjacent violators)
    const off = [];
    let acc = 0;
    for (const it of col) { off.push(acc); acc += it.h + (it.kind === "dummy" ? 10 : NODE_GAP); }
    const t = col.map((it, i) => want[i] - off[i]);
    const blocks = [];
    for (let i = 0; i < t.length; i++) {
      blocks.push({ sum: t[i], n: 1, start: i });
      while (blocks.length > 1 && blocks[blocks.length - 2].sum / blocks[blocks.length - 2].n > blocks[blocks.length - 1].sum / blocks[blocks.length - 1].n) {
        const b = blocks.pop();
        blocks[blocks.length - 1].sum += b.sum;
        blocks[blocks.length - 1].n += b.n;
      }
    }
    for (const b of blocks) for (let i = b.start; i < b.start + b.n; i++) y.set(col[i], b.sum / b.n + off[i]);
  };
  cols.forEach((col) => pack(col, col.map(() => 0)));
  for (let s = 0; s < 6; s++) {
    const down = s % 2 === 0;
    const seq = down ? cols : [...cols].reverse();
    for (const col of seq) {
      const want = col.map((it) => {
        const ks = down ? inL.get(it) : outL.get(it);
        if (!ks.length) return y.get(it);
        const ys = ks.map((k) => (down ? y.get(k.from) + k.fromY - k.toY : y.get(k.to) + k.toY - k.fromY));
        return ys.reduce((a, b) => a + b, 0) / ys.length;
      });
      pack(col, want);
    }
  }
  // ---- x: columns left to right, each as wide as its widest node
  const pos = new Map();
  let x = 0;
  for (const col of cols) {
    const width = Math.max(0, ...col.map((it) => it.w));
    for (const it of col) if (it.kind !== "dummy") pos.set(it, { x, y: y.get(it) });
    x += width + (width ? LAYER_GAP : 0);
  }
  const minY = Math.min(...[...pos.values()].map((p) => p.y));
  for (const p of pos.values()) p.y -= minY;
  return pos;
}
