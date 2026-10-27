// Character Select's face on the canvas: the character (its picture and name: click to pick another from your
// characters, searchable), its outfit, and the tags it will write, each clicked to leave it out. The node's own
// widgets (character, character_id, outfit, off_tags) hold what's picked and are kept out of sight; the prompt is
// built in Python (smf/character_node.py) from the list as it is when the workflow runs.
import { h, call, apiUrl } from "./util.js";

const HIDDEN = ["character", "character_id", "outfit", "off_tags"];
const PARTS = [["include_character", "character"], ["include_series", "series"], ["include_appearance", "appearance"], ["include_outfit", "outfit"]];

export const norm = (t) => String(t || "").replace(/_/g, " ").replace(/\s+/g, " ").trim().toLowerCase();
const show = (t) => String(t || "").replace(/_/g, " ");

// ---------------------------------------------------------------- pure (tested)
// The tags the node writes for a character and outfit, in order, each with the part it's from and whether it's off.
export function tagsFor(c, outfit, on = {}, off = "") {
  if (!c) return [];
  const out = new Set(String(off || "").split(/[,\n]/).map(norm).filter(Boolean));
  const tags = [];
  if (on.character !== false && c.tag) tags.push([c.tag, "character"]);
  if (on.series && c.series) tags.push([String(c.series).toLowerCase(), "series"]);
  if (on.appearance !== false) for (const t of c.appearance || []) tags.push([t, "appearance"]);
  if (on.outfit !== false && outfit) for (const t of (c.outfits || {})[outfit] || []) tags.push([t, "outfit"]);
  const seen = new Set();
  return tags.filter(([t]) => norm(t) && !seen.has(norm(t)) && seen.add(norm(t))).map(([t, part]) => ({ t: show(t), part, off: out.has(norm(t)) }));
}

// off_tags with one tag turned off or back on
export function toggleOff(off, tag) {
  const list = String(off || "").split(",").map((x) => x.trim()).filter(Boolean);
  const k = norm(tag);
  return (list.some((x) => norm(x) === k) ? list.filter((x) => norm(x) !== k) : [...list, show(tag)]).join(", ");
}

// the outfit a newly picked character starts with: "default" when it has one, else its first, else none
export const firstOutfit = (c) => (c && c.outfits ? ("default" in c.outfits ? "default" : Object.keys(c.outfits)[0] || "") : "");

// characters matching what's typed (name, series or tag), the ones whose name starts with it first
export function search(list, q) {
  const k = norm(q);
  if (!k) return list;
  const hit = list.filter((c) => [c.name, c.series, c.tag].some((x) => norm(x).includes(k)));
  return [...hit.filter((c) => norm(c.name).startsWith(k)), ...hit.filter((c) => !norm(c.name).startsWith(k))];
}

// ---------------------------------------------------------------- the list
let cached = null; // {at, list}
async function characters(fresh = false) {
  if (!fresh && cached && Date.now() - cached.at < 10000) return cached.list;
  const r = await call("/characters");
  cached = { at: Date.now(), list: r.characters || [] };
  return cached.list;
}
const picture = (c) => (c && c.has_image ? apiUrl(`/characters/${encodeURIComponent(c.id)}/picture`) + `?v=${Math.round(c.updated || 0)}` : null);
const face = (c, cls) => (picture(c) ? h(`img.${cls}`, { src: picture(c), alt: "" }) : h(`span.${cls}.mlcs-initial`, (c && c.name ? c.name[0] : "?").toUpperCase()));

