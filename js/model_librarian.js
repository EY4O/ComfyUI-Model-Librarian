// Model Librarian — ComfyUI frontend extension entry point.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
import { setContext, ctx, h, clear, refreshStatus, call, toast } from "./lib/util.js";
import { mountTray, poll } from "./lib/downloads.js";
import * as wf from "./lib/workflow.js";
import * as lib from "./lib/library.js";
import { mountOrganize, mountDuplicates } from "./lib/organize.js";
import { mountRegistry, mountSettings, checkLeftovers } from "./lib/settings.js";
import * as rec from "./lib/recipes.js";
import * as storage from "./lib/storage.js";

setContext(app, api);

// The logo (docs/images/icon.png at 64px), for the window header and the toolbar button.
const LOGO = new URL("./assets/logo-64.png", import.meta.url).href;

const CSS = `
.smf-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10000;display:flex;align-items:center;justify-content:center}
.smf-modal{--smf-bg:var(--comfy-menu-bg,#202020);--smf-bg2:var(--comfy-input-bg,#2a2a2a);--smf-fg:var(--input-text,#ddd);--smf-dim:var(--descrip-text,#999);--smf-border:var(--border-color,#444);--smf-accent:#3b82f6;
 width:min(1500px,94vw);height:90vh;background:var(--smf-bg);color:var(--smf-fg);border:1px solid var(--smf-border);border-radius:12px;display:flex;flex-direction:column;overflow:hidden;font-size:13px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.smf-header{display:flex;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid var(--smf-border)}
.smf-logo{font-weight:700;margin-right:12px;white-space:nowrap;display:inline-flex;align-items:center;gap:7px}
.smf-logo-img{width:22px;height:22px;flex:none}
.smf-logo-icon{display:inline-block;width:16px;height:16px;background:url(${LOGO}) center/contain no-repeat;vertical-align:middle}
.smf-tab{background:none;border:none;color:var(--smf-dim);padding:6px 12px;border-radius:8px;cursor:pointer;font-size:13px}
.smf-tab.sel{background:var(--smf-accent);color:#fff}
.smf-tab:hover:not(.sel){background:var(--smf-bg2);color:var(--smf-fg)}
.smf-kofi-banner{display:flex;align-items:center;gap:12px;margin-bottom:12px;padding:10px 12px 10px 16px;border-radius:10px;background:#FF813F;color:#fff}
.smf-kofi-banner .smf-kofi-text{flex:1;font-size:13px;line-height:1.4}
.smf-kofi-banner .smf-kofi-text b{font-size:13.5px}
.smf-kofi-link{background:#fff;color:#E2621F;border-radius:8px;padding:6px 12px;font-weight:700;font-size:12.5px;text-decoration:none;white-space:nowrap}
.smf-kofi-link:hover{background:#FFF1E8}
.smf-kofi-x{background:none;border:none;color:#fff;font-size:20px;line-height:1;cursor:pointer;padding:0 4px;opacity:.85}
.smf-kofi-x:hover{opacity:1}
.smf-close{margin-left:auto;background:none;border:none;color:var(--smf-dim);font-size:20px;cursor:pointer}
.smf-body{flex:1;overflow:auto;padding:12px;position:relative}
.smf-body.lib{overflow:hidden;display:flex;flex-direction:column}
.smf-tray{border-top:1px solid var(--smf-border);padding:6px 12px;max-height:150px;overflow:auto;background:var(--smf-bg2);flex-shrink:0}
.smf-tray-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.smf-job{margin:3px 0;font-size:12px}.smf-job-row{display:flex;gap:8px;align-items:center}.smf-job-name{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.smf-job-meta{color:var(--smf-dim);font-size:12px}.smf-job-err{color:#f87171;font-size:12px}
.smf-bar{height:5px;background:rgba(255,255,255,.08);border-radius:3px;overflow:hidden;margin-top:3px}.smf-bar>div{height:100%;background:var(--smf-accent);transition:width .3s}
.smf-job.done .smf-bar>div{background:#22c55e}.smf-job.error .smf-bar>div{background:#ef4444}
.smf-bar.inline{width:160px;display:inline-block;margin:0 8px}
.smf-toolbar{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
.smf-row{display:flex;gap:8px;align-items:center}.smf-row.wrap{flex-wrap:wrap}
.smf-spacer{flex:1}
.smf-actions{display:flex;gap:6px;flex-wrap:wrap}
.smf-btn{background:var(--smf-bg2);color:var(--smf-fg);border:1px solid var(--smf-border);border-radius:7px;padding:5px 11px;cursor:pointer;font-size:12.5px;white-space:nowrap}
.smf-btn:hover:not(:disabled){border-color:var(--smf-accent)}.smf-btn:disabled{opacity:.45;cursor:default}
.smf-btn.primary{background:var(--smf-accent);border-color:var(--smf-accent);color:#fff}
.smf-btn.warn{border-color:#d97706;color:#fbbf24}.smf-btn.ghost{background:none}.smf-btn.small{padding:2px 8px;font-size:11.5px}
.smf-input,.smf-select{background:var(--smf-bg2);color:var(--smf-fg);border:1px solid var(--smf-border);border-radius:7px;padding:5px 8px;font-size:12.5px}
.smf-input{min-width:220px}.smf-input.small{min-width:0;width:140px}
textarea.smf-input{width:100%;font-family:monospace}
.smf-pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;border:1px solid var(--smf-border);color:var(--smf-dim);white-space:nowrap}
.smf-pill.ok{color:#4ade80;border-color:#166534}.smf-pill.warn{color:#fbbf24;border-color:#92400e}.smf-pill.bad{color:#f87171;border-color:#991b1b}
.smf-pill.src{color:#93c5fd;border-color:#1e3a8a}.smf-pill.dim{opacity:.8}
.smf-fam{display:inline-block;padding:0 6px;border:1px solid;border-radius:4px;font-size:10.5px;font-weight:700;letter-spacing:.3px}
.smf-dim{color:var(--smf-dim)}.small{font-size:11.5px}.err{color:#f87171}
.smf-empty{padding:40px;text-align:center;color:var(--smf-dim)}
.smf-help{color:var(--smf-dim);margin-bottom:10px;line-height:1.5}.smf-help code,.smf-modal code{background:var(--smf-bg2);padding:0 4px;border-radius:4px}
.smf-warnline{color:#fbbf24;margin:4px 0}
.smf-list{display:flex;flex-direction:column;gap:6px}
.smf-item{border:1px solid var(--smf-border);border-radius:9px;padding:8px 10px;background:rgba(255,255,255,.015)}
.smf-item.missing{border-left:3px solid #ef4444}.smf-item.elsewhere{border-left:3px solid #f59e0b}.smf-item.present{border-left:3px solid #22c55e}
.smf-item-head{display:flex;gap:10px;align-items:center}.smf-item-title{flex:1;min-width:0}.smf-item-title b{word-break:break-all}
.smf-item-sub{margin:4px 0 0 0}.smf-item-body{margin-top:8px;display:flex;flex-direction:column;gap:5px}
.smf-cand{display:flex;gap:8px;align-items:center;padding:5px 8px;border-radius:7px;border:1px solid transparent;cursor:pointer}
.smf-cand.sel{border-color:var(--smf-accent);background:rgba(59,130,246,.08)}.smf-cand-main{flex:1}
.smf-link{color:#93c5fd;text-decoration:none}.smf-link:hover{text-decoration:underline}
.smf-table{width:100%;border-collapse:collapse}.smf-table th{text-align:left;color:var(--smf-dim);font-weight:500;padding:4px 6px;border-bottom:1px solid var(--smf-border)}
.smf-table td{padding:5px 6px;border-bottom:1px solid rgba(255,255,255,.05);vertical-align:top}.smf-table tr.rec td{background:rgba(34,197,94,.07)}
.smf-table tr.off td{opacity:.5}.smf-table td.thumb img{width:44px;height:58px;object-fit:cover;border-radius:4px}
.smf-check{display:inline-flex;align-items:center;gap:4px;cursor:pointer;margin-right:8px}
.smf-details{margin-top:12px}.smf-details summary{cursor:pointer;color:var(--smf-dim)}
.smf-subtabs{display:flex;gap:4px;flex-wrap:wrap}.smf-subtab{background:var(--smf-bg2);border:1px solid var(--smf-border);color:var(--smf-dim);border-radius:7px;padding:4px 10px;cursor:pointer}
.smf-subtab.sel{color:#fff;border-color:var(--smf-accent);background:rgba(59,130,246,.25)}
.smf-lib{display:flex;flex:1;min-height:0;gap:10px}
.smf-lib-side{width:220px;overflow:auto;border-right:1px solid var(--smf-border);padding-right:8px;flex-shrink:0}
.smf-side-title{font-weight:600;margin:8px 0 4px;color:var(--smf-dim);font-size:11.5px;text-transform:uppercase;letter-spacing:.5px}
.smf-tree-item{padding:4px 8px;border-radius:6px;cursor:pointer;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.smf-tree-item:hover{background:var(--smf-bg2)}.smf-tree-item.sel{background:rgba(59,130,246,.2);color:#fff}
.smf-lib-main{flex:1;overflow:auto;min-width:0}
.smf-lib-head{display:flex;align-items:center;gap:8px;position:sticky;top:0;background:var(--smf-bg);padding:4px 0 8px;z-index:2}
.smf-jobinline{display:flex;align-items:center;gap:6px}
.smf-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:12px;padding-bottom:20px}
.smf-card{position:relative;aspect-ratio:3/4;border-radius:10px;overflow:hidden;background:#111;border:1px solid var(--smf-border);transition:transform .12s, box-shadow .12s}
.smf-card:hover{transform:translateY(-2px);box-shadow:0 6px 20px rgba(0,0,0,.4)}
.smf-media{position:absolute;inset:0;width:100%;height:100%;object-fit:cover}
.smf-media.none{display:flex;align-items:center;justify-content:center;background:repeating-linear-gradient(45deg,#2a2a2a,#2a2a2a 10px,#262626 10px,#262626 20px);color:#666;font-weight:800;font-size:22px;letter-spacing:2px}
.smf-media.blur{filter:blur(18px) brightness(.7)}
.smf-nsfw{position:absolute;inset:40% 10%;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.6);border-radius:8px;cursor:pointer;font-size:12px}
.smf-card-top{position:absolute;top:0;left:0;right:0;display:flex;align-items:center;gap:5px;padding:6px;background:linear-gradient(rgba(0,0,0,.75),transparent)}
.smf-type{font-size:10.5px;font-weight:700;color:#e5e7eb;letter-spacing:.3px}
.smf-icon{background:rgba(0,0,0,.35);border:none;color:#e5e7eb;width:24px;height:24px;border-radius:6px;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;text-decoration:none;font-size:13px;opacity:0;transition:opacity .15s}
.smf-card:hover .smf-icon{opacity:1}.smf-icon:hover{background:rgba(59,130,246,.7)}
.smf-card-bottom{position:absolute;bottom:0;left:0;right:0;padding:26px 8px 8px;background:linear-gradient(transparent,rgba(0,0,0,.85))}
.smf-card-title{font-weight:700;color:#fff;font-size:13px;line-height:1.25;text-shadow:0 1px 2px #000;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;margin-bottom:4px}
.smf-chip{display:inline-block;font-size:11px;padding:1px 6px;border:1px solid rgba(255,255,255,.35);border-radius:4px;color:#e5e7eb;background:rgba(0,0,0,.35);max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.smf-chip.dim{opacity:.75}
.smf-sentinel{grid-column:1/-1;text-align:center;padding:20px}
.smf-settings section{border:1px solid var(--smf-border);border-radius:9px;padding:10px 12px;margin-bottom:10px;display:flex;flex-direction:column;gap:8px}
.smf-settings h3{margin:0;font-size:14px}.smf-field{display:flex;flex-direction:column;gap:3px}.smf-field label{color:var(--smf-dim);font-size:12px}
.smf-famgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:6px}.smf-famgrid .smf-fam{min-width:70px;text-align:center}
.smf-dupgroup{border:1px solid var(--smf-border);border-radius:9px;padding:8px 10px;margin-bottom:8px}
.smf-duprow{display:flex;gap:8px;align-items:center;padding:3px 0}.smf-duprow span{word-break:break-all}
.smf-spin{display:inline-block;width:12px;height:12px;border:2px solid var(--smf-dim,#999);border-top-color:transparent;border-radius:50%;animation:smf-spin .8s linear infinite;vertical-align:-2px}
@keyframes smf-spin{to{transform:rotate(360deg)}}
.smf-badge-count{background:#ef4444;color:#fff;border-radius:99px;padding:0 6px;font-size:11px;margin-left:4px}
.smf-notice{position:fixed;right:16px;bottom:16px;z-index:9998;display:flex;align-items:center;gap:10px;padding:8px 10px 8px 14px;border-radius:10px;font-size:13px;
 background:var(--comfy-menu-bg,#202020);color:var(--input-text,#ddd);border:1px solid #92400e;box-shadow:0 8px 24px rgba(0,0,0,.45)}
.smf-notice-x{background:none;border:none;color:var(--descrip-text,#999);font-size:18px;cursor:pointer;padding:0 2px}
.smf-drop{border:2px dashed var(--smf-border);border-radius:12px;padding:34px 20px;text-align:center;cursor:pointer;display:flex;flex-direction:column;gap:6px;transition:border-color .15s,background .15s}
.smf-drop:hover,.smf-overlay.smf-dragging .smf-drop{border-color:var(--smf-accent);background:rgba(59,130,246,.06)}
.smf-overlay.smf-dragging .smf-modal{outline:2px solid var(--smf-accent);outline-offset:-2px}
.smf-recipe{display:flex;gap:16px;align-items:flex-start;margin-bottom:12px;flex-wrap:wrap}
.smf-recipe-img{max-width:260px;max-height:340px;border-radius:10px;object-fit:contain;background:#111}
.smf-recipe-side{flex:1;min-width:280px;display:flex;flex-direction:column;gap:8px}
.smf-drop.compact{padding:14px 20px}
.smf-scope{margin-bottom:10px;gap:4px}
.smf-chip.upd{border-color:#22c55e;color:#dcfce7;background:rgba(22,101,52,.75);cursor:pointer;display:inline-flex;align-items:center;gap:3px}
.smf-chip.upd:hover{background:rgba(22,163,74,.9)}
.smf-oldbanner{grid-column:1/-1;display:flex;align-items:center;gap:8px;padding:8px 12px;border:1px solid #22c55e;border-radius:9px;background:rgba(22,101,52,.18)}
.smf-chip-x{opacity:.7;padding:0 2px}.smf-chip-x:hover{opacity:1}
.smf-card.clickable{cursor:pointer}.smf-chip.stars{color:#facc15;border-color:rgba(250,204,21,.6)}
.smf-stars{display:flex;gap:2px}.smf-star{background:none;border:none;color:#9ca3af;font-size:20px;cursor:pointer;padding:0 2px;line-height:1}.smf-star.on{color:#facc15}
.smf-chip.hf{border-color:#f59e0b;background:rgba(120,72,0,.7);cursor:pointer}.smf-chip.hf:hover{background:rgba(180,110,0,.9)}
.smf-hf-pop{position:fixed;inset:0;z-index:10001;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center}
.smf-hf-card{width:min(720px,94%);max-height:86%;overflow:auto;background:var(--smf-bg,#1e1e1e);border:1px solid var(--smf-border);border-radius:12px;padding:14px 16px;display:flex;flex-direction:column;gap:8px;box-shadow:0 12px 40px rgba(0,0,0,.5)}
.smf-hf-row{display:grid;grid-template-columns:110px 1fr;gap:8px;font-size:13px}
.smf-share-card{width:min(940px,96%)}
.smf-chip.gone{border-color:#f87171;color:#fee2e2;background:rgba(127,29,29,.75)}
.smf-archive{display:flex;flex-direction:column;gap:4px;padding:6px 0;border-top:1px solid var(--smf-border);border-bottom:1px solid var(--smf-border)}
.smf-hf-readme{white-space:pre-wrap;word-break:break-word;font-size:12.5px;line-height:1.45;border-top:1px solid var(--smf-border);padding-top:10px;margin-top:6px;color:var(--smf-fg)}
.smf-wflist{border:1px solid var(--smf-border);border-radius:9px;padding:8px 10px;margin-bottom:10px;display:flex;flex-direction:column;gap:6px}
.smf-wfrows{max-height:190px;overflow:auto;display:flex;flex-direction:column}
.smf-wfrow{display:flex;align-items:center;gap:8px;padding:3px 4px;border-radius:6px}.smf-wfrow.sel{background:rgba(59,130,246,.12)}
.smf-recipe-card{cursor:pointer}.smf-video-badge{position:absolute;left:8px;bottom:56px;background:rgba(0,0,0,.6);color:#fff;border-radius:999px;width:24px;height:24px;display:flex;align-items:center;justify-content:center;font-size:11px}.smf-lm-section{margin-top:18px}.smf-lm-section h3{font-size:14px;margin:0 0 8px}.smf-recipe-card.off{opacity:.45}
.smf-choose{grid-template-columns:repeat(auto-fill,minmax(140px,1fr))}
.smf-fav{opacity:.85;font-size:15px}.smf-fav.on{opacity:1;color:#facc15}
.smf-promptbox{white-space:pre-wrap;word-break:break-word;max-height:120px;overflow:auto;border:1px solid var(--smf-border);border-radius:8px;padding:6px 8px;font-size:12.5px;color:var(--smf-fg)}
.smf-recipe-prompt{display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;margin-bottom:4px;color:var(--smf-fg)}
`;

