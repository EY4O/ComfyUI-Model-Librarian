// Compare a LoRA's strengths in ComfyUI: builds the comparison (compare.js) from a workflow in API format,
// opens it as a new workflow (yours isn't changed), with fixed seeds so every copy renders the same picture,
// and lays it out with Re-organize.
import { strengthGraph } from "./compare.js";
import { tidyCanvas, fitView } from "./tidyComfy.js";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Open a workflow in a new tab without risking the one that's open. ComfyUI's loaders (loadApiJson,
// loadGraphData) load onto the canvas and then make the new tab, and now and then the tab that was open
// keeps the new graph instead of its own. So a blank tab is opened first, to take that risk, and closed
// once the new workflow has its own tab. `load()` does the loading; `name` is the new tab's name.
export async function loadInNewTab(app, load, name) {
  const ws = app.extensionManager?.workflow;
  const before = ws?.activeWorkflow;
  let blank = null;
  if (before && app.extensionManager.command) {
    await app.extensionManager.command.execute("Comfy.NewBlankWorkflow");
    for (let i = 0; i < 30 && ws.activeWorkflow === before; i++) await sleep(100);
    if (ws.activeWorkflow !== before) { blank = ws.activeWorkflow; await sleep(300); }
  }
  await load();
  for (let i = 0; i < 50 && !String(ws?.activeWorkflow?.filename || "").startsWith(name); i++) await sleep(100);
  await sleep(500); // ComfyUI reopens the new tab from its own copy once loading finishes
  if (blank && blank !== ws.activeWorkflow && ws.isOpen?.(blank)) {
    try { await ws.closeWorkflow(blank); } catch {}
  }
}

export async function openComparison(app, toast, api, lora, strengths, name) {
  const r = strengthGraph(api, lora, strengths);
  if (r.error) return toast("warn", "Compare strengths", r.error, 6000);
  if (!app.loadApiJson) return toast("error", "Compare strengths", "This ComfyUI version can't open API-format workflows.", 6000);
  // ComfyUI sets widgets from the API data when it loads it, the seed's "control after generate" included:
  // set there, it survives ComfyUI reopening the new tab from its own copy
  for (const n of Object.values(r.prompt)) {
    if (n.inputs && ("seed" in n.inputs || "noise_seed" in n.inputs)) n.inputs.control_after_generate = "fixed";
  }
  await loadInNewTab(app, () => app.loadApiJson(r.prompt, name), name);
  tidyCanvas(app.canvas, { mode: "reorganize" });
  fitView(app.canvas);
  try {
    const tracker = app.extensionManager?.workflow?.activeWorkflow?.changeTracker;
    tracker?.captureCanvasState ? tracker.captureCanvasState() : tracker?.checkState?.();
  } catch {}
  toast("success", "Comparison ready", `${r.copies} strengths: ${strengths.join(", ")} · ${r.nodes} nodes each · queue it to render them`, 6000);
}
