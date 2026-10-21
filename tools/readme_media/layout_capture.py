"""Tidy and Re-organize on ComfyUI's real frontend with sample workflows: checks each result and writes
before/after screenshots for the README.

  python tools/readme_media/layout_capture.py [--url http://127.0.0.1:8199] [--out docs/images] [--mode tidy|reorganize|both]

  tidy        a crowded, spread-out workflow -> tidy-before.png / tidy-after.png
              checks: no overlaps, groups kept, pinned node untouched, undo, a second Tidy changes nothing
  reorganize  a scrambled workflow (sampler far left, loader far right, save on top) -> reorganize-before.png / -after.png
              checks: the preview moves nothing (Cancel / Esc put the view back); Apply: every wire left to right,
              no overlaps, groups kept, pinned untouched; Ctrl+Z; a second Re-organize finds nothing to do; a
              selection moves only those nodes. Also reorganize-preview.png

Needs a running test ComfyUI with this Model Librarian (it loads sample workflows in a new tab and briefly turns
on wires and full-detail rendering, restoring those settings after), Microsoft Edge, websockets and Pillow
(ComfyUI's environment). The samples' model names don't exist, so ComfyUI's "missing" notices are hidden.
"""
import argparse
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = 9335
REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def node(id, type, x, y, w, h, inputs=(), outputs=(), widgets=None, title=None, flags=None):
    return {"id": id, "type": type, "pos": [x, y], "size": [w, h], "flags": flags or {}, "order": id, "mode": 0,
            "inputs": [{"name": n, "type": t, "link": l} for n, t, l in inputs],
            "outputs": [{"name": n, "type": t, "links": ls, "slot_index": i} for i, (n, t, ls) in enumerate(outputs)],
            "properties": {}, "widgets_values": widgets or [], **({"title": title} if title else {})}


# links: [id, origin, origin_slot, target, target_slot, type]
LINKS = [[1, 1, 0, 2, 0, "MODEL"], [2, 1, 1, 2, 1, "CLIP"], [3, 2, 1, 3, 0, "CLIP"], [4, 2, 1, 4, 0, "CLIP"],
         [5, 2, 0, 6, 0, "MODEL"], [6, 3, 0, 6, 1, "CONDITIONING"], [7, 4, 0, 6, 2, "CONDITIONING"], [8, 5, 0, 6, 3, "LATENT"],
         [9, 6, 0, 7, 0, "LATENT"], [10, 1, 2, 7, 1, "VAE"], [11, 7, 0, 8, 0, "IMAGE"], [12, 7, 0, 9, 0, "IMAGE"]]


def workflow(pos, groups):
    """The same text-to-image graph, with nodes at `pos` (id -> (x, y)) and these groups."""
    P = lambda i: pos[i]  # noqa: E731
    return {
        "last_node_id": 10, "last_link_id": 12, "version": 0.4, "links": LINKS, "config": {}, "extra": {}, "groups": groups,
        "nodes": [
            node(1, "CheckpointLoaderSimple", *P(1), 320, 100, outputs=[("MODEL", "MODEL", [1]), ("CLIP", "CLIP", [2]), ("VAE", "VAE", [10])], widgets=["sample_model.safetensors"]),
            node(2, "LoraLoader", *P(2), 320, 130, inputs=[("model", "MODEL", 1), ("clip", "CLIP", 2)], outputs=[("MODEL", "MODEL", [5]), ("CLIP", "CLIP", [3, 4])],
                 widgets=["sample_lora.safetensors", 0.8, 0.8]),
            node(3, "CLIPTextEncode", *P(3), 420, 200, inputs=[("clip", "CLIP", 3)], outputs=[("CONDITIONING", "CONDITIONING", [6])], widgets=["a lighthouse at dusk, paper cut style"], title="Positive"),
            node(4, "CLIPTextEncode", *P(4), 420, 200, inputs=[("clip", "CLIP", 4)], outputs=[("CONDITIONING", "CONDITIONING", [7])], widgets=["blurry, lowres"], title="Negative"),
            node(5, "EmptyLatentImage", *P(5), 300, 110, outputs=[("LATENT", "LATENT", [8])], widgets=[1024, 1024, 1]),
            node(6, "KSampler", *P(6), 320, 270, inputs=[("model", "MODEL", 5), ("positive", "CONDITIONING", 6), ("negative", "CONDITIONING", 7), ("latent_image", "LATENT", 8)],
                 outputs=[("LATENT", "LATENT", [9])], widgets=[42, "fixed", 8, 1, "euler", "simple", 1]),
            node(7, "VAEDecode", *P(7), 210, 50, inputs=[("samples", "LATENT", 9), ("vae", "VAE", 10)], outputs=[("IMAGE", "IMAGE", [11, 12])]),
            node(8, "SaveImage", *P(8), 420, 420, inputs=[("images", "IMAGE", 11)], widgets=["layout_sample"]),
            node(9, "PreviewImage", *P(9), 300, 300, inputs=[("images", "IMAGE", 12)]),
            node(10, "Note", *P(10), 300, 120, widgets=["pinned note: stays put"], flags={"pinned": True}),
        ],
    }


