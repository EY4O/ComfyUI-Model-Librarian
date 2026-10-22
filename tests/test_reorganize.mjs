// Re-organize (js/lib/reorganize.js): a layered layout from the connections, without a browser.
import { pathToFileURL, fileURLToPath } from "node:url";
const PLUGIN = process.argv[2] || fileURLToPath(new URL("..", import.meta.url));
const R = await import(pathToFileURL(PLUGIN + "/js/lib/reorganize.js").href);
const T = await import(pathToFileURL(PLUGIN + "/js/lib/tidy.js").href);
let fail = 0;
const ok = (cond, m, extra = "") => { console.log((cond ? "PASS " : "FAIL ") + m + (cond ? "" : ` ${extra}`)); if (!cond) fail++; };

const N = (id, x, y, w, h, inputs = [], extra = {}) => ({ id, x, y, w, h, inputs, ...extra });
const I = (slot, origin, originSlot = 0) => ({ slot, origin, originSlot });
const overlap = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
const apply = (g, r) => g.nodes.map((n) => ({ ...n, ...r.nodes.get(n.id) }));
const noOverlaps = (ns) => ns.every((a, i) => ns.every((b, j) => i >= j || !overlap(a, b)));
const rightwards = (g, ns) => {
  const by = Object.fromEntries(ns.map((n) => [n.id, n]));
  return g.nodes.every((n) => (n.inputs || []).every((inp) => by[inp.origin].x + by[inp.origin].w < by[n.id].x));
};

// a text-to-image graph thrown around the canvas: the sampler far left, the loader far right, save on top
const scrambled = {
  nodes: [
    N(1, 2600, 900, 300, 130),                                   // checkpoint loader (MODEL 0, CLIP 1, VAE 2)
    N(2, 1400, -300, 300, 160, [I(0, 1, 0), I(1, 1, 1)]),         // LoRA
    N(3, 300, 600, 400, 230, [I(0, 2, 1)]),                       // positive
    N(4, 2000, 200, 400, 230, [I(0, 2, 1)]),                      // negative
    N(5, 900, 1300, 300, 140),                                    // empty latent
    N(6, 0, 0, 320, 300, [I(0, 2, 0), I(1, 3, 0), I(2, 4, 0), I(3, 5, 0)]), // sampler
    N(7, 1700, 1100, 210, 80, [I(0, 6, 0), I(1, 1, 2)]),          // decode
    N(8, 500, -500, 420, 450, [I(0, 7, 0)]),                      // save
  ],
};
let r = R.reorganize(scrambled);
let ns = apply(scrambled, r);
ok(rightwards(scrambled, ns), "every wire runs left to right (each node after what feeds it)");
ok(noOverlaps(ns), "no overlaps");
ok(ns.every((n) => n.x % T.GRID === 0 && n.y % T.GRID === 0), "on the grid");
const by = Object.fromEntries(ns.map((n) => [n.id, n]));
ok(by[3].x === by[4].x, "both prompts in one column");
ok(by[5].x < by[6].x && by[5].x > by[1].x, `the empty latent sits just before the sampler it feeds, not at the far left (${by[5].x} vs loader ${by[1].x}, sampler ${by[6].x})`);
const minX = Math.min(...scrambled.nodes.map((n) => n.x)), minY = Math.min(...scrambled.nodes.map((n) => n.y));
ok(Math.min(...ns.map((n) => n.x)) === T.GRID * Math.round(minX / T.GRID) && Math.min(...ns.map((n) => n.y)) === T.GRID * Math.round(minY / T.GRID), "keeps the workflow's top-left corner");
ok(r.moved === 8, `everything was moved (${r.moved})`);
const again = R.reorganize({ nodes: ns });
ok(again.moved === 0, `re-organizing a re-organized workflow changes nothing (${again.moved} moved)`);