const TABS = [
  ["workflow", "Workflow", (el) => wf.mount(el)],
  ["library", "Library", (el) => lib.mount(el), "lib"],
  ["organize", "Organize", (el) => mountOrganize(el)],
  ["duplicates", "Duplicates", (el) => mountDuplicates(el)],
  ["recipes", "Recipes", (el) => rec.mount(el)],
  ["storage", "Storage", (el) => storage.mount(el)],
  ["registry", "Registry", (el) => mountRegistry(el)],
  ["settings", "Settings", (el) => mountSettings(el)],
];

let overlay = null;
let closeOpen = null; // close() of the open window: removes its global listeners
let current = "workflow";

function injectCss() {
  if (document.getElementById("smf-css")) return;
  document.head.append(h("style", { id: "smf-css" }, CSS));
}

export async function openFetcher(tab) {
  injectCss();
  if (tab) current = tab;
  if (!ctx.status) {
    try {
      await refreshStatus();
    } catch (e) {
      toast("error", "Model Librarian", "Backend not reachable: " + e.message);
      return;
    }
  }
  closeOpen?.();
  notice(null);
  const body = h("div.smf-body");
  const tray = h("div.smf-tray");
  const tabsEl = h("div.smf-row");
  const show = (key) => {
    current = key;
    const t = TABS.find((x) => x[0] === key);
    body.className = "smf-body" + (t[3] ? " " + t[3] : "");
    clear(tabsEl, TABS.map(([k, label]) => h("button.smf-tab" + (k === key ? ".sel" : ""), { onclick: () => show(k) }, label)));
    clear(body);
    Promise.resolve(t[2](body)).catch((e) => clear(body, h("div.smf-empty.err", String(e.message || e))));
  };
  // Drops on our window import a recipe. Capture on window so ComfyUI's own
  // drop handler (which would load the image's workflow over the open graph)
  // never sees them.
  let dragTimer = null;
  const inside = (e) => overlay && e.target instanceof Node && overlay.contains(e.target);
  const onDragOver = (e) => {
    if (!inside(e)) return;
    e.preventDefault();
    e.stopPropagation();
    overlay.classList.add("smf-dragging");
    clearTimeout(dragTimer);
    dragTimer = setTimeout(() => overlay?.classList.remove("smf-dragging"), 150);
  };
  const onDrop = (e) => {
    if (!inside(e)) return;
    e.preventDefault();
    e.stopPropagation();
    overlay.classList.remove("smf-dragging");
    if (!rec.canHandle(e.dataTransfer)) return;
    if (current !== "recipes") show("recipes");
    rec.handleDrop(e.dataTransfer);
  };
  window.addEventListener("dragover", onDragOver, true);
  window.addEventListener("drop", onDrop, true);
  const close = () => {
    overlay?.remove();
    overlay = null;
    document.removeEventListener("keydown", onKey, true);
    window.removeEventListener("dragover", onDragOver, true);
    window.removeEventListener("drop", onDrop, true);
    closeOpen = null;
  };
  closeOpen = close;
  const onKey = (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      close();
    }
  };
  document.addEventListener("keydown", onKey, true);
  overlay = h("div.smf-overlay", { onmousedown: (e) => { if (e.target === overlay) close(); } },
    h("div.smf-modal",
      h("div.smf-header", h("span.smf-logo", h("img.smf-logo-img", { src: LOGO, alt: "" }), "Model Librarian"), tabsEl, h("button.smf-close", { onclick: close, title: "Close (Esc)" }, "×")),
      body, tray));
  // keep ComfyUI's canvas shortcuts from firing while typing in our inputs
  overlay.addEventListener("keydown", (e) => e.stopPropagation());
  document.body.append(overlay);
  mountTray(tray);
  poll();
  show(current);
}