# Tidy: crowded (overlapping) and spread out, roughly in flow order
CROWDED = workflow({1: (40, 120), 2: (70, 190), 3: (470, 60), 4: (520, 230), 5: (300, 900), 6: (2100, 640), 7: (2900, 120), 8: (2950, 1500), 9: (3000, 260), 10: (1300, 1250)},
                   [{"title": "Models", "bounding": [10, 30, 420, 330], "color": "#3f789e"}, {"title": "Prompts", "bounding": [450, -40, 520, 520], "color": "#a1309b"}])
# Re-organize: scrambled against the flow (no groups: Re-organize places groups too, but this shows the wiring best)
SCRAMBLED = workflow({1: (2300, 700), 2: (1500, 80), 3: (300, 820), 4: (1900, 1180), 5: (2600, 1300), 6: (40, 260), 7: (1000, 1250), 8: (700, 40), 9: (2550, 220), 10: (1250, 620)},
                     [{"title": "Prompts", "bounding": [270, 720, 500, 360], "color": "#a1309b"}])


class CDP:
    def __init__(self, ws):
        self.ws, self.n = ws, 0

    async def call(self, method, **params):
        self.n += 1
        my = self.n
        await self.ws.send(json.dumps({"id": my, "method": method, "params": params}))
        while True:
            m = json.loads(await self.ws.recv())
            if m.get("id") == my:
                if "error" in m:
                    raise RuntimeError(m["error"])
                return m.get("result", {})

    async def js(self, expr):
        r = await self.call("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"])[:400])
        return r["result"].get("value")

    async def wait(self, expr, timeout=60):
        t = time.time()
        while time.time() - t < timeout:
            try:
                if await self.js(f"!!({expr})"):
                    return
            except RuntimeError:
                pass
            await asyncio.sleep(0.4)
        raise RuntimeError(f"timed out: {expr}")


GEOM = """(() => { const g = app.canvas.graph;
  const ns = (g._nodes || g.nodes).map((n) => { try { n.updateArea?.(app.canvas.ctx); } catch {} const b = n.boundingRect;
    return {id: String(n.id), x: b[0], y: b[1], w: b[2], h: b[3], pos: [n.pos[0], n.pos[1]], inputs: (n.inputs || []).map((i) => { const l = g.getLink?.(i.link) ?? (g.links?.get ? g.links.get(i.link) : g.links?.[i.link]); return l ? String(l.origin_id) : null; }).filter(Boolean)}; });
  const gs = (g._groups || g.groups).map((x) => { const b = x._bounding || x.boundingRect; return {title: x.title, x: b[0], y: b[1], w: b[2], h: b[3]}; });
  return {ns, gs}; })()"""
