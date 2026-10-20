// Tidy (js/lib/tidy.js) on crowded, spread-out sample graphs, without a browser.
import { pathToFileURL, fileURLToPath } from "node:url";
const PLUGIN = process.argv[2] || fileURLToPath(new URL("..", import.meta.url));
const T = await import(pathToFileURL(PLUGIN + "/js/lib/tidy.js").href);
let fail = 0;
const ok = (cond, m, extra = "") => { console.log((cond ? "PASS " : "FAIL ") + m + (cond ? "" : ` ${extra}`)); if (!cond) fail++; };

const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const apply = (g, r) => g.nodes.map((n) => ({ ...n, ...r.nodes.get(n.id) }));
const noOverlaps = (ns) => ns.every((a, i) => ns.every((b, j) => i >= j || !overlap(a, b)));

// a typical text-to-image graph, dropped in a mess: overlapping, ragged, far apart
const N = (id, x, y, w, h, inputs = [], extra = {}) => ({ id, x, y, w, h, inputs, ...extra });
const messy = {
  nodes: [
    N(1, 10, 40, 300, 120),                                          // checkpoint loader
    N(2, 22, 150, 300, 90, [{ slot: 0, origin: 1, originSlot: 0 }]),  // LoRA, overlapping the loader
    N(3, 400, 20, 400, 200, [{ slot: 0, origin: 2, originSlot: 1 }]), // positive prompt
    N(4, 430, 180, 400, 200, [{ slot: 0, origin: 2, originSlot: 1 }]), // negative prompt, overlapping
    N(5, 1700, 700, 320, 260, [{ slot: 0, origin: 2, originSlot: 0 }, { slot: 1, origin: 3, originSlot: 0 }, { slot: 2, origin: 4, originSlot: 0 }]), // sampler, far away
    N(6, 2500, 90, 220, 60, [{ slot: 0, origin: 5, originSlot: 0 }]), // decode
    N(7, 2520, 1400, 400, 400, [{ slot: 0, origin: 6, originSlot: 0 }]), // save, way down
  ],
};
let r = T.tidy(messy);
let ns = apply(messy, r);
ok(noOverlaps(ns), "no node overlaps another afterwards");
ok(ns.every((n) => n.x % T.GRID === 0 && n.y % T.GRID === 0), "everything on the grid");
const by = Object.fromEntries(ns.map((n) => [n.id, n]));
ok(by[1].x === by[2].x && by[3].x === by[4].x, "nodes that were roughly in a column share one left edge");
ok(by[1].x < by[3].x && by[3].x < by[5].x && by[5].x < by[6].x, "left-to-right order is kept");
ok(by[5].x - (by[3].x + 400) <= T.GAP_X * T.SPREAD && by[5].x - (by[3].x + 400) >= T.GAP_X, `the huge gap before the sampler is closed (${by[5].x - (by[3].x + 400)})`);
ok(by[7].y - (by[6].y + 60) === T.GAP_Y || by[7].x !== by[6].x, `a node far below in its column is pulled up (${by[7].y})`);
ok(by[1].y < by[2].y && by[3].y < by[4].y, "top-to-bottom order in a column is kept");
ok(r.moved === 6, `moved count: all but the loader, already on the grid at its column edge (${r.moved})`);

// straighter wires: a chain lines up when it's close
const chain = { nodes: [N(1, 0, 100, 200, 100), N(2, 300, 160, 200, 100, [{ slot: 0, origin: 1, originSlot: 0 }])] };
r = T.tidy(chain);
ok(r.nodes.get(2).y === 100, `a node lines up its input with what feeds it (${r.nodes.get(2).y})`);
const stray = { nodes: [N(1, 0, 420, 200, 100), N(2, 300, 160, 200, 100, [{ slot: 0, origin: 1, originSlot: 0 }])] };
ok(T.tidy(stray).nodes.get(1).y === 160, `a stray source node (nothing feeds it) is drawn towards what it feeds (${T.tidy(stray).nodes.get(1).y})`);
const far = { nodes: [N(1, 0, 100, 200, 100), N(2, 300, 900, 200, 100, [{ slot: 0, origin: 1, originSlot: 0 }])] };
ok(T.tidy(far).nodes.get(2).y === 900, "but isn't dragged far from where you put it");

// in a column, a node comes after what feeds it: decode above the preview it feeds, not below
const col2 = { nodes: [N(1, 0, 300, 200, 100), N(2, 300, 300, 200, 60, [{ slot: 0, origin: 1, originSlot: 0 }]),
  N(3, 310, 80, 200, 150, [{ slot: 0, origin: 2, originSlot: 0 }]), N(4, 305, 520, 200, 150, [{ slot: 0, origin: 2, originSlot: 0 }])] };
