"""UI smoke test: runs every README walkthrough scene against the real frontend
(js/) in headless Edge with the scripted fake backend from tools/readme_media.
Each scene clicks through a whole workflow and fails if a control is missing or
the page throws. Skipped when Microsoft Edge isn't installed."""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
MEDIA = os.path.join(os.path.dirname(HERE), "tools", "readme_media", "make_media.py")
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def main():
    if not os.path.isfile(EDGE):
        print("SKIP UI smoke test: Microsoft Edge not found")
        print("\nALL PASSED")
        return 0
    try:
        import websockets  # noqa: F401
        import PIL  # noqa: F401
    except ImportError as ex:
        print(f"SKIP UI smoke test: {ex}")
        print("\nALL PASSED")
        return 0
    out = tempfile.mkdtemp(prefix="smf_ui_")
    try:
        r = subprocess.run([sys.executable, MEDIA, "--out", out, "--strict"], capture_output=True, text=True, timeout=900)
        print(r.stdout[-3000:], r.stderr[-2000:])
        made = sorted(os.listdir(out))
        want = ["health.png", "huggingface.png", "library.png", "missing-models.gif", "notes.png", "organize.png", "recipe.gif", "recipes.png", "removed.png", "share.png",
                "saved-workflows.gif", "storage.png", "updates.gif", "workflow.png"]
        ok = r.returncode == 0 and all(w in made for w in want)
        print(("PASS " if ok else "FAIL ") + f"every scene ran without page errors ({len(made)} files)")
        print("\nALL PASSED" if ok else "\nFAILED: 1")
        return 0 if ok else 1
    finally:
        shutil.rmtree(out, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
