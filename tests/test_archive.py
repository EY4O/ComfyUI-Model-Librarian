"""Archive: a folder of generated images -> grouped report, CSV, recipes, per-variant workflows and
WebP thumbnails that carry their own workflow. All images are made here (never real outputs)."""
import csv
import io
import json
import os
import shutil
import tempfile
import time

import test_shared as T

check = T.check


def graph(prompt, seed, ckpt="Illustrious\\aurora_v4.safetensors", lora=0.8, neg="blurry, lowres"):
    return {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "LoraLoader", "inputs": {"model": ["1", 0], "clip": ["1", 1], "lora_name": "paper_cut.safetensors",
                                                     "strength_model": lora, "strength_clip": lora}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": prompt}},
        "4": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 1], "text": neg}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": 832, "height": 1216, "batch_size": 1}},
        "6": {"class_type": "KSampler", "inputs": {"model": ["2", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["5", 0],
                                                   "seed": seed, "steps": 28, "cfg": 5, "sampler_name": "euler_ancestral", "scheduler": "normal", "denoise": 1.0}},
    }


def ui_workflow(prompt, seed):
    return {"last_node_id": 6, "nodes": [
        {"id": 3, "type": "CLIPTextEncode", "widgets_values": [prompt], "inputs": []},
        {"id": 6, "type": "KSampler", "widgets_values": [seed, "fixed", 28, 5, "euler_ancestral", "normal", 1], "inputs": []}], "links": []}


def make_png(path, prompt, seed, color, **kw):
    from PIL import Image
    from PIL.PngImagePlugin import PngInfo
    info = PngInfo()
    info.add_text("prompt", json.dumps(graph(prompt, seed, **kw)))
    info.add_text("workflow", json.dumps(ui_workflow(prompt, seed)))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (1024, 1536), color).save(path, pnginfo=info)


def make_a1111_jpeg(path):
    from PIL import Image
    ex = Image.Exif()
    text = ("a red fox in snow, winter forest\nNegative prompt: lowres\nSteps: 20, Sampler: DPM++ 2M Karras, CFG scale: 6, "
            "Seed: 42, Size: 768x768, Model hash: 1a2b3c4d5e, Model: dreamshaper_8")
    ex.get_ifd(0x8769)[0x9286] = b"UNICODE\0" + text.encode("utf-16-be")
    Image.new("RGB", (768, 768), (200, 60, 30)).save(path, "JPEG", exif=ex.tobytes())


