// Recipe -> ComfyUI graph: fill the open workflow, build a txt2img graph, LoRA Manager metadata.
import { pathToFileURL, fileURLToPath } from "node:url";
const PLUGIN = process.argv[2] || fileURLToPath(new URL("..", import.meta.url));
const A = await import(pathToFileURL(PLUGIN + "/js/lib/recipe_apply.js").href);
let fail = 0;
const ok = (c, m) => { console.log((c ? "PASS " : "FAIL ") + m); if (!c) fail++; };
const eq = (a, b, m) => { const c = JSON.stringify(a) === JSON.stringify(b); console.log((c ? "PASS " : "FAIL ") + m + (c ? "" : ` got ${JSON.stringify(a)}`)); if (!c) fail++; };

// ---- a tiny LiteGraph: nodes, links (Map), connect() replacing an input's old link
const LORAS = ["Illustrious\\watercolor_v3.safetensors", "soft_pastel.safetensors", "Illustrious\\detail.safetensors", "other.safetensors"];
const SPECS = {
  CheckpointLoaderSimple: { w: { ckpt_name: ["a.safetensors", "Illustrious\\illustriousXL_v20.safetensors"] }, out: ["MODEL", "CLIP", "VAE"] },
  LoraLoader: { w: { lora_name: LORAS, strength_model: 1, strength_clip: 1 }, in: [["model", "MODEL"], ["clip", "CLIP"]], out: ["MODEL", "CLIP"] },
  CLIPTextEncode: { w: { text: "" }, in: [["clip", "CLIP"]], out: ["CONDITIONING"] },
  EmptyLatentImage: { w: { width: 512, height: 512, batch_size: 1 }, out: ["LATENT"] },
  KSampler: { w: { seed: 0, control_after_generate: "fixed", steps: 20, cfg: 7, sampler_name: ["euler", "dpmpp_2m"], scheduler: ["normal", "karras"], denoise: 1 },
    in: [["model", "MODEL"], ["positive", "CONDITIONING"], ["negative", "CONDITIONING"], ["latent_image", "LATENT"]], out: ["LATENT"] },
  "Lora Loader (LoraManager)": { w: { text: "", loras: [] }, in: [["model", "MODEL"], ["clip", "CLIP"]], out: ["MODEL", "CLIP"] },
};
function graph() {
  const g = { _nodes: [], links: new Map(), next: 1, getNodeById: (id) => g._nodes.find((n) => n.id === id), add: (n) => { n.id ??= 100 + g._nodes.length; g._nodes.push(n); } };
  g.make = (type, id) => {
    const s = SPECS[type];
    const n = {
      id, type, mode: 0, pos: [0, 0], size: [200, 100],
      widgets: Object.entries(s.w).map(([name, v]) => Array.isArray(v) ? { name, value: v[0], options: { values: v } } : { name, value: v, options: {} }),
      inputs: (s.in || []).map(([name, type]) => ({ name, type, link: null })), outputs: s.out.map((type) => ({ type, links: [] })),
    };
    n.connect = (slot, target, tslot) => {
      const old = target.inputs[tslot].link;
      if (old != null) {
        const l = g.links.get(old), o = g.getNodeById(l.origin_id);
        o.outputs[l.origin_slot].links = o.outputs[l.origin_slot].links.filter((x) => x !== old);
        g.links.delete(old);
      }
      const lid = g.next++;
      g.links.set(lid, { id: lid, origin_id: n.id, origin_slot: slot, target_id: target.id, target_slot: tslot });
      n.outputs[slot].links.push(lid);
      target.inputs[tslot].link = lid;
    };
    if (id != null) g._nodes.push(n);
    return n;
  };
  return g;
}
const src = (g, node, name) => { const l = g.links.get(node.inputs.find((i) => i.name === name).link); return l && g.getNodeById(l.origin_id); };
const w = (n, name) => n.widgets.find((x) => x.name === name).value;

