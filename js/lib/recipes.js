// "Recipes" tab: drop an image (or paste a CivitAI image link), let LoRA Manager
// read its generation data, save it as a LoRA Manager recipe, and download every
// model it used (checkpoint + LoRAs) into Stability Matrix's shared folders.
import { call, ctx, h, clear, fmtSize, toast, pill, spinner, familyBadge, copy } from "./util.js";
import { startDownload, onJobsChange } from "./downloads.js";

const r = {
  root: null, file: null, url: "", preview: null, isVideo: false, analysis: null, plan: null,
  busy: null, error: null, name: "", tags: "", savedId: null,
};
const queued = new Map(); // jobId -> plan item

onJobsChange((jobs, finished) => {
  let changed = false;
  for (const j of finished) {
    const it = queued.get(j.id);
    if (!it) continue;
    queued.delete(j.id);
    it.job = null;
    if (j.status === "done") {
      it.status = "present";
      it.local = it.download.rel;
      it.matched_by = "downloaded";
    } else it.note = j.error || "Download failed";
    changed = true;
  }
  if (changed) render();
});

export function mount(root) {
  r.root = root;
  render();
}

// Called for drops anywhere on the Model Librarian window. Must read the
// DataTransfer synchronously: it's emptied once the event handler returns.
export function canHandle(dt) {
  return !!pickFile(dt) || !!pickUrl(dt);
}

export function handleDrop(dt) {
  const f = pickFile(dt);
  if (f) return analyzeFile(f);
  const u = pickUrl(dt);
  if (u) {
    r.url = u;
    return analyzeUrl(u);
  }
}

// ComfyUI writes the workflow into PNG tEXt/iTXt chunks ("workflow")
async function pngWorkflow(file) {
  if (!file || file.type !== "image/png") return null;
  const buf = new Uint8Array(await file.arrayBuffer());
  const sig = [137, 80, 78, 71, 13, 10, 26, 10];
  if (!sig.every((b, i) => buf[i] === b)) return null;
  const view = new DataView(buf.buffer);
  const latin1 = new TextDecoder("latin1"), utf8 = new TextDecoder("utf-8");
  for (let off = 8; off + 8 <= buf.length;) {
    const len = view.getUint32(off);
    const type = latin1.decode(buf.subarray(off + 4, off + 8));
    const data = buf.subarray(off + 8, off + 8 + len);
    if (type === "tEXt" || type === "iTXt") {
      const nul = data.indexOf(0);
      const key = latin1.decode(data.subarray(0, nul));
      if (key === "workflow") {
        let rest = data.subarray(nul + 1);
        if (type === "iTXt") { // compression flag, method, language\0, translated keyword\0
          if (rest[0] !== 0) return null; // compressed iTXt: not used by ComfyUI
          rest = rest.subarray(2);
          rest = rest.subarray(rest.indexOf(0) + 1);
          rest = rest.subarray(rest.indexOf(0) + 1);
        }
        try { return JSON.parse((type === "iTXt" ? utf8 : latin1).decode(rest)); } catch { return null; }
      }
    }
    if (type === "IEND") break;
    off += 12 + len;
  }
  return null;
}

function loraSyntax() {
  const stem = (p) => (p || "").split(/[\\/]/).pop().replace(/\.(safetensors|ckpt|pt|bin)$/i, "");
  // LoRA Manager resolves <lora:name:...> by file stem, wherever the file lives
  return (r.plan?.items || []).filter((it) => it.kind === "lora" && it.status !== "unavailable")
    .map((it) => `<lora:${stem(it.local || it.download?.rel) || it.name}:${Number(it.weight ?? 1)}>`)
    .join(" ");
}