CLEAN = ("(app.canvas.graph._nodes || app.canvas.graph.nodes).forEach((n) => { n.has_errors = false; }); app.lastNodeErrors = null;"
         "[...document.querySelectorAll('div,section,aside')].filter((e) => /errors found|missing models in this workflow|Tidied|Re-organized/.test(e.textContent)"
         " && e.offsetWidth > 150 && e.offsetWidth < 620 && e.offsetHeight > 20 && e.offsetHeight < 220).forEach((e) => e.style.setProperty('display', 'none', 'important'));"
         " app.canvas.setDirty(true, true); true")


def overlap(a, b):
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


def inside(n, g):
    return n["x"] >= g["x"] - 1 and n["y"] >= g["y"] - 1 and n["x"] + n["w"] <= g["x"] + g["w"] + 1 and n["y"] + n["h"] <= g["y"] + g["h"] + 1


async def load(c, wf, view):
    await c.js(f"app.loadGraphData({json.dumps(wf)}).then(() => true)")
    await asyncio.sleep(1.5)
    scale, ox, oy = view
    await c.js(f"app.canvas.ds.scale = {scale}; app.canvas.ds.offset = [{ox}, {oy}]; app.canvas.setDirty(true, true); true")
    await asyncio.sleep(0.6)
    await c.js(CLEAN)
    await asyncio.sleep(0.5)
    before = await c.js(GEOM)
    return {n["id"]: n["pos"] for n in before["ns"]}


async def shoot(c, path):
    shot = await c.call("Page.captureScreenshot", format="png", clip={"x": 60, "y": 110, "width": 1740, "height": 860, "scale": 1})
    open(path, "wb").write(base64.b64decode(shot["data"]))


TRACKER = "app.extensionManager.workflow.activeWorkflow.changeTracker"
BAR = "document.querySelector('.smf-keepbar')"
CLICK = "[...document.querySelectorAll('.smf-keepbar button')].find((b) => b.textContent === '{}').click(); true"


async def scene_tidy(c, check, tmp, view):
    command = "app.extensionManager.command.execute('ModelLibrarian.Tidy'); true"
    bpos = await load(c, CROWDED, view)
    await shoot(c, os.path.join(tmp, "tidy-before.png"))
    await c.js(command)
    await asyncio.sleep(1)
    after = await c.js(GEOM)
    ns = after["ns"]
    by = {n["id"]: n for n in ns}
    check(sum(1 for n in ns if n["pos"] != bpos[n["id"]]) >= 6, "tidy: nodes moved")
    check(not any(overlap(a, b) for i, a in enumerate(ns) for b in ns[i + 1:]), "tidy: no overlapping nodes")
    check(by["10"]["pos"] == bpos["10"], "tidy: the pinned note didn't move")
    g = {x["title"]: x for x in after["gs"]}
    check(inside(by["1"], g["Models"]) and inside(by["2"], g["Models"]) and inside(by["3"], g["Prompts"]) and inside(by["4"], g["Prompts"]) and not overlap(g["Models"], g["Prompts"]),
          "tidy: groups still hold their nodes and don't overlap")
    await c.js(CLEAN)
    await asyncio.sleep(0.8)
    await shoot(c, os.path.join(tmp, "tidy-after.png"))
    await c.js(f"{TRACKER}.undo().then?.(() => true) ?? true")
    await asyncio.sleep(1.5)
    check(all(bpos[n["id"]] == n["pos"] for n in (await c.js(GEOM))["ns"]), "tidy: Ctrl+Z puts every node back")
    await c.js(command)
    await asyncio.sleep(0.8)
    r1 = await c.js(GEOM)
    await c.js(command)
    await asyncio.sleep(0.8)
    r2 = await c.js(GEOM)
    check(all(a["pos"] == b["pos"] for a, b in zip(r1["ns"], r2["ns"])), "tidy: a second run changes nothing")


