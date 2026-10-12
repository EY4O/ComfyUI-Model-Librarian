// Applying a recipe to a ComfyUI graph: fill the open workflow (prompts,
// sampler settings, model, LoRAs), or build a plain txt2img graph from scratch.
// No ComfyUI imports, so the logic runs under Node for the tests: the graph and
// a createNode(type) function are passed in.

export const stem = (p) => String(p || "").split(/[\\/]/).pop().replace(/\.(safetensors|ckpt|pt|pth|bin|gguf|sft)$/i, "");
const base = (p) => String(p || "").split(/[\\/]/).pop().toLowerCase();

// The models a recipe uses, with the names this ComfyUI knows them by. `items`
// is the plan from /recipe/plan (model first, then LoRAs in recipe order, then VAE).
export function resolved(recipe, items) {
  const name = (it) => it.comfy_name || (it.status === "present" ? it.local : null) || it.download?.rel || it.file || it.name;
  const ck = (items || []).find((it) => it.kind === "checkpoint");
  const loras = (items || []).filter((it) => it.kind === "lora" && it.status !== "unavailable").map((it) => ({
    name: name(it), stem: stem(name(it)), installed: it.status === "present",
    weight: Number(it.weight ?? 1), clip: Number(it.clip_weight ?? it.weight ?? 1),
  }));
  const vae = (items || []).find((it) => it.kind === "vae");
  return {
    model: ck ? { name: name(ck), installed: ck.status === "present", type: recipe?.model?.type || null } : null,
    vae: vae ? { name: name(vae), installed: vae.status === "present" } : null,
    loras,
  };
}

// <lora:name:w> text, for LoRA Manager's loader box or A1111-style prompts
export function loraSyntax(loras) {
  const n = (x) => Number(x.toFixed(3));
  return loras.map((l) => `<lora:${l.stem}:${n(l.weight)}${Math.abs(l.clip - l.weight) > 1e-6 ? ":" + n(l.clip) : ""}>`).join(" ");
}

// ---------------------------------------------------------------- graph helpers
const PROMPT_NAMES = ["text", "prompt", "text_g", "text_l", "clip_l", "t5xxl"];
const TEXT_NAMES = [...PROMPT_NAMES, "positive", "wildcard_text", "string", "value", "text_positive"];
const isTextWidget = (w) => typeof w.value === "string" && (TEXT_NAMES.includes(w.name) || w.type === "customtext" || !!w.options?.multiline);
const textWidgets = (n) => (n.widgets || []).filter(isTextWidget);
const widget = (n, name) => (n.widgets || []).find((w) => w.name === name);
const nodesOf = (graph) => graph._nodes || graph.nodes || [];
const BYPASS = 4;

function setValue(w, v) {
  if (!w) return;
  w.value = v;
  w.callback?.(v);
}

// A combo widget only takes values from its own list (matched by file name).
function comboValue(w, v) {
  const opts = Array.isArray(w?.options?.values) ? w.options.values : null;
  if (!opts) return v;
  return opts.find((o) => o === v) ?? opts.find((o) => base(o) === base(v)) ?? opts.find((o) => stem(o).toLowerCase() === stem(v).toLowerCase()) ?? null;
}

function setPrompt(node, text) {
  const boxes = textWidgets(node).filter((w) => PROMPT_NAMES.includes(w.name));
  for (const w of boxes.length ? boxes : textWidgets(node).slice(0, 1)) setValue(w, text);
}

function inputNode(graph, node, slot) {
  if (node.getInputNode) return node.getInputNode(slot);
  const link = node.inputs?.[slot]?.link;
  const l = link == null ? null : linkById(graph, link);
  return l ? graph.getNodeById(l.origin_id) : null;
}

function linkById(graph, id) {
  const L = graph.links;
  return L instanceof Map ? L.get(id) : L?.[id];
}

