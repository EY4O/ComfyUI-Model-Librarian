"""Tidy on ComfyUI's real frontend with a crowded sample workflow: checks the result (no overlaps, groups
kept, pinned node untouched, undo, a second Tidy changes nothing) and writes before/after screenshots.

  python tools/readme_media/tidy_capture.py [--url http://127.0.0.1:8199] [--out docs/images]

Needs a running ComfyUI with this Model Librarian (a test instance: it loads a sample workflow in a new tab
and briefly turns on wires and full-detail rendering, restoring those settings after), Microsoft Edge, and
websockets + Pillow (ComfyUI's environment). The sample's model names don't exist, so ComfyUI's
"missing" notices are hidden for the shots."""
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
import argparse
ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8199")
ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docs", "images"))
ARGS = ap.parse_args()
OUT = tempfile.mkdtemp(prefix="tidy_shots_")


def node(id, type, x, y, w, h, inputs=(), outputs=(), widgets=None, title=None, flags=None):
    return {"id": id, "type": type, "pos": [x, y], "size": [w, h], "flags": flags or {}, "order": id, "mode": 0,
            "inputs": [{"name": n, "type": t, "link": l} for n, t, l in inputs],
            "outputs": [{"name": n, "type": t, "links": ls, "slot_index": i} for i, (n, t, ls) in enumerate(outputs)],
            "properties": {}, "widgets_values": widgets or [], **({"title": title} if title else {})}


# links: [id, origin, origin_slot, target, target_slot, type]
LINKS = [[1, 1, 0, 2, 0, "MODEL"], [2, 1, 1, 2, 1, "CLIP"], [3, 2, 1, 3, 0, "CLIP"], [4, 2, 1, 4, 0, "CLIP"],
         [5, 2, 0, 6, 0, "MODEL"], [6, 3, 0, 6, 1, "CONDITIONING"], [7, 4, 0, 6, 2, "CONDITIONING"], [8, 5, 0, 6, 3, "LATENT"],
         [9, 6, 0, 7, 0, "LATENT"], [10, 1, 2, 7, 1, "VAE"], [11, 7, 0, 8, 0, "IMAGE"], [12, 7, 0, 9, 0, "IMAGE"]]
WORKFLOW = {
    "last_node_id": 10, "last_link_id": 12, "version": 0.4, "links": LINKS,
    "nodes": [
        node(1, "CheckpointLoaderSimple", 40, 120, 320, 100, outputs=[("MODEL", "MODEL", [1]), ("CLIP", "CLIP", [2]), ("VAE", "VAE", [10])], widgets=["sample_model.safetensors"]),
        node(2, "LoraLoader", 70, 190, 320, 130, inputs=[("model", "MODEL", 1), ("clip", "CLIP", 2)], outputs=[("MODEL", "MODEL", [5]), ("CLIP", "CLIP", [3, 4])],
             widgets=["sample_lora.safetensors", 0.8, 0.8]),
        node(3, "CLIPTextEncode", 470, 60, 420, 200, inputs=[("clip", "CLIP", 3)], outputs=[("CONDITIONING", "CONDITIONING", [6])], widgets=["a lighthouse at dusk, paper cut style"], title="Positive"),
        node(4, "CLIPTextEncode", 520, 230, 420, 200, inputs=[("clip", "CLIP", 4)], outputs=[("CONDITIONING", "CONDITIONING", [7])], widgets=["blurry, lowres"], title="Negative"),
        node(5, "EmptyLatentImage", 300, 900, 300, 110, outputs=[("LATENT", "LATENT", [8])], widgets=[1024, 1024, 1]),
        node(6, "KSampler", 2100, 640, 320, 270, inputs=[("model", "MODEL", 5), ("positive", "CONDITIONING", 6), ("negative", "CONDITIONING", 7), ("latent_image", "LATENT", 8)],
             outputs=[("LATENT", "LATENT", [9])], widgets=[42, "fixed", 8, 1, "euler", "simple", 1]),
        node(7, "VAEDecode", 2900, 120, 210, 50, inputs=[("samples", "LATENT", 9), ("vae", "VAE", 10)], outputs=[("IMAGE", "IMAGE", [11, 12])]),
        node(8, "SaveImage", 2950, 1500, 420, 420, inputs=[("images", "IMAGE", 11)], widgets=["tidy_sample"]),
        node(9, "PreviewImage", 3000, 260, 300, 300, inputs=[("images", "IMAGE", 12)]),
        node(10, "Note", 1300, 1250, 300, 120, widgets=["pinned note: stays put"], flags={"pinned": True}),
    ],
    "groups": [{"title": "Models", "bounding": [10, 30, 420, 330], "color": "#3f789e"},
               {"title": "Prompts", "bounding": [450, -40, 520, 520], "color": "#a1309b"}],
    "config": {}, "extra": {},
}


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