const CSS = `
.mlcs{display:flex;flex-direction:column;gap:6px;font:12px system-ui,"Segoe UI",sans-serif;color:var(--input-text,#ddd);box-sizing:border-box;padding:2px 0;overflow:hidden}
.mlcs-pick{display:flex;align-items:center;gap:8px;width:100%;padding:5px 8px;border:1px solid var(--border-color,#444);border-radius:8px;background:var(--comfy-input-bg,#2a2a2a);color:inherit;cursor:pointer;text-align:left;font:inherit}
.mlcs-pick:focus-visible,.mlcs-lora:focus-visible,.mlcs-chip:focus-visible,.mlcs select:focus-visible{outline:2px solid #3b82f6;outline-offset:1px}
.mlcs-face{width:40px;height:40px;border-radius:7px;object-fit:cover;flex:none;background:rgba(255,255,255,.06)}
.mlcs-initial{display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:16px;color:var(--descrip-text,#999)}
.mlcs-who{display:flex;flex-direction:column;min-width:0;flex:1}
.mlcs-who b{font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mlcs-dim{color:var(--descrip-text,#999);font-size:11.5px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mlcs-row{display:flex;align-items:center;gap:6px}
.mlcs-lora{flex:1;min-width:0;text-align:left;padding:3px 6px;border:1px solid var(--border-color,#444);border-radius:7px;background:var(--comfy-input-bg,#2a2a2a);color:inherit;font:inherit;cursor:pointer;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.mlcs-lora:hover:not(:disabled),.mlcs-pick:hover:not(:disabled){border-color:#3b82f6}
.mlcs-lora:disabled,.mlcs-pick:disabled{cursor:default;opacity:.7}
.mlcs select{flex:1;min-width:0;background:var(--comfy-input-bg,#2a2a2a);color:inherit;border:1px solid var(--border-color,#444);border-radius:7px;padding:3px 6px;font:inherit}
.mlcs-chips{display:flex;flex-wrap:wrap;gap:4px}
.mlcs-chip{padding:2px 8px;border-radius:999px;border:1px solid var(--border-color,#444);background:rgba(255,255,255,.05);color:inherit;font:500 11.5px system-ui,sans-serif;cursor:pointer;transition:opacity .15s,background .15s}
.mlcs-chip.character{border-color:rgba(59,130,246,.6)}
.mlcs-chip.outfit{border-color:rgba(227,179,65,.55)}
.mlcs-chip.off{opacity:.45;text-decoration:line-through}
.mlcs-chip:hover{background:rgba(255,255,255,.1)}
.mlcs-overlay{position:fixed;inset:0;background:rgba(0,0,0,.55);z-index:10001;display:flex;align-items:flex-start;justify-content:center;padding-top:10vh}
.mlcs-dialog{width:min(520px,92vw);max-height:70vh;display:flex;flex-direction:column;background:var(--comfy-menu-bg,#202020);color:var(--input-text,#ddd);border:1px solid var(--border-color,#444);border-radius:12px;box-shadow:0 20px 60px rgba(0,0,0,.5);font:13px system-ui,"Segoe UI",sans-serif;overflow:hidden}
.mlcs-dialog input{margin:10px;padding:8px 10px;border-radius:8px;border:1px solid var(--border-color,#444);background:var(--comfy-input-bg,#2a2a2a);color:inherit;font:inherit;outline:none}
.mlcs-dialog input:focus{border-color:#3b82f6}
.mlcs-list{overflow:auto;padding:0 6px 6px}
.mlcs-item{display:flex;align-items:center;gap:10px;width:100%;padding:6px 8px;border:0;border-radius:8px;background:none;color:inherit;font:inherit;text-align:left;cursor:pointer}
.mlcs-item[aria-selected=true],.mlcs-item:hover{background:rgba(59,130,246,.18)}
.mlcs-empty{padding:16px;color:var(--descrip-text,#999)}
`;
function css() {
  if (!document.getElementById("mlcs-css")) document.head.append(h("style", { id: "mlcs-css" }, CSS));
}