// Follows conditioning back from a sampler input to the node holding the text.
function upstreamText(graph, node, inputName, depth = 0) {
  if (!node || depth > 8 || !node.inputs) return null;
  const slot = node.inputs.findIndex((i) => i.name === inputName);
  if (slot < 0) return null;
  const src = inputNode(graph, node, slot);
  if (!src) return null;
  if (textWidgets(src).length) return src;
  for (const k of ["conditioning", "conditioning_1", "positive", "text", "guider"]) {
    const found = upstreamText(graph, src, k, depth + 1);
    if (found) return found;
  }
  return null;
}

const outSlot = (n, type) => (n.outputs || []).findIndex((o) => o.type === type);
const lmLoader = (n) => /LoraManager/.test(n.type || "") && !/Randomizer/.test(n.type || "") && widget(n, "loras");

// Inserts a LoraLoader right after `after` (a checkpoint or LoRA loader): its
// MODEL and CLIP consumers are moved onto the new node.
function insertLoader(graph, after, createNode) {
  const n = createNode("LoraLoader");
  if (!n) return null;
  graph.add(n);
  const [x, y] = after.pos || [0, 0];
  n.pos = [x + 40, y + (after.size?.[1] || 120) + 40];
  for (const type of ["MODEL", "CLIP"]) {
    const from = outSlot(after, type), to = outSlot(n, type);
    const inp = (n.inputs || []).findIndex((i) => i.type === type);
    if (from < 0 || to < 0 || inp < 0) continue;
    for (const id of [...(after.outputs[from].links || [])]) {
      const l = linkById(graph, id);
      const target = l && graph.getNodeById(l.target_id);
      if (target && target !== n) n.connect(to, target, l.target_slot);
    }
    after.connect(from, n, inp);
  }
  return n;
}

// The end of the checkpoint -> LoRA chain, where new loaders go.
function chainEnd(graph, loaders) {
  const nodes = nodesOf(graph);
  const feedsLoader = (n) => {
    const s = outSlot(n, "MODEL");
    return s >= 0 && (n.outputs[s].links || []).some((id) => {
      const l = linkById(graph, id);
      return l && loaders.includes(graph.getNodeById(l.target_id));
    });
  };
  const withClip = (n) => outSlot(n, "MODEL") >= 0 && outSlot(n, "CLIP") >= 0;
  const end = loaders.filter(withClip).find((n) => !feedsLoader(n));
  if (end) return end;
  return nodes.find((n) => withClip(n) && widget(n, "ckpt_name")) || null;
}

function applyLoras(graph, loras, createNode, applied, warnings) {
  const nodes = nodesOf(graph);
  const missing = loras.filter((l) => !l.installed);
  if (missing.length) warnings.push(`${missing.length} LoRA${missing.length > 1 ? "s aren't" : " isn't"} installed yet: ${missing.map((l) => l.stem).join(", ")}`);
  const use = loras.filter((l) => l.installed);

  // LoRA Manager's loader takes the whole list
  const lm = nodes.find((n) => lmLoader(n) && n.mode !== BYPASS);
  if (lm) {
    setValue(widget(lm, "loras"), loras.map((l) => ({ name: l.stem, strength: l.weight, clipStrength: l.clip, active: l.installed, expanded: false })));
    const text = widget(lm, "text");
    if (text && typeof text.value === "string") setValue(text, loraSyntax(use));
    if (loras.length) applied.push(`${use.length} LoRA${use.length === 1 ? "" : "s"} (LoRA Manager loader)`);
    return;
  }

  const loaders = nodes.filter((n) => widget(n, "lora_name") && /Lora/i.test(n.type || "")).sort((a, b) => a.id - b.id);
  let set = 0, added = 0, noRoom = 0;
  const fill = (n, l) => {
    const w = widget(n, "lora_name");
    const v = comboValue(w, l.name);
    if (v == null) return false;
    setValue(w, v);
    setValue(widget(n, "strength_model"), l.weight);
    setValue(widget(n, "strength_clip"), l.clip);
    if (n.mode === BYPASS) n.mode = 0;
    return true;
  };
  use.forEach((l, i) => {
    let n = loaders[i];
    if (!n) {
      const after = chainEnd(graph, loaders);
      n = after && insertLoader(graph, after, createNode);
      if (!n) return void noRoom++;
      loaders.push(n);
      added++;
    }
    if (fill(n, l)) set++;
    else warnings.push(`${l.stem} isn't in ComfyUI's LoRA list yet (refresh after the download finishes)`);
  });
  const spare = loaders.slice(use.length).filter((n) => n.mode !== BYPASS);
  for (const n of spare) n.mode = BYPASS;
  if (spare.length) warnings.push(`bypassed ${spare.length} unused LoRA loader${spare.length > 1 ? "s" : ""}`);
  if (noRoom) warnings.push(`${noRoom} LoRA${noRoom > 1 ? "s" : ""} left out: couldn't add a loader (no checkpoint loader found)`);
  if (set) applied.push(`${set} LoRA${set === 1 ? "" : "s"}${added ? ` (${added} loader${added > 1 ? "s" : ""} added)` : ""}`);
}