function basic() {
  const g = graph();
  const ck = g.make("CheckpointLoaderSimple", 1), lo = g.make("LoraLoader", 2), pos = g.make("CLIPTextEncode", 3), neg = g.make("CLIPTextEncode", 4);
  const lat = g.make("EmptyLatentImage", 5), ks = g.make("KSampler", 6);
  ck.connect(0, lo, 0); ck.connect(1, lo, 1);
  lo.connect(1, pos, 0); lo.connect(1, neg, 0); lo.connect(0, ks, 0);
  pos.connect(0, ks, 1); neg.connect(0, ks, 2); lat.connect(0, ks, 3);
  return { g, ck, lo, pos, neg, lat, ks };
}

const recipe = {
  prompt: { positive: "a lighthouse", negative: "blurry" }, model: { type: "checkpoint", file: "illustriousXL_v20" },
  settings: { seed: 81723, steps: 28, cfg: 5.5, sampler: "dpmpp_2m", scheduler: "karras", width: 832, height: 1216, clip_skip: 2 },
  loras: [{ file: "watercolor_v3", weight: 0.7, clip_weight: 0.5, hash: "AAAA", civitai_version_id: 111, display_name: "Watercolor Wash", version: "v3" }],
  base_model: "Illustrious", source: { url: "https://civitai.com/images/555" },
};
const items = [
  { kind: "checkpoint", status: "present", comfy_name: "Illustrious\\illustriousXL_v20.safetensors" },
  { kind: "lora", status: "present", comfy_name: "Illustrious\\watercolor_v3.safetensors", weight: 0.7, clip_weight: 0.5 },
  { kind: "lora", status: "present", comfy_name: "soft_pastel.safetensors", weight: 0.55 },
  { kind: "lora", status: "missing", download: { rel: "Illustrious/new_one.safetensors" }, weight: 1 },
  { kind: "lora", status: "present", comfy_name: "Illustrious\\detail.safetensors", weight: -1.5 },
];

// ---- resolved + syntax
const res = A.resolved(recipe, items);
eq(res.loras.map((l) => [l.stem, l.installed]), [["watercolor_v3", true], ["soft_pastel", true], ["new_one", false], ["detail", true]], "resolved: names + installed flags in recipe order");
eq(A.loraSyntax(res.loras), "<lora:watercolor_v3:0.7:0.5> <lora:soft_pastel:0.55> <lora:new_one:1> <lora:detail:-1.5>", "LoRA syntax (clip strength only when different)");

// ---- fill: one existing loader, three installed LoRAs -> two loaders inserted in the chain
{
  const { g, ck, lo, pos, neg, lat, ks } = basic();
  let made = 0;
  const r = A.fillWorkflow(g, recipe, items, { createNode: (t) => (made++, g.make(t)) });
  ok(r.ok, "fill: ok");
  eq([w(pos, "text"), w(neg, "text")], ["a lighthouse", "blurry"], "fill: positive + negative traced from the sampler");
  eq([w(ks, "seed"), w(ks, "steps"), w(ks, "cfg"), w(ks, "sampler_name"), w(ks, "scheduler")], [81723, 28, 5.5, "dpmpp_2m", "karras"], "fill: sampler settings");
  eq(w(ck, "ckpt_name"), "Illustrious\\illustriousXL_v20.safetensors", "fill: checkpoint set from the combo list");
  eq([w(lat, "width"), w(lat, "height")], [832, 1216], "fill: size");
  eq([w(lo, "lora_name"), w(lo, "strength_model"), w(lo, "strength_clip")], ["Illustrious\\watercolor_v3.safetensors", 0.7, 0.5], "fill: existing loader gets the first LoRA");
  eq(made, 2, "fill: two loaders added for the other installed LoRAs (missing one skipped)");
  const m1 = src(g, ks, "model"), m0 = src(g, m1, "model");
  eq([m1.type, w(m1, "lora_name"), w(m1, "strength_model")], ["LoraLoader", "Illustrious\\detail.safetensors", -1.5], "fill: sampler's model now comes from the last new loader");
  eq([w(m0, "lora_name"), src(g, m0, "model") === lo, src(g, m0, "clip") === lo], ["soft_pastel.safetensors", true, true], "fill: chain is checkpoint -> existing -> new -> new");
  ok(src(g, pos, "clip") === m1 && src(g, neg, "clip") === m1, "fill: text encoders' CLIP moved to the end of the chain");
  ok(r.warnings.some((x) => /new_one/.test(x)), "fill: warns about the LoRA that isn't installed");
  ok(r.applied.includes("2 LoRAs (2 loaders added)") === false && r.applied.some((x) => /3 LoRAs \(2 loaders added\)/.test(x)), "fill: summary counts LoRAs and added loaders");
}

