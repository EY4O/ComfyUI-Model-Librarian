// Tidy: a gentle clean-up of a crowded or spread-out workflow. Nodes stay roughly where you put them:
// they're sorted into the columns they're already in, columns are lined up and spaced, nodes in a
// column are stacked without overlaps, big empty gaps are closed, and a node is lined up with what feeds
// it (straighter wires) when that's close to where it was. Groups stay blocks: their contents are tidied
// inside, then the groups themselves are arranged like nodes, nested groups included. Pinned nodes don't
// move (others make room). Sizes, wires and settings are never changed: only positions.
//
// Pure (no ComfyUI): tidy() takes boxes and links and returns new positions, so it can be tested.

export const GRID = 10;       // snap
export const GAP_X = 60;      // between columns
export const GAP_Y = 30;      // between nodes in a column
export const PAD = 20;        // inside a group, around its contents
export const GROUP_TITLE = 40; // a group's title bar
export const TITLE = 30;      // a node's title bar (slots start under it)
export const SLOT = 20;       // a slot row
export const PULL = 300;      // how far a node may move to line up with what feeds it
export const SPREAD = 3;      // gaps bigger than this many GAPs are closed

const snap = (v) => Math.round(v / GRID) * GRID;
const slotY = (box, i) => (box.collapsed ? box.h / 2 : TITLE + (i + 0.5) * SLOT);
const inside = (outer, b, tol = 4) => b.x >= outer.x - tol && b.y >= outer.y - tol && b.x + b.w <= outer.x + outer.w + tol && b.y + b.h <= outer.y + outer.h + tol;
const centerIn = (g, b) => { const cx = b.x + b.w / 2, cy = b.y + b.h / 2; return cx >= g.x && cx <= g.x + g.w && cy >= g.y && cy <= g.y + g.h; };
const overlaps = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

/**
 * @param {{nodes: {id, x, y, w, h, pinned?, collapsed?, inputs?: {slot, origin, originSlot}[]}[],
 *          groups?: {x, y, w, h}[], only?: (string|number)[]}} graph
 *   Boxes are full bounding boxes (title bar included). `only`: tidy just these nodes (groups untouched).
 * @returns {{nodes: Map<id, {x, y}>, groups: {x, y, w, h}[], moved: number}}  new top-left corners
 */
export function tidy(graph) {
  const home = new Map(graph.nodes.map((n) => [n.id, n.y])); // where you put each node: moves are limited from here
  let cur = graph, res = null;
  for (let pass = 0; pass < 5; pass++) { // until it settles (lining up A with B can move B's sources a bit)
    res = tidyPass(cur, home);
    const nodes = cur.nodes.map((n) => ({ ...n, ...res.nodes.get(n.id) }));
    const settled = cur.nodes.every((n) => { const p = res.nodes.get(n.id); return p.x === n.x && p.y === n.y; });
    cur = { ...cur, nodes, groups: res.groups.length ? res.groups.map(({ index, ...g }) => g) : cur.groups };
    if (settled) break;
  }
  let moved = 0;
  for (const n of graph.nodes) {
    const p = res.nodes.get(n.id);
    if (p.x !== n.x || p.y !== n.y) moved++;
  }
  return { ...res, moved };
}

