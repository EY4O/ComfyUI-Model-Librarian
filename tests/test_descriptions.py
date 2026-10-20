"""CivitAI descriptions follow the model: saved in its .cm-info.json, read from any tool's sidecar,
synced with LoRA Manager, and shown as plain text (never the page's HTML)."""
import asyncio
import json
import os

import test_shared as T

check = T.check


def main():
    base, user = T.fake_install("DESC")
    os.makedirs(T.LORA, exist_ok=True)
    smf = T.load_smf(base, user)
    from smf import htmltext, smmeta, bridge

    # ---- HTML -> text
    t = htmltext.to_text('<p>Photoreal <b>characters</b>.</p><h3>Settings</h3><ul><li>8 steps</li><li>CFG 1</li></ul>'
                         '<p>See <a href="https://example.com/guide">my guide</a>, <a href="javascript:alert(1)">bad</a>'
                         ' and <a href="https://x.io">https://x.io</a>.</p><script>alert("x")</script><img src=x onerror=alert(1)>')
    check(t == "Photoreal characters.\n\nSettings\n• 8 steps\n• CFG 1\n\nSee my guide (https://example.com/guide), bad and https://x.io.",
          f"HTML becomes plain text: paragraphs, bullets, links as text; scripts and javascript: links dropped ({t!r})")
    check(htmltext.to_text(None) == "" and len(htmltext.to_text("<p>" + "a" * 30000 + "</p>")) == htmltext.MAX_CHARS + 1, "empty and very long descriptions")

    # ---- saved with the metadata
    model = os.path.join(T.LORA, "paper.safetensors")
    open(model, "wb").write(b"x" * 10)
    meta = {"modelId": 1, "modelName": "Paper Cut", "versionId": 11, "versionName": "v1", "modelDescription": "<p>Layered paper.</p>",
            "versionDescription": "<p>First release.</p>", "hashes": {"SHA256": "AB" * 32}}
    smmeta.write_cm_info(model, meta)
    cm = smmeta.read_cm_info(model)
    check(cm["ModelDescription"] == "<p>Layered paper.</p>" and cm["VersionDescription"] == "<p>First release.</p>", "written into .cm-info.json")
    check(smmeta.descriptions(model) == {"model": "<p>Layered paper.</p>", "version": "<p>First release.</p>"}, "read back")
    smmeta.write_cm_info(model, {**meta, "modelDescription": None, "versionDescription": None}, overwrite=True)
    check(smmeta.read_cm_info(model)["ModelDescription"] == "<p>Layered paper.</p>", "a refresh without one keeps the saved description")
    check(not smmeta.save_descriptions(model, "<p>other</p>", None), "save_descriptions doesn't replace a saved one")

    # ---- from LoRA Manager's sidecar, and synced both ways
    m2 = os.path.join(T.LORA, "lmonly.safetensors")
    open(m2, "wb").write(b"y")
    lm = {"model_name": "LM Model", "modelDescription": "<p>From LM.</p>", "sha256": "cd" * 32,
          "civitai": {"id": 22, "modelId": 2, "name": "v2", "description": "<p>LM version notes.</p>", "model": {"name": "LM Model"}}}
    json.dump(lm, open(smmeta.model_stem(m2) + ".metadata.json", "w"))
    check(smmeta.descriptions(m2) == {"model": "<p>From LM.</p>", "version": "<p>LM version notes.</p>"}, "LoRA Manager's descriptions are read too")
    check(bridge.cm_meta_from_lm(lm)["modelDescription"] == "<p>From LM.</p>", "LM -> SM metadata carries the description")
    smmeta.write_cm_info(m2, {"modelId": 2, "modelName": "LM Model", "versionId": 22})
    e = {"path": m2, "section": "loras"}
    acts, _ = bridge._actions(e)
    check("description" in acts, f"a description only one side has is offered for syncing ({acts})")
    bridge._apply_one(e, acts)
    check(smmeta.read_cm_info(m2).get("ModelDescription") == "<p>From LM.</p>", "synced LM -> SM")
    json.dump({**lm, "modelDescription": ""}, open(smmeta.model_stem(m2) + ".metadata.json", "w"))
    bridge._apply_one(e, bridge._actions(e)[0])
    check(smmeta.read_lm_metadata(m2)["modelDescription"] == "<p>From LM.</p>", "synced SM -> LM")
    check(bridge.lm_civitai_from_cm(smmeta.read_cm_info(m2)).get("description") == "<p>LM version notes.</p>", "version notes go to LM's civitai block")

    # ---- fetched once per model per session
    calls = []

    async def fake_get_json(url, params=None, timeout=30):
        calls.append(url)
        return {"description": "<p>From CivitAI.</p>"}
    smf.net.get_json = fake_get_json

    async def run():
        a = await smf.sources.with_description({"modelId": 7, "modelName": "X"})
        b = await smf.sources.with_description({"modelId": 7, "modelName": "X"})
        c = await smf.sources.with_description({"modelId": 8, "modelDescription": "<p>already</p>"})
        return a, b, c
    a, b, c = asyncio.run(run())
    check(a["modelDescription"] == "<p>From CivitAI.</p>" and b["modelDescription"] == a["modelDescription"] and len(calls) == 1,
          "the model page's description is fetched once per model")
    check(c["modelDescription"] == "<p>already</p>" and len(calls) == 1, "not fetched when the metadata has it")
    print("\nFAILED: %d" % check.failed if check.failed else "\nALL PASSED")
    return 1 if check.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
