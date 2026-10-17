// A stateful fake Model Librarian backend for README screenshots and GIFs.
// Downloads advance on every /jobs poll; finished files "appear on disk", so
// scans, the library and recipes update the way they do for real.
const GB = 1024 ** 3, MB = 1024 ** 2;
const now = () => Date.now() / 1000;
const json = (o, s = 200) => new Response(JSON.stringify(o), { status: s, headers: { "Content-Type": "application/json" } });
const base = (p) => String(p).split(/[\\/]/).pop();
const stem = (p) => base(p).replace(/\.[^.]+$/, "");
const FAMILIES = ["Illustrious", "Pony", "SDXL", "Flux", "Qwen", "Wan", "ZImage", "Krea 2"];

// ---------------------------------------------------------------- the fake disk
const disk = {
  checkpoints: new Set(["Illustrious\\aurora_illustrious_v4.safetensors"]),
  loras: new Set(["Illustrious\\paper_cut_style.safetensors", "Illustrious\\soft_pastel_v15.safetensors", "Pony\\Characters\\ink_wash_v2.safetensors", "Illustrious\\Scenery\\glass_garden.safetensors"]),
  diffusion_models: new Set(["Flux\\flux1-dev-Q5_K_M.gguf"]),
  vae: new Set(["ae.safetensors"]),
  text_encoders: new Set(["t5xxl_fp8_e4m3fn.safetensors", "clip_l.safetensors"]),
};
const moved = { "glass_garden.safetensors": "Illustrious\\Scenery\\glass_garden.safetensors" }; // renamed by Organize
const sizes = {};
const nodeFolder = { CheckpointLoaderSimple: "checkpoints", LoraLoader: "loras", UNETLoader: "diffusion_models", UnetLoaderGGUF: "diffusion_models", VAELoader: "vae", DualCLIPLoader: "text_encoders" };

function findOnDisk(folder, value) {
  const set = disk[folder] || new Set();
  if (set.has(value)) return { status: "present", found_as: value };
  const hit = [...set].find((n) => base(n).toLowerCase() === base(value).toLowerCase());
  if (hit) return { status: "elsewhere", found_as: hit };
  if (moved[base(value)]) return { status: "elsewhere", found_as: moved[base(value)] };
  return { status: "missing", found_as: null };
}

function scanItems(refs, extra = () => ({})) {
  const groups = new Map();
  for (const r of refs) {
    const folder = nodeFolder[r.node_type] || "loras";
    const k = folder + "|" + r.value.toLowerCase();
    let g = groups.get(k);
    if (!g) {
      const f = findOnDisk(folder, r.value);
      g = { value: r.value, folder, how: "known-node", status: f.status, found_as: f.found_as, found_folder: f.found_as ? folder : null,
        refs: [], node_types: [], embedded: null, size: f.found_as ? (sizes[base(f.found_as)] || 2.1 * GB) : null,
        dest: `E:\\StabilityMatrix\\Data\\Models\\${folder === "loras" ? "Lora" : folder === "checkpoints" ? "StableDiffusion" : "DiffusionModels"}\\${r.value}`,
        shared: true, too_big: false, hint: null, ...extra(r) };
      groups.set(k, g);
    }
    g.refs.push(r.key);
    if (!g.node_types.includes(r.node_type)) g.node_types.push(r.node_type);
  }
  const order = { missing: 0, invalid: 1, elsewhere: 2, present: 3 };
  return [...groups.values()].sort((a, b) => order[a.status] - order[b.status] || a.value.localeCompare(b.value));
}

// ---------------------------------------------------------------- sources
const SOURCES = {
  "lumen_xl_v3.safetensors": { source: "civitai", filename: "lumen_xl_v3.safetensors", size: 6.46 * GB, title: "Lumen XL — v3.0", page: "https://civitai.com/models/101" },
  "harbor_lights.safetensors": { source: "civitai", filename: "harbor_lights.safetensors", size: 218 * MB, title: "Harbor Lights — v1.2", page: "https://civitai.com/models/102" },
  "qwen_image_vae.safetensors": { source: "huggingface", filename: "qwen_image_vae.safetensors", size: 254 * MB, title: "Comfy-Org/Qwen-Image_ComfyUI/split_files/vae", page: "https://huggingface.co/Comfy-Org/Qwen-Image_ComfyUI" },
  "krea2_turbo-Q5_K_M.gguf": { source: "huggingface", filename: "krea2_turbo-Q5_K_M.gguf", size: 8.26 * GB, title: "vantage/Krea-2-Turbo-GGUF/krea2_turbo-Q5_K_M.gguf", page: "https://huggingface.co/vantage/Krea-2-Turbo-GGUF" },
};
function candidates(value) {
  const s = SOURCES[base(value)];
  if (!s) return [];
  const alt = s.source === "huggingface" ? [{ ...s, filename: s.filename.replace("Q5_K_M", "Q4_K_M"), size: s.size * 0.85, confidence: "low" }] : [];
  return [{ ...s, url: `https://example.invalid/${s.filename}`, sha256: "ab".repeat(32), confidence: "high", page_url: s.page }, ...alt.map((a) => ({ ...a, url: "https://example.invalid/x", page_url: s.page }))];
}