GEOM = """(() => { const g = app.canvas.graph; const ns = (g._nodes||g.nodes).map((n) => { try { n.updateArea?.(app.canvas.ctx); } catch {} const b = n.boundingRect; return {id: n.id, x: b[0], y: b[1], w: b[2], h: b[3], pos: [n.pos[0], n.pos[1]]}; });
  const gs = (g._groups||g.groups).map((x) => { const b = x._bounding || x.boundingRect; return {title: x.title, x: b[0], y: b[1], w: b[2], h: b[3]}; });
  return {ns, gs}; })()"""


def overlap(a, b):
    return a["x"] < b["x"] + b["w"] and b["x"] < a["x"] + a["w"] and a["y"] < b["y"] + b["h"] and b["y"] < a["y"] + a["h"]


async def main():
    profile = tempfile.mkdtemp(prefix="ml_ext_edge_")
    subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={profile}", "--no-first-run", "--window-size=1600,1000", "about:blank"])
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
        t = json.loads(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?{ARGS.url}/", method="PUT")).read())
        async with websockets.connect(t["webSocketDebuggerUrl"], max_size=None) as ws:
            c = CDP(ws)
            await c.call("Page.enable")
            await c.call("Emulation.setDeviceMetricsOverride", width=1800, height=1000, deviceScaleFactor=1, mobile=False)
            await c.wait("window.app && app.canvas && app.extensionManager && app.extensionManager.workflow", 90)
            await asyncio.sleep(2)
            await c.js(f"app.loadGraphData({json.dumps(WORKFLOW)}).then(() => true)")
            await asyncio.sleep(1.5)
            await c.js("document.querySelectorAll('.p-toast-message-content, .p-dialog-mask').forEach((e) => e.closest('.p-toast-message, .p-dialog-mask')?.remove()); true")
            old_lod = await c.js("app.extensionManager.setting.get('LiteGraph.Canvas.MinFontSizeForLOD')")
            old_links = await c.js("app.extensionManager.setting.get('Comfy.LinkRenderMode')")
            await c.js("app.extensionManager.setting.set('LiteGraph.Canvas.MinFontSizeForLOD', 1).then(() => app.extensionManager.setting.set('Comfy.LinkRenderMode', 2)).then(() => true)")
            await c.js("app.canvas.ds.scale = 0.46; app.canvas.ds.offset = [150, 190]; [...document.querySelectorAll('div,section,aside')].filter((e) => /errors found|missing models in this workflow/.test(e.textContent) && e.offsetWidth > 150 && e.offsetWidth < 520 && e.offsetHeight > 30 && e.offsetHeight < 220).forEach((e) => e.style.setProperty('display', 'none', 'important')); app.canvas.setDirty(true, true); true")
            await asyncio.sleep(0.8)
            before = await c.js(GEOM)
            print("  loaded nodes:", [(n["id"], n["pos"]) for n in before["ns"]], "groups:", [x["title"] for x in before["gs"]])
            await c.js("(app.canvas.graph._nodes || app.canvas.graph.nodes).forEach((n) => { n.has_errors = false; }); app.lastNodeErrors = null; [...document.querySelectorAll('[role=alert], [role=alertdialog], [class*=toast], [class*=Toast]'), ...[...document.querySelectorAll('body *')].filter((e) => e.children.length === 0 && /errors found|missing models in this workflow|Tidied/.test(e.textContent))].forEach((e) => { let p = e; while (p && getComputedStyle(p).position !== 'fixed') p = p.parentElement; (p && p !== document.body ? p : (e.matches('[role=alert], [role=alertdialog], [class*=toast], [class*=Toast]') ? e : null))?.style.setProperty('display', 'none', 'important'); }); [...document.querySelectorAll('div,section,aside')].filter((e) => /errors found|missing models in this workflow/.test(e.textContent) && e.offsetWidth > 150 && e.offsetWidth < 520 && e.offsetHeight > 30 && e.offsetHeight < 220).forEach((e) => e.style.setProperty('display', 'none', 'important')); app.canvas.setDirty(true, true); true")
            await asyncio.sleep(0.5)
            shot = await c.call("Page.captureScreenshot", format="png", clip={"x": 60, "y": 110, "width": 1740, "height": 860, "scale": 1})
            open(os.path.join(OUT, "before.png"), "wb").write(base64.b64decode(shot["data"]))
            check(any(overlap(a, b) for i, a in enumerate(before["ns"]) for b in before["ns"][i + 1:]), "set-up: the sample workflow has overlapping nodes")
            items = await c.js("app.extensions?.find?.((e) => e.name === 'ModelLibrarian')?.getCanvasMenuItems?.(app.canvas)?.map((x) => x && x.content)")
            check(items and "Tidy workflow" in items, f"the canvas menu offers Tidy ({items})")
            await c.js("app.extensionManager.command.execute('ModelLibrarian.Tidy'); true")
            await asyncio.sleep(1)
            after = await c.js(GEOM)
            print("  after nodes:", [(n["id"], n["pos"]) for n in after["ns"]])
            ns = after["ns"]
            moved = [n for n in ns if n["pos"] != next(b for b in before["ns"] if b["id"] == n["id"])["pos"]]
            check(len(moved) >= 6, f"nodes moved ({len(moved)})")
            pairs = [(a["id"], b["id"]) for i, a in enumerate(ns) for b in ns[i + 1:] if overlap(a, b)]
            if pairs:
                print("  overlapping:", pairs, [(n["id"], round(n["x"]), round(n["y"]), round(n["w"]), round(n["h"])) for n in ns])
            check(not pairs, "no overlapping nodes afterwards")
            note_b = next(n for n in before["ns"] if str(n["id"]) == "10")["pos"]
            note_a = next(n for n in ns if str(n["id"]) == "10")["pos"]
            check(note_a == note_b, "the pinned note didn't move")
            by = {int(n["id"]): n for n in ns}
            span_b = max(n["x"] + n["w"] for n in before["ns"]) - min(n["x"] for n in before["ns"])
            span_a = max(n["x"] + n["w"] for n in ns) - min(n["x"] for n in ns)
            check(span_a < span_b * 0.7, f"the spread-out workflow is more compact ({span_b:.0f} -> {span_a:.0f} px wide)")
            g = {x["title"]: x for x in after["gs"]}
            inside = lambda n, gr: n["x"] >= gr["x"] - 1 and n["y"] >= gr["y"] - 1 and n["x"] + n["w"] <= gr["x"] + gr["w"] + 1 and n["y"] + n["h"] <= gr["y"] + gr["h"] + 1
            check(inside(by[1], g["Models"]) and inside(by[2], g["Models"]) and inside(by[3], g["Prompts"]) and inside(by[4], g["Prompts"]), "groups still hold their nodes")
            check(not overlap(g["Models"], g["Prompts"]), "groups don't overlap")
            await c.js("(app.canvas.graph._nodes || app.canvas.graph.nodes).forEach((n) => { n.has_errors = false; }); app.lastNodeErrors = null; [...document.querySelectorAll('[role=alert], [role=alertdialog], [class*=toast], [class*=Toast]'), ...[...document.querySelectorAll('body *')].filter((e) => e.children.length === 0 && /errors found|missing models in this workflow|Tidied/.test(e.textContent))].forEach((e) => { let p = e; while (p && getComputedStyle(p).position !== 'fixed') p = p.parentElement; (p && p !== document.body ? p : (e.matches('[role=alert], [role=alertdialog], [class*=toast], [class*=Toast]') ? e : null))?.style.setProperty('display', 'none', 'important'); }); [...document.querySelectorAll('div,section,aside')].filter((e) => /errors found|missing models in this workflow/.test(e.textContent) && e.offsetWidth > 150 && e.offsetWidth < 520 && e.offsetHeight > 30 && e.offsetHeight < 220).forEach((e) => e.style.setProperty('display', 'none', 'important')); app.canvas.setDirty(true, true); true")
            await asyncio.sleep(0.8)
            shot = await c.call("Page.captureScreenshot", format="png", clip={"x": 60, "y": 110, "width": 1740, "height": 860, "scale": 1})
            open(os.path.join(OUT, "after.png"), "wb").write(base64.b64decode(shot["data"]))
            # undo: one step back
            await c.js("app.extensionManager.workflow.activeWorkflow.changeTracker.undo().then?.(() => true) ?? true")
            await asyncio.sleep(1.5)
            undone = await c.js(GEOM)
            same = all(next(b for b in before["ns"] if b["id"] == n["id"])["pos"] == n["pos"] for n in undone["ns"])
            check(same, "undo puts every node back where it was")
            # tidy again, then again: nothing more to do
            await c.js("app.extensionManager.command.execute('ModelLibrarian.Tidy'); true")
            await asyncio.sleep(0.8)
            r1 = await c.js(GEOM)
            await c.js("app.extensionManager.command.execute('ModelLibrarian.Tidy'); true")
            await asyncio.sleep(0.8)
            r2 = await c.js(GEOM)
            diff = [(a["id"], a["pos"], b["pos"], round(a["w"]), round(a["h"])) for a, b in zip(r1["ns"], r2["ns"]) if a["pos"] != b["pos"]]
            if diff:
                print("  second tidy moved:", diff, "groups:", [(x["title"], round(x["x"]), round(x["y"]), round(x["w"]), round(x["h"])) for x in r1["gs"]], "->", [(round(x["x"]), round(x["y"]), round(x["w"]), round(x["h"])) for x in r2["gs"]])
                print("  run1 boxes:", [(n["id"], round(n["x"]), round(n["y"]), round(n["w"]), round(n["h"])) for n in r1["ns"]])
            check(all(a["pos"] == b["pos"] for a, b in zip(r1["ns"], r2["ns"])), "tidying a tidy workflow changes nothing")
            await c.js(f"app.extensionManager.setting.set('LiteGraph.Canvas.MinFontSizeForLOD', {json.dumps(old_lod)}).then(() => app.extensionManager.setting.set('Comfy.LinkRenderMode', {json.dumps(old_links)})).then(() => true)")
        if not fails:  # crop to the workflow (no zoom controls or stats)
            from PIL import Image
            Image.open(os.path.join(OUT, "before.png")).crop((0, 0, 1580, 760)).save(os.path.join(ARGS.out, "tidy-before.png"), optimize=True)
            Image.open(os.path.join(OUT, "after.png")).crop((0, 0, 1010, 640)).save(os.path.join(ARGS.out, "tidy-after.png"), optimize=True)
            print("wrote tidy-before.png and tidy-after.png to", ARGS.out)
        return 1 if fails else 0
    finally:
        subprocess.run(["powershell", "-NoProfile", "-Command", "Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\" | Where-Object { $_.CommandLine -like '*ml_ext_edge_*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"], capture_output=True)
        time.sleep(1)
        shutil.rmtree(profile, ignore_errors=True)
        shutil.rmtree(OUT, ignore_errors=True)
        print("\nFAILED: %d" % fails if fails else "\nALL PASSED")


sys.exit(asyncio.run(main()))
