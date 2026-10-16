// Share: model links written into a saved copy of a workflow (js/lib/workflow.js embedInJson).
import { pathToFileURL, fileURLToPath } from "node:url";
const PLUGIN = process.argv[2] || fileURLToPath(new URL("..", import.meta.url));
const { embedInJson } = await import(pathToFileURL(PLUGIN + "/js/lib/workflow.js").href);
let fail = 0;
const eq = (a, b, m) => { const ok = JSON.stringify(a) === JSON.stringify(b); console.log((ok ? "PASS " : "FAIL ") + m + (ok ? "" : ` got ${JSON.stringify(a)}`)); if (!ok) fail++; };

const rows = [
  { value: "sdxl/base.safetensors", folder: "checkpoints", url: "https://civitai.com/api/download/models/1", sha256: "a".repeat(64) },
  { value: "clay", folder: "loras", lm: true, file: "clay.safetensors", url: "https://huggingface.co/x/y/resolve/main/clay.safetensors", sha256: null },
  { value: "nolink.safetensors", folder: "vae", url: null },
];
const wf = {
  nodes: [
    { id: 1, type: "CheckpointLoaderSimple", widgets_values: ["sdxl/base.safetensors"], properties: { models: [{ name: "sdxl/base.safetensors", url: "https://old" }, { name: "keep.safetensors", url: "https://k" }] } },
    { id: 2, type: "Lora Loader (LoraManager)", widgets_values: ["<lora:clay:1>", [{ name: "clay", strength: 1, active: true }]] },
    { id: 3, type: "VAELoader", widgets_values: ["nolink.safetensors"] },
    { id: 4, type: "Note", widgets_values: ["sdxl/base.safetensors"] },
  ],
  definitions: { subgraphs: [{ id: "sg", nodes: [{ id: 9, type: "CheckpointLoaderSimple", widgets_values: { ckpt_name: "SDXL/BASE.safetensors" } }] }] },
};
const n = embedInJson(wf, rows);
eq(n, 3, "three nodes get links (checkpoint, LoRA Manager, the subgraph's loader)");
eq(wf.nodes[0].properties.models, [
  { name: "keep.safetensors", url: "https://k" },
  { name: "sdxl/base.safetensors", url: "https://civitai.com/api/download/models/1", directory: "checkpoints", hash: "a".repeat(64), hash_type: "sha256" },
], "the old link for the same file is replaced; other entries kept");
eq(wf.nodes[1].properties.models, [{ name: "clay.safetensors", url: "https://huggingface.co/x/y/resolve/main/clay.safetensors", directory: "loras" }],
  "LoRA Manager LoRA stored on its node under the file name, once");
eq(wf.nodes[2].properties, undefined, "no link known: node left alone");
eq(wf.nodes[3].properties, undefined, "notes are skipped");
eq(wf.definitions.subgraphs[0].nodes[0].properties.models[0].name, "SDXL/BASE.safetensors", "subgraph loader: named as its widget names it");

console.log(fail ? `\nFAILED: ${fail}` : "\nALL PASSED");
process.exit(fail ? 1 : 0);