async def scene_reorganize(c, check, tmp, view):
    command = "app.extensionManager.command.execute('ModelLibrarian.Reorganize'); true"
    bpos = await load(c, SCRAMBLED, view)
    await shoot(c, os.path.join(tmp, "reorganize-before.png"))

    def unchanged(geom):
        return all(bpos[n["id"]] == n["pos"] for n in geom["ns"])

    # the preview: nothing moves until Apply; Cancel and Esc put the view back
    await c.js(command)
    await asyncio.sleep(1)
    bar = await c.js(f"{BAR}?.innerText || ''")
    check("preview" in bar and "Apply" in bar and "Cancel" in bar, f"reorganize: the preview bar appears ({bar!r})")
    check(unchanged(await c.js(GEOM)), "reorganize: the preview moves nothing")
    await c.js(CLEAN)
    await asyncio.sleep(0.6)
    await shoot(c, os.path.join(tmp, "reorganize-preview.png"))
    await c.js(CLICK.format("Cancel"))
    await asyncio.sleep(0.6)
    ds = await c.js("[app.canvas.ds.scale, app.canvas.ds.offset[0], app.canvas.ds.offset[1]]")
    check(unchanged(await c.js(GEOM)) and not await c.js(f"!!{BAR}") and abs(ds[0] - view[0]) < 1e-6 and abs(ds[1] - view[1]) < 1e-6,
          f"reorganize: Cancel closes it, nothing moved, the view is put back ({ds})")
    await c.js(command)
    await asyncio.sleep(0.8)
    await c.js("document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); true")
    await asyncio.sleep(0.5)
    check(unchanged(await c.js(GEOM)) and not await c.js(f"!!{BAR}"), "reorganize: Esc cancels too")

    # Apply
    await c.js(command)
    await asyncio.sleep(0.8)
    await c.js(CLICK.format("Apply"))
    await asyncio.sleep(1)
    after = await c.js(GEOM)
    ns = after["ns"]
    by = {n["id"]: n for n in ns}
    check(not await c.js(f"!!{BAR}") and sum(1 for n in ns if n["pos"] != bpos[n["id"]]) >= 6, "reorganize: Apply moves the nodes")
    check(not any(overlap(a, b) for i, a in enumerate(ns) for b in ns[i + 1:]), "reorganize: no overlapping nodes")
    check(by["10"]["pos"] == bpos["10"], "reorganize: the pinned note didn't move")
    backwards = [(o, n["id"]) for n in ns for o in n["inputs"] if by[o]["x"] + by[o]["w"] >= n["x"]]
    check(not backwards, f"reorganize: every wire runs left to right ({backwards})")
    g = {x["title"]: x for x in after["gs"]}
    check(inside(by["3"], g["Prompts"]) and not inside(by["4"], g["Prompts"]), "reorganize: the group keeps its node, and only its node")
    scale, ox, oy = view
    await c.js(f"app.canvas.ds.scale = {scale}; app.canvas.ds.offset = [{ox}, {oy}]; app.canvas.setDirty(true, true); true")
    await c.js(CLEAN)
    await asyncio.sleep(0.8)
    await shoot(c, os.path.join(tmp, "reorganize-after.png"))
    await c.js(f"{TRACKER}.undo().then?.(() => true) ?? true")
    await asyncio.sleep(1.5)
    check(unchanged(await c.js(GEOM)), "reorganize: Ctrl+Z puts every node back")
    await c.js(command)
    await asyncio.sleep(0.8)
    await c.js(CLICK.format("Apply"))
    await asyncio.sleep(0.8)
    r1 = await c.js(GEOM)
    await c.js(command)
    await asyncio.sleep(0.8)
    r2 = await c.js(GEOM)
    check(not await c.js(f"!!{BAR}") and all(a["pos"] == b["pos"] for a, b in zip(r1["ns"], r2["ns"])), "reorganize: a second run finds it already laid out")

    # just the selected nodes
    bpos = await load(c, SCRAMBLED, view)
    picked = ["5", "6", "7"]
    n = await c.js("(() => { const c = app.canvas, g = c.graph; c.deselectAll?.(); for (const id of %s) c.select(g.getNodeById(Number(id))); return c.selectedItems?.size ?? 0; })()" % json.dumps(picked))
    check(n == 3, f"reorganize selection: three nodes selected ({n})")
    await c.js("app.extensionManager.command.execute('ModelLibrarian.ReorganizeSelection'); true")
    await asyncio.sleep(0.8)
    await c.js(CLICK.format("Apply"))
    await asyncio.sleep(0.8)
    ns = (await c.js(GEOM))["ns"]
    by = {n["id"]: n for n in ns}
    others = [n["id"] for n in ns if n["id"] not in picked and n["pos"] != bpos[n["id"]]]
    check(not others and any(by[i]["pos"] != bpos[i] for i in picked), f"reorganize selection: only the selected nodes move ({others})")
    check(by["5"]["x"] + by["5"]["w"] < by["6"]["x"] and by["6"]["x"] + by["6"]["w"] < by["7"]["x"], "reorganize selection: in flow order")