function pickFile(dt) {
  return [...(dt?.files || [])].find((f) => /^(image|video)\//.test(f.type)) || null;
}

function pickUrl(dt) {
  const txt = dt?.getData?.("text/uri-list") || dt?.getData?.("text/plain") || "";
  return txt.split(/\r?\n/).map((l) => l.trim()).find((l) => /^https:\/\//.test(l)) || null;
}

function reset() {
  if (r.preview?.startsWith("blob:")) URL.revokeObjectURL(r.preview);
  Object.assign(r, { file: null, preview: null, isVideo: false, analysis: null, plan: null, error: null, savedId: null, workflow: null });
}

async function lm(path, opts) {
  const res = await ctx.api.fetchApi(path, opts);
  let data = null;
  try { data = await res.json(); } catch {}
  if (!res.ok) throw new Error(data?.error || `LoRA Manager: HTTP ${res.status}`);
  return data;
}

async function analyzeFile(f) {
  reset();
  r.file = f;
  r.preview = URL.createObjectURL(f);
  r.isVideo = f.type.startsWith("video/");
  r.name = f.name.replace(/\.[^.]+$/, "");
  r.workflow = await pngWorkflow(f).catch(() => null);
  const fd = new FormData();
  fd.append("image", f);
  await analyze(() => lm("/lm/recipes/analyze-image", { method: "POST", body: fd }));
}

async function analyzeUrl(url) {
  url = (url || "").trim();
  if (!/^https:\/\//.test(url)) return toast("warn", "Invalid link", "Paste an https:// CivitAI image link.");
  reset();
  r.url = url;
  const id = url.match(/\/images\/(\d+)/)?.[1];
  r.name = id ? `CivitAI image ${id}` : "Imported image";
  await analyze(() => lm("/lm/recipes/analyze-image", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url }),
  }));
}

async function analyze(fetcher) {
  r.busy = "Reading generation data (LoRA Manager)…";
  render();
  try {
    const a = await fetcher();
    r.analysis = a;
    if (!r.preview && a.image_base64) {
      const ext = (a.extension || ".jpg").replace(".", "").toLowerCase();
      r.isVideo = !!a.is_video;
      r.preview = `data:${r.isVideo ? "video" : "image"}/${ext === "jpg" ? "jpeg" : ext};base64,${a.image_base64}`;
    }
    const checkpoint = a.checkpoint || a.model || null;
    if (!a.loras?.length && !checkpoint) {
      r.error = a.error || "No generation data found in this image (it may have been stripped when it was saved or shared).";
    } else {
      r.busy = "Looking up the models it used…";
      render();
      r.plan = await call("/recipe/plan", { method: "POST", body: { loras: a.loras || [], checkpoint } });
    }
  } catch (e) {
    r.error = e.message;
  }
  r.busy = null;
  render();
}

async function save() {
  const a = r.analysis;
  const fd = new FormData();
  if (r.file) fd.append("image", r.file);
  else if (a.image_base64) fd.append("image_base64", a.image_base64);
  else return toast("error", "Can't save", "LoRA Manager didn't return the image.");
  fd.append("name", r.name.trim() || "Imported recipe");
  fd.append("tags", JSON.stringify(r.tags.split(",").map((t) => t.trim()).filter(Boolean)));
  const meta = {
    base_model: a.base_model || "", loras: a.loras || [], gen_params: a.gen_params || {},
    raw_metadata: a.raw_metadata || {},
  };
  const checkpoint = a.checkpoint || a.model || a.gen_params?.checkpoint;
  if (checkpoint && typeof checkpoint === "object") meta.checkpoint = checkpoint;
  if (a.diagnostics && typeof a.diagnostics === "object") meta.diagnostics = a.diagnostics;
  if (a.preview_nsfw_level !== undefined && a.preview_nsfw_level !== null) meta.preview_nsfw_level = a.preview_nsfw_level;
  if (!r.file && r.url) meta.source_path = r.url;
  if (a.extension) fd.append("extension", a.extension);
  fd.append("metadata", JSON.stringify(meta));
  const res = await lm("/lm/recipes/save", { method: "POST", body: fd });
  if (!res?.success) throw new Error(res?.error || "LoRA Manager didn't save the recipe");
  r.savedId = res.recipe_id || true;
}

async function downloadItem(it) {
  const { confidence, dest, shared, ...payload } = it.download;
  // CivitAI calls UNet-only files "Checkpoint" too; the backend moves those to diffusion_models
  if (it.kind === "checkpoint") payload.auto_place = true;
  const job = await startDownload(payload);
  it.job = job.id;
  queued.set(job.id, it);
}

function missing(includeLow) {
  return (r.plan?.items || []).filter((it) => it.status === "missing" && it.download && !it.job &&
    (includeLow || it.download.confidence !== "low"));
}

