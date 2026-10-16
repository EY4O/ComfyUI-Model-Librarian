"""CivArchive fallback (only when CivitAI has nothing), removed models, sharing a
workflow's download list, and leftovers of unfinished downloads."""
import asyncio
import json
import os
import struct
import time

import test_shared as T

check = T.check

SHA = "d" * 64
SHA2 = "e" * 64


def sha_page(sha=SHA, live_hf=True):
    """A /sha256/<hash> page as CivArchive serves it (trimmed to what we read)."""
    props = {
        "id": sha,
        "files": [
            {"filename": "Ember.safetensors", "url": "https://civitai.com/api/download/models/501", "source": "civitai",
             "deleted_at": "2026-09-01T00:00:00Z", "is_gated": False, "is_paid": False},
            {"filename": "Ember.safetensors", "url": "https://huggingface.co/keeper/backup/resolve/main/Ember.safetensors",
             "source": "huggingface", "deleted_at": None if live_hf else "2026-09-02T00:00:00Z", "is_gated": False, "is_paid": False},
            {"filename": "Ember.safetensors", "url": "https://files.example/abc", "source": "elsewhere",
             "deleted_at": None, "is_gated": False, "is_paid": False},
            {"filename": "Ember.safetensors", "url": "magnet:?xt=urn:btih:1", "source": "torrent", "deleted_at": None},
        ],
        "models": [{
            "id": "400", "name": "Ember Style", "type": "LORA", "is_nsfw": False, "creator_username": "maker",
            "deleted_at": "2026-09-01T00:00:00Z", "tags": [{"name": "style"}],
            "version": {"id": "501", "model_id": 400, "name": "v2", "base_model": "Illustrious", "trigger": ["embr"],
                        "civitai_model_id": 400, "civitai_model_version_id": 501,
                        "files": [{"name": "Ember.safetensors", "size_kb": 2048, "sha256": sha}],
                        "images": [{"url": "https://img.example/nsfw.webp", "nsfwLevel": 8},
                                   {"url": "https://img.example/sfw.webp", "nsfwLevel": 1}]},
        }],
    }
    data = {"props": {"pageProps": props}, "page": "/sha256/[id]", "buildId": "x"}
    return f'<html><body><div id="__next"></div><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>'


def search_page(results):
    data = {"props": {"pageProps": {"data": {"results": results, "total_hits": len(results)}}}}
    return f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'