async def main(args):
    profile = tempfile.mkdtemp(prefix="ml_ext_edge_")
    tmp = tempfile.mkdtemp(prefix="layout_shots_")
    subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", "--no-first-run", "--window-size=1800,1000", "about:blank"])
    fails = 0

    def check(ok, msg):
        nonlocal fails
        print(("PASS " if ok else "FAIL ") + msg)
        fails += 0 if ok else 1
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2)
                break
            except OSError:
                await asyncio.sleep(0.5)
        t = json.loads(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?{args.url}/", method="PUT")).read())
        async with websockets.connect(t["webSocketDebuggerUrl"], max_size=None) as ws:
            c = CDP(ws)
            await c.call("Page.enable")
            await c.call("Emulation.setDeviceMetricsOverride", width=1800, height=1000, deviceScaleFactor=1, mobile=False)
            await c.wait("window.app && app.canvas && app.extensionManager && app.extensionManager.workflow", 90)
            await asyncio.sleep(2)
            setting = "app.extensionManager.setting"
            old_lod = await c.js(f"{setting}.get('LiteGraph.Canvas.MinFontSizeForLOD')")
            old_links = await c.js(f"{setting}.get('Comfy.LinkRenderMode')")
            await c.js(f"{setting}.set('LiteGraph.Canvas.MinFontSizeForLOD', 1).then(() => {setting}.set('Comfy.LinkRenderMode', 2)).then(() => true)")
            try:
                if args.mode in ("tidy", "both"):
                    await scene_tidy(c, check, tmp, (0.46, 150, 190))
                if args.mode in ("reorganize", "both"):
                    await scene_reorganize(c, check, tmp, (0.45, 150, 220))
            finally:
                await c.js(f"{setting}.set('LiteGraph.Canvas.MinFontSizeForLOD', {json.dumps(old_lod)}).then(() => {setting}.set('Comfy.LinkRenderMode', {json.dumps(old_links)})).then(() => true)")
        if not fails:
            from PIL import Image
            crops = {"tidy-before": (0, 0, 1580, 760), "tidy-after": (0, 0, 1010, 640), "reorganize-before": (0, 0, 1600, 760), "reorganize-after": (0, 0, 1600, 760), "reorganize-preview": (0, 0, 1740, 860)}
            for name, box in crops.items():
                src = os.path.join(tmp, name + ".png")
                if os.path.exists(src):
                    im = Image.open(src).crop(box)
                    bbox = im.convert("L").point(lambda v: 255 if v > 30 else 0).getbbox()  # trim empty canvas on the right/bottom
                    if bbox:
                        im = im.crop((0, 0, min(box[2], bbox[2] + 20), min(box[3], bbox[3] + 20)))
                    im.save(os.path.join(args.out, name + ".png"), optimize=True)
                    print("wrote", name + ".png")
        return 1 if fails else 0
    finally:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -like '*ml_ext_edge_*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"], capture_output=True)
        time.sleep(1)
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(tmp, ignore_errors=True)
        print("\nFAILED: %d" % fails if fails else "\nALL PASSED")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", default="http://127.0.0.1:8199")
    ap.add_argument("--out", default=os.path.join(REPO, "docs", "images"))
    ap.add_argument("--mode", choices=("tidy", "reorganize", "both"), default="both")
    sys.exit(asyncio.run(main(ap.parse_args())))