// crossed wires get untangled: A1 -> B2 and A2 -> B1 drawn crossed
const crossed = { nodes: [N(1, 0, 0, 200, 100), N(2, 0, 200, 200, 100), N(3, 400, 0, 200, 100, [I(0, 2)]), N(4, 400, 200, 200, 100, [I(0, 1)])] };
r = R.reorganize(crossed);
ns = apply(crossed, r);
const c = Object.fromEntries(ns.map((n) => [n.id, n]));
ok((c[1].y < c[2].y) === (c[4].y < c[3].y), "crossed wires are untangled");

// a simple chain comes out straight (the connected slots at the same height)
const chain = { nodes: [N(1, 500, 300, 200, 100), N(2, 0, 0, 200, 140, [I(0, 1)]), N(3, 900, 900, 200, 80, [I(0, 2)])] };
r = R.reorganize(chain);
const ch = apply(chain, r);
ok(ch[0].y === ch[1].y && ch[1].y === ch[2].y, `a chain lines up (${ch.map((n) => n.y)})`);

// separate pieces are laid out on their own and stacked
const two = { nodes: [N(1, 0, 0, 200, 100), N(2, 900, 900, 200, 100, [I(0, 1)]), N(3, 50, 500, 200, 100), N(4, 70, 80, 200, 100, [I(0, 3)]), N(5, 3000, 3000, 300, 120)] };
r = R.reorganize(two);
ns = apply(two, r);
ok(noOverlaps(ns) && rightwards(two, ns), "two pipelines and a loose node: no overlaps, wires rightwards");
const p1 = [ns[0], ns[1]], p2 = [ns[2], ns[3]];
const bottom = (p) => Math.max(...p.map((n) => n.y + n.h)), top = (p) => Math.min(...p.map((n) => n.y));
ok(top(p2) >= bottom(p1) + R.PIECE_GAP - T.GRID || top(p1) >= bottom(p2) + R.PIECE_GAP - T.GRID, "the pieces are stacked, apart");

// groups stay blocks around their own nodes, placed by what they connect to
const grouped = {
  nodes: [N(1, 900, 900, 300, 120), N(2, 950, 1000, 300, 150, [I(0, 1)]), N(3, 0, 0, 400, 200, [I(0, 2)]), N(4, 30, 260, 400, 200, [I(0, 2)]), N(5, 2000, 0, 300, 200, [I(0, 3), I(1, 4)])],
  groups: [{ x: 880, y: 860, w: 400, h: 330 }, { x: -20, y: -40, w: 480, h: 540 }],
};
r = R.reorganize(grouped);
ns = apply(grouped, r);
const gs = r.groups;
const inG = (n, g) => n.x >= g.x && n.y >= g.y && n.x + n.w <= g.x + g.w && n.y + n.h <= g.y + g.h;
ok(noOverlaps(ns), "groups: no overlapping nodes");
ok(inG(ns[0], gs[0]) && inG(ns[1], gs[0]) && inG(ns[2], gs[1]) && inG(ns[3], gs[1]) && !overlap(gs[0], gs[1]), "each group holds its nodes; groups don't overlap");
ok(gs[0].x + gs[0].w < gs[1].x && gs[1].x + gs[1].w < ns[4].x, "groups placed in flow order: models group, then prompts group, then the sampler");

// pinned nodes stay; the layout keeps clear of them
const pinned = { nodes: [N(1, 0, 0, 200, 100), N(2, 300, 0, 200, 100, [I(0, 1)]), N(9, 10, 20, 250, 150, [], { pinned: true })] };
r = R.reorganize(pinned);
ns = apply(pinned, r);
ok(r.nodes.get(9).x === 10 && r.nodes.get(9).y === 20 && noOverlaps(ns), "a pinned node stays and nothing lands on it");
ok(R.reorganize({ nodes: [] }).moved === 0, "an empty workflow is fine");
ok(R.reorganize({ nodes: [N(1, 0, 0, 100, 100, [I(0, 2)]), N(2, 300, 0, 100, 100, [I(0, 1)])] }).nodes.size === 2, "a loop (not valid in ComfyUI) doesn't hang it");

