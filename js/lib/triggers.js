// Trigger words: which of a LoRA's trigger words are in the workflow's positive prompt, and adding the
// missing ones. Works on a LiteGraph graph (or anything shaped like one), no ComfyUI imports, so it's tested
// in node.

// CivitAI keeps trigger words as entries that may hold several, comma separated: one word or phrase each.
export function splitWords(list) {
  const out = [], seen = new Set();
  for (const entry of list || []) {
    for (const w of String(entry).split(",")) {
      const t = w.trim().replace(/\s+/g, " ");
      if (t && !seen.has(t.toLowerCase())) { seen.add(t.toLowerCase()); out.push(t); }
    }
  }
  return out;
}

// Prompt text and trigger words compared as the model reads them: case, <lora:…> tags, \( \) escapes,
// (word:1.2) weights and underscores (blue_hair = blue hair) don't matter.
const norm = (s) => String(s || "").toLowerCase()
  .replace(/<lora:[^>]*>/g, " ")
  .replace(/\\([()])/g, "$1")
  .replace(/:\s*-?\d*\.?\d+\s*\)/g, ")")
  .replace(/_/g, " ")
  .replace(/\s+/g, " ");
const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// The word or phrase on its own in the text (not inside another word, in any alphabet).
export function hasWord(text, word) {
  const w = norm(word).trim();
  return !!w && new RegExp(`(^|[^\\p{L}\\p{N}])${escape(w)}($|[^\\p{L}\\p{N}])`, "u").test(norm(text));
}

// The words in front of the prompt (where the model weighs them most), comma separated. Brackets in a
// word are escaped, so ComfyUI doesn't read them as a weight.
export function addWords(text, words) {
  const t = String(text || "").replace(/^[\s,]+/, "");
  const ws = words.map((w) => w.replace(/(?<!\\)([()])/g, "\\$1"));
  return ws.length ? ws.join(", ") + (t ? ", " + t : "") : t;
}

const TEXT_WIDGET = /^(text|text_g|text_l|clip_l|t5xxl|prompt|positive|positive_prompt|string|value|wildcard_text|populated_text)$/i;
const OFF = (n) => n.mode === 2 || n.mode === 4; // muted or bypassed
const TEXT_INPUT = /^(text|text_g|prompt|positive|string|value)$/i;

/**
 * The positive prompts: each sampler's `positive` input followed back through conditioning nodes to the
 * text that makes it. A text box fed by another node (a String node, a prompt tool) is followed to that node.
 * @returns {{sources: {node, widget}[]}[]}  one per distinct prompt; a prompt may be built from several texts
 */
export function positivePrompts(graph) {
  const nodes = graph?._nodes ?? graph?.nodes ?? [];
  const byId = (id) => graph.getNodeById?.(id) ?? nodes.find((n) => n.id === id);
  const link = (id) => (id == null ? null : graph.getLink?.(id) ?? (graph.links?.get ? graph.links.get(id) : graph.links?.[id]));
  const from = (inp) => byId(link(inp.link)?.origin_id);
  const prompts = [], used = new Set();
  for (const sampler of nodes) {
    if (OFF(sampler)) continue;
    // a sampler's positive, or a guider's conditioning (Flux's BasicGuider)
    const pos = (sampler.inputs ?? []).find((i) => i.link != null && (i.name === "positive" || (i.name === "conditioning" && /Guider/i.test(sampler.type || ""))));
    if (!pos) continue;
    const sources = [], seen = new Set();
    const walk = (n, depth) => {
      if (!n || seen.has(n) || depth > 10 || n.mode === 2) return;
      seen.add(n);
      if (n.mode === 4 || /^Reroute/i.test(n.type || "")) { // passed straight through
        for (const i of n.inputs ?? []) if (i.link != null) walk(from(i), depth + 1);
        return;
      }
      const fed = (n.inputs ?? []).find((i) => TEXT_INPUT.test(i.name) && i.link != null);
      if (fed) return walk(from(fed), depth + 1); // the text comes from another node
      const w = (n.widgets ?? []).find((x) => typeof x.value === "string" && TEXT_WIDGET.test(x.name));
      if (w) return void sources.push({ node: n, widget: w });
      for (const i of n.inputs ?? []) if (i.link != null && /CONDITIONING|STRING/i.test(String(i.type ?? ""))) walk(from(i), depth + 1);
    };
    walk(from(pos), 0);
    const key = sources.map((s) => `${s.node.id}:${s.widget.name}`).join("|");
    if (sources.length && !used.has(key)) { used.add(key); prompts.push({ sources }); }
  }
  return prompts;
}

// For each word: is it in every positive prompt?
export function wordStatus(words, prompts) {
  const texts = prompts.map((p) => p.sources.map((s) => s.widget.value).join("\n"));
  return words.map((w) => ({ word: w, present: texts.length > 0 && texts.every((t) => hasWord(t, w)) }));
}

// Put the missing words in front of each positive prompt that lacks them (its first text). -> texts changed
export function addToPrompts(words, prompts, setValue) {
  let changed = 0;
  for (const p of prompts) {
    const all = p.sources.map((s) => s.widget.value).join("\n");
    const missing = words.filter((w) => !hasWord(all, w));
    if (!missing.length) continue;
    const s = p.sources[0];
    setValue(s, addWords(s.widget.value, missing));
    changed++;
  }
  return changed;
}