// ---- fill: spare loaders get bypassed when the recipe has fewer LoRAs
{
  const { g, lo } = basic();
  const r = A.fillWorkflow(g, { ...recipe, loras: [] }, items.slice(0, 1), {});
  eq(lo.mode, 4, "fill: unused LoRA loader bypassed");
  ok(r.warnings.some((x) => /bypassed 1/.test(x)), "fill: says so");
}

// ---- fill: LoRA Manager loader gets the whole list
{
  const g = graph();
  const ck = g.make("CheckpointLoaderSimple", 1), lm = g.make("Lora Loader (LoraManager)", 2), pos = g.make("CLIPTextEncode", 3), ks = g.make("KSampler", 6);
  ck.connect(0, lm, 0); ck.connect(1, lm, 1); lm.connect(0, ks, 0); lm.connect(1, pos, 0); pos.connect(0, ks, 1);
  let made = 0;
  const r = A.fillWorkflow(g, recipe, items, { createNode: () => (made++, null) });
  eq(w(lm, "loras").map((l) => [l.name, l.strength, l.clipStrength, l.active]),
    [["watercolor_v3", 0.7, 0.5, true], ["soft_pastel", 0.55, 0.55, true], ["new_one", 1, 1, false], ["detail", -1.5, -1.5, true]], "LM loader: list set, missing LoRA inactive");
  eq(w(lm, "text"), "<lora:watercolor_v3:0.7:0.5> <lora:soft_pastel:0.55> <lora:detail:-1.5>", "LM loader: text box in sync (installed only)");
  ok(made === 0 && r.applied.some((x) => /LoRA Manager/.test(x)), "LM loader: no nodes added");
}

// ---- fill: nothing to fill
{
  const g = graph();
  g.make("CheckpointLoaderSimple", 1);
  const r = A.fillWorkflow(g, recipe, items, {});
  ok(!r.ok && /Open as new workflow/.test(r.error), "fill: no prompt box -> suggests opening as a new workflow");
}

// ---- txt2img graph
{
  const p = A.buildApiGraph(recipe, items);
  eq(p[1].inputs.ckpt_name, "Illustrious\\illustriousXL_v20.safetensors", "graph: checkpoint");
  eq(Object.values(p).filter((n) => n.class_type === "LoraLoader").map((n) => n.inputs.lora_name),
    ["Illustrious\\watercolor_v3.safetensors", "soft_pastel.safetensors", "Illustrious/new_one.safetensors", "Illustrious\\detail.safetensors"], "graph: LoRA chain incl. a queued download's name");
  eq(p[9].inputs.stop_at_clip_layer, -2, "graph: clip skip");
  eq([p[5].inputs.model, p[2].inputs.clip], [["13", 0], ["9", 0]], "graph: sampler uses the last LoRA, encoders the clip-skip node");
  eq([p[4].inputs.width, p[5].inputs.seed, p[5].inputs.sampler_name], [832, 81723, "dpmpp_2m"], "graph: size, seed, sampler");
  eq(A.buildApiGraph({ ...recipe, model: { type: "unet" } }, items), null, "graph: UNet models aren't guessed");
}

// ---- LoRA Manager mirror metadata
{
  const m = A.lmMetadata(recipe);
  eq(m.loras[0], { file_name: "watercolor_v3", hash: "aaaa", weight: 0.7, id: 111, name: "Watercolor Wash", version: "v3", isDeleted: false, exclude: false }, "LM metadata: LoRA entry");
  eq([m.gen_params.size, m.gen_params.cfg_scale, m.checkpoint.file_name, m.source_path], ["832x1216", 5.5, "illustriousXL_v20", "https://civitai.com/images/555"], "LM metadata: params, checkpoint, source");
}

process.exit(fail ? 1 : 0);