// ---------------------------------------------------------------- picking one
// A searchable list over everything (Esc or a click outside: nothing picked). load() gives the items; row(item) draws one;
// find(items, typed) filters them; `none` (a label) adds a first entry that picks null on purpose ({none: true}).
function choose({ label, load, row, find, empty, current, none = null }) {
  return new Promise(async (resolve) => {
    css();
    const input = h("input", { type: "search", placeholder: `Search ${label}`, "aria-label": `Search ${label}`, spellcheck: false });
    const listEl = h("div.mlcs-list", { role: "listbox", "aria-label": label });
    const overlay = h("div.mlcs-overlay", h("div.mlcs-dialog", { role: "dialog", "aria-modal": "true", "aria-label": label }, input, listEl));
    let all = [], shown = [], at = 0;
    const done = (c) => { overlay.remove(); resolve(c); };
    const entries = () => (none && !input.value.trim() ? [{ none: true }, ...shown] : shown);
    const draw = () => {
      const list = entries();
      listEl.replaceChildren(...(list.length ? list.map((c, i) => h("button.mlcs-item", { type: "button", role: "option", "aria-selected": String(i === at), onclick: () => done(c) },
        c.none ? h("span.mlcs-who", h("b", none)) : row(c)))
        : [h("div.mlcs-empty", all.length ? "Nothing matches that." : empty)]));
      listEl.querySelector('[aria-selected="true"]')?.scrollIntoView({ block: "nearest" });
    };
    input.addEventListener("input", () => { shown = find(all, input.value); at = 0; draw(); });
    overlay.addEventListener("keydown", (e) => {
      e.stopPropagation();  // (typing here isn't ComfyUI's shortcuts)
      const list = entries();
      if (e.key === "Escape") done(null);
      else if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); at = Math.max(0, Math.min(list.length - 1, at + (e.key === "ArrowDown" ? 1 : -1))); draw(); }
      else if (e.key === "Enter" && list[at]) { e.preventDefault(); done(list[at]); }
    });
    for (const t of ["keyup", "keypress"]) overlay.addEventListener(t, (e) => e.stopPropagation());
    overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) done(null); });
    document.body.append(overlay);
    input.focus();
    setTimeout(() => input.focus(), 50);  // (the canvas takes the focus back as the click that opened this ends)
    try { all = await load(); } catch (e) { listEl.replaceChildren(h("div.mlcs-empty", `Couldn't read ${label}: ${e.message}`)); return; }
    shown = all;
    at = Math.max(0, entries().findIndex((c) => current && current(c)));
    draw();
  });
}

// one of your characters (also Model Librarian's Library: "Use for character")
export function pickCharacter(currentId = null) {
  return choose({
    label: "your characters", load: () => characters(true), find: search, current: (c) => c.id === currentId,
    empty: "No characters yet: add some with + Character on Danbooru (the Model Librarian Chrome extension).",
    row: (c) => [face(c, "mlcs-face"), h("span.mlcs-who", h("b", c.name),
      h("span.mlcs-dim", [c.series, `${Object.keys(c.outfits || {}).length} outfit${Object.keys(c.outfits || {}).length === 1 ? "" : "s"}`, c.lora ? `LoRA ${loraLabel(c.lora.name)}` : ""].filter(Boolean).join(" · ")))],
  });
}

export const loraLabel = (name) => String(name || "").split(/[\\/]/).pop().replace(/\.(safetensors|ckpt|pt|pth|bin)$/i, "");

// one of your LoRAs (or none) for a character
function pickLora(current) {
  return choose({
    label: "your LoRAs", none: "No LoRA", current: (n) => (current ? n === current : n.none),
    load: async () => (await call("/characters/loras")).loras || [],
    find: (all, q) => { const k = norm(q); return k ? all.filter((n) => norm(n).includes(k)) : all; },
    empty: "No LoRAs in your loras folder.",
    row: (n) => h("span.mlcs-who", h("b", loraLabel(n)), h("span.mlcs-dim", n)),
  });
}

// links a LoRA to a character in the list (its trigger words from the LoRA's metadata) -> the character
export async function linkLora(id, name) {
  const r = await call(`/characters/${encodeURIComponent(id)}/lora`, { method: "POST", body: { name: name || "" } });
  cached = null;
  return r.character;
}

// ---------------------------------------------------------------- on the node
function hide(w) {
  w.hidden = true;
  w.options = { ...(w.options || {}), hidden: true };
  w.computeSize = () => [0, -4];
  if (["text", "customtext", "STRING"].includes(w.type)) w.type = "hidden";
}