def main():
    base, user = T.fake_install("ARCHIVE")
    smf = T.load_smf(base, user)
    ar = smf.archive
    root = tempfile.mkdtemp(prefix="smf_archive_")
    try:
        P1 = "1girl, red dress, standing in the rain, city at night, neon lights"
        P2 = "1girl, red dress, standing in the rain, forest, neon lights, umbrella"     # a tweak of P1
        P3 = "a lighthouse on a cliff at dusk, paper cut style, layered paper"
        P4 = "café au lait, 東京の夜, cozy 🌙"                                            # non-ASCII survives
        for i, seed in enumerate((101, 102, 103)):
            make_png(os.path.join(root, f"rain_{i}.png"), P1, seed, (30, 30, 90 + i))
        make_png(os.path.join(root, "rain_model2.png"), P1, 101, (40, 40, 100), ckpt="Pony\\velvet_v12.safetensors")
        make_png(os.path.join(root, "sub", "forest_0.png"), P2, 201, (20, 90, 20))
        make_png(os.path.join(root, "sub", "forest_1.png"), P2, 202, (25, 95, 25))
        make_png(os.path.join(root, "sub", "deeper", "light_0.png"), P3, 7, (200, 150, 90))
        make_png(os.path.join(root, "cafe.png"), P4, 9, (120, 80, 40))
        make_a1111_jpeg(os.path.join(root, "fox.jpg"))
        from PIL import Image
        Image.new("RGB", (64, 64), "white").save(os.path.join(root, "plain.png"))

        # ---- prompt similarity and diffs
        check(ar.similarity(P1, P2) >= 0.6 and ar.similarity(P1, P3) < 0.3, f"tweaked prompts are close, different ones far ({ar.similarity(P1, P2):.2f}, {ar.similarity(P1, P3):.2f})")
        d = ar.diff(P1, P2)
        check(d["added"] == ["forest", "umbrella"] and d["removed"] == ["city at night"], f"phrase diff ({d})")
        long_a = "anime style, cute girl with fox ears, she is sitting beside a campfire at night playing guitar under the stars, warm light"
        long_b = "anime style, cute girl with fox ears, she is sitting beside a campfire at night reading a book under the stars, warm light"
        d = ar.diff(long_a, long_b)
        check(d["replaced"] == [["playing guitar", "reading a book"]] and not d["added"] and not d["removed"],
              f"an edited phrase shows just the words that changed ({d})")
        d = ar.diff("a cat sitting on a red chair", "a cat sitting on a blue chair")
        check(d["replaced"] == [["red", "blue"]], f"word diff for prose ({d})")
        check(ar.norm_prompt("A (red:1.2) dress <lora:x:0.5>,  rain") == "a red dress , rain", "LoRA tags and weights don't split groups")

        # ---- the run
        events = []
        res = ar.run(root, mode="loose", progress=lambda **kw: events.append(kw))
        out = os.path.join(root, "_ml_archive")
        check(res["images"] == 10 and res["with_meta"] == 9 and res["no_meta"] == 1, f"10 images, 9 with data, 1 without ({res['images']}, {res['with_meta']}, {res['no_meta']})")
        check(any(e.get("phase") == "reading" for e in events) and any(e.get("phase") == "writing" for e in events), "progress reported")
        for f in ("report.md", "images.csv", "recipes.jsonl", "index.json", "summary.json"):
            check(os.path.isfile(os.path.join(out, f)), f"{f} written")
        fams = ar.group([e for e in json.load(open(os.path.join(out, "index.json"), encoding="utf-8"))["files"].values() if not e.get("error")], "loose")
        rain = next(f for f in fams if "city at night" in f["base"])
        check(rain["count"] == 6 and len(rain["variants"]) == 2, f"the tweaked prompt joins the family as a variant ({rain['count']}, {len(rain['variants'])})")
        v1, v2 = rain["variants"]
        check(v1["count"] == 4 and v1["diff"] is None and v2["diff"]["added"] == ["forest", "umbrella"], "base variant first; the other shows what changed")
        check(v1["shared"].get("steps") == 28 and v1["shared"].get("loras") == "paper_cut:0.8" and set(v1["varying"]) == {"seed", "model"},
              f"shared settings once, only seed and model vary ({v1['varying']})")
        exact = ar.group([e for e in json.load(open(os.path.join(out, "index.json"), encoding="utf-8"))["files"].values() if not e.get("error")], "exact")
        check(len(exact) == len(fams) + 1, "Exact only: the tweak becomes its own family")

        report = open(os.path.join(out, "report.md"), encoding="utf-8").read()
        check("`+ forest`" in report and "`− city at night`" in report and "Without generation data (1)" in report and "plain.png" in report,
              "report: variant diffs and the image without data")
        check('<img src="thumbs/' in report and "workflows/f001-v1.json" in report, "report: thumbnails and workflow links")
        rows = list(csv.DictReader(open(os.path.join(out, "images.csv"), encoding="utf-8-sig")))
        fox = next(r for r in rows if r["file"] == "fox.jpg")
        check(len(rows) == 10 and fox["seed"] == "42" and fox["model"] == "dreamshaper_8" and fox["sampler"], "CSV: one row per image, A1111 JPEG included")
        sub = next(r for r in rows if r["file"] == "sub/deeper/light_0.png")
        check(sub["prompt"] == P3 and sub["width"] == "832" and sub["denoise"] == "1.0", "subfolders scanned, relative paths")
        lines = [json.loads(x) for x in open(os.path.join(out, "recipes.jsonl"), encoding="utf-8")]
        check(len(lines) == 9 and all(x["recipe"]["schema"] == "recipe/1" and "comfy" not in x["recipe"] for x in lines), "recipes.jsonl: recipe/1 per image, no graph")
        wfs = sorted(os.listdir(os.path.join(out, "workflows")))
        check(len(wfs) == res["variants"] - 1 and all(w.endswith(".json") for w in wfs), f"one workflow per variant made in ComfyUI (not the A1111 one) ({wfs})")

        # ---- thumbnails carry their own workflow, prompt and recipe
        thumbs = os.listdir(os.path.join(out, "thumbs"))
        check(len(thumbs) == 10, f"a thumbnail per image ({len(thumbs)})")
        t = os.path.join(out, "thumbs", next(r for r in rows if r["file"] == "rain_1.png")["thumb"].split("/")[-1])
        data = open(t, "rb").read()
        with Image.open(io.BytesIO(data)) as im:
            check(im.format == "WEBP" and max(im.size) == 512, f"512 px WebP ({im.size})")
        meta = smf.imagemeta.read(data)["text"]
        check({"workflow", "prompt", "recipe"} <= set(meta), f"EXIF carries workflow, prompt and recipe ({sorted(meta)})")
        rec = smf.recipe_parse.from_text(meta)
        check(rec["settings"]["seed"] == 102 and rec["prompt"]["positive"] == P1 and json.loads(meta["workflow"])["nodes"][1]["widgets_values"][0] == 102,
              "the thumbnail reproduces that exact image (seed 102)")
        cafe = smf.imagemeta.read(open(os.path.join(out, "thumbs", next(r for r in rows if r["file"] == "cafe.png")["thumb"].split("/")[-1]), "rb").read())["text"]
        check(smf.recipe_parse.from_text(cafe)["prompt"]["positive"] == P4, "non-ASCII prompts survive the EXIF round trip")
        foxmeta = smf.imagemeta.read(open(os.path.join(out, "thumbs", fox["thumb"].split("/")[-1]), "rb").read())["text"]
        check("Seed: 42" in foxmeta.get("UserComment", ""), "A1111 parameters kept for other readers")
        check(os.path.getsize(t) < 60_000, f"thumbnail stays small ({os.path.getsize(t)} bytes)")

        # ---- re-runs only read what changed
        mt = os.path.getmtime(t)
        time.sleep(0.05)
        ev2 = []
        res2 = ar.run(root, mode="loose", progress=lambda **kw: ev2.append(kw))
        check(any(e.get("reused") == 10 for e in ev2) and os.path.getmtime(t) == mt and res2["images"] == 10, "second run: nothing re-read")
        os.remove(os.path.join(root, "rain_0.png"))
        make_png(os.path.join(root, "rain_3.png"), P1, 104, (30, 30, 99))
        ev3 = []
        res3 = ar.run(root, mode="loose", progress=lambda **kw: ev3.append(kw))
        check(any(e.get("reused") == 9 for e in ev3) and res3["images"] == 10 and len(os.listdir(os.path.join(out, "thumbs"))) == 10,
              "a new image is read, a deleted one's thumbnail is removed")
        check(not any(f.endswith(".webp") for f in os.listdir(root)), "nothing written outside _ml_archive")

        # ---- without thumbnails / embedding
        root2 = tempfile.mkdtemp(prefix="smf_archive2_")
        make_png(os.path.join(root2, "a.png"), P3, 1, (10, 10, 10))
        r = ar.run(root2, thumbs=False)
        check(r["images"] == 1 and not os.listdir(os.path.join(root2, "_ml_archive", "thumbs")), "thumbnails can be turned off")
        r = ar.run(root2, thumbs=True, embed=False)
        tt = os.listdir(os.path.join(root2, "_ml_archive", "thumbs"))
        check(len(tt) == 1 and not smf.imagemeta.read(open(os.path.join(root2, "_ml_archive", "thumbs", tt[0]), "rb").read())["text"],
              "plain thumbnails when embedding is off (turning it on later re-makes them)")
        shutil.rmtree(root2, ignore_errors=True)

        # ---- the job and routes' helpers
        live = os.listdir(os.path.join(out, "thumbs"))[0]
        check(ar.thumb_path(root, "../../x.webp") is None and ar.thumb_path(root, "..\report.md") is None and ar.thumb_path(root, live),
              "thumb names are validated")
        check(ar.summary(root)["images"] == 10, "summary for the tab")
        try:
            ar.start(os.path.join(root, "nope"))
            check(False, "a missing folder is refused")
        except ValueError:
            check(True, "a missing folder is refused")
        ar.start(root, mode="similar")
        for _ in range(200):
            if ar.job_status()["status"] != "running":
                break
            time.sleep(0.05)
        check(ar.job_status()["status"] == "done" and ar.job_status()["result"]["images"] == 10, "background job")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
