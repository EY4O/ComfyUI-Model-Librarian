// A stand-in for ComfyUI's app: a small open workflow for the Workflow tab, and
// toasts drawn on the page (ComfyUI shows them with PrimeVue).
const node = (id, type, widgets) => ({ id, type, widgets: Object.entries(widgets).map(([name, value]) => ({ name, value })), properties: {}, setDirtyCanvas() {} });

const graph = {
  _nodes: [
    node(4, "CheckpointLoaderSimple", { ckpt_name: "lumen_xl_v3.safetensors" }),
    node(10, "LoraLoader", { lora_name: "Illustrious\\paper_cut_style.safetensors", strength_model: 0.8, strength_clip: 0.8 }),
    node(11, "LoraLoader", { lora_name: "harbor_lights.safetensors", strength_model: 0.55, strength_clip: 0.55 }),
    node(12, "LoraLoader", { lora_name: "glass_garden.safetensors", strength_model: 0.4, strength_clip: 0.4 }),
    node(8, "VAELoader", { vae_name: "ae.safetensors" }),
  ],
  setDirtyCanvas() {},
  change() {},
};

function toastUI(t) {
  let box = document.getElementById("demo-toasts");
  if (!box) {
    box = document.createElement("div");
    box.id = "demo-toasts";
    document.body.append(box);
  }
  const el = document.createElement("div");
  el.className = "demo-toast " + (t.severity || "info");
  el.innerHTML = `<b></b><div></div>`;
  el.querySelector("b").textContent = t.summary || "";
  el.querySelector("div").textContent = t.detail || "";
  box.append(el);
  setTimeout(() => el.remove(), Math.min(t.life || 4000, 6000));
}

export const app = {
  registerExtension() {}, rootGraph: graph, graph,
  canvas: { setDirty() {} },
  async loadGraphData() {}, async loadApiJson() {}, async refreshComboInNodes() {},
  extensionManager: { toast: { add: toastUI }, workflow: { activeWorkflow: null } },
};