def safetensors(path, data_len, write_len=None):
    hdr = json.dumps({"w": {"dtype": "F16", "shape": [data_len // 2], "data_offsets": [0, data_len]}}).encode()
    body = struct.pack("<Q", len(hdr)) + hdr + b"\0" * data_len
    with open(path, "wb") as f:
        f.write(body[:write_len] if write_len is not None else body)
    old = time.time() - 3600
    os.utime(path, (old, old))


def main():
    base, user = T.fake_install("CA")
    smf = T.load_smf(base, user)
    ca = smf.civarchive
    os.makedirs(T.LORA, exist_ok=True)

    async def no_civitai(sha):
        return None
    smf.sources.civitai_by_hash = no_civitai  # never reach the real CivitAI

    async def offline(*a, **k):
        return None
    smf.net.get_json = offline  # nor HuggingFace (details of the copy's repo after identify)
    smf.hfmeta._readme = offline

    # ---- reading a page
    pp = ca.page_data(sha_page())
    rec = ca.parse(pp, SHA)
    check(rec["filename"] == "Ember.safetensors" and rec["size"] == 2048 * 1024 and rec["folder"] == "loras", "file name, size and folder")
    m = rec["meta"]
    check(m["modelName"] == "Ember Style" and m["versionName"] == "v2" and m["baseModel"] == "Illustrious"
          and m["trainedWords"] == ["embr"] and m["modelId"] == 400 and m["versionId"] == 501, "the CivitAI details it kept")
    check(m["preview"] == "https://img.example/sfw.webp", "SFW preview picked (NSFW previews are off)")
    check(rec["deleted_on_civitai"] and len(rec["files"]) == 3, "removed from CivitAI; non-https copies (magnets) dropped")
    check(ca.best_url(rec) == "https://huggingface.co/keeper/backup/resolve/main/Ember.safetensors", "a live HuggingFace copy to download")
    cands = ca.candidates(rec, "Ember.safetensors")
    check([(c["via"], c["confidence"], bool(c.get("link_only"))) for c in cands] == [("huggingface.co", "high", False), ("files.example", "medium", True)],
          f"live copies only; other hosts are links to open ({[(c['via'], c.get('link_only')) for c in cands]})")
    check(cands[0]["sha256"] == SHA and cands[0]["source"] == "civarchive" and cands[0]["page_url"].endswith("/sha256/" + SHA),
          "candidates are SHA256-verified and point at the CivArchive page")
    check(ca.best_url(ca.parse(ca.page_data(sha_page(live_hf=False)), SHA)) is None, "no live copy on a host we download from")
    check(ca.page_data("<html>no data</html>") is None and ca.parse({}, SHA) is None, "pages without data / unlisted files")
    stale = ca.page_data(sha_page())
    stale["files"][0].update(deleted_at=None, model_version_id="501")  # CivArchive still calls the removed version's link live
    srec = ca.parse(stale, SHA)
    check(not srec["files"][0]["live"] and "huggingface.co" in ca.best_url(srec),
          "the removed version's own CivitAI link isn't trusted; the HuggingFace copy is used")
    other = ca.page_data(sha_page())
    other["models"][0].update(platform="tensorart")
    for k in ("civitai_model_id", "civitai_model_version_id"):
        other["models"][0]["version"].pop(k)
    om = ca.parse(other, SHA)["meta"]
    check("modelId" not in om and "versionId" not in om, "a model from another site gets no CivitAI ids (they'd point at the wrong model)")
    check(ca.search_hits({"data": {"results": [
        {"name": "Ember.safetensors", "url": "/sha256/" + SHA}, {"name": "Ember_v1.safetensors", "url": "/sha256/" + SHA2},
        {"name": "EMBER.SAFETENSORS", "url": "/sha256/" + SHA}, {"name": "Ember.safetensors", "url": "/models/1"}]}}, "loras/Ember.safetensors") == [SHA],
        "search: exact file names only, each hash once")

    # ---- lookups are cached in the shared data folder, misses too
    pages = []

    async def fake_page(path):
        pages.append(path)
        if path == f"/sha256/{SHA}":
            return ca.page_data(sha_page())
        if path.startswith("/search"):
            return ca.page_data(search_page([{"name": "Ember.safetensors", "url": "/sha256/" + SHA}]))
        return None
    orig_page = ca._page
    ca._page = fake_page
    got = asyncio.run(ca.by_hash(SHA.upper()))
    again = asyncio.run(ca.by_hash(SHA))
    check(got and again and pages == [f"/sha256/{SHA}"], f"fetched once, then cached ({pages})")
    asyncio.run(ca.by_hash(SHA2))
    asyncio.run(ca.by_hash(SHA2))
    check(pages.count(f"/sha256/{SHA2}") == 1 and ca.load()[SHA2]["found"] is False, "a miss is remembered too")
    check(asyncio.run(ca.by_hash("not-a-hash")) is None, "only real SHA256s are looked up")


    class FakeResp:
        status = 200

        class content:
            chunks = [b"<html>Just a moment...</html>", b""]

            @classmethod
            async def read(cls, n):
                return cls.chunks.pop(0) if cls.chunks else b""

        def raise_for_status(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    class FakeSession:
        def get(self, *a, **k):
            return FakeResp()
    real_session = smf.net.session
    smf.net.session = lambda: FakeSession()
    ca._page = orig_page
    sha3 = "f" * 64
    try:
        asyncio.run(ca.by_hash(sha3))
        check(False, "a bot-check page raises")
    except RuntimeError:
        check(sha3 not in ca.load(), "a bot-check page isn't cached as 'not listed'")
    smf.net.session = real_session
    ca._page = fake_page
    pages.clear()
    byname = asyncio.run(ca.by_name("Ember.safetensors"))
    check([r["sha256"] for r in byname] == [SHA] and pages[0].startswith("/search?q=Ember&"), "by name: searched by stem, matched exactly")

    # ---- the missing-model finder asks CivArchive only when nothing else found the file
    async def none(*a, **k):
        return []
    smf.sources.from_manager = none
    smf.sources.from_civitai = none
    smf.sources.from_huggingface = none
    out = asyncio.run(smf.sources.resolve("Ember.safetensors", "loras"))
    check(out and out[0]["source"] == "civarchive" and out[0]["via"] == "huggingface.co", "not on CivitAI: CivArchive's copies are offered")

    async def civ_found(filename, folder):
        return [smf.sources._cand("civitai", "https://civitai.com/api/download/models/9", filename, confidence="high")]
    smf.sources.from_civitai = civ_found
    pages.clear()
    out = asyncio.run(smf.sources.resolve("Ember.safetensors", "loras"))
    check(not pages and all(c["source"] != "civarchive" for c in out), "on CivitAI: CivArchive isn't asked")
    smf.sources.from_civitai = none
    smf.config.save({"use_civarchive": False})
    pages.clear()
    asyncio.run(smf.sources.resolve("Ember.safetensors", "loras"))
    check(not pages, "turned off in Settings: never asked")
    smf.config.save({"use_civarchive": True})
    out = asyncio.run(smf.sources.resolve("other.safetensors", "loras", {"url": "", "hash": SHA, "hash_type": "sha256"}))
    check(any(c["source"] == "civarchive" for c in out), "a workflow's embedded SHA256 is looked up directly")

    # ---- Library → Fetch metadata: details from CivArchive when CivitAI says 404
    lora = os.path.join(T.LORA, "Ember.safetensors")
    safetensors(lora, 64)
    smf.hashing.store(lora, SHA)
    smf.config.save({"write_sm_metadata": True, "download_previews": False})

    async def identify():
        await smf.library.identify(["loras"], ids=[smf.library.file_id(lora)])
        while smf.library.job_status()["status"] == "running":
            await asyncio.sleep(0.02)
        return smf.library.job_status()
    st = asyncio.run(identify())
    cm = smf.smmeta.read_cm_info(lora) or {}
    check(st["status"] == "done" and st["found"] == 1 and st.get("archived") == 1, f"found via CivArchive ({st.get('found')}, {st.get('log')})")
    check(cm.get("ModelName") == "Ember Style" and cm.get("TrainedWords") == ["embr"] and cm.get("BaseModel") == "Illustrious",
          "its details written next to the file")
    reg = smf.registry.lookup("Ember.safetensors")
    check(reg and reg["source"] == "civarchive" and "huggingface.co" in reg["url"], "the live copy remembered as its source")
    check("removed from CivitAI" in st["log"][-1]["title"], "the log says it was removed from CivitAI")

    # ---- removed models: the daily check notices them
    ups = smf.updates
    cache = {"models": {"400": {"checked": 1, "gone": True, "versions": []},
                        "401": {"checked": 2, "versions": [{"id": 900, "name": "v3", "base_model": "Illustrious"}]},
                        "402": {"checked": 3, "versions": [{"id": 950, "name": "v1", "base_model": "Illustrious"}]}}}
    check(ups.removed_for({"model_id": 400, "version_id": 501}, cache) == {"where": "CivitAI", "what": "model", "at": 1}, "model removed")
    check(ups.removed_for({"model_id": 401, "version_id": 899}, cache)["what"] == "version", "your version removed (others remain)")
    check(ups.removed_for({"model_id": 402, "version_id": 950}, cache) is None and ups.removed_for({"model_id": 9, "version_id": 1}, cache) is None,
          "still listed / never checked: not removed")
    smf.config.write_json(ups.CACHE, cache)
    entries = smf.library.build("loras")
    ups.annotate(entries)
    e = next(x for x in entries if x["name"] == "Ember.safetensors")
    check(e.get("removed", {}).get("what") == "model", "the Library marks it")

    # ---- sharing: a link for every model, CivArchive's copy for the removed one
    other = os.path.join(T.LORA, "Glow.safetensors")
    safetensors(other, 32)
    smf.hashing.store(other, SHA2)
    smf.registry.remember("Glow.safetensors", "https://civitai.com/api/download/models/77", source="civitai", sha256=SHA2,
                          page_url="https://civitai.com/models/7?modelVersionId=77", title="Glow — v1")
    smf.registry.forget("ember.safetensors")
    rows = asyncio.run(smf.share.sources_for([
        {"value": "Glow.safetensors", "folder": "loras"},
        {"value": "Ember", "folder": "loras", "lm": True},
        {"value": "Nope.safetensors", "folder": "loras"}]))
    g, em, nope = rows
    check(g["url"].endswith("/models/77") and g["sha256"] == SHA2 and g["source"] == "civitai", "registry link with its SHA256")
    check(em["file"] == "Ember.safetensors" and em["source"] == "civarchive" and "huggingface.co" in em["url"]
          and em["removed"]["where"] == "CivitAI", f"removed from CivitAI: the live copy CivArchive knows ({em})")
    check(nope["url"] is None and nope["note"] == "not installed", "models you don't have aren't linked")
    md = smf.share.markdown(rows, "My flow")
    check(md.startswith("**Models for My flow**") and "`Glow.safetensors`" in md and "removed from CivitAI" in md
          and "[page](https://civitai.com/models/7?modelVersionId=77)" in md, "a list to post")

    # LoRA Manager nodes keep their own embedded sources
    wf = {"nodes": [{"id": 1, "type": "Lora Loader (LoraManager)", "widgets_values": [[{"name": "Ember", "strength": 1, "active": True}]],
                     "properties": {"models": [{"name": "Ember.safetensors", "url": "https://huggingface.co/k/b/resolve/main/Ember.safetensors",
                                                "directory": "loras", "hash": SHA, "hash_type": "sha256"}]}}]}
    refs = smf.workflows.refs_of(wf, "a.json")
    check(refs and refs[0]["embedded"] and refs[0]["embedded"]["hash"] == SHA, "LoRA Manager node's own embedded source is read")

    # ---- leftovers of unfinished downloads
    dl = smf.downloader
    cut = os.path.join(T.LORA, "Cut.safetensors")
    safetensors(cut, 4096, write_len=600)
    check(dl.truncated(cut, os.path.getsize(cut)) and not dl.truncated(lora, os.path.getsize(lora)), "a cut-short .safetensors is spotted, a whole one isn't")
    odd = os.path.join(T.LORA, "Odd.safetensors")
    hdr = json.dumps({"w": {"dtype": "F16", "shape": [2], "data_offsets": [0, None]}, "v": {"data_offsets": [0, True]}}).encode()
    open(odd, "wb").write(struct.pack("<Q", len(hdr)) + hdr + b"\0" * 8)
    os.utime(odd, (time.time() - 3600,) * 2)
    check(dl.truncated(odd, os.path.getsize(odd)) is False and "Odd.safetensors" not in {os.path.basename(p["path"]) for p in dl.partials()},
          "a header with odd offsets is left alone, and doesn't break the scan")
    os.remove(odd)
    crd = os.path.join(T.LORA, "Big.safetensors.crdownload")
    open(crd, "wb").write(b"x" * 100)
    os.utime(crd, (time.time() - 7200,) * 2)
    fresh = os.path.join(T.LORA, "Live.safetensors.part")
    open(fresh, "wb").write(b"x" * 100)
    fresh_cut = os.path.join(T.LORA, "Copying.safetensors")
    safetensors(fresh_cut, 4096, write_len=600)
    os.utime(fresh_cut, None)  # being written right now
    found = {os.path.basename(p["path"]): p for p in dl.partials()}
    check(found.get("Cut.safetensors", {}).get("kind") == "truncated", "incomplete model listed")
    check(found.get("Big.safetensors.crdownload", {}).get("app") == "Chrome / Edge", "a browser's partial download, with the app named")
    check("Live.safetensors.part" not in found and "Copying.safetensors" not in found, "files touched in the last 30 minutes are left alone")
    check("Ember.safetensors" not in found and "Glow.safetensors" not in found, "whole models aren't listed")
    s = dl.partials_summary()
    check(s["truncated"] == 1 and s["count"] == len(found), "summary for the once-a-session notice")
    r = dl.delete_partials([cut, crd, lora])
    check(r["deleted"] == 2 and not os.path.exists(cut) and os.path.exists(lora) and r["errors"], "deletes listed leftovers only")

    for p in (lora, other, fresh, fresh_cut, smf.smmeta.cm_info_path(lora)):
        if os.path.exists(p):
            os.remove(p)
    asyncio.run(smf.net.close())
    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