function tidyPass(graph, home) {
  const nodes = new Map(graph.nodes.map((n) => [n.id, { ...n, home: home.get(n.id) }]));
  const only = graph.only && graph.only.length ? new Set(graph.only) : null;
  const groups = only ? [] : (graph.groups || []).map((g, i) => ({ ...g, index: i }));

  // who's inside what: each node in its smallest group (by its center), each group in its smallest parent
  const byArea = [...groups].sort((a, b) => a.w * a.h - b.w * b.h);
  for (const g of groups) g.parent = byArea.find((p) => p !== g && p.w * p.h > g.w * g.h && inside(p, g)) || null;
  for (const n of nodes.values()) n.group = only ? null : byArea.find((g) => centerIn(g, n)) || null;

  // a group's contents, laid out bottom-up (smallest groups first), then the top level
  const descendantsOf = (g) => {
    const ns = [...nodes.values()].filter((n) => { for (let p = n.group; p; p = p.parent) if (p === g) return true; return false; });
    const gs = groups.filter((x) => { for (let p = x.parent; p; p = p.parent) if (p === g) return true; return false; });
    return { ns, gs };
  };
  const shift = (item, dx, dy) => {
    if (!dx && !dy) return;
    item.x += dx; item.y += dy;
    if (item.kind === "group") {
      const { ns, gs } = descendantsOf(item.g);
      for (const n of ns) { n.x += dx; n.y += dy; }
      for (const x of gs) { x.x += dx; x.y += dy; }
    }
  };

  // who each node feeds (a source node with no inputs is drawn towards what it feeds)
  const consumers = new Map();
  for (const n of graph.nodes) {
    for (const inp of n.inputs || []) {
      if (!consumers.has(inp.origin)) consumers.set(inp.origin, []);
      consumers.get(inp.origin).push({ target: n, slot: inp.slot, originSlot: inp.originSlot });
    }
  }
  const ctx = { nodes, consumers, groupOf: (n) => n.group };

  const containers = [...byArea, null]; // null = the top level
  for (const c of containers) {
    const items = [
      ...[...nodes.values()].filter((n) => (only ? only.has(n.id) : n.group === c)).map((n) => ({ kind: "node", n, ...box(n) })),
      ...groups.filter((g) => g.parent === c).map((g) => ({ kind: "group", g, x: g.x, y: g.y, w: g.w, h: g.h })),
    ];
    if (!items.length) continue;
    layout(items, ctx, shift);
    for (const it of items) { // write back
      if (it.kind === "node") { it.n.x = it.x; it.n.y = it.y; } else { it.g.x = it.x; it.g.y = it.y; }
    }
    if (c) { // the group fits its tidied contents
      const xs = items.map((i) => i.x), ys = items.map((i) => i.y);
      const x0 = Math.min(...xs) - PAD, y0 = Math.min(...ys) - GROUP_TITLE;
      const x1 = Math.max(...items.map((i) => i.x + i.w)) + PAD, y1 = Math.max(...items.map((i) => i.y + i.h)) + PAD;
      Object.assign(c, { x: x0, y: y0, w: x1 - x0, h: y1 - y0 });
    }
  }

  const out = new Map();
  let moved = 0;
  for (const n of nodes.values()) {
    const orig = graph.nodes.find((o) => o.id === n.id);
    out.set(n.id, { x: n.x, y: n.y });
    if (orig.x !== n.x || orig.y !== n.y) moved++;
  }
  return { nodes: out, groups: (only ? [] : groups).map((g) => ({ index: g.index, x: g.x, y: g.y, w: g.w, h: g.h })), moved };
}

const box = (n) => ({ x: n.x, y: n.y, w: n.w, h: n.h, pinned: !!n.pinned, collapsed: !!n.collapsed });

// Close enough to move there: within PULL of where it is now, and twice that of where you put it.
const near = (y, it) => Math.abs(y - it.y) <= PULL && Math.abs(y - it.n.home) <= 2 * PULL;

// The item of this container that holds node n (the node itself, or the group block it's inside), or null.
function holder(items, n) {
  for (const it of items) {
    if (it.kind === "node" && it.n === n) return it;
    if (it.kind === "group") for (let g = n.group; g; g = g.parent) if (g === it.g) return it;
  }
  return null;
}

// Within a column, a node comes after the nodes of that column that feed it (wires run downwards, never
// back up the column); otherwise the order by where they'd like to be is kept.
function feedersFirst(col, items) {
  const inCol = new Set(col);
  const feeders = new Map(col.map((it) => [it, (it.kind === "node" ? it.n.inputs || [] : [])
    .map((inp) => col.find((o) => o.kind === "node" && o.n.id === inp.origin)).filter((o) => o && o !== it && inCol.has(o))]));
  const out = [], done = new Set(), visiting = new Set();
  const visit = (it) => {
    if (done.has(it) || visiting.has(it)) return; // a loop (shouldn't happen in a workflow): keep going
    visiting.add(it);
    for (const f of feeders.get(it)) visit(f);
    visiting.delete(it);
    done.add(it);
    out.push(it);
  };
  for (const it of col) visit(it);
  return out;
}