// Fills the open workflow with the recipe. -> { ok, applied: [...], warnings: [...] }
export function fillWorkflow(graph, recipe, items, { createNode } = {}) {
  const nodes = nodesOf(graph);
  const res = resolved(recipe, items);
  const applied = [], warnings = [];
  let pos = null, neg = null;
  for (const n of nodes) {
    if (n.mode === BYPASS) continue;
    pos = pos || upstreamText(graph, n, "positive");
    neg = neg || upstreamText(graph, n, "negative");
  }
  if (!pos) for (const n of nodes) if (/Guider/.test(n.type || "")) pos = pos || upstreamText(graph, n, "conditioning");
  if (!pos) return { ok: false, error: "Couldn't find the prompt box in this workflow — try “Open as new workflow”.", applied, warnings };
  const p = recipe.prompt || {};
  setPrompt(pos, p.positive || "");
  applied.push("prompt");
  if (neg && neg !== pos) {
    setPrompt(neg, p.negative || "");
    applied.push("negative");
  }

  // first match wins, samplers first, so a hires-fix pass keeps its own steps
  const hasCond = (n) => (n.inputs || []).some((i) => i.name === "positive" || i.name === "noise");
  const ordered = nodes.filter((n) => n.mode !== BYPASS).sort((a, b) => hasCond(b) - hasCond(a) || a.id - b.id);
  const setFirst = (names, v, label) => {
    if (v == null || v === "") return false;
    for (const n of ordered) {
      const w = (n.widgets || []).find((x) => names.includes(x.name));
      if (!w) continue;
      const val = comboValue(w, v);
      if (val == null) continue;
      setValue(w, val);
      applied.push(label);
      return true;
    }
    return false;
  };
  const s = recipe.settings || {};
  setFirst(["seed", "noise_seed"], s.seed, "seed");
  setFirst(["steps"], s.steps, "steps");
  setFirst(["cfg"], s.cfg, "CFG");
  if (s.sampler && !setFirst(["sampler_name"], s.sampler, "sampler")) warnings.push(`sampler ${s.sampler} isn't available here`);
  setFirst(["scheduler"], s.scheduler, "scheduler");
  if (s.clip_skip) setFirst(["stop_at_clip_layer"], -Math.abs(Number(s.clip_skip)), "clip skip");
  if (res.model) {
    if (!res.model.installed) warnings.push(`model ${stem(res.model.name)} isn't installed yet`);
    else if (!setFirst(["ckpt_name", "unet_name"], res.model.name, "model")) warnings.push(`couldn't set the model (${stem(res.model.name)})`);
  }
  if (s.width && s.height) {
    const sized = nodes.filter((n) => n.mode !== BYPASS && widget(n, "width") && widget(n, "height"));
    const latent = sized.find((n) => /Latent/i.test(n.type || "")) || sized[0];
    if (latent) {
      setValue(widget(latent, "width"), Number(s.width));
      setValue(widget(latent, "height"), Number(s.height));
      applied.push("size");
    }
  }
  applyLoras(graph, res.loras, createNode || (() => null), applied, warnings); // no LoRAs: loaders get bypassed
  graph.setDirtyCanvas?.(true, true);
  return { ok: true, applied, warnings };
}

