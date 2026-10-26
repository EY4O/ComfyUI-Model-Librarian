"""Drives headless Edge over the DevTools protocol through demo scenes and writes
README screenshots (PNG) and walkthrough GIFs.

    python capture.py <base url> <out dir> [scene ...]
    MEDIA_SCALE=2 python capture.py ...   (stills at twice the pixels; GIFs keep their width)
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
SCALE = float(os.environ.get("MEDIA_SCALE", "1"))  # 2 for crisp copies on high-density screens (the site); the README keeps 1
GIF_W = 1024  # GIFs are scaled to this width


def free_port() -> int:
    import socket
    with socket.socket() as sk:
        sk.bind(("127.0.0.1", 0))
        return sk.getsockname()[1]


class Browser:
    async def start(self):
        self.prof = tempfile.mkdtemp(prefix="smf-cdp-")
        self.port = port = free_port()
        self.proc = subprocess.Popen([EDGE, "--headless=new", f"--remote-debugging-port={port}", f"--user-data-dir={self.prof}",
                                      f"--window-size={W},{H}", "--hide-scrollbars", f"--force-device-scale-factor={SCALE:g}",
                                      "--disable-gpu", "--no-first-run", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        page = None
        for _ in range(150):
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                page = next(t for t in tabs if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.2)
        if not page:
            self.kill()
            raise RuntimeError("Edge didn't start its DevTools endpoint")
        self.ws = await websockets.connect(page["webSocketDebuggerUrl"], max_size=64 * 1024 * 1024)
        self.n = 0
        await self.send("Page.enable")
        await self.send("Runtime.enable")
        await self.send("Emulation.setDeviceMetricsOverride", {"width": W, "height": H, "deviceScaleFactor": SCALE, "mobile": False})

    async def send(self, method, params=None, timeout=45):
        self.n += 1
        mid = self.n
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))

        async def answer():
            while True:
                msg = json.loads(await self.ws.recv())
                if msg.get("id") == mid:
                    return msg
        try:
            msg = await asyncio.wait_for(answer(), timeout)
        except asyncio.TimeoutError:
            raise RuntimeError(f"{method}: no answer from the browser in {timeout}s")
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    async def js(self, code):
        r = await self.send("Runtime.evaluate", {"expression": f"(async () => {{ {code} }})()", "awaitPromise": True, "returnByValue": True})
        if r.get("exceptionDetails"):
            raise RuntimeError(f"JS error in {code[:80]!r}: {r['exceptionDetails'].get('exception', {}).get('description') or r['exceptionDetails']}")
        return r.get("result", {}).get("value")

    async def goto(self, url):
        # mark the current page, so we wait for the new one rather than see the old one as ready
        try:
            await self.js("window.__leaving = true; return true")
        except RuntimeError:
            pass
        self.nav = getattr(self, "nav", 0) + 1
        if "index.html" in url:  # a new URL each time: re-navigating to the same one can wedge headless screenshots
            url += ("&" if "?" in url else "?") + f"n={self.nav}"
        await self.send("Page.navigate", {"url": url})
        for _ in range(300):
            await asyncio.sleep(0.1)
            try:
                if await self.js("return !window.__leaving && document.readyState === 'complete' && (window.ready === true || !location.href.includes('index.html'))"):
                    return
            except RuntimeError:
                pass
        raise RuntimeError(f"page didn't load: {url}")

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

    def kill(self):
        # the whole tree: Edge's renderer processes would otherwise outlive it
        if sys.platform == "win32":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.proc.pid)], capture_output=True)
        else:
            self.proc.kill()

    async def close(self):
        try:
            await self.ws.close()
        except Exception:
            pass
        self.kill()


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
    # Share…: a download link for every model, to embed or post
    await b.js(f"""document.getElementById('demo-cursor').style.display = 'none';
      document.getElementById('demo-caption').style.display = 'none'; demo.click({B}('button', 'Share')); return true""")
    await b.wait_for("document.querySelector('.smf-share-card table')")
    await asyncio.sleep(0.3)
    (await b.shot()).save(os.path.join(out, "share.png"))


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
    # most used first, then a model's details with your rating, tags and notes
    await b.js("""document.querySelector('.smf-hf-pop')?.remove();
      const sel = [...document.querySelectorAll('select.smf-select')].find((x) => x.title === 'Sort');
      sel.value = 'used'; sel.dispatchEvent(new Event('change')); return true""")
    await asyncio.sleep(0.5)
    await b.images_loaded()
    await b.js("document.querySelector('.smf-card').click(); return true")
    await asyncio.sleep(0.6)
    (await b.shot()).save(os.path.join(out, "notes.png"))
    # a diffusion model's details: how it fits this GPU and what it also needs
    await b.js("""document.querySelector('.smf-hf-pop')?.remove();
      [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === 'Diffusion models').click(); return true""")
    await b.wait_for("document.querySelector('.smf-card')")
    await asyncio.sleep(0.4)
    await b.js("document.querySelector('.smf-card').click(); return true")
    await b.wait_for("document.querySelector('.smf-fitbox .smf-fit')", 15)
    await asyncio.sleep(0.3)
    (await b.shot()).save(os.path.join(out, "fit.png"))
    await b.js("""document.querySelector('.smf-hf-pop')?.remove();
      [...document.querySelectorAll('button')].find((x) => x.textContent.trim() === 'LoRAs').click(); return true""")
    await b.wait_for("document.querySelector('.smf-card')")
    await asyncio.sleep(0.4)
    # a model removed from CivitAI: marked, and CivArchive's copies one click away
    await b.js("""document.querySelector('.smf-hf-pop')?.remove();
      const card = [...document.querySelectorAll('.smf-card')].find((c) => c.querySelector('.smf-chip.gone'));
      card.click(); return true""")
    await asyncio.sleep(0.4)
    await b.js(f"demo.click({B}('button', 'Find copies on CivArchive')); return true")
    await b.wait_for(f"{B}('a', 'Open on CivArchive')")
    await asyncio.sleep(0.3)
    (await b.shot()).save(os.path.join(out, "removed.png"))
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
    print("  stills: library, huggingface, notes, fit, removed, organize, storage")


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


# (a scene of its own: long headless sessions can wedge screenshots)
async def scene_more(b, base, out):
    # an update next to the version you have
    await b.goto(f"{base}/index.html?tab=library")
    await b.js("document.getElementById('demo-cursor').style.display = 'none'; return true")
    await b.wait_for("document.querySelector('.smf-chip.upd')")
    await b.js("document.querySelector('.smf-chip.upd').click(); return true")
    await b.wait_for("document.querySelector('.smf-cmp img')")
    await asyncio.sleep(0.6)
    await b.images_loaded()
    (await b.shot()).save(os.path.join(out, "compare.png"))
    # free space over time
    await b.goto(f"{base}/index.html?tab=storage")
    await b.js("document.getElementById('demo-cursor').style.display = 'none'; return true")
    await b.wait_for("document.querySelector('.smf-viz svg')")
    await b.js("document.querySelector('.smf-history').scrollIntoView(); return true")
    await asyncio.sleep(0.4)
    (await b.shot()).save(os.path.join(out, "history.png"))
    # a recipe's LoRA you have under another name: pick it
    await b.goto(f"{base}/index.html?tab=recipes")
    await b.js("document.getElementById('demo-cursor').style.display = 'none'; return demo.dropImage()")
    last = "[...document.querySelectorAll('.smf-table tr')].find((r) => r.textContent.includes('InkWashPDXL'))"
    await b.wait_for(last)
    await b.js(f"demo.click([...{last}.querySelectorAll('button')].find((x) => x.textContent.includes('Use my file'))); return true")
    await b.wait_for(f"{B}('button', 'ink_wash')")
    await b.js("document.querySelector('.smf-table tr:last-child')?.scrollIntoView({block: 'center'}); return true")
    await asyncio.sleep(0.3)
    (await b.shot()).save(os.path.join(out, "recipe-link.png"))
    print("  stills: compare, history, recipe-link")


async def scene_archive(b, base, out):
    # a folder of images archived: prompt families with their thumbnails
    await b.goto(f"{base}/index.html?tab=archive")
    await b.js("document.getElementById('demo-cursor').style.display = 'none'; return true")
    await b.wait_for("document.querySelector('input[list=smf-archive-recent]')")
    await b.js("""const i = document.querySelector('input[list=smf-archive-recent]');
      i.value = 'E:\\\\StabilityMatrix\\\\Data\\\\Images\\\\Text2Img'; i.dispatchEvent(new Event('input'));
      [...document.querySelectorAll('button')].find((x) => x.textContent.includes('Archive this folder')).click(); return true""")
    await b.wait_for("document.querySelector('.smf-archive-grid img')", 30)
    await asyncio.sleep(0.6)
    await b.images_loaded()
    (await b.shot()).save(os.path.join(out, "archive.png"))
    # then: move the originals to the archive drive (checked first)
    await b.js("""[...document.querySelectorAll('button')].find((x) => x.textContent.includes('Move the originals')).click();
      const box = document.querySelector('.smf-archive-move'); box.scrollIntoView({ block: 'start' }); return true""")
    await b.wait_for("document.querySelector('.smf-archive-movebox input')")
    await b.js("""[...document.querySelectorAll('.smf-archive-movebox button')].find((x) => x.textContent === 'Check').click(); return true""")
    await b.wait_for("document.querySelector('.smf-archive-plan')")
    await b.js("document.querySelector('.smf-archive-plan').scrollIntoView({ block: 'end' }); return true")
    await asyncio.sleep(0.3)
    (await b.shot()).save(os.path.join(out, "archive-move.png"))
    # a thumbnail opens as a recipe (smoke check, no still)
    await b.js("document.querySelector('.smf-archive-grid img').click(); return true")
    await b.wait_for("[...document.querySelectorAll('.smf-tab.sel')].some((t) => t.textContent === 'Recipes') && document.querySelector('.smf-body').textContent.includes('crashing waves, seagulls')", 20)
    print("  stills: archive, archive-move")


SCENES = {"workflow": scene_workflow, "health": scene_health, "recipe": scene_recipe, "updates": scene_updates, "stills": scene_stills,
          "more": scene_more, "archive": scene_archive}


async def main():
    base, out = sys.argv[1], sys.argv[2]
    names = sys.argv[3:]
    strict = "--strict" in names  # fail on page errors (the UI smoke test)
    names = [n for n in names if n != "--strict"] or list(SCENES)
    failed = []
    os.makedirs(out, exist_ok=True)
    for n in names:
        # a fresh browser per scene: long sessions can wedge headless screenshots
        b = Browser()
        await b.start()
        try:
            if n.startswith("backdrop="):
                await backdrop(b, n.split("=", 1)[1], os.path.join(os.path.dirname(os.path.abspath(__file__)), "backdrop.png"))
                continue
            print(n)
            await SCENES[n](b, base, out)
            errs = await b.js("return window.errs || []")
            if errs:
                print("  page errors:", errs)
                failed.append(n)
        except Exception as ex:
            print(f"  scene failed: {ex}")
            failed.append(n)
        finally:
            await b.close()
    if strict and failed:
        sys.exit(f"UI errors in: {', '.join(failed)}")
    if failed and not strict:
        print("  (errors above; run with --strict to fail)")


if __name__ == "__main__":
    asyncio.run(main())