// One container: columns from the x positions you already have, stacked and spaced.
function layout(items, ctx, shift) {
  const { nodes, consumers } = ctx;
  const fixed = items.filter((i) => i.pinned);
  const free = items.filter((i) => !i.pinned).sort((a, b) => a.x - b.x || a.y - b.y);

  // columns: an item joins the current column when it starts within half the narrower width of it
  const cols = [];
  for (const it of free) {
    const c = cols[cols.length - 1];
    if (c && it.x - c.left < 0.5 * Math.min(c.firstW, it.w)) c.items.push(it);
    else cols.push({ left: it.x, firstW: it.w, items: [it] });
  }

  const placed = new Set();
  let prevRight = null;
  for (const c of cols) {
    const width = Math.max(...c.items.map((i) => i.w));
    let x = snap(Math.min(...c.items.map((i) => i.x)));
    if (prevRight !== null) {
      const min = snap(prevRight + GAP_X);
      if (x < min || x - prevRight > SPREAD * GAP_X) x = min; // no overlap, no huge gap
    }
    // where each would like to be: lined up with what feeds it (if that's close), else where it is.
    // A source counts once its position is final: placed already in this container (or inside a group
    // block placed here), or outside this container altogether.
    for (const it of c.items) {
      it.want = it.y;
      if (it.kind !== "node" || it.collapsed) continue;
      const ys = (it.n.inputs || []).map((inp) => {
        const src = nodes.get(inp.origin);
        if (!src) return null;
        const h = holder(items, src);
        if (h && !placed.has(h)) return null;
        const left = h && h.kind === "node" ? h.x + h.w : src.x + src.w;
        if (left > x + GRID) return null; // wires are lined up left to right: not with a node in the same column
        const top = h && h.kind === "node" ? h.y : src.y;
        return top + slotY(src, inp.originSlot) - slotY(it, inp.slot);
      }).filter((v) => v !== null);
      if (!ys.length && !(it.n.inputs || []).length) {
        // nothing feeds it (a loader, an empty latent): a stray one, well out of line with the first node
        // it feeds, is drawn towards it; one that's roughly in line stays put
        // only a node that feeds one other node, to its right (a loader feeding half the graph isn't a stray)
        const uses = consumers.get(it.n.id) || [];
        const use = new Set(uses.map((u) => u.target)).size === 1 && uses[0].target.x >= it.x + it.w - GRID ? uses[0] : null;
        const aligned = use ? use.target.y + slotY(use.target, use.slot) - slotY(it, use.originSlot) : null;
        if (aligned !== null && Math.abs(aligned - it.y) > SPREAD * GAP_Y && near(aligned, it)) it.want = aligned;
        continue;
      }
      if (ys.length) {
        const aligned = ys.reduce((a, b) => a + b, 0) / ys.length;
        if (near(aligned, it)) it.want = aligned;
      }
    }
    c.items.sort((a, b) => a.want - b.want || a.y - b.y);
    c.items = feedersFirst(c.items, items);
    let bottom = null;
    for (const it of c.items) {
      let y = it.want;
      if (bottom !== null) {
        const min = bottom + GAP_Y;
        if (y < min || y - bottom > SPREAD * GAP_Y) y = min; // stacked, and spread-out ones pulled together
      }
      y = snap(y);
      // pinned nodes stay put: anything that would land on one goes below it
      for (let guard = 0; guard < fixed.length + 1; guard++) {
        const hit = fixed.find((f) => overlaps({ x, y, w: it.w, h: it.h }, f));
        if (!hit) break;
        y = snap(hit.y + hit.h + GAP_Y);
      }
      shift(it, x - it.x, y - it.y);
      bottom = it.y + it.h;
      placed.add(it);
    }
    prevRight = x + width;
  }
}