export function setupNode(node, app) {
  css();
  const W = (n) => node.widgets?.find((w) => w.name === n);
  for (const n of HIDDEN) if (W(n)) hide(W(n));
  const pickBtn = h("button.mlcs-pick", { type: "button", title: "Pick a character" });
  const outfit = h("select", { "aria-label": "Outfit" });
  const loraBtn = h("button.mlcs-lora", { type: "button", title: "Link a LoRA to this character (Character Select loads it when model and clip are wired through)" });
  const chips = h("div.mlcs-chips");
  const el = h("div.mlcs", pickBtn, h("div.mlcs-row", h("span.mlcs-dim", "Outfit"), outfit), h("div.mlcs-row", h("span.mlcs-dim", "LoRA"), loraBtn), chips);
  let char = null;

  const set = (n, v) => { const w = W(n); if (w) { w.value = v; w.callback?.(v); } };
  const dirty = () => (node.graph || app.graph)?.setDirtyCanvas?.(true, true);
  const draw = () => {
    const name = W("character")?.value || "";
    const anyone = !!W("random_character")?.value, anyOutfit = !!W("random_outfit")?.value;
    pickBtn.replaceChildren(face(anyone ? null : char, "mlcs-face"), h("span.mlcs-who", h("b", anyone ? "A random character" : char ? char.name : name || "Pick a character"),
      h("span.mlcs-dim", anyone ? "One of your characters each run, from the seed" : char ? char.series || show(char.tag) : name ? "Not in your characters any more" : "Click to choose from your characters")));
    pickBtn.disabled = anyone;
    const names = char && !anyone ? Object.keys(char.outfits || {}) : [];
    const now = W("outfit")?.value || "";
    outfit.replaceChildren(h("option", { value: "" }, anyOutfit ? "A random outfit each run" : anyone ? "Its first outfit" : "No outfit"), ...names.map((o) => h("option", { value: o, selected: o === now }, o)));
    outfit.value = names.includes(now) && !anyOutfit ? now : "";
    outfit.disabled = !char || anyone || anyOutfit;
    const lora = anyone ? null : char?.lora;  // (picking at random: each character's own)
    loraBtn.replaceChildren(...[h("b", lora ? loraLabel(lora.name) : anyone ? "Each character's own" : "None: link one"),
      lora && lora.trigger?.length ? h("span.mlcs-dim", ` · ${lora.trigger.join(", ")}`) : null].filter(Boolean));
    loraBtn.disabled = !char || anyone;
    const on = Object.fromEntries(PARTS.map(([w, part]) => [part, W(w) ? !!W(w).value : true]));
    const tags = anyone ? [] : tagsFor(char, anyOutfit ? "" : outfit.value, on, W("off_tags")?.value);
    chips.replaceChildren(...tags.map((x) => h(`button.mlcs-chip.${x.part}${x.off ? ".off" : ""}`, {
      type: "button", title: x.off ? "Left out: click to put it back" : "Click to leave it out", "aria-pressed": String(!x.off),
      onclick: () => { set("off_tags", toggleOff(W("off_tags")?.value, x.t)); draw(); dirty(); },
    }, x.t)));
    requestAnimationFrame(fit);
  };
  const fit = () => {  // the node grows to show every tag (it never shrinks on its own: a size you set stays)
    const need = node.computeSize?.();
    if (need && need[1] > (node.size?.[1] || 0)) { node.setSize([node.size[0], need[1]]); dirty(); }
  };
  const load = async (fresh = false) => {
    const id = W("character_id")?.value, name = W("character")?.value;
    try {
      const list = await characters(fresh);
      char = list.find((c) => c.id === id) || list.find((c) => norm(c.name) === norm(name)) || null;
      if (char && W("character")?.value !== char.name) set("character", char.name);  // (renamed since)
      if (char && W("character_id")?.value !== char.id) set("character_id", char.id);
    } catch { char = null; }
    draw();
  };

  pickBtn.addEventListener("click", async () => {
    const c = await pickCharacter(char?.id);
    if (!c) return;
    char = c;
    set("character", c.name);
    set("character_id", c.id);
    set("outfit", firstOutfit(c));
    set("off_tags", "");
    draw();
    dirty();
  });
  outfit.addEventListener("change", () => { set("outfit", outfit.value); draw(); dirty(); });
  loraBtn.addEventListener("click", async () => {
    if (!char) return;
    const n = await pickLora(char.lora?.name || null);
    if (!n) return;
    try {
      char = await linkLora(char.id, n.none ? "" : n);
      draw();
    } catch (e) { loraBtn.title = `Couldn't link it: ${e.message}`; }
  });
  for (const [n] of [...PARTS, ["random_character"], ["random_outfit"]]) {  // a part switched off or on: its chips go or come back
    const w = W(n);
    if (!w) continue;
    const cb = w.callback;
    w.callback = function (...a) { const r = cb?.apply(this, a); draw(); return r; };
  }

  node.addDOMWidget("character_view", "mlcharacter", el, { serialize: false, getValue: () => undefined, setValue: () => {}, getMinHeight: () => Math.max(110, el.scrollHeight + 4) });
  const configure = node.onConfigure;
  node.onConfigure = function (...a) { const r = configure?.apply(this, a); load(); return r; };  // (a saved workflow's values are in now)
  load();
  if ((node.size?.[0] || 0) < 300) node.setSize?.([300, node.size?.[1] || 0]);
}
