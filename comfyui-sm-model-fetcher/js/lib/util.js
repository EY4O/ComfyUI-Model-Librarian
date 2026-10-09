// Shared helpers for SM Model Fetcher (no side effects on import).
export const ctx = { app: null, api: null, status: null };

export function setContext(app, api) {
  ctx.app = app;
  ctx.api = api;
}

export async function call(path, { method = "GET", body } = {}) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.body = JSON.stringify(body);
    opts.headers["Content-Type"] = "application/json";
  }
  const r = await ctx.api.fetchApi("/sm-fetcher" + path, opts);
  let data = null;
  try {
    data = await r.json();
  } catch {
    data = null;
  }
  if (!r.ok) throw new Error((data && data.error) || `HTTP ${r.status}`);
  return data;
}

// LoRA Manager keeps its own model cache and has no file watcher: after we add or
// move files, ask it to rescan so its loaders (and queue-time validation) see them.
const LM_PREFIX = { loras: "loras", checkpoints: "checkpoints", diffusion_models: "checkpoints", embeddings: "embeddings" };
const lmScan = { running: false, queued: new Map() }; // prefix -> full rebuild?

// full: re-read every .metadata.json (LoRA Manager's quick scan only picks up
// added/removed files, not edited metadata)
export async function lmRescan(folders = Object.keys(LM_PREFIX), { full = false } = {}) {
  if (!ctx.status?.lm_installed) return;
  for (const f of folders) {
    const p = LM_PREFIX[f];
    if (p) lmScan.queued.set(p, full || !!lmScan.queued.get(p));
  }
  if (lmScan.running) return; // the running loop picks up the new prefixes
  lmScan.running = true;
  try {
    while (lmScan.queued.size) {
      const [prefix, isFull] = lmScan.queued.entries().next().value;
      lmScan.queued.delete(prefix);
      try {
        const r = await ctx.api.fetchApi(`/lm/${prefix}/scan${isFull ? "?full_rebuild=true" : ""}`);
        if (!r.ok) console.warn(`[SM Model Fetcher] LoRA Manager ${prefix} rescan: HTTP ${r.status}`);
      } catch (e) {
        console.warn("[SM Model Fetcher] LoRA Manager rescan failed", e);
      }
    }
  } finally {
    lmScan.running = false;
  }
}

export function apiUrl(path) {
  return ctx.api.apiURL ? ctx.api.apiURL("/sm-fetcher" + path) : "/api/sm-fetcher" + path;
}

export async function refreshStatus() {
  ctx.status = await call("/status");
  return ctx.status;
}

// tiny hyperscript: h("div.cls", {onclick}, children...)
export function h(tag, attrs, ...kids) {
  const [name, ...classes] = tag.split(".");
  const el = document.createElement(name || "div");
  if (classes.length) el.className = classes.join(" ");
  if (attrs && (typeof attrs !== "object" || attrs instanceof Node || Array.isArray(attrs))) {
    kids.unshift(attrs);
    attrs = null;
  }
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "style" && typeof v === "object") Object.assign(el.style, v);
    else if (k === "class") el.className += " " + v;
    else if (k in el && k !== "list" && k !== "type") el[k] = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  append(el, kids);
  return el;
}

function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k === null || k === undefined || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}

export function clear(el, ...kids) {
  el.replaceChildren();
  append(el, kids);
  return el;
}

export function fmtSize(b) {
  if (!b && b !== 0) return "?";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (b >= 1024 && i < u.length - 1) {
    b /= 1024;
    i++;
  }
  return `${b.toFixed(i >= 3 ? 2 : i >= 2 ? 1 : 0)} ${u[i]}`;
}

export function toast(severity, summary, detail, life = 4000) {
  const t = ctx.app?.extensionManager?.toast;
  if (t?.add) t.add({ severity, summary, detail, life });
  else console.log(`[SM Model Fetcher] ${summary}: ${detail || ""}`);
}

export async function copy(text, what = "Copied") {
  try {
    await navigator.clipboard.writeText(text);
    toast("success", what, text.length > 80 ? text.slice(0, 80) + "…" : text, 2000);
  } catch {
    window.prompt("Copy:", text);
  }
}

export function pill(text, kind = "", title = "") {
  return h("span.smf-pill" + (kind ? "." + kind : ""), { title }, text);
}

export function spinner() {
  return h("span.smf-spin");
}

export const FAMILY_COLORS = {
  Illustrious: "#c084fc", NoobAI: "#a78bfa", Pony: "#f472b6", SDXL: "#60a5fa", "SD1.5": "#34d399",
  SD2: "#2dd4bf", SD3: "#38bdf8", Flux: "#fbbf24", "Flux Kontext": "#f59e0b", "Flux.2": "#fb923c",
  Chroma: "#facc15", "Krea 2": "#fde047", Qwen: "#818cf8", Wan: "#f87171", HunyuanVideo: "#fb7185",
  LTXV: "#e879f9", Lumina: "#a3e635", "Z-Image": "#4ade80", Anima: "#f0abfc", HiDream: "#5eead4",
};

export function familyBadge(family, badge) {
  const c = FAMILY_COLORS[family] || "#9ca3af";
  return h("span.smf-fam", { style: { color: c, borderColor: c + "88" }, title: family || "Unknown" },
    badge || (family ? family.toUpperCase() : "UNKN"));
}

export function confPill(conf) {
  const map = { high: ["High", "ok"], medium: ["Medium", "warn"], low: ["Low", "bad"] };
  const [t, k] = map[conf] || ["?", ""];
  return pill(t, k, "Detection confidence");
}

export function debounce(fn, ms = 200) {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
}
