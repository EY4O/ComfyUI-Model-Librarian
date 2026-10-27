// Character Select's picker (js/lib/characters.js), without a browser: the tags the node shows, turning one off, the
// outfit a character starts with, searching your characters. Made-up characters only.
import { pathToFileURL, fileURLToPath } from "node:url";
const PLUGIN = process.argv[2] || fileURLToPath(new URL("..", import.meta.url));
const C = await import(pathToFileURL(PLUGIN + "/js/lib/characters.js").href);
let fail = 0;
const ok = (cond, m, extra = "") => { console.log((cond ? "PASS " : "FAIL ") + m + (cond ? "" : ` ${extra}`)); if (!cond) fail++; };
const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

const aurelia = { id: "chr_1", name: "Aurelia", series: "Lighthouse Tales", tag: "aurelia_(lighthouse_tales)", appearance: ["silver hair", "Long_Hair", "blue eyes"],
  outfits: { winter: ["red coat", "scarf"], default: ["white dress", "silver hair"] } };

let tags = C.tagsFor(aurelia, "default");
ok(same(tags.map((x) => [x.t, x.part]), [["aurelia (lighthouse tales)", "character"], ["silver hair", "appearance"], ["Long Hair", "appearance"],
  ["blue eyes", "appearance"], ["white dress", "outfit"]]), "tags: its tag, appearance, the outfit; spaces for underscores; none twice", JSON.stringify(tags));
tags = C.tagsFor(aurelia, "winter", { character: false, series: true, appearance: false }, "Scarf, long hair");
ok(same(tags.map((x) => [x.t, x.off]), [["lighthouse tales", false], ["red coat", false], ["scarf", true]]), "  parts switched off or on; a tag turned off shown as off");
ok(same(C.tagsFor(aurelia, "", { appearance: false }).map((x) => x.t), ["aurelia (lighthouse tales)"]) && same(C.tagsFor(null, "x"), []), "  no outfit; no character");

ok(C.toggleOff("", "silver_hair") === "silver hair" && C.toggleOff("silver hair, scarf", "Silver Hair") === "scarf" && C.toggleOff("scarf", "red coat") === "scarf, red coat",
  "toggleOff: a tag left out, then put back (any case)");
ok(C.firstOutfit(aurelia) === "default" && C.firstOutfit({ outfits: { winter: [] } }) === "winter" && C.firstOutfit({ outfits: {} }) === "" && C.firstOutfit(null) === "",
  "firstOutfit: default when there is one, else the first, else none");

const list = [aurelia, { name: "Nova", series: "Starfall", tag: "nova_(starfall)" }, { name: "Lumen", series: "Nightglass", tag: "lumen" }, { name: "Stella", series: "Nova Saga", tag: "stella" }];
ok(same(C.search(list, "nova").map((c) => c.name), ["Nova", "Stella"]), "search: by name, series or tag, names starting with it first");
ok(C.search(list, " ").length === 4 && C.search(list, "lighthouse_tales")[0].name === "Aurelia", "  nothing typed: all; underscores as spaces");

ok(C.loraLabel("chars\\aurelia_v2.safetensors") === "aurelia_v2" && C.loraLabel("a/b/x.ckpt") === "x" && C.loraLabel(null) === "", "loraLabel: a LoRA's file name without folders or extension");

process.exit(fail ? 1 : 0);
