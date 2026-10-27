"""tools/install.py keeps only the newest backups of each install, and leaves other folders in backups/ alone."""
import importlib.util
import os
import sys
import tempfile

import test_shared as T

check = T.check

spec = importlib.util.spec_from_file_location("ml_install", os.path.join(T.PLUGIN, "tools", "install.py"))
inst = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inst)
inst.REPO = tempfile.mkdtemp(prefix="smf_install_")
root = os.path.join(inst.REPO, "backups")

check(inst.prune_backups("ComfyUI") == 0, "no backups folder: nothing to do")

names = [f"ComfyUI-202610{d:02d}-120000" for d in range(10, 18)]  # 8, oldest first
names += ["ComfyUI-20261017-120000-2", "Latest-ComfyUI-20261001-090000", "desktop-install-before-update",
          "ComfyUI-Qwen-20261001-090000"]
for n in names:
    os.makedirs(os.path.join(root, n))
with open(os.path.join(root, "ComfyUI-20261001-000000"), "w") as f:  # a file, not a backup folder
    f.write("x")

removed = inst.prune_backups("ComfyUI", keep=3)
left = sorted(os.listdir(root))
check(removed == 6, f"removed the 6 older ComfyUI backups ({removed})")
check({"ComfyUI-20261017-120000-2", "ComfyUI-20261017-120000", "ComfyUI-20261016-120000"} <= set(left),
      "the newest 3 kept, a same-second -2 counted as newer")
check("ComfyUI-20261015-120000" not in left, "older ones removed")
check({"Latest-ComfyUI-20261001-090000", "desktop-install-before-update", "ComfyUI-Qwen-20261001-090000",
       "ComfyUI-20261001-000000"} <= set(left), "other installs' backups, hand-made folders and files left alone")
check(inst.prune_backups("ComfyUI", keep=3) == 0, "running it again removes nothing")

print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
sys.exit(1 if check.failed else 0)
