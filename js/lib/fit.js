// Shared between Model Librarian (js/lib/fit.js) and its Chrome extension (lib/fit.js): keep both copies the same.
// Which file of a model suits this PC. Model Librarian tells us the GPU, the VRAM budget, the
// formats this ComfyUI runs at full speed and the loaders installed (ext/hello -> system); the
// file's format is read from its name first, because CivitAI's format tags are often wrong
// (an "NVFP4" file tagged fp8 or bf16). Pure functions: no DOM, no chrome.*.

// -> {kind, bits, label}: kind is gguf | nvfp4 | mxfp8 | fp8 | int8 | int4 | fp16 | bf16 | fp32 | null
export function quantOf(file, versionName = "") {
  const name = String(file.name || "");
  const md = file.metadata || {};
  if (/\.gguf$/i.test(name) || md.format === "GGUF") {
    const m = name.match(/q([2-8])/i) || String(versionName).match(/q([2-8])/i); // Q4_K_M, q40, Q8_0
    const bits = m ? Number(m[1]) : 4;
    return { kind: "gguf", bits, label: m ? `GGUF Q${bits}` : "GGUF" };
  }
  // the last format word in the file name is the one that counts ("..._Int8_fp8Scaled" is FP8)
  const words = [
    ["nvfp4", /nvfp4|(?:^|[^a-z])fp4(?![a-z0-9])/gi], ["mxfp8", /mxfp8/gi], ["fp8", /fp8|e4m3|e5m2/gi],
    ["int4", /int4|w4a4|svdq/gi], ["int8", /int8|w8a8/gi], ["bf16", /bf16/gi], ["fp16", /fp16/gi], ["fp32", /fp32/gi],
  ];
  const lastIn = (text) => {
    let best = null;
    for (const [kind, re] of words) {
      for (const m of text.matchAll(re)) if (!best || m.index >= best.at) best = { kind, at: m.index };
    }
    return best && best.kind;
  };
  const tag = String(md.fp || "").toLowerCase();
  const fromTag = /nvfp4/.test(tag) ? "nvfp4" : /fp8/.test(tag) ? "fp8" : /int4/.test(tag) ? "int4" : /int8/.test(tag) ? "int8"
    : ["bf16", "fp16", "fp32"].includes(tag) ? tag : null;
  const kind = lastIn(name) || lastIn(versionName) || fromTag;
  const bits = { nvfp4: 4, int4: 4, mxfp8: 8, fp8: 8, int8: 8, bf16: 16, fp16: 16, fp32: 32 }[kind] || null;
  return { kind: kind || null, bits, label: kind ? kind.toUpperCase() : "" };
}

const gb = (b) => `${(b / 1024 ** 3).toFixed(b >= 100 * 1024 ** 3 ? 0 : 1)} GB`;

// -> {verdict: "good" | "slow" | "no" | "unknown", score, notes: [..]} for one file on this system.
// A standalone diffusion model (not an all-in-one checkpoint) also loads a text encoder. ComfyUI can move
// the encoder out of VRAM while sampling, so its full size isn't held back, but some of it stays busy:
// about 2 GB is kept for it (the encoder's own size when that's smaller), as model makers advise.
export const TE_RESERVE = 2 * 1024 ** 3;
export const needsTextEncoder = (f) => f.type === "Diffusion Model" || /\.gguf$/i.test(f.name || "");

export function textEncoderOf(companions) {
  const tes = (companions || []).filter((c) => c.folder === "text_encoders");
  if (!tes.length) return null;
  const size = tes.every((c) => c.size) ? tes.reduce((a, c) => a + c.size, 0) : null;
  return { names: tes.map((c) => c.name), size };
}

