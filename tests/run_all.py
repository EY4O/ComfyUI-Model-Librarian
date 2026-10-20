"""Run every test suite.

Needs a Python with aiohttp and PyYAML, e.g. a ComfyUI venv:
    <StabilityMatrix>/Data/Packages/ComfyUI/venv/Scripts/python.exe tests/run_all.py
The JavaScript tests need Node 20+ on PATH.
"""
import glob
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8", PYTHONUTF8="1")  # test names use → and ✓
failed = []

for t in sorted(glob.glob(os.path.join(HERE, "test_*.py"))):
    name = os.path.basename(t)
    r = subprocess.run([sys.executable, t], cwd=HERE, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = (r.stdout + r.stderr).strip().splitlines()
    fails = [l for l in lines if l.startswith("FAIL ")]
    print(f"{'ok  ' if r.returncode == 0 else 'FAIL'} {name}: "
          f"{sum(l.startswith('PASS') for l in lines)} passed, {len(fails)} failed")
    for l in fails + ([l for l in lines[-15:] if "Error" in l or "Traceback" in l] if r.returncode else []):
        print("     ", l)
    if r.returncode and os.environ.get("CI"):  # GitHub: the whole output, to see why
        for l in lines[-60:]:
            print("      |", l)
    if r.returncode:
        failed.append(name)

node = shutil.which("node")
for t in sorted(glob.glob(os.path.join(HERE, "test_*.mjs"))):
    name = os.path.basename(t)
    if not node:
        print(f"skip {name}: node not found")
        continue
    r = subprocess.run([node, t], cwd=HERE, capture_output=True, text=True, encoding="utf-8", errors="replace")
    lines = (r.stdout + r.stderr).strip().splitlines()
    fails = [l for l in lines if l.startswith("FAIL ")]
    print(f"{'ok  ' if r.returncode == 0 else 'FAIL'} {name}: "
          f"{sum(l.startswith('PASS') for l in lines)} passed, {len(fails)} failed")
    for l in fails + (lines[-10:] if r.returncode and not fails else []):
        print("     ", l)
    if r.returncode:
        failed.append(name)

print("\nALL SUITES PASSED" if not failed else f"\nFAILED: {', '.join(failed)}")
sys.exit(1 if failed else 0)
