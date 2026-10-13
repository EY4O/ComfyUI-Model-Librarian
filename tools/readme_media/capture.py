"""Drives headless Edge over the DevTools protocol through demo scenes and writes
README screenshots (PNG) and walkthrough GIFs.

    python capture.py <base url> <out dir> [scene ...]
"""
import asyncio
import base64
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

import websockets
from PIL import Image

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
W, H = 1280, 800
GIF_W = 1024  # GIFs are scaled to this width
PORT = 9334


class Browser:
    async def start(self):
        self.prof = tempfile.mkdtemp(prefix="smf-cdp-")
        self.proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={PORT}", f"--user-data-dir={self.prof}",
                                      f"--window-size={W},{H}", "--hide-scrollbars", "--force-device-scale-factor=1",
                                      "--disable-gpu", "--no-first-run", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        self.ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024)
        self.n = 0
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send("Emulation.setDeviceMetricsOverride", {"width": W, "height": H, "deviceScaleFactor": 1, "mobile": False})

    async def send(self, method, params=None):
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(await self.ws.recv())
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    async def js(self, code):
        r = await self.send("Runtime.evaluate", {"expression": f"(async () => {{ {code} }})()", "awaitPromise": True, "returnByValue": True})
        if r.get("exceptionDetails"):
            raise RuntimeError(f"JS error in {code[:80]!r}: {r['exceptionDetails'].get('exception', {}).get('description') or r['exceptionDetails']}")
        return r.get("result", {}).get("value")

    async def goto(self, url):
        await self.send("Page.navigate", {"url": url})
        for _ in range(150):
            await asyncio.sleep(0.1)
            try:
                if await self.js("return document.readyState === 'complete' && (window.ready === true || !location.href.includes('index.html'))"):
                    return
            except RuntimeError:
                pass

    async def wait_for(self, expr, timeout=15):
        for _ in range(int(timeout * 10)):
            try:
                if await self.js(f"return !!({expr})"):
                    return True
            except RuntimeError:
                pass
            await asyncio.sleep(0.1)
        raise RuntimeError(f"timed out waiting for {expr}")

    async def images_loaded(self):
        await self.js("for (let i = 0; i < 60 && [...document.images].some((im) => !im.complete); i++) await demo.sleep(100); return true")

    async def shot(self):
        r = await self.send("Page.captureScreenshot", {"format": "png"})
        return Image.open(io.BytesIO(base64.b64decode(r["data"]))).convert("RGB")

    async def close(self):
        await self.ws.close()
        self.proc.terminate()