async function run({ doSave, doDownload }) {
  r.busy = doSave ? "Saving recipe…" : "Queueing downloads…";
  render();
  try {
    if (doSave && !r.savedId) await save();
    let n = 0;
    if (doDownload) for (const it of missing(false)) { await downloadItem(it); n++; }
    const parts = [];
    if (doSave) parts.push(`saved “${r.name}” to LoRA Manager`);
    if (doDownload) parts.push(n ? `${n} download(s) queued` : "nothing to download");
    toast("success", "Recipe", parts.join(" · "), 5000);
  } catch (e) {
    toast("error", "Recipe failed", e.message, 8000);
  }
  r.busy = null;
  render();
}

// ---------------------------------------------------------------- render
function statusCell(it) {
  if (it.job) return h("span", spinner(), " downloading");
  if (it.status === "present") return h("span", pill("Installed", "ok", `Matched by ${it.matched_by}`), " ",
    h("span.smf-dim.small", { title: it.local }, it.matched_by));
  if (it.status === "missing") {
    const c = it.download?.confidence;
    return h("span", pill("Missing", "bad"), c && c !== "high" ? [" ", pill(`${c} match`, "warn", "Found by searching the file name — check it's the right model")] : null);
  }
  return pill("Unavailable", "dim", it.note || "");
}

function itemRow(it) {
  const d = it.download;
  return h("tr" + (it.status === "present" ? ".off" : ""),
    h("td", h("span.smf-type", it.kind === "lora" ? "LORA" : "CKPT")),
    h("td",
      h("div", h("b", it.name), it.version ? h("span.smf-dim", " — " + it.version) : null),
      it.base_model ? h("div.smf-dim.small", it.base_model) : null,
      it.note ? h("div.smf-warnline.small", it.note) : null),
    h("td", it.kind === "lora" && it.weight != null ? h("b", Number(it.weight).toFixed(2)) : h("span.smf-dim", "—")),
    h("td", statusCell(it)),
    h("td.small", d && it.status === "missing"
      ? [h("div", { title: d.dest }, d.shared ? pill("SM shared", "ok") : pill("ComfyUI only", "warn"), " ", `${d.folder}/${d.rel}`),
        d.size ? h("div.smf-dim", fmtSize(d.size), d.sha256 ? " · sha256 verified" : "") : null,
        it.kind === "checkpoint" ? h("div.smf-dim", "→ diffusion_models instead if it turns out to be UNet-only") : null]
      : null),
    h("td",
      it.page_url ? h("a.smf-link", { href: it.page_url, target: "_blank", rel: "noopener" }, "page ↗") : null, " ",
      d && it.status === "missing" && !it.job
        ? h("button.smf-btn.small", { onclick: () => downloadItem(it).then(render).catch((e) => toast("error", "Download failed", e.message)) }, "Download")
        : null));
}

function genParams(gp) {
  if (!gp || typeof gp !== "object") return null;
  const keys = [["steps", "Steps"], ["sampler", "Sampler"], ["cfg_scale", "CFG"], ["seed", "Seed"], ["size", "Size"], ["clip_skip", "Clip skip"]];
  const bits = keys.filter(([k]) => gp[k] !== undefined && gp[k] !== "").map(([k, l]) => `${l} ${gp[k]}`);
  return h("div.smf-dim.small",
    gp.prompt ? h("div.smf-recipe-prompt", { title: gp.prompt }, gp.prompt) : null,
    bits.length ? h("div", bits.join(" · ")) : null);
}

function dropZone() {
  const input = h("input", { type: "file", accept: "image/*,video/*", style: { display: "none" },
    onchange: (e) => e.target.files[0] && analyzeFile(e.target.files[0]) });
  const url = h("input.smf-input", { placeholder: "…or paste a CivitAI image link (civitai.com / civitai.red /images/…)", value: r.url,
    style: { flex: 1 }, oninput: (e) => (r.url = e.target.value), onkeydown: (e) => e.key === "Enter" && analyzeUrl(r.url) });
  return h("div",
    h("div.smf-drop", { onclick: () => input.click() }, input,
      h("div", h("b", "Drop an image here"), " or click to choose one"),
      h("div.smf-dim.small", "PNG / JPEG / WebP made with ComfyUI, A1111, Forge or downloaded from CivitAI. LoRA Manager reads the generation data.")),
    h("div.smf-row", { style: { marginTop: "8px" } }, url, h("button.smf-btn", { onclick: () => analyzeUrl(r.url) }, "Import link")));
}

