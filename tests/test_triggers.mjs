// Trigger words (js/lib/triggers.js): finding the positive prompt, checking and adding words, without a browser.
import { pathToFileURL, fileURLToPath } from "node:url";
const PLUGIN = process.argv[2] || fileURLToPath(new URL("..", import.meta.url));
const T = await import(pathToFileURL(PLUGIN + "/js/lib/triggers.js").href);
let fail = 0;
const ok = (cond, m, extra = "") => { console.log((cond ? "PASS " : "FAIL ") + m + (cond ? "" : ` ${extra}`)); if (!cond) fail++; };

ok(JSON.stringify(T.splitWords(["ohwx woman", "tifa lockhart, final  fantasy", "Ohwx Woman", " "])) === JSON.stringify(["ohwx woman", "tifa lockhart", "final fantasy"]),
  "entries split on commas, spaces tidied, repeats dropped");
ok(T.hasWord("masterpiece, (ohwx woman:1.2), smiling", "OHWX woman"), "a phrase is found, ignoring case and a weight around it");
ok(!T.hasWord("ohwxian style", "ohwx") && !T.hasWord("", "ohwx"), "  not inside another word, not in an empty prompt");
ok(T.addWords("a lighthouse at dusk", ["ohwx", "paper cut"]) === "ohwx, paper cut, a lighthouse at dusk" && T.addWords("", ["ohwx"]) === "ohwx",
  "missing words go in front of the prompt");

// a small graph shaped like LiteGraph's: nodes with inputs (name, type, link) and widgets, links by id
function graph(nodes, links) {
  return { _nodes: nodes, links: new Map(links.map(([id, origin]) => [id, { id, origin_id: origin }])), getNodeById: (id) => nodes.find((n) => n.id === id) };
}
const W = (name, value) => ({ name, value });
const In = (name, type, link = null) => ({ name, type, link });

// sampler <- CLIPTextEncode (positive), negative ignored
let g = graph([
  { id: 1, title: "Positive", type: "CLIPTextEncode", inputs: [In("clip", "CLIP", 9)], widgets: [W("text", "a lighthouse")] },
  { id: 2, title: "Negative", type: "CLIPTextEncode", inputs: [In("clip", "CLIP", 9)], widgets: [W("text", "blurry")] },
  { id: 3, type: "KSampler", inputs: [In("model", "MODEL"), In("positive", "CONDITIONING", 11), In("negative", "CONDITIONING", 12)], widgets: [W("sampler_name", "euler")] },
  { id: 4, type: "KSampler", inputs: [In("positive", "CONDITIONING", 13)], widgets: [] },   // a second pass on the same prompt
], [[11, 1], [12, 2], [13, 1]]);
let ps = T.positivePrompts(g);
ok(ps.length === 1 && ps[0].sources[0].node.id === 1, "the positive prompt is found, once even when two samplers use it");
let st = T.wordStatus(["lighthouse", "ohwx"], ps);
ok(st[0].present && !st[1].present, "word status: in the prompt or not");
const changed = T.addToPrompts(["ohwx"], ps, (s, v) => { s.widget.value = v; });
ok(changed === 1 && g._nodes[0].widgets[0].value === "ohwx, a lighthouse" && g._nodes[1].widgets[0].value === "blurry", "added to the positive prompt only");
ok(T.addToPrompts(["ohwx"], ps, () => { throw new Error("no"); }) === 0, "  and not again");

// sampler <- ConditioningCombine <- CLIPTextEncode whose text comes from a StringConcatenate of two String nodes
g = graph([
  { id: 1, type: "PrimitiveStringMultiline", title: "Subject", inputs: [], widgets: [W("value", "a woman reading")] },
  { id: 2, type: "PrimitiveStringMultiline", title: "Style", inputs: [], widgets: [W("value", "paper cut style")] },
  { id: 3, type: "StringConcatenate", inputs: [In("string_a", "STRING", 21), In("string_b", "STRING", 22)], widgets: [W("delimiter", ", ")] },
  { id: 4, type: "CLIPTextEncode", inputs: [In("clip", "CLIP"), In("text", "STRING", 23)], widgets: [W("text", "")] },
  { id: 5, type: "ConditioningCombine", inputs: [In("conditioning_1", "CONDITIONING", 24), In("conditioning_2", "CONDITIONING")], widgets: [] },
  { id: 6, type: "KSampler", inputs: [In("positive", "CONDITIONING", 25)], widgets: [] },
], [[21, 1], [22, 2], [23, 3], [24, 4], [25, 5]]);
ps = T.positivePrompts(g);
ok(ps.length === 1 && ps[0].sources.map((s) => s.node.id).join() === "1,2", "a prompt built from String nodes: both texts are its sources");
ok(T.wordStatus(["paper cut style"], ps)[0].present, "  a word in either text counts");
T.addToPrompts(["ohwx"], ps, (s, v) => { s.widget.value = v; });
ok(g._nodes[0].widgets[0].value === "ohwx, a woman reading" && g._nodes[1].widgets[0].value === "paper cut style", "  a missing word goes in front of the first text");
ok(T.positivePrompts(graph([{ id: 1, type: "KSampler", inputs: [In("positive", "CONDITIONING")], widgets: [] }], [])).length === 0, "nothing connected: no prompt");

// matching as the model reads it
ok(!T.hasWord("café scene", "caf") && T.hasWord("Ваня улыбается", "Ваня"), "words in any alphabet, not inside a longer word");
ok(!T.hasWord("<lora:mystyle:0.8> a cat", "mystyle"), "a <lora:…> tag isn't the trigger word");
ok(T.hasWord("(masterpiece:1.2), best", "(masterpiece)") && T.hasWord("blue_hair, smile", "blue hair") && T.hasWord("artist \\(style\\)", "artist (style)"),
  "weights, underscores and escaped brackets don't hide a word");
ok(T.addWords("a cat", ["artist (style)"]) === "artist \\(style\\), a cat" && T.addWords("x", ["already \\(escaped\\)"]) === "already \\(escaped\\), x",
  "brackets in an added word are escaped once, so they aren't read as a weight");

// bypassed samplers are skipped; reroutes and Flux's guider are followed
{
  const g = graph([
    { id: 1, type: "CLIPTextEncodeFlux", inputs: [In("clip", "CLIP")], widgets: [W("clip_l", "a lighthouse"), W("t5xxl", "a lighthouse at dusk"), W("guidance", 3.5)] },
    { id: 2, type: "Reroute", inputs: [In("", "*", 31)], widgets: [] },
    { id: 3, type: "BasicGuider", inputs: [In("model", "MODEL"), In("conditioning", "CONDITIONING", 32)], widgets: [] },
    { id: 4, type: "CLIPTextEncode", inputs: [In("clip", "CLIP")], widgets: [W("text", "old pass")] },
    { id: 5, type: "KSampler", mode: 4, inputs: [In("positive", "CONDITIONING", 33)], widgets: [] },
  ], [[31, 1], [32, 2], [33, 4]]);
  const ps = T.positivePrompts(g);
  ok(ps.length === 1 && ps[0].sources[0].node.id === 1 && ps[0].sources[0].widget.name === "clip_l",
    `Flux: the guider's conditioning through a reroute; the bypassed sampler's prompt left out (${ps.map((p) => p.sources[0].node.id)})`);
}

process.exit(fail ? 1 : 0);
