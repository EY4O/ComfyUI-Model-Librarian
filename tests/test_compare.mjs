// Compare a LoRA's strengths (js/lib/compare.js): copies of everything after the LoRA, one per strength.
import { pathToFileURL, fileURLToPath } from "node:url";
const PLUGIN = process.argv[2] || fileURLToPath(new URL("..", import.meta.url));
const C = await import(pathToFileURL(PLUGIN + "/js/lib/compare.js").href);
let fail = 0;
const ok = (cond, m, extra = "") => { console.log((cond ? "PASS " : "FAIL ") + m + (cond ? "" : ` ${extra}`)); if (!cond) fail++; };

ok(JSON.stringify(C.parseStrengths("0, 0.4 .7;1, 1, x, 9")) === "[0,0.4,0.7,1]", "strengths: numbers read, repeats and nonsense dropped");
ok(C.parseStrengths("0 0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9").length === 8, "  at most 8");

const api = {
  1: { class_type: "CheckpointLoaderSimple", inputs: { ckpt_name: "base.safetensors" } },
  2: { class_type: "LoraLoader", inputs: { model: ["1", 0], clip: ["1", 1], lora_name: "Styles/paper_cut.safetensors", strength_model: 0.8, strength_clip: 0.8 } },
  3: { class_type: "CLIPTextEncode", inputs: { clip: ["2", 1], text: "a lighthouse" }, _meta: { title: "Positive" } },
  4: { class_type: "CLIPTextEncode", inputs: { clip: ["1", 1], text: "blurry" } },
  5: { class_type: "EmptyLatentImage", inputs: { width: 1024, height: 1024, batch_size: 1 } },
  6: { class_type: "KSampler", inputs: { model: ["2", 0], positive: ["3", 0], negative: ["4", 0], latent_image: ["5", 0], seed: 42, steps: 20 } },
  7: { class_type: "VAEDecode", inputs: { samples: ["6", 0], vae: ["1", 2] } },
  8: { class_type: "SaveImage", inputs: { images: ["7", 0], filename_prefix: "test" } },
};
const r = C.strengthGraph(api, "paper_cut", [0, 0.5, 1]);
const p = r.prompt;
ok(r.copies === 3 && r.nodes === 5, `everything after the LoRA (loader, positive, sampler, decode, save) is copied (${r.nodes})`);
ok(Object.keys(p).length === 8 + 2 * 5, "  twice more, for 3 strengths");
const loaders = Object.values(p).filter((n) => n.class_type === "LoraLoader").map((n) => n.inputs.strength_model).sort();
ok(JSON.stringify(loaders) === "[0,0.5,1]", "each copy has its strength");
const saves = Object.values(p).filter((n) => n.class_type === "SaveImage").map((n) => n.inputs.filename_prefix).sort();
ok(JSON.stringify(saves) === JSON.stringify(["test_lora0", "test_lora0.5", "test_lora1"]), "  and saves with it in the name");
const samplers = Object.values(p).filter((n) => n.class_type === "KSampler");
ok(samplers.every((n) => n.inputs.seed === 42 && n.inputs.latent_image[0] === "5" && n.inputs.negative[0] === "4"), "same seed; the shared latent and negative aren't copied");
ok(samplers.every((n) => p[n.inputs.model[0]].class_type === "LoraLoader" && p[n.inputs.positive[0]].inputs.clip[0] === n.inputs.model[0]),
  "each copy is wired to its own loader");
ok(api[2].inputs.strength_model === 0.8, "the original workflow isn't changed");
ok(C.strengthGraph(api, "other_lora", [1]).error && C.strengthGraph(api, "paper_cut", []).error, "a LoRA that isn't there, or no strengths: says why");

// LoRA Manager's loader: the list entry and its <lora:> text change
const lm = {
  1: { class_type: "UNETLoader", inputs: { unet_name: "krea.safetensors" } },
  2: { class_type: "Lora Loader (LoraManager)", inputs: { model: ["1", 0], text: "<lora:paper_cut:0.8> <lora:ink:1>",
    loras: { __value__: [{ name: "paper_cut", strength: 0.8, clipStrength: 0.8, active: true }, { name: "ink", strength: 1, active: true }] } } },
  3: { class_type: "KSampler", inputs: { model: ["2", 0], seed: 1 } },
  4: { class_type: "PreviewImage", inputs: { images: ["3", 0] } },
};
const q = C.strengthGraph(lm, "paper_cut.safetensors", [0.3, 0.9]).prompt;
const lms = Object.values(q).filter((n) => n.class_type === "Lora Loader (LoraManager)");
ok(lms.length === 2 && lms.map((n) => n.inputs.loras.__value__[0].strength).sort().join() === "0.3,0.9" && lms.every((n) => n.inputs.loras.__value__[1].strength === 1),
  "LoRA Manager loader: only that LoRA's strength changes");
ok(lms.some((n) => n.inputs.text === "<lora:paper_cut:0.3> <lora:ink:1>"), "  in its <lora:> text too");

process.exit(fail ? 1 : 0);