// Small corner notice instead of a popup over ComfyUI's own missing-models dialog
function notice(text) {
  document.querySelector(".smf-notice")?.remove();
  if (!text) return;
  injectCss();
  const el = h("div.smf-notice", { role: "status" },
    h("span", "⚠ ", text, " in this workflow"),
    h("button.smf-btn.small.primary", { onclick: () => { el.remove(); openFetcher("workflow"); } }, "Review"),
    h("button.smf-notice-x", { title: "Dismiss", onclick: () => el.remove() }, "×"));
  document.body.append(el);
}

async function autoCheck() {
  if (!ctx.status) {
    try { await refreshStatus(); } catch { return; }
  }
  notice(null);
  if (!ctx.status.config.auto_check_on_load) return;
  try {
    const items = await wf.scan();
    const missing = items.filter((i) => i.status === "missing").length;
    const moved = items.filter((i) => i.status === "elsewhere").length;
    if (!missing && !moved) return;
    const text = `${missing ? `${missing} missing` : ""}${missing && moved ? ", " : ""}${moved ? `${moved} moved` : ""} model${missing + moved === 1 ? "" : "s"}`;
    if (ctx.status.config.auto_check_action === "open") {
      toast("warn", "Models missing", `${text} — opening Model Librarian`, 5000);
      openFetcher("workflow");
    } else notice(text);
  } catch (e) {
    console.warn("[Model Librarian] auto-check failed", e);
  }
}

