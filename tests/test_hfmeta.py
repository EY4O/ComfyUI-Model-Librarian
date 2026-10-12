"""HuggingFace details: repo links from the registry, license / tags / model card, Library annotation."""
import asyncio
import os
import shutil
import sys

import test_shared as T

check = T.check

CARD = """---
license: apache-2.0
base_model: black-forest-labs/FLUX.1-dev
tags: [lora, flux]
---
<!-- hidden note -->
# Watercolor Flux LoRA

Trigger with `wtrclr`. """ + "x" * 3000


def main():
    base, user = T.fake_install("HF")
    smf = T.load_smf(base, user)
    hf = smf.hfmeta

    # ---- URL → repo
    check(hf.repo_of("https://huggingface.co/owner/repo/resolve/main/sub/model.safetensors?download=true")
          == {"repo": "owner/repo", "rev": "main", "path": "sub/model.safetensors"}, "resolve URL → repo, revision, path")
    check(hf.repo_of("https://huggingface.co/datasets/x/y/resolve/main/a.bin") is None and hf.repo_of("https://civitai.com/x") is None,
          "datasets and other sites aren't model repos")

    # ---- parsing what HuggingFace returns
    info = {"id": "owner/watercolor", "author": "owner", "pipeline_tag": "text-to-image", "library_name": "diffusers",
            "downloads": 1234, "likes": 56, "gated": "manual", "lastModified": "2026-09-01T00:00:00.000Z",
            "tags": ["lora", "flux", "license:apache-2.0", "region:us", "base_model:black-forest-labs/FLUX.1-dev", "endpoints_compatible"],
            "cardData": {"license": "apache-2.0", "base_model": ["black-forest-labs/FLUX.1-dev"]}}
    d = hf.parse(info, CARD)
    check(d["license"] == "apache-2.0" and d["base_model"] == "black-forest-labs/FLUX.1-dev" and d["pipeline"] == "text-to-image",
          "license, base model, task")
    check(d["tags"] == ["lora", "flux"] and d["gated"] == "manual" and d["likes"] == 56, "noise tags dropped; gating and likes kept")
    check(d["card"].startswith("# Watercolor Flux LoRA") and "hidden note" not in d["card"] and len(d["card"]) == hf.CARD_CHARS and d["card_truncated"],
          "model card without front matter or comments, trimmed")
    check(hf.parse({"tags": ["license:mit"]}, None)["license"] == "mit", "license from tags when the card has none")
    md = "[![Badge](https://img.shields.io/x.svg)](https://x.com/req)\n# Title\n\nSee [the base](https://huggingface.co/a/b) and ![bench](b.png).\n<p align=center>hi</p>\n\n\n\nend"
    check(hf.readable(md) == "# Title\n\nSee the base and .\nhi\n\nend", f"model card cleaned for reading ({hf.readable(md)!r})")

    # ---- fetch: cached for a week; a 404 is remembered
    calls = []

    async def fake_get_json(url, params=None, timeout=30):
        calls.append(url)
        return info if url.endswith("/owner/watercolor") else None

    async def fake_readme(repo):
        return CARD
    smf.net.get_json = fake_get_json
    hf._readme = fake_readme
    got = asyncio.run(hf.fetch("owner/watercolor"))
    check(got["license"] == "apache-2.0" and got["fetched"] > 0, "fetched and stored")
    asyncio.run(hf.fetch("owner/watercolor"))
    check(len(calls) == 1, "second fetch within a week comes from the cache")
    check(asyncio.run(hf.fetch("owner/gone"))["gone"], "missing repo remembered")

    # ---- Library entries linked through the registry
    os.makedirs(T.LORA, exist_ok=True)
    path = os.path.join(T.LORA, "watercolor_flux.safetensors")
    open(path, "wb").write(b"w")
    open(os.path.join(T.LORA, "local_only.safetensors"), "wb").write(b"l")
    smf.registry.remember("watercolor_flux.safetensors", "https://huggingface.co/owner/watercolor/resolve/main/watercolor_flux.safetensors",
                          source="huggingface")
    entries = {e["name"]: e for e in hf.annotate(smf.library.build("loras"))}
    w = entries["watercolor_flux.safetensors"]
    check(w["hf"]["repo"] == "owner/watercolor" and w["hf"]["license"] == "apache-2.0" and w["page_url"] == "https://huggingface.co/owner/watercolor",
          "linked entry gets the repo, its details and a page link")
    check("hf" not in entries["local_only.safetensors"], "files without an HF source aren't touched")

    # ---- Fetch metadata also fills in HuggingFace details
    smf.registry.remember("other.safetensors", "https://huggingface.co/owner/other/resolve/main/other.safetensors", source="huggingface")
    open(os.path.join(T.LORA, "other.safetensors"), "wb").write(b"o")
    info2 = dict(info, cardData={"license": "openrail++"}, tags=[])

    async def fake_get_json2(url, params=None, timeout=30):
        calls.append(url)
        return info2 if url.endswith("/owner/other") else (info if url.endswith("/owner/watercolor") else None)
    smf.net.get_json = fake_get_json2

    async def no_civitai(sha):
        return None
    smf.sources.civitai_by_hash = no_civitai
    calls.clear()

    async def identify():
        await smf.library.identify(["loras"])
        while smf.library.job_status()["status"] == "running":
            await asyncio.sleep(0.02)
        return smf.library.job_status()
    st = asyncio.run(identify())
    check(st["status"] == "done" and st.get("hf") == 1 and calls == [f"{smf.net.HF_BASE}/api/models/owner/other"],
          f"only the repo not cached yet is fetched ({st.get('hf')}, {calls})")
    check(smf.hfmeta.load()["owner/other"]["license"] == "openrail++", "its license stored")

    # ---- HTTP: refresh one repo; bad names refused
    from aiohttp import web, ClientSession

    async def http():
        routes = web.RouteTableDef()
        smf.routes.register(routes)
        app = web.Application()
        app.add_routes(routes)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        try:
            async with ClientSession() as s:
                async with s.post(f"http://127.0.0.1:{port}/sm-fetcher/hf/details", json={"repo": "owner/watercolor", "force": True}) as r:
                    ok = (r.status, await r.json())
                async with s.post(f"http://127.0.0.1:{port}/sm-fetcher/hf/details", json={"repo": "../etc/passwd"}) as r:
                    bad = r.status
                async with s.get(f"http://127.0.0.1:{port}/sm-fetcher/library?section=loras") as r:
                    lib = await r.json()
                return ok, bad, lib
        finally:
            await runner.cleanup()
    (st_ok, body), bad, lib = asyncio.run(http())
    check(st_ok == 200 and body["details"]["license"] == "apache-2.0", "refresh route")
    check(bad == 400, "repo names that aren't owner/name refused")
    check(next(e for e in lib["entries"] if e["name"] == "watercolor_flux.safetensors")["hf"]["likes"] == 56, "the library route carries HF details")

    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    shutil.rmtree(T.ROOT, ignore_errors=True)
    sys.exit(1 if check.failed else 0)


if __name__ == "__main__":
    main()
