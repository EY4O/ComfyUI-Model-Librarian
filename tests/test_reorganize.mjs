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

process.exit(fail ? 1 : 0);