class Recorder:
    def __init__(self, b):
        self.b, self.frames = b, []

    async def frame(self, ms):
        img = await self.b.shot()
        self.frames.append([img, ms])

    async def frames_for(self, total_ms, step_ms=220):
        t = 0
        while t < total_ms:
            start = time.time()
            await self.frame(step_ms)
            spent = (time.time() - start) * 1000
            if spent < step_ms:
                await asyncio.sleep((step_ms - spent) / 1000)
            t += step_ms

    async def move(self, expr, settle=640):

        await self.b.js(f"return demo.move({expr})")
        await self.frames_for(settle, 160)

    async def click(self, expr, after=600):

        await self.b.js(f"return demo.click({expr})")
        await self.frames_for(after, 200)

    async def caption(self, text):
        await self.b.js(f"return demo.caption({json.dumps(text)})")

    def save_gif(self, path):
        # merge identical neighbours, scale, one adaptive palette per frame
        merged = []
        for img, ms in self.frames:
            if merged and merged[-1][0].tobytes() == img.tobytes():
                merged[-1][1] += ms
            else:
                merged.append([img, ms])
        h = round(H * GIF_W / W)
        pal = [im.resize((GIF_W, h), Image.LANCZOS).quantize(colors=192, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for im, _ in merged]
        pal[0].save(path, save_all=True, append_images=pal[1:], duration=[max(60, int(ms)) for _, ms in merged], loop=0, optimize=True, disposal=1)
        print(f"  {os.path.basename(path)}: {len(merged)} frames, {os.path.getsize(path) / 1e6:.1f} MB")


B = "demo.find"


async def scene_workflow(b, base, out):
    r = Recorder(b)
    await b.goto(f"{base}/index.html?tab=workflow")
    await asyncio.sleep(1.2)
    await r.caption("A workflow needs models you don't have")
    await r.frame(1800)
    await r.move(f"{B}('button', 'Find all sources')")
    await r.click(f"{B}('button', 'Find all sources')", 200)
    await r.caption("Find all sources: your registry, ComfyUI-Manager, HuggingFace, CivitAI")
    await r.frames_for(2600, 260)
    (await b.shot()).save(os.path.join(out, "workflow.png"))
    await r.frame(1200)
    await r.move(f"{B}('button', 'Download all')")
    await r.click(f"{B}('button', 'Download all')", 200)
    await r.caption("SHA256-verified downloads into Stability Matrix's shared folders")
    await r.frames_for(5200, 320)
    await r.caption("A model that was moved is repointed in one click")
    await r.move(f"{B}('button', 'Fix moved paths')")
    await r.click(f"{B}('button', 'Fix moved paths')", 1600)
    await r.caption("Everything the workflow needs is in place")
    await r.frame(2400)
    r.save_gif(os.path.join(out, "missing-models.gif"))


async def scene_health(b, base, out):
    r = Recorder(b)
    await b.goto(f"{base}/index.html?tab=workflow")
    await asyncio.sleep(1.0)
    await r.caption("Check every saved workflow at once")
    await r.frame(900)
    await r.move(f"{B}('.smf-scope button', 'All saved workflows')")
    await r.click(f"{B}('.smf-scope button', 'All saved workflows')", 1400)
    (await b.shot()).save(os.path.join(out, "health.png"))
    await r.frame(1600)
    await r.caption("Pick a workflow to see what it's missing")
    await r.move(f"{B}('.smf-wfrow a', 'Qwen Image edit')")
    await r.click(f"{B}('.smf-wfrow a', 'Qwen Image edit')", 1200)
    await r.move(f"{B}('button', 'Find all sources')")
    await r.click(f"{B}('button', 'Find all sources')", 200)
    await r.frames_for(1800, 260)
    await r.caption("Download them under the names the workflow uses — no edits needed")
    await r.move(f"{B}('button', 'Download all')")
    await r.click(f"{B}('button', 'Download all')", 200)
    await r.frames_for(5600, 320)
    await r.move(f"{B}('button', 'Show all')")
    await r.click(f"{B}('button', 'Show all')", 1200)
    await r.caption("Moved models are repointed in the saved files (backed up first)")
    await r.move(f"{B}('button', 'Fix moved paths')")
    await r.click(f"{B}('button', 'Fix moved paths')", 2200)
    await r.frame(1800)
    r.save_gif(os.path.join(out, "saved-workflows.gif"))


async def scene_recipe(b, base, out):
    r = Recorder(b)
    await b.goto(f"{base}/index.html?tab=recipes")
    await asyncio.sleep(1.2)
    await r.caption("Drop any AI image — ComfyUI, A1111, CivitAI, NovelAI…")
    await r.frame(1800)
    await b.js("return demo.dropImage()")
    await r.frames_for(1600, 240)
    await r.caption("Its prompt, settings and every model it used, with strengths")
    await r.frame(2000)
    (await b.shot()).save(os.path.join(out, "recipes.png"))
    await r.move(f"{B}('button', 'Save recipe')")
    await r.click(f"{B}('button', 'Save recipe')", 200)
    await r.caption("Saved, and the two missing models download to the right folders")
    await r.frames_for(5400, 320)
    await r.caption("Then fill your workflow with it, or open it as a new one")
    await r.move(f"{B}('button', 'Fill current workflow')")
    await r.frame(1400)
    await r.move(f"{B}('button', 'Open as new workflow')")
    await r.frame(1200)
    await r.move(f"{B}('button', '← Back to recipes')")
    await r.click(f"{B}('button', '← Back to recipes')", 1000)
    await r.caption("Your recipe library, shared by every ComfyUI in Stability Matrix")
    await r.frame(2400)
    r.save_gif(os.path.join(out, "recipe.gif"))


async def scene_updates(b, base, out):
    r = Recorder(b)
    await b.goto(f"{base}/index.html?tab=library")
    await asyncio.sleep(1.0)
    await r.move(f"{B}('.smf-subtab', 'Checkpoints')")
    await r.click(f"{B}('.smf-subtab', 'Checkpoints')", 1200)
    await r.caption("A daily check finds newer CivitAI versions — same base model, same variant")
    await r.frame(2000)
    await r.move(f"{B}('label.smf-check', 'Updates only')", 0.2)
    await r.click(f"{B}('label.smf-check', 'Updates only').querySelector('input')", 1000)
    await r.move(f"{B}('button', 'Download all updates')")
    await r.click(f"{B}('button', 'Download all updates')", 400)
    await r.caption("The new versions download next to the old ones")
    await r.frames_for(6200, 320)
    await r.caption("Then the old versions can move to the archive drive")
    await r.frame(1600)
    await r.move(f"{B}('button', 'Archive old versions')")
    await r.click(f"{B}('button', 'Archive old versions')", 1400)
    await r.move(f"{B}('label.smf-check', 'Updates only')", 0.2)
    await r.click(f"{B}('label.smf-check', 'Updates only').querySelector('input')", 600)
    await r.move(f"{B}('button', 'Reload')")
    await r.click(f"{B}('button', 'Reload')", 1200)
    await r.caption("New versions on the SSD, the old ones on the HDD — still usable")
    await r.frame(2600)
    r.save_gif(os.path.join(out, "updates.gif"))


async def scene_stills(b, base, out):
    await b.goto(f"{base}/index.html?tab=library")
    await b.js("document.getElementById('demo-cursor').style.display = 'none'; return true")
    await b.wait_for("document.querySelector('.smf-card img')")
    await b.js("document.querySelectorAll('img[loading=lazy]').forEach((im) => (im.loading = 'eager')); return true")
    await asyncio.sleep(0.6)
    await b.images_loaded()
    (await b.shot()).save(os.path.join(out, "library.png"))
    await b.js(f"demo.click({B}('.smf-chip.hf')); return true")
    await asyncio.sleep(0.8)
    (await b.shot()).save(os.path.join(out, "huggingface.png"))
    await b.goto(f"{base}/index.html?tab=organize")
    await b.js("document.getElementById('demo-cursor').style.display = 'none'; return true")
    await b.wait_for(f"{B}('button', 'Build plan')")
    await b.js(f"demo.click({B}('button', 'Build plan')); return true")
    await b.wait_for("document.querySelector('table.plan')")
    await asyncio.sleep(0.3)
    (await b.shot()).save(os.path.join(out, "organize.png"))
    await b.goto(f"{base}/index.html?tab=storage")
    await b.js("document.getElementById('demo-cursor').style.display = 'none'; return true")
    await b.wait_for("document.querySelector('.smf-table')")
    await asyncio.sleep(0.3)
    (await b.shot()).save(os.path.join(out, "storage.png"))
    print("  stills: library, huggingface, organize, storage")


async def backdrop(b, comfy, out):
    await b.goto(comfy)
    await b.wait_for("window.app && window.app.graph && document.querySelector('canvas') && window.app.graph._nodes.length", 120)
    await asyncio.sleep(4)
    await b.js("""
      document.querySelectorAll('.p-toast-close-button, .p-toast-icon-close, .p-dialog-close-button, .smf-notice-x').forEach((x) => x.click());
      document.querySelectorAll('.p-toast, .smf-notice').forEach((x) => x.remove());
      window.app.canvas.ds.scale = 0.8; window.app.canvas.ds.offset = [-250, -60]; window.app.canvas.setDirty(true, true);
      return true""")
    await asyncio.sleep(1.5)
    (await b.shot()).save(out)
    print("  backdrop from", comfy)


SCENES = {"workflow": scene_workflow, "health": scene_health, "recipe": scene_recipe, "updates": scene_updates, "stills": scene_stills}


async def main():
    base, out = sys.argv[1], sys.argv[2]
    names = sys.argv[3:] or list(SCENES)
    os.makedirs(out, exist_ok=True)
    b = Browser()
    await b.start()
    try:
        for n in names:
            if n.startswith("backdrop="):
                await backdrop(b, n.split("=", 1)[1], os.path.join(os.path.dirname(os.path.abspath(__file__)), "backdrop.png"))
                continue
            print(n)
            await SCENES[n](b, base, out)
            errs = await b.js("return window.errs || []")
            if errs:
                print("  page errors:", errs)
    finally:
        await b.close()


if __name__ == "__main__":
    asyncio.run(main())