r = T.tidy(col2);
ok(r.nodes.get(2).y < r.nodes.get(3).y && r.nodes.get(2).y < r.nodes.get(4).y, `wires run down a column, never back up (decode ${r.nodes.get(2).y}, preview ${r.nodes.get(3).y})`);
ok(T.tidy({ nodes: col2.nodes.map((n) => ({ ...n, ...r.nodes.get(n.id) })) }).moved === 0, "and it stays that way");

// compact: no distance limit, so a far-off node comes in to its connections
ok(T.tidy({ ...far, compact: true }).nodes.get(2).y === 100, `compact Tidy brings a far-off node in (${T.tidy({ ...far, compact: true }).nodes.get(2).y})`);
const cm = T.tidy({ ...messy, compact: true });
ok(T.tidy({ nodes: apply(messy, cm), compact: true }).moved === 0, "compact Tidy twice = once");
ok(noOverlaps(apply(messy, cm)), "compact Tidy: no overlaps");

// tidy twice = tidy once
const once = T.tidy(messy);
const twice = T.tidy({ nodes: apply(messy, once) });
ok(twice.moved === 0, `tidying a tidy graph changes nothing (${twice.moved} moved)`);

// groups stay blocks around their own nodes, and don't overlap each other or loose nodes
const grouped = {
  nodes: [
    N(1, 30, 70, 300, 120), N(2, 40, 160, 300, 90, [{ slot: 0, origin: 1, originSlot: 0 }]),       // in group A, overlapping
    N(3, 900, 80, 300, 150, [{ slot: 0, origin: 2, originSlot: 0 }]), N(4, 920, 300, 300, 150),     // in group B
    N(5, 1200, 380, 200, 80),                                                                        // loose (center outside), overlapping group B's edge
  ],
  groups: [{ x: 0, y: 0, w: 380, h: 300 }, { x: 860, y: 20, w: 400, h: 460 }],
};
r = T.tidy(grouped);
ns = apply(grouped, r);
const gs = r.groups;
const inG = (n, g) => n.x >= g.x && n.y >= g.y && n.x + n.w <= g.x + g.w && n.y + n.h <= g.y + g.h;
ok(noOverlaps(ns), "no overlaps inside or around groups");
ok(inG(ns[0], gs[0]) && inG(ns[1], gs[0]) && inG(ns[2], gs[1]) && inG(ns[3], gs[1]), "each group still holds its own nodes");
ok(!overlap(gs[0], gs[1]), "groups don't overlap each other");
ok(!ns.filter((n) => n.id === 5).some((n) => gs.some((g) => overlap(n, g))), "a loose node isn't left on top of a group");

// nested groups
const nested = {
  nodes: [N(1, 50, 90, 200, 100), N(2, 60, 150, 200, 100)],
  groups: [{ x: 20, y: 30, w: 300, h: 260 }, { x: 0, y: 0, w: 600, h: 500 }],
};
r = T.tidy(nested);
ns = apply(nested, r);
ok(inG(ns[0], r.groups[0]) && inG(ns[1], r.groups[0]) && inG({ ...r.groups[0] }, r.groups[1]), "a group inside a group stays inside it");

// pinned nodes don't move; others make room
const pinned = { nodes: [N(1, 0, 0, 200, 100), N(2, 10, 40, 200, 100, [], { pinned: true }), N(3, 5, 300, 200, 100)] };
r = T.tidy(pinned);
ns = apply(pinned, r);
ok(r.nodes.get(2).x === 10 && r.nodes.get(2).y === 40, "a pinned node stays exactly where it is");
ok(noOverlaps(ns), "and nothing lands on it");

// only the selected nodes
const sel = { nodes: [N(1, 0, 0, 200, 100), N(2, 15, 30, 200, 100), N(3, 777, 777, 100, 100)], groups: [{ x: 700, y: 700, w: 300, h: 300 }], only: [1, 2] };
r = T.tidy(sel);
ok(r.nodes.get(3).x === 777 && r.nodes.get(3).y === 777 && r.groups.length === 0 && r.moved === 1, "Tidy selection moves only the selected nodes, groups untouched");

// collapsed nodes are small boxes, never aligned by slot
const col = { nodes: [N(1, 0, 0, 200, 100), N(2, 260, 37, 90, 30, [{ slot: 0, origin: 1, originSlot: 0 }], { collapsed: true })] };
r = T.tidy(col);
ok(r.nodes.get(2).y === 40, `a collapsed node only snaps (${r.nodes.get(2).y})`);
ok(T.tidy({ nodes: [] }).moved === 0, "an empty workflow is fine");

process.exit(fail ? 1 : 0);