// A plain txt2img graph (API format) for recipes without a ComfyUI workflow.
// -> prompt object, or null when the model isn't a regular checkpoint.
export function buildApiGraph(recipe, items) {
  const res = resolved(recipe, items);
  if (!res.model || (res.model.type && res.model.type !== "checkpoint")) return null;
  const s = recipe.settings || {}, p = recipe.prompt || {};
  const g = { 1: { class_type: "CheckpointLoaderSimple", inputs: { ckpt_name: res.model.name }, _meta: { title: "Load Checkpoint" } } };
  let model = ["1", 0], clip = ["1", 1], id = 10;
  for (const l of res.loras) {
    const k = String(id++);
    g[k] = { class_type: "LoraLoader", inputs: { model, clip, lora_name: l.name, strength_model: l.weight, strength_clip: l.clip } };
    model = [k, 0];
    clip = [k, 1];
  }
  if (s.clip_skip && Math.abs(Number(s.clip_skip)) > 1) {
    g[9] = { class_type: "CLIPSetLastLayer", inputs: { clip, stop_at_clip_layer: -Math.abs(Number(s.clip_skip)) } };
    clip = ["9", 0];
  }
  let vae = ["1", 2];
  if (res.vae) {
    g[8] = { class_type: "VAELoader", inputs: { vae_name: res.vae.name } };
    vae = ["8", 0];
  }
  g[2] = { class_type: "CLIPTextEncode", inputs: { clip, text: p.positive || "" }, _meta: { title: "Positive" } };
  g[3] = { class_type: "CLIPTextEncode", inputs: { clip, text: p.negative || "" }, _meta: { title: "Negative" } };
  g[4] = { class_type: "EmptyLatentImage", inputs: { width: Number(s.width) || 1024, height: Number(s.height) || 1024, batch_size: 1 } };
  g[5] = { class_type: "KSampler", inputs: {
    model, positive: ["2", 0], negative: ["3", 0], latent_image: ["4", 0],
    seed: s.seed ?? Math.floor(Math.random() * 2 ** 32), steps: s.steps || 20, cfg: s.cfg ?? 7,
    sampler_name: s.sampler || "euler", scheduler: s.scheduler || "normal", denoise: 1,
  } };
  g[6] = { class_type: "VAEDecode", inputs: { samples: ["5", 0], vae } };
  g[7] = { class_type: "SaveImage", inputs: { images: ["6", 0], filename_prefix: "ModelLibrarian" } };
  return g;
}

// LoRA Manager's /api/lm/recipes/save metadata (its analysis shape), for the
// optional mirror into its recipe list.
export function lmMetadata(recipe) {
  const s = recipe.settings || {}, p = recipe.prompt || {}, m = recipe.model;
  const meta = {
    base_model: recipe.base_model || "",
    loras: (recipe.loras || []).map((l) => ({
      file_name: stem(l.file || l.name), hash: (l.hash || "").toLowerCase(), weight: Number(l.weight ?? 1),
      id: l.civitai_version_id || 0, name: l.display_name || l.name || stem(l.file), version: l.version || "",
      isDeleted: false, exclude: false,
    })),
    gen_params: Object.fromEntries(Object.entries({
      prompt: p.positive, negative_prompt: p.negative, steps: s.steps, sampler: s.sampler_raw || s.sampler, cfg_scale: s.cfg,
      seed: s.seed, size: s.width && s.height ? `${s.width}x${s.height}` : null, clip_skip: s.clip_skip,
      denoising_strength: s.denoise != null && s.denoise !== 1 ? s.denoise : null,
    }).filter(([, v]) => v != null && v !== "")),
  };
  if (m) meta.checkpoint = { name: m.name || stem(m.file), file_name: stem(m.file || m.name), hash: (m.hash || "").toLowerCase(), modelVersionId: m.civitai_version_id || 0 };
  if (recipe.source?.url) meta.source_path = recipe.source.url;
  return meta;
}