// ---------------------------------------------------------------- downloads
const jobs = [];
let jobN = 0;
const afterDownload = []; // callbacks(job)
function startJob(b) {
  const j = { id: "j" + ++jobN, rel: b.rel, folder: b.folder, status: "downloading", done: 0, total: b.size || 300 * MB, speed: 0, error: null,
    dest: `E:\\StabilityMatrix\\Data\\Models\\…\\${b.rel}`, started: now(), source: b.source };
  jobs.unshift(j);
  return j;
}
function tickJobs() {
  for (const j of jobs) {
    if (j.status !== "downloading") continue;
    j.done = Math.min(j.total, j.done + j.total * (0.24 + Math.random() * 0.1));
    j.speed = (38 + Math.random() * 20) * MB;
    if (j.done >= j.total) {
      j.status = "done";
      j.speed = 0;
      (disk[j.folder] ||= new Set()).add(j.rel.replace(/\//g, "\\"));
      sizes[base(j.rel)] = j.total;
      afterDownload.forEach((fn) => fn(j));
    }
  }
}

// ---------------------------------------------------------------- saved workflows
const SAVED = {
  "workflows/Illustrious portrait.json": [["CheckpointLoaderSimple", "lumen_xl_v3.safetensors"], ["LoraLoader", "Illustrious\\paper_cut_style.safetensors"], ["LoraLoader", "harbor_lights.safetensors"]],
  "workflows/Qwen Image edit.json": [["UNETLoader", "qwen_image_edit_fp8.safetensors"], ["VAELoader", "qwen_image_vae.safetensors"]],
  "workflows/Krea2/Krea2 turbo GGUF.json": [["UnetLoaderGGUF", "krea2_turbo-Q5_K_M.gguf"], ["LoraLoader", "glass_garden.safetensors"]],
  "workflows/Flux basic.json": [["UnetLoaderGGUF", "Flux\\flux1-dev-Q5_K_M.gguf"], ["VAELoader", "ae.safetensors"], ["DualCLIPLoader", "t5xxl_fp8_e4m3fn.safetensors"]],
  "workflows/Pony ink.json": [["LoraLoader", "Pony\\Characters\\ink_wash_v2.safetensors"]],
};
SOURCES["qwen_image_edit_fp8.safetensors"] = { source: "huggingface", filename: "qwen_image_edit_fp8.safetensors", size: 20.4 * GB, title: "Comfy-Org/Qwen-Image-Edit_ComfyUI", page: "https://huggingface.co/Comfy-Org/Qwen-Image-Edit_ComfyUI" };
function health() {
  const refs = [];
  for (const [file, models] of Object.entries(SAVED)) models.forEach(([t, v], i) => refs.push({ key: `default/${file}|${i}`, node_type: t, value: v }));
  const items = scanItems(refs);
  for (const it of items) it.workflows = [...new Set(it.refs.map((k) => k.split("|")[0]))];
  const wfs = Object.keys(SAVED).map((f) => {
    const file = "default/" + f;
    const mine = items.filter((it) => it.workflows.includes(file));
    return { file, user: "default", path: f, models: mine.length, missing: mine.filter((i) => i.status === "missing").length, moved: mine.filter((i) => i.status === "elsewhere").length };
  }).sort((a, b) => b.missing - a.missing || b.moved - a.moved || a.file.localeCompare(b.file));
  return { workflows: wfs, items, sm_mode: "shared" };
}

// ---------------------------------------------------------------- library
let pid = 0;
const P = () => ++pid;
function entry(section, rel, o = {}) {
  const id = "f" + (pid + 1);
  return { id, section, rel, name: base(rel), size: o.size || 220 * MB, mtime: 1, title: o.title || null, version: o.version || null,
    base_label: o.base || null, family: o.family || null, badge: o.badge || (o.family || "UNKN").slice(0, 5).toUpperCase(), confidence: "high", evidence: "CivitAI base model",
    trained_words: o.words || [], model_id: o.mid || null, version_id: o.vid || null, has_meta: !!o.title, has_preview: true, preview_video: false,
    favorite: false, nsfw: false, archived: !!o.archived, root_name: "Lora", lookup_failed: false, page_url: o.mid ? `https://civitai.com/models/${o.mid}` : null,
    _img: P(), ...(o.update ? { update: o.update } : {}), ...(o.hf ? { hf: o.hf } : {}) };
}
const upd = (mid, id, name, n = 1) => ({ id, name, base_model: "Illustrious", published: "2026-09-20", model_id: mid, newer_count: n, model_name: "", page_url: `https://civitai.com/models/${mid}` });
const LIB = {
  checkpoints: [
    entry("checkpoints", "Illustrious/aurora_illustrious_v4.safetensors", { title: "Aurora Illustrious", version: "v4.0", base: "Illustrious", family: "Illustrious", badge: "IL", mid: 11, vid: 1104, size: 6.46 * GB, update: upd(11, 1105, "v5.0") }),
    entry("checkpoints", "Illustrious/lumen_xl_v3.safetensors", { title: "Lumen XL", version: "v3.0", base: "Illustrious", family: "Illustrious", badge: "IL", mid: 12, vid: 1203, size: 6.46 * GB }),
    entry("checkpoints", "Pony/velvet_pony_v12.safetensors", { title: "Velvet Pony", version: "v12", base: "Pony", family: "Pony", badge: "PONY", mid: 13, vid: 1312, size: 6.62 * GB, update: { ...upd(13, 1318, "v18 CoreShift", 3), base_model: "Pony" } }),
    entry("checkpoints", "SDXL/studio_real_xl.safetensors", { title: "Studio Real XL", version: "v2.1", base: "SDXL 1.0", family: "SDXL", badge: "XL", mid: 14, vid: 1421, size: 6.94 * GB }),
    entry("checkpoints", "Illustrious/tidewater_anime.safetensors", { title: "Tidewater Anime", version: "Play V2", base: "Illustrious", family: "Illustrious", badge: "IL", mid: 15, vid: 1502, size: 6.46 * GB, update: upd(15, 1504, "Play V4", 2) }),
    entry("checkpoints", "Illustrious/maple_mix_v7.safetensors", { title: "Maple Mix", version: "v7.0", base: "Illustrious", family: "Illustrious", badge: "IL", mid: 16, vid: 1607, size: 6.46 * GB }),
    entry("checkpoints", "SDXL/nightfall_xl.safetensors", { title: "Nightfall XL", version: "v1.0", base: "SDXL 1.0", family: "SDXL", badge: "XL", mid: 17, vid: 1701, size: 6.94 * GB }),
    entry("checkpoints", "Pony/sunlit_pony.safetensors", { title: "Sunlit Pony", version: "v8.5", base: "Pony", family: "Pony", badge: "PONY", mid: 18, vid: 1885, size: 6.62 * GB }),
  ],
  loras: [
    entry("loras", "Illustrious/paper_cut_style.safetensors", { title: "Paper Cut Style", version: "v1.1", base: "Illustrious", family: "Illustrious", badge: "IL", mid: 21, vid: 2101, words: ["papercut"], update: upd(21, 2102, "v1.2") }),
    entry("loras", "Illustrious/soft_pastel_v15.safetensors", { title: "Soft Pastel", version: "v1.5", base: "Illustrious", family: "Illustrious", badge: "IL", mid: 22, vid: 2215 }),
    entry("loras", "Pony/Characters/ink_wash_v2.safetensors", { title: "Ink Wash", version: "v2", base: "Pony", family: "Pony", badge: "PONY", mid: 23, vid: 2302 }),
    entry("loras", "Flux/neon_rim_light.safetensors", { title: "Neon Rim Light", version: "v1.0", base: "Flux.1 D", family: "Flux", badge: "FLUX", mid: 24, vid: 2401 }),
    entry("loras", "Qwen/clay_render.safetensors", { title: null, base: null, family: "Qwen", badge: "QWEN", hf: { repo: "studio-lab/qwen-clay-render", path: "clay_render.safetensors", license: "apache-2.0", fetched: 1, likes: 1840, downloads: 52310, pipeline: "text-to-image", library: "diffusers", base_model: "Qwen/Qwen-Image", tags: ["lora", "qwen-image", "3d", "clay"], updated: "2026-09-02", card: "# Clay Render LoRA for Qwen-Image\n\nTurns any prompt into a soft clay / plasticine render.\n\nTrigger word: clayrender\n\n## Recommended settings\n\n- Strength 0.7–0.9\n- 20 steps, CFG 4\n\nTrained on 400 hand-made clay figures photographed under studio light." } }),
    entry("loras", "Illustrious/Scenery/glass_garden.safetensors", { title: "Glass Garden", version: "v2", base: "Illustrious", family: "Illustrious", badge: "IL", mid: 25, vid: 2502 }),
    entry("loras", "Wan/motion_sway_HIGH.safetensors", { title: "Motion Sway", version: "v1.0 HN", base: "Wan Video 2.2 I2V-A14B", family: "Wan", badge: "WAN", mid: 26, vid: 2601, update: { ...upd(26, 2604, "v2.1 HN"), base_model: "Wan Video 2.2 I2V-A14B" } }),
    entry("loras", "ZImage/film_grain_z.safetensors", { title: "Film Grain Z", version: "v1.0", base: "ZImageTurbo", family: "ZImage", badge: "ZIMG", mid: 27, vid: 2701 }),
  ],
  diffusion_models: [
    entry("diffusion_models", "Flux/flux1-dev-Q5_K_M.gguf", { title: "FLUX.1 dev GGUF", version: "Q5_K_M", base: "Flux.1 D", family: "Flux", badge: "FLUX", size: 8.4 * GB, hf: { repo: "city96/FLUX.1-dev-gguf", path: "flux1-dev-Q5_K_M.gguf", license: "other", license_name: "flux-1-dev-non-commercial-license", fetched: 1, likes: 1210, downloads: 140000, pipeline: "text-to-image", tags: ["gguf", "flux"], card: "# FLUX.1 [dev] GGUF\n\nQuantized versions of FLUX.1 [dev] for ComfyUI-GGUF." } }),
  ],
  embeddings: [],
};
for (const list of Object.values(LIB)) for (const e of list) e.id = "f" + e._img;
// usage and your own notes, for the Most used sort and the details popup
const USE = { "Paper Cut Style": [42, 1], "Aurora Illustrious": [58, 0], "Soft Pastel": [17, 3], "Lumen XL": [31, 2], "Neon Rim Light": [9, 12], "Velvet Pony": [4, 40], "Ink Wash": [12, 6], "Glass Garden": [6, 20] };
for (const e of Object.values(LIB).flat()) {
  const [n, days] = USE[e.title] || [0, 0];
  e.use_count = n;
  e.last_used = n ? now() - days * 86400 : null;
}
LIB.loras[0].notes = { rating: 5, note: "Best at 0.7–0.8 with Aurora. Layered paper look; add 'papercut' to the prompt.", tags: ["keeper", "style"] };
LIB.checkpoints[0].notes = { rating: 4, note: "Go-to Illustrious base.", tags: ["base"] };
LIB.loras[2].notes = { rating: 3, note: "", tags: ["portrait"] };
// a model CivitAI no longer has; CivArchive knows a live copy
Object.assign(LIB.loras[2], { removed: { where: "CivitAI", what: "model", at: now() - 5 * 86400 }, sha256: "7c".repeat(32) });
const ARCHIVE = {
  sha256: "7c".repeat(32), filename: "ink_wash_v2.safetensors", size: 144 * MB, deleted_on_civitai: true, folder: "loras",
  page_url: "https://civarchive.com/sha256/" + "7c".repeat(32),
  meta: { modelName: "Ink Wash", versionName: "v2", baseModel: "Pony" },
  files: [
    { filename: "ink_wash_v2.safetensors", url: "https://civitai.com/api/download/models/2302", host: "civitai.com", source: "civitai", live: false },
    { filename: "ink_wash_v2.safetensors", url: "https://huggingface.co/archivist/pony-loras/resolve/main/ink_wash_v2.safetensors", host: "huggingface.co", source: "huggingface", live: true },
    { filename: "InkWash.safetensors", url: "https://civitai.com/api/download/models/1990", host: "civitai.com", source: "civitai", live: false },
  ],
};

function shareRows(items) {
  return items.map((it) => {
    const file = it.lm ? base(it.value) + ".safetensors" : base(it.value);
    const s = SOURCES[file];
    const row = { value: it.value, folder: it.lm ? "loras" : it.folder, lm: !!it.lm, file, size: sizes[file] || s?.size || 2.1 * GB,
      sha256: (file.length.toString(16) + "ab").repeat(16).slice(0, 64), title: s?.title || stem(file).replace(/_/g, " "), base: "Illustrious",
      url: s ? `https://civitai.com/api/download/models/${100 + file.length}` : `https://civitai.com/api/download/models/${300 + file.length}`,
      page_url: s?.page || `https://civitai.com/models/${200 + file.length}`, source: s?.source || "civitai", removed: null };
    if (/harbor/i.test(file)) {
      Object.assign(row, { source: "civarchive", url: "https://huggingface.co/archivist/sdxl-loras/resolve/main/" + file,
        page_url: "https://civarchive.com/sha256/" + row.sha256, archive_url: "https://civarchive.com/sha256/" + row.sha256,
        removed: { where: "CivitAI", what: "model" } });
    }
    if (/vae/i.test(file)) Object.assign(row, { url: null, page_url: null, source: null, note: "no known source" });
    return row;
  });
}
function shareMarkdown(rows, title) {
  return [`**Models for ${title}**`, ""].concat(rows.map((r) => `- \`${r.file}\` → \`models/${r.folder}\` — ${r.title}` + (r.page_url ? ` · [page](${r.page_url})` : ""))).join("\n");
}
afterDownload.push((j) => {
  // an update finished: the new version appears next to the old one, the alert goes
  for (const list of Object.values(LIB)) {
    const old = list.find((e) => e.update && j.rel === e.rel.replace(/[^/]+$/, "") + `${stem(e.name)}_new.safetensors`);
    if (!old) continue;
    const ne = entry(old.section, j.rel, { title: old.title, version: old.update.name, base: old.base_label, family: old.family, badge: old.badge, mid: old.model_id, vid: old.update.id, size: old.size });
    ne.id = "f" + ne._img;
    ne._img = old._img;
    delete old.update;
    list.push(ne);
  }
});

// ---------------------------------------------------------------- recipes
const RECIPE = {
  schema: "recipe/1", title: "Lighthouse at dusk", format: "civitai", base_model: "Illustrious",
  source: { url: "https://civitai.com/images/555", site: "civitai" },
  prompt: { positive: "masterpiece, a lighthouse on a cliff at dusk, paper cut style, layered paper, soft pastel palette, crashing waves, seagulls", negative: "blurry, lowres, watermark" },
  settings: { sampler: "euler_ancestral", sampler_raw: "Euler a", steps: 28, cfg: 5, seed: 81723, width: 832, height: 1216, clip_skip: 2 },
  model: { name: "Lumen XL", file: "lumen_xl_v3", civitai_version_id: 1203, type: "checkpoint" },
  loras: [{ name: "Paper Cut Style", file: "paper_cut_style", weight: 0.8 }, { name: "Harbor Lights", file: "harbor_lights", weight: 0.55 }, { name: "Soft Pastel", file: "soft_pastel_v15", weight: 0.35 }],
  tags: [], comfy: null,
};
function recipeItems() {
  const one = (kind, name, version, value, folder, w, cand) => {
    const f = findOnDisk(folder, value);
    const c = candidates(base(value))[0];
    return { kind, name, version, weight: w, base_model: "Illustrious", status: f.status === "missing" ? "missing" : "present", comfy_name: f.found_as, local: f.found_as, matched_by: "file name",
      page_url: c?.page_url, download: f.status === "missing" && c ? { url: c.url, folder, rel: value.replace(/\\/g, "/"), sha256: c.sha256, size: c.size, source: c.source, confidence: "high", dest: "E:\\…", shared: true } : null };
  };
  return [one("checkpoint", "Lumen XL", "v3.0", "Illustrious\\lumen_xl_v3.safetensors", "checkpoints", null),
    one("lora", "Paper Cut Style", "v1.1", "Illustrious\\paper_cut_style.safetensors", "loras", 0.8),
    one("lora", "Harbor Lights", "v1.2", "Illustrious\\harbor_lights.safetensors", "loras", 0.55),
    one("lora", "Soft Pastel", "v1.5", "Illustrious\\soft_pastel_v15.safetensors", "loras", 0.35),
    // named differently in the image than on disk, and not on CivitAI any more: linked by hand
    { kind: "lora", name: "InkWashPDXL", version: "", weight: 0.6, base_model: "Pony", status: "unavailable", note: "No download source found",
      local: null, comfy_name: null, matched_by: null, download: null, page_url: null }];
}

// ---------------------------------------------------------------- 1.8: compare, history
function compareData(body) {
  const v = (id, name, date, size, words, dl, likes, imgs, desc) => ({ id, name, base_model: "Illustrious", published: date, early_access: false,
    description: desc, trained_words: words, file: `paper_cut_style_${name.replace(/\W/g, "")}.safetensors`, size, format: "fp16 pruned SafeTensor",
    downloads: dl, likes, images: imgs.map((n) => ({ url: `previews/${n}.png`, nsfw: false })), hidden_images: 0 });
  return { model: { id: body.model_id, name: "Paper Cut Style", type: "LORA", creator: "foldworks" },
    have: v(body.have, "v1.1", "2026-06-02", 218 * MB, ["papercut"], 18240, 2210, [1, 9, 12], ""),
    newer: v(body.newer, "v1.2", "2026-09-20", 218 * MB, ["papercut", "layered paper"], 3410, 640, [13, 14, 15],
      "Retrained on 300 new images.\n\n• Cleaner edges at strength 0.6–0.8\n• New trigger: layered paper, for deep multi-layer scenes\n• Less colour bleed into backgrounds") };
}

// ---------------------------------------------------------------- 1.9: archive
const archiveJob = { status: "idle" };
const FAMS = [
  ["1girl, red dress, standing in the rain, city at night, neon lights, reflections on wet street", 412, 5],
  ["a lighthouse on a cliff at dusk, paper cut style, layered paper, soft pastel palette, crashing waves", 288, 3],
  ["cozy reading nook, warm lamp light, rain on the window, cat sleeping on a blanket, watercolor", 251, 4],
  ["cyberpunk street market, night, holographic signs, crowded, cinematic lighting, 35mm", 197, 2],
  ["forest spirit, glowing moss, ancient trees, volumetric light, fantasy art, highly detailed", 164, 6],
  ["portrait of an old sailor, weathered face, oil painting, dramatic rim light, dark background", 120, 1],
];
function tickArchive() {
  const j = archiveJob;
  j.done = Math.min(j.total, j.done + 610);
  j.current = `2026-10/batch_${String(Math.floor(j.done / 400)).padStart(2, "0")}/ComfyUI_${String(j.done).padStart(5, "0")}_.png`;
  if (j.done >= j.total) {
    Object.assign(j, { status: "done", phase: null, current: null, result: {
      folder: j.folder, out_dir: j.folder + "\\_ml_archive", images: 3482, with_meta: 3455, families: 61, variants: 143, no_meta: 27,
      original_mb: 19480, archive_mb: 172, finished: now(),
      top: FAMS.map(([base, count, variants], i) => ({ id: `f${String(i + 1).padStart(3, "0")}`, base, count, variants,
        thumbs: [0, 1, 2, 3, 4, 5].map((k) => `t${1 + ((i * 3 + k) % 16)}`) })) } });
  }
  return j;
}

function storageHistory() {
  const t1 = now(), samples = [], moves = [];
  let ssd = 160 * GB, hdd = 2.9 * 1024 * GB;
  const day = (t) => new Date(t * 1000).toISOString().slice(0, 10);
  for (let t = t1 - 90 * 86400; t <= t1; t += 6 * 3600) {
    ssd -= (0.18 + 0.12 * Math.sin(t / 50000)) * GB; // downloads eat the SSD
    const d = Math.floor((t1 - t) / 86400);
    if ([75, 52, 30, 9].includes(d) && Math.floor(((t1 - t) % 86400) / 21600) === 0) {
      const a = (d === 9 ? 46 : 28) * GB, r = 4.2 * GB;
      ssd += a - r; hdd -= a - r;
      moves.push({ day: day(t), archived: a, archived_n: Math.round(a / (6.5 * GB)), restored: r, restored_n: 1 });
    }
    samples.push({ t, drives: { "E:": { role: "models", free: ssd, total: 1024 * GB }, "F:": { role: "archive", free: hdd, total: 4096 * GB } } });
  }
  return { samples, moves, drives: [{ label: "E:", role: "models" }, { label: "F:", role: "archive" }], goal: 120 * GB, days: 90, now: t1 };
}
SOURCES["lumen_xl_v3.safetensors"].filename = "lumen_xl_v3.safetensors";
const recipes = [
  { id: "a1b2c3d4e5f6", title: "Paper-cut koi pond", base_model: "Illustrious", model: "Illustrious\\aurora_illustrious_v4.safetensors", lora_count: 2, tags: ["paper"], fav: true, has_thumb: true, created: 3, _img: 101 },
  { id: "0123456789ab", title: "Neon rain alley (Flux)", base_model: "Flux.1 D", model: "flux1-dev-Q5_K_M.gguf", lora_count: 1, tags: [], fav: false, has_thumb: true, created: 2, _img: 102 },
  { id: "abcdefabcdef", title: "Clay robot", base_model: "Qwen", model: "qwen_image_fp8", lora_count: 1, tags: ["clay"], fav: false, has_thumb: true, created: 1, _img: 103 },
];

// ---------------------------------------------------------------- storage + organize
function tierPlan() {
  const item = (name, rel, size, section, days, family, reason) => ({ id: "t" + name, name, rel, section, size, title: null, family, last_used: days ? now() - days * 86400 : null, idle_days: days, reason });
  const ready = [
    item("lumen_xl_v3_ft.safetensors", "Illustrious/old/lumen_xl_v3_ft.safetensors", 6.46 * GB, "checkpoints", 34, "Illustrious", "goal"),
    item("studio_real_xl.safetensors", "SDXL/studio_real_xl.safetensors", 6.94 * GB, "checkpoints", 96, "SDXL", "idle"),
    item("nightfall_xl.safetensors", "SDXL/nightfall_xl.safetensors", 6.94 * GB, "checkpoints", 71, "SDXL", "idle"),
    item("sunlit_pony.safetensors", "Pony/sunlit_pony.safetensors", 6.62 * GB, "checkpoints", 64, "Pony", "idle"),
    item("film_grain_z.safetensors", "ZImage/film_grain_z.safetensors", 170 * MB, "loras", 88, "ZImage", "idle"),
  ];
  return { archive_dir: "R:\\ModelArchive", connected: true, free: 1.62 * 1024 * GB, after_days: 60, sections: ["checkpoints", "loras", "diffusion_models"],
    ready, archived: [item("old_concept_v1.safetensors", "SD15/old_concept_v1.safetensors", 2.13 * GB, "checkpoints", 210, "SD1.5")],
    ready_bytes: ready.reduce((a, x) => a + x.size, 0), archived_bytes: 2.13 * GB, restore_on_use: true, queued_restores: 0,
    goal: { drive: "E:\\StabilityMatrix\\Data\\Models", free: 171 * GB, goal: 200 * GB, protect_days: 14, need: 29 * GB, picked: 1, after: 204 * GB, reachable: true } };
}
const organizePlan = {
  already_sorted: 214, unknown: [{ rel: "mystery_merge.safetensors" }], folders: FAMILIES,
  moves: [
    ["harbor_lights.safetensors", "loras", "Illustrious", "IL", "high", "CivitAI base model: Illustrious", "Illustrious/harbor_lights.safetensors", "loose file"],
    ["neon_rim_light.safetensors", "loras", "Flux", "FLUX", "high", "LoRA training metadata (ss_base_model_version flux1)", "Flux/neon_rim_light.safetensors", "loose file"],
    ["velvet_pony_v12.safetensors", "checkpoints", "Pony", "PONY", "high", "CivitAI base model: Pony", "Pony/velvet_pony_v12.safetensors", "loose file"],
    ["clay_render.safetensors", "loras", "Qwen", "QWEN", "medium", "Tensor layout: Qwen-Image transformer blocks", "Qwen/clay_render.safetensors", "in the wrong family folder (SDXL)"],
    ["motion_sway_LOW.safetensors", "loras", "Wan", "WAN", "high", "CivitAI base model: Wan Video 2.2 I2V-A14B", "Wan/motion_sway_LOW.safetensors", "loose file"],
    ["anime_lines.safetensors", "loras", "Illustrious", "IL", "low", "File name contains 'il'", "Illustrious/anime_lines.safetensors", "loose file"],
  ].map(([name, section, family, badge, confidence, evidence, to_rel, reason], i) => ({
    id: "o" + i, name, section, root_name: section === "loras" ? "Lora" : "StableDiffusion", from_rel: reason.startsWith("in the") ? "SDXL/" + name : name,
    family, badge, confidence, evidence, to_rel, reason, conflict: null, checked: confidence !== "low", target_folder: to_rel.split("/")[0],
  })),
};

// ---------------------------------------------------------------- routes
window.reqs = [];
const status = {
  config: { has_civitai_token: true, recipes_mirror_lm: false, archive_dir: "R:\\ModelArchive", check_updates: false, free_goal_gb: 200, protect_days: 14, auto_check_on_load: false },
  lm_installed: false, gguf_installed: true, sep: "\\", families: FAMILIES,
  sections: { loras: "LoRAs", checkpoints: "Checkpoints", diffusion_models: "Diffusion models", embeddings: "Embeddings" },
  sm: { mode: "shared", models_root: "E:\\StabilityMatrix\\Data\\Models" }, destinations: {},
};
const imgUrl = (n) => `previews/${((n - 1) % 16) + 1}.png`;

export const api = {
  api_base: "",
  apiURL(p) {
    let m = p.match(/^\/sm-fetcher\/preview\/(f\d+)/);
    if (m) {
      const e = Object.values(LIB).flat().find((x) => x.id === m[1]);
      return imgUrl(e ? e._img : 1);
    }
    m = p.match(/^\/sm-fetcher\/archive\/thumb\?.*name=t(\d+)/);
    if (m) return imgUrl(Number(m[1]));
    m = p.match(/^\/sm-fetcher\/recipes\/(\w+)\/thumb/);
    if (m) {
      const r = recipes.find((x) => x.id === m[1]);
      return imgUrl(r ? r._img : 104);
    }
    return "/api" + p;
  },
  async fetchApi(path, opts = {}) {
    const method = opts.method || "GET";
    const body = typeof opts.body === "string" ? JSON.parse(opts.body) : opts.body;
    window.reqs.push({ path, method });
    await new Promise((r) => setTimeout(r, 60));
    const p = path.replace(/^\/sm-fetcher/, "");
    if (p === "/status") return json(status);
    if (p === "/scan") return json({ items: scanItems(body.refs), budget: 10.5 * GB, sm_mode: "shared" });
    if (p === "/resolve") { await new Promise((r) => setTimeout(r, 500)); return json({ candidates: candidates(body.value) }); }
    if (p === "/download") return json({ job: startJob(body) });
    if (p === "/jobs") { tickJobs(); return json({ jobs }); }
    if (p === "/jobs/clear") { jobs.splice(0, jobs.length, ...jobs.filter((j) => j.status === "downloading")); return json({ ok: true }); }
    if (p === "/workflows/health") return json(health());
    if (p === "/workflows/scan") {
      let n = 0;
      if (body?.apply) for (const [f, models] of Object.entries(SAVED)) models.forEach((m) => { if (moved[base(m[1])]) { m[1] = moved[base(m[1])]; n++; } });
      return json({ workflows: [], fixed_files: n ? 1 : 0, fixable_files: 0, fixes: n, backup_dir: n ? "…\\workflow_backups\\20261012-2310" : null });
    }
    if (p.startsWith("/library?")) {
      const sec = new URLSearchParams(p.split("?")[1]).get("section");
      return json({ section: sec, roots: [sec === "loras" ? "Lora" : "Models"], entries: (LIB[sec] || []).map(({ _img, ...e }) => e), blur_nsfw: true });
    }
    if (p === "/identify") return json({ status: "idle" });
    if (p === "/updates") return json({ status: "done", last_check: now() - 3600, stale: false, updates: 4 });
    if (p === "/updates/candidate") {
      const e = Object.values(LIB).flat().find((x) => x.id === body.id);
      const rel = e.rel.replace(/[^/]+$/, "") + `${stem(e.name)}_new.safetensors`;
      return json({ candidate: { url: "https://example.invalid/u", filename: base(rel), sha256: "cd".repeat(32), size: e.size, source: "civitai" }, folder: e.section, rel });
    }
    if (p === "/updates/dismiss") return json({ ok: true });
    if (p === "/tiering/plan") return json(tierPlan());
    if (p === "/tiering/job") return json({ status: "idle" });
    if (p === "/tiering/archive") {
      for (const e of Object.values(LIB).flat()) if ((body.ids || []).includes(e.id)) e.archived = true;
      return json({ status: "running", kind: "archive", done: 0, total: (body.ids || []).length });
    }
    if (p === "/tiering/events") return json({ events: [], now: now() });
    if (p === "/organize/history") return json({ runs: [{ id: "r1", time: now() - 86400 * 3, kind: "organize", count: 42 }] });
    if (p === "/organize/plan") { await new Promise((r) => setTimeout(r, 400)); return json(JSON.parse(JSON.stringify(organizePlan))); }
    if (p === "/recipes" && method === "GET") return json({ recipes: recipes.map(({ _img, ...x }) => x) });
    if (p === "/recipes" && method === "POST") {
      const id = "ffffffffffff";
      recipes.unshift({ id, title: body.recipe.title, base_model: body.recipe.base_model, model: body.recipe.model?.file, lora_count: body.recipe.loras.length, tags: body.recipe.tags || [], fav: false, has_thumb: true, created: 9, _img: 104 });
      return json({ recipe: { ...body.recipe, id, created: 9 } });
    }
    if (p.match(/^\/recipes\/\w+$/)) return json({ recipe: { ...RECIPE, title: recipes.find((x) => p.endsWith(x.id))?.title || RECIPE.title } });
    if (p === "/recipe/analyze") { await new Promise((r) => setTimeout(r, 600)); return json({ recipe: RECIPE, thumb: null, items: recipeItems() }); }
    if (p === "/recipe/plan") return json({ items: recipeItems(), recipe: body.recipe });
    if (p === "/library/notes") {
      const e = Object.values(LIB).flat().find((x) => x.id === body.id);
      const tags = String(body.tags || "").split(",").map((t) => t.trim()).filter(Boolean);
      e.notes = { rating: body.rating || 0, note: body.note || "", tags };
      return json({ notes: e.notes });
    }
    if (p === "/archive/status") return json(archiveJob.status === "running" ? tickArchive() : archiveJob);
    if (p === "/archive/start") { Object.assign(archiveJob, { status: "running", folder: body.folder, phase: "reading", done: 0, total: 3482, started: now(), reused: 0 }); return json(archiveJob); }
    if (p === "/archive/cancel") { archiveJob.status = "cancelled"; return json({ ok: true }); }
    if (p.startsWith("/archive/summary")) return json({ summary: archiveJob.status === "done" ? archiveJob.result : null });
    if (p === "/updates/compare") { await new Promise((r) => setTimeout(r, 400)); return json(compareData(body)); }
    if (p.startsWith("/storage/history")) return json(storageHistory());
    if (p === "/recipe/link") return json({ item: { ...body.item, status: "present", local: body.file, comfy_name: body.file, matched_by: "your link", note: null } });
    if (p === "/workflows/sources") { await new Promise((r) => setTimeout(r, 500)); const rows = shareRows(body.items || []); return json({ sources: rows, markdown: shareMarkdown(rows, body.title) }); }
    if (p === "/civarchive/lookup") { await new Promise((r) => setTimeout(r, 400)); return json({ record: ARCHIVE, page_url: ARCHIVE.page_url }); }
    if (p === "/partials/summary") return json({ count: 0, size: 0, truncated: 0, resumable: 0 });
    if (p === "/partials") return json({ partials: [] });
    if (p === "/hf/details") return json({ repo: body.repo, details: Object.values(LIB).flat().find((x) => x.hf?.repo === body.repo)?.hf });
    if (p.startsWith("/lm/")) return json({ items: [] });
    return json({ error: "unmocked " + p }, 404);
  },
};