// opts.te: {names, size} from textEncoderOf (null: not known, the usual 2 GB is kept anyway)
export function assess(file, versionName, sys, opts = {}) {
  const q = quantOf(file, versionName);
  if (!sys || !sys.budget) return { verdict: "unknown", score: 0, notes: [], q };
  const notes = [];
  let verdict = "good";
  const fast = sys.fast || {};
  const loaders = sys.loaders || {};
  const formats = sys.formats || [];
  const slow = (why) => { notes.push(why); if (verdict === "good") verdict = "slow"; };

  // can this ComfyUI load it, and at full speed?
  if (q.kind === "gguf") {
    if (loaders.gguf === false) return { verdict: "no", score: -1, notes: ["Needs the ComfyUI-GGUF nodes"], q };
  } else if (q.kind === "nvfp4") {
    if (fast.nvfp4 === false) slow("NVFP4 runs at full speed only on RTX 50-series; here it's unpacked on the fly");
    else if (fast.nvfp4) notes.push("NVFP4 runs natively on this GPU");
  } else if (q.kind === "mxfp8") {
    if (fast.mxfp8 === false) slow("MXFP8 runs at full speed only on RTX 50-series");
  } else if (q.kind === "fp8") {
    if (fast.fp8 === false) slow("FP8 is converted on the fly on this GPU (RTX 40-series or newer runs it natively)");
    else if (fast.fp8) notes.push("FP8 runs natively on this GPU");
  } else if (q.kind === "int8" || q.kind === "int4") {
    const core = formats.some((f) => /int8|w4a4|w4a8/.test(f));
    if (!core && !loaders.nunchaku) return { verdict: "no", score: -1, notes: [`This ComfyUI can't load ${q.label} files (update ComfyUI, or install Nunchaku)`], q };
    if (fast.int8 === false) slow(`${q.label} is slow on this GPU`);
    else notes.push(`${q.label} runs natively`);
  }

  // does it fit in VRAM? (with room kept for the text encoder, when the model needs a separate one)
  const size = file.size || 0;
  const te = opts.te || null;
  const reserve = needsTextEncoder(file) ? Math.min(TE_RESERVE, (te && te.size) || TE_RESERVE) : 0;
  const budget = Math.max(sys.budget - reserve, sys.budget / 2);
  const room = reserve ? `your ${gb(budget)} (${gb(sys.budget)} VRAM budget less ${gb(reserve)} for the text encoder)` : `your ${gb(sys.budget)} VRAM budget`;
  if (size && size <= budget) notes.unshift(`${gb(size)} fits in ${room}`);
  else if (size && size <= budget * 1.6) slow(`${gb(size)} is over ${room}: part of it runs from RAM (slower)`);
  else if (size) { slow(`${gb(size)} is far over ${room}: mostly runs from RAM (much slower)`); verdict = "slow"; }
  if (reserve) {
    notes.push(te && te.names.length
      ? `Also loads ${te.names.join(" + ")}${te.size ? ` (${gb(te.size)})` : ""}; ComfyUI can move it out of VRAM while sampling, so ${gb(reserve)} is kept for it`
      : `Also needs a text encoder: ${gb(reserve)} is kept for it (its size isn't known yet)`);
  }

  // more bits = closer to the original, as long as it fits and runs fast
  const bits = q.bits || 16;
  const quality = q.kind === "gguf" ? bits - 0.5 : bits; // GGUF dequantizes on the fly: a little slower than native
  if (q.kind === "gguf" && bits <= 3) notes.push(`Q${bits} trades a lot of quality for size`);
  const fitPenalty = !size ? 0 : size <= budget ? 0 : size <= budget * 1.6 ? 20 : 40;
  const speedPenalty = notes.some((n) => /full speed only|converted on the fly|is slow/.test(n)) ? 15 : 0;
  return { verdict, score: 100 + Math.min(quality, 16) - fitPenalty - speedPenalty, notes, q };
}

// The best file across all versions: highest score, the newer version on ties (CivitAI lists newest first).
// -> {versionId, fileId, score} | null
// tes: {baseModel: textEncoderOf(...)} for the versions' base models (optional)
export function recommend(model, sys, tes = {}) {
  if (!sys || !sys.budget || !model || !model.downloadable) return null;
  let best = null;
  model.versions.forEach((v, vi) => {
    for (const f of v.files) {
      if (f.type && !["Model", "Pruned Model", "Diffusion Model"].includes(f.type)) continue; // VAE, text encoder…
      const a = assess(f, v.name, sys, { te: tes[v.baseModel] || null });
      if (a.verdict === "no" || a.verdict === "unknown") continue;
      const key = a.score - vi * 0.01;
      if (!best || key > best.key) best = { versionId: v.id, fileId: f.id, score: a.score, verdict: a.verdict, key };
    }
  });
  return best && { versionId: best.versionId, fileId: best.fileId, score: best.score, verdict: best.verdict };
}

// "cuda:0 NVIDIA GeForce RTX 4070 : cudaMallocAsync" -> "RTX 4070"
export function gpuName(sys) {
  const n = String((sys && sys.gpu) || "").replace(/^\w+:\d+\s+/, "").replace(/\s*:.*$/, "").replace(/^NVIDIA\s+(GeForce\s+)?/i, "").trim();
  return n || "your GPU";
}

export const MARK = { good: "✓", slow: "◐", no: "✗", unknown: "" };
