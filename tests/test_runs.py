"""Recipes from what a run made (smf/runs.py): ComfyUI's run history, image paths kept inside its folders,
a recipe from the image's data or (saved without it) from the run itself, and a kept full-size copy."""
import asyncio
import io
import json
import os
import sys
import types

import test_shared as T

check = T.check

PROMPT = {
    "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "base_model.safetensors"}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": "a lighthouse at dusk, paper cut"}},
    "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["1", 1], "text": "blurry"}},
    "4": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
    "5": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0],
                                               "seed": 1234, "steps": 24, "cfg": 5.5, "sampler_name": "euler", "scheduler": "normal", "denoise": 1}},
    "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
    "7": {"class_type": "SaveImage", "inputs": {"images": ["6", 0], "filename_prefix": "run"}},
}
WORKFLOW = {"id": "wf-1111", "nodes": [{"id": 7, "type": "SaveImage"}], "links": [], "version": 0.4}


def png(text=None, color=(40, 90, 160)):
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    info = PngInfo()
    for k, v in (text or {}).items():
        info.add_text(k, v)
    buf = io.BytesIO()
    Image.new("RGB", (64, 96), color).save(buf, "PNG", pnginfo=info)
    return buf.getvalue()


def entry(pid, wf_id, node, files, prompt=PROMPT):
    wf = dict(WORKFLOW, id=wf_id)
    return {"prompt": (1, pid, prompt, {"extra_pnginfo": {"workflow": wf}}, [node]),
            "outputs": {node: {"images": [{"filename": f, "subfolder": "", "type": "output"} for f in files]}},
            "status": {"messages": [["execution_start", {"prompt_id": pid, "timestamp": 1792000000000}]]},
            "meta": {node: {"display_node": node}}}


def main():
    base, user = T.fake_install("Runs")
    os.makedirs(T.LORA, exist_ok=True)
    smf = T.load_smf(base, user)
    out_dir = os.path.join(base, "output")
    tmp_dir = os.path.join(base, "temp")
    for d in (out_dir, tmp_dir):
        os.makedirs(d, exist_ok=True)
    fp = sys.modules["folder_paths"]
    fp.get_output_directory = lambda: out_dir
    fp.get_temp_directory = lambda: tmp_dir
    fp.get_input_directory = lambda: os.path.join(base, "input")

    # a fake ComfyUI run history: three runs, oldest first
    history = {
        "p1": entry("p1", "wf-1111", "7", ["old_00001_.png"]),
        "p2": entry("p2", "wf-2222", "9", ["other_00001_.png"]),
        "p3": entry("p3", "wf-1111", "7", ["run_00001_.png", "run_00002_.png"]),
    }

    class Queue:
        def get_history(self, prompt_id=None, max_items=None, offset=-1, map_function=None):
            return {prompt_id: history[prompt_id]} if prompt_id else dict(history) if prompt_id is None else {}
    server = types.ModuleType("server")
    server.PromptServer = types.SimpleNamespace(instance=types.SimpleNamespace(prompt_queue=Queue()))
    sys.modules["server"] = server

    async def no_resolve(*a, **k):
        return []
    smf.sources.resolve = no_resolve

    async def no_json(*a, **k):
        return None
    smf.net.get_json = no_json
    runs = smf.runs

    imgs = runs.recent_images("wf-1111")
    check([i["filename"] for i in imgs] == ["run_00001_.png", "run_00002_.png", "old_00001_.png"] and imgs[0]["prompt_id"] == "p3",
          "recent images: this workflow's runs only, newest first")
    check([i["filename"] for i in runs.recent_images(node="9")] == ["other_00001_.png"], "  or one output node's")
    check(len(runs.recent_images("wf-1111", limit=1)) == 1 and runs.recent_images("nope") == [], "  limited; none for an unknown workflow")

    check(runs.image_path({"filename": "a.png", "subfolder": "x", "type": "temp"}) == os.path.join(os.path.abspath(tmp_dir), "x", "a.png"), "image path: in the temp folder")
    for bad in ({"filename": "../a.png"}, {"filename": "a.png", "subfolder": "../.."}, {"filename": "a.png", "type": "models"}, {"filename": ""}):
        try:
            runs.image_path(bad)
            check(False, f"image path refused: {bad}")
        except ValueError:
            check(True, f"image path refused: {bad}")

    # an image with ComfyUI's data in it
    open(os.path.join(out_dir, "run_00001_.png"), "wb").write(png({"prompt": json.dumps(PROMPT), "workflow": json.dumps(WORKFLOW)}))
    a = asyncio.run(runs.recipe_for({"filename": "run_00001_.png", "subfolder": "", "type": "output"}, "p3"))
    rec = a["recipe"]
    check(rec["prompt"]["positive"] == "a lighthouse at dusk, paper cut" and rec["settings"]["seed"] == 1234 and rec["settings"]["steps"] == 24,
          "recipe from the image's own data: prompt and settings")
    check(rec["comfy"].get("workflow", {}).get("id") == "wf-1111" and rec["source"]["output"] == {"filename": "run_00001_.png", "subfolder": "", "type": "output"},
          "  with the workflow and where the image is")
    check((a["thumb"] or "").startswith("data:image/webp") and any(i["kind"] == "checkpoint" for i in a["items"]), "  a thumbnail and the models it needs")

    # saved without any data: the run's own prompt, found by the file name
    open(os.path.join(out_dir, "run_00002_.png"), "wb").write(png())
    b = asyncio.run(runs.recipe_for({"filename": "run_00002_.png", "subfolder": "", "type": "output"}))
    check(b["recipe"]["prompt"]["positive"] == "a lighthouse at dusk, paper cut" and b["recipe"]["comfy"]["prompt"]["5"]["inputs"]["seed"] == 1234,
          "no data in the image: read from the run that made it")
    open(os.path.join(out_dir, "stray.png"), "wb").write(png())
    for item, why in (({"filename": "stray.png"}, "no data and no run"), ({"filename": "gone.png"}, "the image is gone")):
        try:
            asyncio.run(runs.recipe_for(item))
            check(False, f"says why: {why}")
        except ValueError as ex:
            check(bool(str(ex)), f"says why: {why} ({ex})")

    # saving: a full-size copy when asked; the full image link
    st = smf.recipe_store
    saved = st.save(rec, a["thumb"])
    check(st.image_path(saved["id"]) == os.path.join(os.path.abspath(out_dir), "run_00001_.png"), "saved: its full image is the output it came from")
    check(st.summary(st.get(saved["id"]))["has_image"], "  (the list knows there is one)")
    name = st.keep_image(saved["id"], runs.image_path(rec["source"]["output"]))
    check(name == saved["id"] + ".png" and st.image_path(saved["id"]) == os.path.join(st.folder(), name), "keep a full-size copy: kept next to the recipe")
    os.remove(os.path.join(out_dir, "run_00001_.png"))
    check(st.image_path(saved["id"]) == os.path.join(st.folder(), name), "  still there when the output is deleted")
    linked = st.save(b["recipe"], b["thumb"])
    os.remove(os.path.join(out_dir, "run_00002_.png"))
    check(st.image_path(linked["id"]) is None, "a linked image that was deleted: none")
    st.delete(saved["id"])
    check(os.path.isfile(os.path.join(st.folder(), "_deleted", name)) and not os.path.isfile(os.path.join(st.folder(), name)), "deleting moves the kept copy with it")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
