// Safety nets for Impact Pack's switch nodes (js/lib/compat.js), on a stand-in LiteGraph, without a browser.
import { pathToFileURL, fileURLToPath } from "node:url";
const PLUGIN = process.argv[2] || fileURLToPath(new URL("..", import.meta.url));
const { guardConnect, longStacksDuring } = await import(pathToFileURL(PLUGIN + "/js/lib/compat.js").href);
let fail = 0;
const ok = (cond, m, extra = "") => { console.log((cond ? "PASS " : "FAIL ") + m + (cond ? "" : ` ${extra}`)); if (!cond) fail++; };

// LiteGraph's connect as of frontend 1.55: only a number is looked up, anything else must be a node
class Node {
  constructor(id, inputs = []) { this.id = id; this.inputs = inputs; }
  findInputSlot(name) { return this.inputs.indexOf(name); }
  connect(slot, target, targetSlot) {
    if (typeof target === "number") target = this.graph.getNodeById(String(target));
    if (target === this) return null;
    const i = typeof targetSlot === "string" ? target.findInputSlot(targetSlot) : targetSlot;
    return i < 0 ? null : { origin: this.id, slot, target: target.id, targetSlot: i };
  }
}
const graph = (...nodes) => {
  const byId = new Map(nodes.map((n) => [String(n.id), n]));
  const g = { getNodeById: (id) => byId.get(String(id)) ?? null };
  for (const n of nodes) n.graph = g;
  return g;
};

// what Impact Pack does while a workflow loads: the origin node connects to its own id (a string once loaded)
const loader = new Node("1", []), sw = new Node("2", ["input1", "select", "sel_mode", "input2"]);
graph(loader, sw);
let threw = null;
try { loader.connect(0, loader.id, "input1"); } catch (e) { threw = e; }
ok(threw instanceof TypeError, "unguarded, a string id reaches findInputSlot and throws (the reported error)", String(threw));

const native = Node.prototype.connect;
ok(guardConnect(Node.prototype) === true, "installs");
ok(guardConnect(Node.prototype) === false && Node.prototype.connect !== native, "installs once (a second call changes nothing)");
const once = Node.prototype.connect;
guardConnect(Node.prototype);
ok(Node.prototype.connect === once, "the prototype keeps the one wrapper");

let r;
try { r = loader.connect(0, loader.id, "input1"); threw = null; } catch (e) { threw = e; }
ok(!threw && r === null, "Impact's call returns null instead of throwing", String(threw));
ok(loader.connect(0, "999", "input1") === null && loader.connect(0, 999, 0) === null, "an id that isn't in the graph returns null");
ok(new Node("9").connect(0, "2", 0) === null, "a node outside any graph returns null for an id");
ok(JSON.stringify(loader.connect(0, sw, "input1")) === JSON.stringify({ origin: "1", slot: 0, target: "2", targetSlot: 0 }), "a node object goes through as before");
ok(loader.connect(0, "2", "input2")?.targetSlot === 3, "a string id of another node is looked up and connected");
ok(loader.connect(0, 2, "select")?.targetSlot === 1, "a number id still works");
let seen;
const passes = new Node("3", ["a"]);
graph(passes);
const before = Node.prototype.connect;
Node.prototype.connect = function (...a) { seen = a; return before.apply(this, a); }; // another extension wraps it later
passes.connect(1, passes, "a", 77);
ok(seen?.length === 4 && seen[1] === passes && seen[3] === 77, "extra arguments and later wrappers pass through");

// another extension's earlier wrapper is kept: guardConnect wraps whatever is there
class Other { connect(slot, target) { return target.findInputSlot ? "inner" : "bad"; } }
const calls = [];
const inner = Other.prototype.connect;
Other.prototype.connect = function (...a) { calls.push("theirs"); return inner.apply(this, a); };
guardConnect(Other.prototype);
const o = new Other(); o.graph = { getNodeById: () => ({ findInputSlot() {} }) };
ok(o.connect(0, "5") === "inner" && calls.length === 1, "an earlier wrapper by another extension still runs");
ok(guardConnect(null) === false && guardConnect({}) === false, "nothing to wrap: no-op");

// longer stacks while a workflow loads, back to the old limit after
const app = { calls: 0, async loadGraphData(x) { this.calls++; await null; return [x, Error.stackTraceLimit]; } };
const prev = Error.stackTraceLimit;
ok(longStacksDuring(app, "loadGraphData") === true && longStacksDuring(app, "loadGraphData") === false, "loader wrapped once");
const res = await app.loadGraphData("wf");
ok(res[0] === "wf" && res[1] >= 50 && app.calls === 1, `the loader runs with at least 50 frames (${res[1]})`);
ok(Error.stackTraceLimit === prev, "the limit is restored afterwards");
const both = await Promise.all([app.loadGraphData(1), app.loadGraphData(2)]);
ok(both.every((b) => b[1] >= 50) && Error.stackTraceLimit === prev, "overlapping loads: raised for both, restored after the last");
const failing = { async loadGraphData() { throw new Error("bad workflow"); } };
longStacksDuring(failing, "loadGraphData");
let msg = null;
try { await failing.loadGraphData(); } catch (e) { msg = e.message; }
ok(msg === "bad workflow" && Error.stackTraceLimit === prev, "a loader error still comes through, and the limit is restored");
Error.stackTraceLimit = 80;
const deep = await app.loadGraphData("x");
ok(deep[1] === 80 && Error.stackTraceLimit === 80, "a higher limit someone set is left alone");
Error.stackTraceLimit = prev;

process.exit(fail ? 1 : 0);