export function render() {
  const root = r.root;
  if (!root || !root.isConnected) return;
  if (!ctx.status?.lm_installed) {
    return clear(root, h("div.smf-empty",
      "Recipes are stored by ", h("b", "LoRA Manager"), ", which isn't installed in this ComfyUI. Install ComfyUI-Lora-Manager via ComfyUI-Manager and restart."));
  }
  const intro = h("div.smf-help",
    "Drop an image to see every model it was made with and the LoRA strengths. ",
    h("b", "Save"), " stores it as a LoRA Manager recipe; ", h("b", "Download"),
    " fetches the checkpoint and LoRAs you're missing into Stability Matrix's shared folders, already sorted by base model.");
  const lmLink = h("a.smf-link", { href: `${ctx.api.api_base || ""}/loras/recipes`, target: "_blank", rel: "noopener" }, "LoRA Manager recipes ↗");
  let body = null;
  if (r.busy) body = h("div.smf-empty", spinner(), " ", r.busy);
  else if (r.error) body = h("div.smf-empty.err", r.error);
  else if (r.plan) {
    const items = r.plan.items;
    const need = missing(false).length;
    const needLow = missing(true).length - need;
    const media = r.preview
      ? r.isVideo ? h("video.smf-recipe-img", { src: r.preview, muted: true, loop: true, autoplay: true, playsInline: true })
        : h("img.smf-recipe-img", { src: r.preview, alt: "" })
      : null;
    const bm = r.analysis?.base_model;
    body = h("div",
      h("div.smf-recipe",
        media,
        h("div.smf-recipe-side",
          h("div.smf-field", h("label", "Recipe name"),
            h("input.smf-input", { value: r.name, oninput: (e) => (r.name = e.target.value), disabled: !!r.savedId })),
          h("div.smf-field", h("label", "Tags (comma separated)"),
            h("input.smf-input", { value: r.tags, oninput: (e) => (r.tags = e.target.value), disabled: !!r.savedId })),
          bm ? h("div", "Base model: ", familyBadge(null, bm)) : null,
          genParams(r.analysis?.gen_params),
          h("div.smf-actions",
            r.savedId
              ? h("span", pill("Saved to LoRA Manager", "ok"), " ", lmLink)
              : h("button.smf-btn.primary", { onclick: () => run({ doSave: true, doDownload: true }) },
                need ? `Save recipe & download ${need} missing` : "Save recipe"),
            !r.savedId && need ? h("button.smf-btn", { onclick: () => run({ doSave: true, doDownload: false }) }, "Save only") : null,
            need ? h("button.smf-btn", { onclick: () => run({ doSave: false, doDownload: true }) }, `Download ${need} missing only`) : null),
          needLow ? h("div.smf-dim.small", `${needLow} more found only by searching the file name — check them and use their Download button.`) : null,
          h("div.smf-actions",
            items.some((it) => it.kind === "lora" && it.status !== "unavailable")
              ? h("button.smf-btn.small", { title: "For LoRA Manager's Lora Loader text box", onclick: () => copy(loraSyntax(), "LoRA syntax copied") }, "Copy LoRA syntax")
              : null,
            r.workflow
              ? h("button.smf-btn.small", {
                title: "This image was made in ComfyUI and contains its workflow",
                onclick: async () => {
                  try {
                    if (ctx.app.handleFile && r.file) await ctx.app.handleFile(r.file);
                    else await ctx.app.loadGraphData(r.workflow);
                    document.querySelector(".smf-close")?.click();
                  } catch (e) {
                    toast("error", "Couldn't open the workflow", e.message);
                  }
                },
              }, "Open its workflow")
              : null))),
      h("table.smf-table",
        h("tr", h("th", ""), h("th", "Model"), h("th", "Strength"), h("th", "Status"), h("th", "Saves to"), h("th", "")),
        items.map(itemRow)),
      h("div.smf-toolbar", { style: { marginTop: "10px" } }, h("button.smf-btn.small", { onclick: () => { reset(); r.url = ""; render(); } }, "Import another image")));
  }
  clear(root, intro, r.plan || r.busy ? null : dropZone(), body, h("div.smf-dim.small", { style: { marginTop: "10px" } }, lmLink));
}
