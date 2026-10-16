// Storage history chart data (js/lib/storehist.js), without a browser.
import { pathToFileURL, fileURLToPath } from "node:url";
const PLUGIN = process.argv[2] || fileURLToPath(new URL("..", import.meta.url));
const { seriesOf, dailyMoves, niceMax } = await import(pathToFileURL(PLUGIN + "/js/lib/storehist.js").href);
let fail = 0;
const eq = (a, b, m) => { const ok = JSON.stringify(a) === JSON.stringify(b); console.log((ok ? "PASS " : "FAIL ") + m + (ok ? "" : ` got ${JSON.stringify(a)}`)); if (!ok) fail++; };
const GB = 1024 ** 3;

const samples = [
  { t: 100, drives: { "F:": { role: "archive", free: 9, total: 10 }, "E:": { role: "models", free: 5, total: 10 } } },
  { t: 200, drives: { "E:": { role: "models", free: 4, total: 10 }, "F:": { role: "archive", free: 8, total: 10 } } },
];
const s = seriesOf(samples, [{ label: "E:", role: "models" }, { label: "F:", role: "archive" }]);
eq(s.map((x) => x.label), ["E:", "F:"], "drives in the server's order (models drive first: it keeps its colour)");
eq(s[0].points, [[100, 5], [200, 4]], "one point per sample");
eq(seriesOf([], []), [], "no samples, no lines");

const now = new Date(2026, 9, 16, 15, 0, 0).getTime() / 1000;
const days = dailyMoves([{ day: "2026-10-15", archived: 3 * GB, archived_n: 1 }], 3, now);
eq(days.map((d) => d.day), ["2026-10-14", "2026-10-15", "2026-10-16"], "every day of the range, oldest first");
eq([days[1].archived, days[0].archived, days[2].restored], [3 * GB, 0, 0], "days without moves are zero");

eq(niceMax(380 * GB) / GB, 400, "380 GB → a 400 GB axis");
eq(niceMax(2.9 * 1024 * GB) / GB / 1024, 3, "2.9 TB → a 3 TB axis (round in TB)");
eq(niceMax(55 * GB) / GB, 60, "55 GB → 60");
eq(niceMax(0) / GB, 1, "nothing yet → 1 GB");

console.log(fail ? `\nFAILED: ${fail}` : "\nALL PASSED");
process.exit(fail ? 1 : 0);