// a pinned node inside a group: the group stays put too (it used to be carried along with its group)
const pinGroup = {
  nodes: [N(1, 900, 900, 200, 100), N(2, 2000, 100, 200, 100, [I(0, 1)]), N(3, 60, 80, 200, 100, [I(0, 2)], { pinned: true }), N(4, 300, 80, 200, 100, [I(0, 3)])],
  groups: [{ x: 40, y: 40, w: 500, h: 180 }],
};
r = R.reorganize(pinGroup);
ok(r.nodes.get(3).x === 60 && r.nodes.get(3).y === 80 && r.groups[0].x <= 40 && r.groups[0].x + r.groups[0].w >= 260, "a pinned node in a group doesn't move with its group");
ns = apply(pinGroup, r);
ok(noOverlaps(ns), "  and nothing lands on it");

// Set/Get nodes: the value passed by name orders the layout like a wire, and keeps it one piece
const wireless = {
  nodes: [
    N(1, 0, 0, 300, 100),                                      // loader
    N(2, 400, 0, 200, 60, [I(0, 1)], { sets: "model" }),       // Set "model"
    N(3, 0, 900, 200, 60, [], { gets: "model" }),              // Get "model", far away
    N(4, 300, 900, 300, 200, [I(0, 3)]),                       // sampler fed by the Get
    N(5, 700, 900, 200, 100, [I(0, 4)]),                       // decode
  ],
};
r = R.reorganize(wireless);
ns = apply(wireless, r);
const wb = Object.fromEntries(ns.map((n) => [n.id, n]));
ok(wb[3].x > wb[2].x && wb[3].x < wb[4].x && wb[4].x < wb[5].x, `a Get comes after its Set and just before what it feeds (${[2, 3, 4, 5].map((i) => wb[i].x)})`);
ok(Math.abs(wb[3].y - wb[4].y) < 100, "  lined up with what it feeds");
ok(Math.max(...ns.map((n) => n.y + n.h)) - Math.min(...ns.map((n) => n.y)) < 500, "  one piece, not stacked pieces");

// a branch that only feeds the end sits near the end, not at the start
const branch = {
  nodes: [N(1, 0, 0, 200, 100), N(2, 300, 0, 200, 100, [I(0, 1)]), N(3, 600, 0, 200, 100, [I(0, 2)]), N(4, 900, 0, 200, 100, [I(0, 3)]),
    N(5, 0, 400, 200, 100), N(6, 300, 400, 200, 100, [I(0, 5)]), N(7, 1200, 0, 200, 150, [I(0, 4), I(1, 6)])],
};
r = R.reorganize(branch);
const bb = Object.fromEntries(apply(branch, r).map((n) => [n.id, n]));
ok(bb[6].x === bb[4].x && bb[5].x === bb[3].x, `a short branch into the last node is placed just before it (${bb[5].x}, ${bb[6].x} vs ${bb[3].x}, ${bb[4].x})`);

// loose nodes (a note, a bypasser) keep their place beside their nearest neighbour
const notes = {
  nodes: [N(1, 2000, 2000, 200, 100), N(2, 0, 0, 200, 100, [I(0, 1)]), N(3, 400, 300, 200, 100, [I(0, 2)]),
    N(9, 2000, 1850, 300, 100)],   // a label above the loader
};
r = R.reorganize(notes);
ns = apply(notes, r);
const nb = Object.fromEntries(ns.map((n) => [n.id, n]));
ok(nb[9].x === nb[1].x && nb[9].y === nb[1].y - 150, `a loose note stays where it was next to its neighbour (${nb[9].x},${nb[9].y} vs ${nb[1].x},${nb[1].y})`);
ok(noOverlaps(ns), "  without overlapping anything");

