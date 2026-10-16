"""Storage history (free space samples, daily moves) and comparing an update with your version."""
import asyncio
import os
import time

import test_shared as T

check = T.check


def main():
    base, user = T.fake_install("HIST")
    smf = T.load_smf(base, user)
    sh = smf.storehist
    os.makedirs(T.LORA, exist_ok=True)

    # ---- samples: at most every 6 hours, per drive
    t = time.time()
    first = sh.sample(now=t)
    check(first and first["drives"] and all(d["total"] > 0 for d in first["drives"].values()), f"a sample per drive ({list((first or {}).get('drives', {}))})")
    check(sh.sample(now=t + 3600) is None, "not again within 6 hours")
    check(sh.sample(now=t + 7 * 3600) is not None, "again after 6 hours")
    check(sh.sample(force=True, now=t + 7 * 3600 + 5) is not None, "forced")
    old = t - 400 * 86400
    smf.config.update_json(sh.FILE, {"samples": [], "moves": {}}, lambda d: d["samples"].insert(0, {"t": old, "drives": {"X:": {"role": "models", "free": 1, "total": 2}}}))
    sh.sample(force=True, now=t + 8 * 3600)
    check(all(s["t"] > old for s in smf.config.read_json(sh.FILE, {})["samples"]), "samples older than a year are dropped")

    # ---- moves add up per day
    sh.record_move("archived", 10 * 1024 ** 3)
    sh.record_move("archived", 5 * 1024 ** 3)
    sh.record_move("restored", 2 * 1024 ** 3)
    sh.record_move("error", 1)
    h = sh.history(30)
    today = time.strftime("%Y-%m-%d")
    m = next(x for x in h["moves"] if x["day"] == today)
    check(m["archived"] == 15 * 1024 ** 3 and m["archived_n"] == 2 and m["restored_n"] == 1, "archived and restored per day, with counts")
    check(h["days"] == 30 and len(h["samples"]) >= 3 and h["drives"], "history for the chart")

    # the storage tiers report their moves
    smf.tiering._event("archived", name="x", section="loras", size=1024)
    m2 = next(x for x in sh.history(1)["moves"] if x["day"] == today)
    check(m2["archived_n"] == 3, "the storage tiers' moves are recorded")

    # two installs writing the same file: merged
    merged = sh._merge({"samples": [{"t": 1}], "moves": {today: {"archived": 5}}}, {"samples": [{"t": 1}, {"t": 2}], "moves": {today: {"archived": 7, "restored": 1}}})
    check([s["t"] for s in merged["samples"]] == [1, 2] and merged["moves"][today] == {"archived": 7, "restored": 1}, "shared file merge")

    # ---- compare an update with your version
    ups = smf.updates
    model = {"id": 21, "name": "Paper Cut", "type": "LORA", "creator": {"username": "fold"}, "modelVersions": [
        {"id": 2102, "name": "v1.2", "baseModel": "Illustrious", "publishedAt": "2026-09-20T00:00:00Z", "trainedWords": ["papercut", "layered paper"],
         "description": "<p>Retrained.</p><ul><li>Cleaner edges</li><li>New trigger</li></ul>", "stats": {"downloadCount": 3410, "thumbsUpCount": 640},
         "files": [{"name": "pc_v12.safetensors", "sizeKB": 2048, "primary": True, "metadata": {"fp": "fp16", "size": "pruned", "format": "SafeTensor"}}],
         "images": [{"url": "https://image.civitai.com/x/abc/width=450/1.jpeg", "nsfwLevel": 1}, {"url": "https://image.civitai.com/x/abc/width=450/2.jpeg", "nsfwLevel": 8}]},
        {"id": 2101, "name": "v1.1", "baseModel": "Illustrious", "publishedAt": "2026-06-02T00:00:00Z", "trainedWords": ["papercut"],
         "files": [{"name": "pc_v11.safetensors", "sizeKB": 1024}], "images": []}]}
    calls = []

    async def fake_get_json(url, params=None, timeout=30):
        calls.append(url)
        return model if url.endswith("/models/21") else None
    smf.net.get_json = fake_get_json
    r = asyncio.run(ups.compare(21, 2101, 2102))
    nv = r["newer"]
    check(r["have"]["name"] == "v1.1" and nv["name"] == "v1.2" and nv["size"] == 2048 * 1024 and nv["format"] == "fp16 pruned SafeTensor", "both versions, file and format")
    check(nv["trained_words"] == ["papercut", "layered paper"] and nv["downloads"] == 3410, "trigger words and popularity")
    check(nv["description"] == "Retrained.\n• Cleaner edges\n• New trigger", f"changelog as text ({nv['description']!r})")
    check(len(nv["images"]) == 1 and nv["hidden_images"] == 1 and "anim=false,width=320" in nv["images"][0]["url"], "NSFW samples hidden (NSFW previews are off); small stills")
    asyncio.run(ups.compare(21, 2101, 2102))
    check(len(calls) == 1, "the model page is cached for a while")
    try:
        asyncio.run(ups.compare(21, 2101, 9999))
        check(False, "an unknown version is an error")
    except LookupError:
        check(True, "an unknown version is an error")
    check(asyncio.run(ups.compare(21, 1, 2102))["have"] is None, "your version no longer listed: only the newer one")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
