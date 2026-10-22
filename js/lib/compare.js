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

function usesLora(node, stem) {
  const i = node?.inputs || {};
  if (typeof i.lora_name === "string") return stemOf(i.lora_name) === stem;
  return !!lmList(i)?.some((l) => l && l.active !== false && stemOf(l.name) === stem);
}

function setStrength(node, stem, s) {
  const i = node.inputs;
  if (typeof i.lora_name === "string") {
    if ("strength_model" in i) i.strength_model = s;
    if ("strength_clip" in i) i.strength_clip = s;
    return;
  }
  for (const l of lmList(i) || []) if (stemOf(l.name) === stem) { l.strength = s; if ("clipStrength" in l) l.clipStrength = s; }
  if (typeof i.text === "string") {
    i.text = i.text.replace(/<lora:([^:>]+):[^>]*>/gi, (m, name) => (stemOf(name) === stem ? `<lora:${name}:${s}>` : m));
  }
}

const isRef = (v) => Array.isArray(v) && v.length === 2 && (typeof v[0] === "string" || typeof v[0] === "number") && Number.isInteger(v[1]);

/**
 * @param {object} api   workflow in API format: {id: {class_type, inputs, _meta?}}
 * @param {string} lora  the LoRA (file name or path; matched by name without extension)
 * @param {number[]} strengths
 * @returns {{prompt?: object, copies?: number, nodes?: number, error?: string}}
 */
export function strengthGraph(api, lora, strengths) {
  const stem = stemOf(lora);
  if (!strengths.length) return { error: "Give at least one strength." };
  const loaderId = Object.keys(api || {}).find((id) => usesLora(api[id], stem));
  if (!loaderId) return { error: "That LoRA isn't loaded in this workflow (or its loader is bypassed)." };

  // everything that depends on the loader, directly or not
  const users = new Map();
  for (const [id, n] of Object.entries(api)) {
    for (const v of Object.values(n.inputs || {})) if (isRef(v)) {
      const from = String(v[0]);
      if (!users.has(from)) users.set(from, new Set());
      users.get(from).add(id);
    }
  }
  const after = new Set([loaderId]), queue = [loaderId];
  while (queue.length) for (const u of users.get(queue.shift()) || []) if (!after.has(u)) { after.add(u); queue.push(u); }

  const prompt = JSON.parse(JSON.stringify(api));
  let next = Math.max(0, ...Object.keys(api).map((id) => parseInt(String(id).split(":").pop(), 10)).filter(Number.isFinite)) + 1;
  const label = (n, s) => {
    n._meta = { ...(n._meta || {}), title: `${n._meta?.title || n.class_type} · LoRA ${s}` };
    if (typeof n.inputs?.filename_prefix === "string") n.inputs.filename_prefix += `_lora${s}`;
  };
  strengths.forEach((s, k) => {
    if (k === 0) { // the workflow's own nodes take the first strength
      for (const id of after) label(prompt[id], s);
      setStrength(prompt[loaderId], stem, s);
      return;
    }
    const ids = new Map([...after].map((id) => [id, String(next++)]));
    for (const id of after) {
      const n = JSON.parse(JSON.stringify(api[id]));
      for (const [key, v] of Object.entries(n.inputs || {})) if (isRef(v) && ids.has(String(v[0]))) n.inputs[key] = [ids.get(String(v[0])), v[1]];
      label(n, s);
      prompt[ids.get(id)] = n;
    }
    setStrength(prompt[ids.get(loaderId)], stem, s);
  });
  return { prompt, copies: strengths.length, nodes: after.size };
}
