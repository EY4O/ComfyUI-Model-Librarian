// Library filtering and sorting (js/lib/libview.js), without a browser.
import { pathToFileURL, fileURLToPath } from "node:url";
const PLUGIN = process.argv[2] || fileURLToPath(new URL("..", import.meta.url));
const V = await import(pathToFileURL(PLUGIN + "/js/lib/libview.js").href);
let fail = 0;
const eq = (a, b, m) => { const ok = JSON.stringify(a) === JSON.stringify(b); console.log((ok ? "PASS " : "FAIL ") + m + (ok ? "" : ` got ${JSON.stringify(a)}`)); if (!ok) fail++; };

const E = [
  { id: "a", name: "paper_cut.safetensors", title: "Paper Cut", rel: "Illustrious/paper_cut.safetensors", root_name: "Lora", family: "Illustrious", has_meta: true, model_id: 1,
    size: 200, mtime: 3, use_count: 42, last_used: 1000, notes: { rating: 5, note: "best at 0.7", tags: ["keeper"] }, trained_words: ["papercut"] },
  { id: "b", name: "clay.safetensors", title: null, rel: "Qwen/clay.safetensors", root_name: "Lora", family: "Qwen", has_meta: false, size: 900, mtime: 9,
    use_count: 3, last_used: 5000, hf: { repo: "lab/clay", tags: ["3d"] }, update: { id: 2 } },
  { id: "c", name: "mystery.safetensors", title: null, rel: "mystery.safetensors", root_name: "Lora", family: null, has_meta: false, size: 50, mtime: 1 },
  { id: "d", name: "aurora.safetensors", title: "Aurora", rel: "Illustrious/aurora.safetensors", root_name: "Lora", family: "Illustrious", has_meta: true, model_id: 2,
    size: 600, mtime: 5, use_count: 42, last_used: 900, notes: { rating: 3 } },
];
const ids = (l) => l.map((e) => e.id);
const f = (v, o) => ids(V.filterEntries(E, v, o));

eq(f({ folder: "Illustrious" }), ["a", "d"], "folder filter");
eq(f({ folder: "Lora/Qwen" }, { multiRoot: true }), ["b"], "folder filter with the root name when there are several roots");
eq(f({ family: "__unknown" }), ["c"], "unknown base model");
eq(f({ family: "Qwen" }), ["b"], "base model filter");
eq(f({ onlyMissing: true }), ["b", "c"], "missing info only");
eq(f({ onlyUpdates: true }), ["b"], "updates only");
eq(f({ onlyUnused: true }, { unused: new Set(["c"]) }), ["c"], "unused only");
eq(f({ source: "hf" }), ["b"], "source: HuggingFace");
eq(f({ source: "civitai" }), ["a", "d"], "source: CivitAI");
eq(f({ source: "none" }), ["c"], "source: unknown");
eq(f({ minRating: 4 }), ["a"], "minimum rating");
eq(f({ search: "keeper" }), ["a"], "search finds my tags");
eq(f({ search: "0.7" }), ["a"], "search finds my notes");
eq(f({ search: "3d" }), ["b"], "search finds HuggingFace tags");
eq(f({ search: "PAPERCUT" }), ["a"], "search finds trigger words, any case");

const s = (sort) => ids(V.sortEntries(E, sort));
eq(s("folder"), ["d", "a", "c", "b"], "folder order (by path)");
eq(s("name"), ["d", "b", "c", "a"], "name (title, else file name)");
eq(s("used"), ["d", "a", "b", "c"], "most used; ties by name");
eq(s("recent"), ["b", "a", "d", "c"], "recently used; never-used last");
eq(s("rating"), ["a", "d", "b", "c"], "my rating");
eq(s("size"), ["b", "d", "a", "c"], "size");
eq(s("newest"), ["b", "d", "a", "c"], "newest file");
eq(ids(E), ["a", "b", "c", "d"], "sorting doesn't change the input");

eq(V.stars(3), "★★★☆☆", "stars");
eq([V.ago(null), V.ago(1000, 1000 + 3600), V.ago(1000, 1000 + 86400 * 1.5), V.ago(1000, 1000 + 86400 * 12)], ["never", "today", "yesterday", "12 days ago"], "ago");
eq(V.sourceOf({ model_id: 1, hf: {} }), "civitai", "CivitAI wins when both are known");
process.exit(fail ? 1 : 0);
