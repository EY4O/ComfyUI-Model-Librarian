// Safety nets for other extensions' bugs that would otherwise break loading workflows. No ComfyUI imports,
// so it's tested in node.

const GUARDED = Symbol.for("ModelLibrarian.connectGuard");
const LONG = Symbol.for("ModelLibrarian.longStacks");

// ComfyUI-Impact-Pack's switch and list nodes (ImpactSwitch, Make*List/Batch, Combine*/Concat*, LatentSwitch,
// SEGSSwitch …) work out whether a workflow is loading with `new Error().stack.includes("loadGraphData")`.
// Since frontend 1.47 that frame is the 11th and V8 keeps 10, so the check misses and their connection handler
// runs while a workflow loads: it retypes the node from its `select` input, adds a spare input and calls
// `node.connect(slot, node.id, "input1")`. LiteGraph only looks up a target given as a number, and loaded nodes
// have string ids, so the id reaches `target.findInputSlot` and loading stops with "Loading aborted due to error
// reloading workflow data — TypeError: t.findInputSlot is not a function". Two nets, one for each half.
// Reported upstream as ltdrdata/ComfyUI-Impact-Pack#1223 and #1244 (fixes in #1228 and #1247); remove both once
// Impact Pack ships one.

// While `obj[name]` (app.loadGraphData) runs, errors keep at least `frames` stack frames, so Impact's check sees
// the loader and leaves the node as it was saved. The old limit comes back when the last call finishes.
export function longStacksDuring(obj, name, frames = 50) {
  if (!obj || typeof obj[name] !== "function" || obj[LONG]) return false;
  const fn = obj[name];
  let running = 0, saved;
  obj[name] = async function (...args) {
    if (!running++) {
      saved = Error.stackTraceLimit;
      if (!(saved >= frames)) Error.stackTraceLimit = frames;
    }
    try {
      return await fn.apply(this, args);
    } finally {
      if (!--running) Error.stackTraceLimit = saved;
    }
  };
  obj[LONG] = true;
  return true;
}

// Loads that don't go through it (pasting, a subgraph) still reach the connect call: a target given as an id
// (number or string) is looked up in the node's graph, and one that isn't a node there makes the call return
// null, as LiteGraph does for a slot it can't find. Every other call goes through as it was.
export function guardConnect(proto) {
  if (!proto || typeof proto.connect !== "function" || proto[GUARDED]) return false;
  const connect = proto.connect; // whatever is there, other extensions' wrappers included
  proto.connect = function (slot, target, ...rest) {
    if (typeof target === "number" || typeof target === "string") {
      const node = this.graph?.getNodeById?.(target);
      if (typeof node?.findInputSlot !== "function") return null;
      target = node;
    }
    return connect.call(this, slot, target, ...rest);
  };
  proto[GUARDED] = true;
  return true;
}
