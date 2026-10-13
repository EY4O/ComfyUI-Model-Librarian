"""Rebuilds the README screenshots and walkthrough GIFs in docs/images/.

    python tools/readme_media/make_media.py [scene ...]          (scenes: workflow health recipe updates stills)
    python tools/readme_media/make_media.py --backdrop http://127.0.0.1:8188/
    python tools/readme_media/make_media.py --out <dir> --strict    (the UI smoke test: tests/test_ui.py)

The real Model Librarian UI (js/) runs against a scripted fake backend
(ext/scripts/api.js) with abstract sample previews, so nothing from your own
library ends up in the README. Needs Microsoft Edge, Pillow and websockets
(both ship with ComfyUI's venv). --backdrop captures a ComfyUI page to show
behind the window (optional; a dark background is used without it).
"""
import functools
import http.server
import os
import shutil
import subprocess
import sys
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(REPO, "docs", "images")
PORT = 8768


def main():
    args = sys.argv[1:]
    out = OUT
    if "--out" in args:
        i = args.index("--out")
        out = args[i + 1]
        del args[i:i + 2]
    # the UI under test is the repo's own js/
    dst = os.path.join(HERE, "ext", "plugin", "js")
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(os.path.join(REPO, "js"), dst)
    subprocess.run([sys.executable, os.path.join(HERE, "gen_previews.py")], check=True)
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    handler = functools.partial(Quiet, directory=HERE)
    class Server(http.server.ThreadingHTTPServer):
        def handle_error(self, request, client_address):
            pass  # the browser closing mid-request at the end isn't an error
    srv = Server(("127.0.0.1", PORT), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        scenes = []
        if args and args[0] == "--backdrop":
            scenes.append("backdrop=" + args[1])
            args = args[2:]
        scenes += args
        r = subprocess.run([sys.executable, "-u", os.path.join(HERE, "capture.py"), f"http://127.0.0.1:{PORT}", out, *scenes])
        if r.returncode:
            sys.exit(r.returncode)
    finally:
        srv.shutdown()
        shutil.rmtree(os.path.join(HERE, "ext", "plugin"), ignore_errors=True)


if __name__ == "__main__":
    main()
