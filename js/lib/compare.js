// Compare a LoRA's strengths: from a workflow in ComfyUI's API format (what it runs), a new one where
// everything after the LoRA's loader is copied once per strength. Same prompt, same seed; each copy saves
// its images with the strength in the name. No ComfyUI imports, so it's tested in node.

const stemOf = (p) => String(p || "").split(/[\\/]/).pop().replace(/\.(safetensors|ckpt|pt|pth|bin)$/i, "").toLowerCase();

// "0, 0.4, .7, 1" -> [0, 0.4, 0.7, 1]: numbers from -5 to 5, at most 8, repeats dropped
export function parseStrengths(text) {
  const out = [];
  for (const part of String(text || "").split(/[,\s;]+/)) {
    const v = Number(part);
    if (part !== "" && Number.isFinite(v) && v >= -5 && v <= 5 && !out.includes(v)) out.push(v);
  }
  return out.slice(0, 8);
}

// LoRA Manager's loader keeps a list (sometimes wrapped as {__value__: [...]}) and <lora:name:w> text
const lmList = (inputs) => (Array.isArray(inputs?.loras) ? inputs.loras : Array.isArray(inputs?.loras?.__value__) ? inputs.loras.__value__ : null);

function usesLora(node, stems) {
  const i = node?.inputs || {};
  if (typeof i.lora_name === "string") return stems.has(stemOf(i.lora_name));
  return !!lmList(i)?.some((l) => l && l.active !== false && stems.has(stemOf(l.name)));
}

// -> whether a strength was set. A plain loader's strength inputs go by several names (strength_model,
// strength_clip, lora_strength …): every number input named like a strength is set.
function setStrength(node, stems, s, rename) {
  const i = node.inputs;
  if (typeof i.lora_name === "string") {
    let set = false;
    for (const [k, v] of Object.entries(i)) if (/strength/i.test(k) && typeof v === "number") { i[k] = s; set = true; }
    if (rename) i.lora_name = rename;
    return set;
  }
  let set = false;
  for (const l of lmList(i) || []) if (stems.has(stemOf(l.name))) { l.strength = s; if ("clipStrength" in l) l.clipStrength = s; set = true; }
  if (typeof i.text === "string") {
    i.text = i.text.replace(/<lora:([^:>]+):[^>]*>/gi, (m, name) => (stems.has(stemOf(name)) ? `<lora:${name}:${s}>` : m));
  }
  return set;
}

const isRef = (v) => Array.isArray(v) && v.length === 2 && (typeof v[0] === "string" || typeof v[0] === "number") && Number.isInteger(v[1]);

/**
 * @param {object} api   workflow in API format: {id: {class_type, inputs, _meta?}}
 * @param {string|string[]} lora  the LoRA (file name or path; matched by name without extension), or the
 *   names it may go by (yours, and the one in someone else's workflow)
 * @param {number[]} strengths
 * @param {{rename?: string}} opts  rename: the LoRA's name here, written into every copy's loader
 * @returns {{prompt?: object, copies?: number, nodes?: number, error?: string}}
 */
export function strengthGraph(api, lora, strengths, { rename = null } = {}) {
  const stems = new Set((Array.isArray(lora) ? lora : [lora]).filter(Boolean).map(stemOf));
  if (!strengths.length) return { error: "Give at least one strength." };
  // every loader of it (a base pass and a hires pass may each load it): all of them change together
  const loaderIds = Object.keys(api || {}).filter((id) => usesLora(api[id], stems));
  if (!loaderIds.length) return { error: "That LoRA isn't loaded in this workflow (or its loader is bypassed)." };

  // everything that depends on the loader, directly or not
  const users = new Map();
  for (const [id, n] of Object.entries(api)) {
    for (const v of Object.values(n.inputs || {})) if (isRef(v)) {
      const from = String(v[0]);
      if (!users.has(from)) users.set(from, new Set());
      users.get(from).add(id);
    }
  }
  const after = new Set(loaderIds), queue = [...loaderIds];
  while (queue.length) for (const u of users.get(queue.shift()) || []) if (!after.has(u)) { after.add(u); queue.push(u); }

  const prompt = JSON.parse(JSON.stringify(api));
  let next = Math.max(0, ...Object.keys(api).map((id) => parseInt(String(id).split(":").pop(), 10)).filter(Number.isFinite)) + 1;
  const label = (n, s) => {
    n._meta = { ...(n._meta || {}), title: `${n._meta?.title || n.class_type} · LoRA ${s}` };
    if (typeof n.inputs?.filename_prefix === "string") n.inputs.filename_prefix += `_lora${s}`;
  };
  if (!loaderIds.some((id) => setStrength(JSON.parse(JSON.stringify(api[id])), stems, 1))) {
    return { error: "This LoRA's loader has no strength setting Model Librarian knows how to change." };
  }
  strengths.forEach((s, k) => {
    if (k === 0) { // the workflow's own nodes take the first strength
      for (const id of after) label(prompt[id], s);
      for (const id of loaderIds) setStrength(prompt[id], stems, s, rename);
      return;
    }
    const ids = new Map([...after].map((id) => [id, String(next++)]));
    for (const id of after) {
      const n = JSON.parse(JSON.stringify(api[id]));
      for (const [key, v] of Object.entries(n.inputs || {})) if (isRef(v) && ids.has(String(v[0]))) n.inputs[key] = [ids.get(String(v[0])), v[1]];
      label(n, s);
      prompt[ids.get(id)] = n;
    }
    for (const id of loaderIds) setStrength(prompt[ids.get(id)], stems, s, rename);
  });
  return { prompt, copies: strengths.length, nodes: after.size };
}