app.registerExtension({
  name: "ModelLibrarian",
  commands: [
    { id: "ModelLibrarian.Open", label: "Model Librarian", icon: "smf-logo-icon", function: () => openFetcher() },
    { id: "ModelLibrarian.Library", label: "Model Librarian: Library", icon: "pi pi-images", function: () => openFetcher("library") },
  ],
  menuCommands: [{ path: ["Extensions"], commands: ["ModelLibrarian.Open", "ModelLibrarian.Library"] }],
  actionBarButtons: [
    { icon: "smf-logo-icon", label: "Models", tooltip: "Model Librarian — missing models, library, organizer", onClick: () => openFetcher() },
  ],
  async beforeConfigureGraph(graphData) {
    wf.topLevelModels.clear();
    for (const m of graphData?.models ?? []) {
      if (m?.name) wf.topLevelModels.set(m.name.split(/[\\/]/).pop().toLowerCase(), m);
    }
  },
  async afterConfigureGraph() {
    setTimeout(autoCheck, 600);
  },
  async setup() {
    injectCss();
    refreshStatus().catch(() => {});
    storage.startEventPolling();
    setTimeout(() => lib.autoCheckUpdates(), 60000); // newer CivitAI versions, once a day
    setTimeout(() => storage.checkGoal(), 45000); // SSD free-space goal, once a session
    setTimeout(() => checkLeftovers(), 90000); // unfinished downloads, once a session
    // Fallback launcher for older frontends without action-bar buttons
    if (!app.extensionManager?.registerSidebarTab && !document.querySelector(".smf-fallback")) {
      const btn = h("button.smf-btn.primary.smf-fallback", {
        style: { position: "fixed", right: "12px", bottom: "12px", zIndex: 9999 }, onclick: () => openFetcher(),
      }, "⬇ Models");
      document.body.append(btn);
    }
  },
});

// expose for debugging / other extensions
// Public surface for other extensions. openRecipe(recipe, {thumb}) takes a
// recipe/1 object (docs/RECIPE_FORMAT.md) and opens it in the Recipes tab, ready
// to download what's missing and fill the workflow.
window.ModelLibrarian = {
  open: openFetcher,
  async openRecipe(recipe, opts = {}) {
    if (!recipe || typeof recipe !== "object") throw new Error("openRecipe needs a recipe/1 object");
    await openFetcher("recipes");
    return rec.openExternal(recipe, opts);
  },
};