// just the selected nodes: laid out where they are, the rest untouched
{
  const g = { nodes: [N(1, 500, 500, 200, 100), N(2, 100, 900, 200, 100, [I(0, 1)]), N(3, 900, 100, 200, 100, [I(0, 2)]), N(7, 5000, 5000, 200, 100, [I(0, 3)])],
    groups: [{ x: 4900, y: 4900, w: 400, h: 300 }], only: [1, 2, 3] };
  const r = R.reorganize(g);
  const q = Object.fromEntries(apply(g, r).map((n) => [n.id, n]));
  ok(q[7].x === 5000 && q[7].y === 5000 && r.groups.length === 0, "selection: other nodes and groups are untouched");
  ok(q[1].x < q[2].x && q[2].x < q[3].x && Math.min(q[1].x, q[2].x, q[3].x) === 100 && Math.min(q[1].y, q[2].y, q[3].y) === 100, "selection: laid out in order, from the selection's top-left corner");
}

// a huge workflow with long wires stays quick (crossings used to be counted pair by pair: minutes, a frozen tab)
{
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const nodes = [];
  for (let i = 0; i < 1000; i++) {
    const inputs = i ? [I(0, i - 1 - Math.floor(rnd() * Math.min(i, 8)))] : [];
    if (i > 20 && rnd() < 0.5) inputs.push(I(1, Math.floor(rnd() * i)));
    nodes.push(N(i, rnd() * 20000, rnd() * 20000, 200 + rnd() * 200, 80 + rnd() * 300, inputs));
  }
  const t = Date.now();
  const big = R.reorganize({ nodes });
  const ms = Date.now() - t;
  const placed = apply({ nodes }, big);
  ok(ms < 5000 && big.nodes.size === 1000, `1000 nodes with long wires laid out in ${ms} ms`);
  ok(rightwards({ nodes }, placed), "  every wire still runs left to right");
}

// shared loaders together: a checkpoint and a VAE used by both stages stay top-left; a loader used once
// (stage 2's upscale model) still sits just before what it uses
{
  const stages = {
    nodes: [
      N(1, 3000, 900, 300, 100),                                   // checkpoint: both samplers
      N(2, 2000, 1500, 300, 60),                                   // VAE: both decodes
      N(3, 900, 100, 300, 200, [I(0, 1)]),                         // sampler 1
      N(4, 1300, 100, 200, 60, [I(0, 3), I(1, 2)]),                // decode 1
      N(9, 0, 1200, 300, 60),                                      // upscale model: stage 2 only
      N(5, 1700, 100, 250, 100, [I(0, 4), I(1, 9)]),               // upscale
      N(6, 2100, 100, 300, 200, [I(0, 1), I(1, 5)]),               // sampler 2
      N(7, 2500, 100, 200, 60, [I(0, 6), I(1, 2)]),                // decode 2
      N(8, 2900, 100, 300, 300, [I(0, 7)]),                        // save
    ],
  };
  const plain = Object.fromEntries(apply(stages, R.reorganize(stages)).map((n) => [n.id, n]));
  const r = R.reorganize({ ...stages, sharedLoaders: true });
  const ns = apply(stages, r);
  const q = Object.fromEntries(ns.map((n) => [n.id, n]));
  const left = Math.min(...ns.map((n) => n.x)), top = Math.min(...ns.map((n) => n.y));
  ok(q[1].x === left && q[2].x === left, `shared loaders: the checkpoint and VAE are in the first column (${q[1].x}, ${q[2].x}; left ${left})`);
  ok(q[1].y === top && q[2].y > q[1].y && q[2].y - (q[1].y + q[1].h) <= R.NODE_GAP + 10, "  stacked together at the top, in the order they're first used");
  ok(q[9].x > left && q[9].x + q[9].w < q[5].x && q[9].x === plain[9].x, "  a loader used once still sits just before what it feeds");
  ok(plain[2].x > left, "  (without the option the VAE moves to just before its first use)");
  ok(noOverlaps(ns) && rightwards(stages, ns), "  no overlaps, every wire left to right");
}

process.exit(fail ? 1 : 0);
