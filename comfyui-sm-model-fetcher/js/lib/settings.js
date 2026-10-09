// "Registry" + "Settings" tabs.
import { call, ctx, h, clear, fmtSize, toast, pill, refreshStatus, familyBadge } from "./util.js";

// ================================================================ Registry
let regRoot = null;
export async function mountRegistry(root) {
  regRoot = root;
  const { entries } = await call("/registry");
  const fn = h("input.smf-input", { placeholder: "file name, e.g. myStyle_v2.safetensors" });
  const url = h("input.smf-input", { placeholder: "https:// download URL", style: { flex: 2 } });
  const q = h("input.smf-input", { placeholder: "Filter…", oninput: () => draw() });
  const tbody = h("tbody");
  const draw = () => {
    const f = q.value.toLowerCase();
    clear(tbody, entries.filter((e) => !f || e.filename.toLowerCase().includes(f) || (e.title || "").toLowerCase().includes(f))
      .map((e) => h("tr",
        h("td", h("b", e.filename), e.title ? h("div.smf-dim.small", e.title) : null),
        h("td", pill(e.source, "src"), e.folder ? h("div.smf-dim.small", e.folder) : null),
        h("td.small", e.size ? fmtSize(e.size) : ""),
        h("td.small.smf-dim", e.sha256 ? e.sha256.slice(0, 10) + "…" : "—"),
        h("td", e.page_url ? h("a.smf-link", { href: e.page_url, target: "_blank" }, "page ↗") : null, " ",
          h("a.smf-link", { href: e.url, target: "_blank", title: e.url }, "url ↗")),
        h("td", h("button.smf-btn.small.ghost", {
          onclick: async () => {
            if (!confirm(`Forget where ${e.filename} came from?`)) return;
            await call(`/registry/${encodeURIComponent(e.filename.toLowerCase())}`, { method: "DELETE" });
            mountRegistry(regRoot);
          },
        }, "Forget")))));
  };
  draw();
  clear(root,
    h("div.smf-help", "Every model you download or identify is remembered here (file name → source URL + SHA256). When a workflow asks for one of these files again — even with a generic name — it resolves instantly."),
    h("div.smf-toolbar", fn, url, h("button.smf-btn", {
      onclick: async () => {
        try {
          await call("/registry", { method: "POST", body: { filename: fn.value.trim(), url: url.value.trim() } });
          toast("success", "Saved", fn.value);
          mountRegistry(root);
        } catch (e) {
          toast("error", "Not saved", e.message);
        }
      },
    }, "Add")),
    h("div.smf-toolbar", q, h("span.smf-dim", `${entries.length} entries`)),
    h("div.smf-list", h("table.smf-table", h("thead", h("tr", h("th", "File"), h("th", "Source"), h("th", "Size"), h("th", "SHA256"), h("th", "Links"), h("th", ""))), tbody)));
}

// leftover .smf-part files from cancelled / failed downloads
function partialsSection() {
  const box = h("div");
  const find = async () => {
    clear(box, h("span.smf-dim", "Looking…"));
    try {
      const { partials } = await call("/partials");
      if (!partials.length) return clear(box, h("span.smf-dim.small", "No leftover partial downloads."));
      const sel = new Set(partials.filter((p) => !p.retryable).map((p) => p.path));
      const total = () => partials.filter((p) => sel.has(p.path)).reduce((a, p) => a + p.size, 0);
      const btn = h("button.smf-btn.warn");
      const label = () => { btn.textContent = `Delete ${sel.size} (${fmtSize(total())})`; btn.disabled = !sel.size; };
      btn.onclick = async () => {
        if (!confirm(`Delete ${sel.size} partial download file(s), ${fmtSize(total())}? They can't be resumed afterwards.`)) return;
        const r = await call("/partials/delete", { method: "POST", body: { paths: [...sel] } });
        toast(r.errors.length ? "warn" : "success", "Partial downloads", `${r.deleted} deleted, ${fmtSize(r.freed)} freed` + (r.errors.length ? ` · ${r.errors[0]}` : ""), 6000);
        find();
      };
      label();
      clear(box,
        h("table.smf-table", partials.map((p) => h("tr",
          h("td", h("input", { type: "checkbox", checked: sel.has(p.path), onchange: (e) => { e.target.checked ? sel.add(p.path) : sel.delete(p.path); label(); } })),
          h("td.small", { title: p.path }, p.path.split(/[\\/]/).slice(-2).join("/")),
          h("td.small", fmtSize(p.size)),
          h("td.small.smf-dim", `${p.age_days} days old`),
          h("td", p.retryable ? pill("can resume", "ok", "A failed/interrupted download in the tray can still resume from this file") : null)))),
        h("div.smf-toolbar", btn));
    } catch (e) {
      clear(box, h("span.err", e.message));
    }
  };
  return h("section",
    h("h3", "Partial downloads"),
    h("div.smf-dim.small", "Cancelled or failed downloads leave .smf-part files so they can resume. Ones a download in the tray can still resume from start unchecked."),
    h("div", h("button.smf-btn", { onclick: find }, "Find leftover partial downloads")),
    box);
}

// ================================================================ Settings
export async function mountSettings(root) {
  const st = await refreshStatus();
  const c = st.config;
  const f = {};
  const field = (label, input, help) => h("div.smf-field", h("label", label), input, help ? h("div.smf-dim.small", help) : null);
  f.hf_token = h("input.smf-input", { type: "password", placeholder: c.has_hf_token ? "saved ✓ (type to replace)" : "hf_…", autocomplete: "off" });
  f.civitai_token = h("input.smf-input", { type: "password", placeholder: c.has_civitai_token ? "saved ✓ (type to replace)" : "CivitAI API key", autocomplete: "off" });
  f.vram_gb = h("input.smf-input", { type: "number", step: "0.5", min: "2", value: c.vram_gb });
  f.headroom_gb = h("input.smf-input", { type: "number", step: "0.5", min: "0", value: c.headroom_gb });
  f.max_concurrent = h("input.smf-input", { type: "number", min: "1", max: "6", value: c.max_concurrent });
  const chk = (k, label) => (f[k] = h("input", { type: "checkbox", checked: !!c[k] }), h("label.smf-check", f[k], " ", label));

  const famInputs = {};
  const famGrid = h("div.smf-famgrid", st.families.map((fam) => {
    famInputs[fam] = h("input.smf-input.small", { value: (c.folder_names || {})[fam] || "", placeholder: fam });
    return h("div.smf-row", familyBadge(fam), famInputs[fam]);
  }));
  const rules = h("textarea.smf-input", {
    rows: 4, placeholder: "One rule per line:  regex => Family\ne.g.  waiNSFW|hassaku => Illustrious",
    value: (c.extra_rules || []).map((r) => `${r.match} => ${r.family}`).join("\n"),
  });

  const save = async () => {
    const patch = {
      vram_gb: f.vram_gb.value, headroom_gb: f.headroom_gb.value, max_concurrent: f.max_concurrent.value,
      write_sm_metadata: f.write_sm_metadata.checked, download_previews: f.download_previews.checked,
      auto_check_on_load: f.auto_check_on_load.checked, auto_check_action: f.auto_check_action.value,
      fix_workflows_after_moves: f.fix_workflows_after_moves.checked, nsfw_previews: f.nsfw_previews.checked,
      blur_nsfw: f.blur_nsfw.checked, share_data: f.share_data.checked,
      folder_names: Object.fromEntries(Object.entries(famInputs).map(([k, el]) => [k, el.value.trim()]).filter(([, v]) => v)),
      extra_rules: rules.value.split("\n").map((l) => l.split("=>")).filter((p) => p.length === 2 && p[0].trim() && p[1].trim())
        .map(([m, fam]) => ({ match: m.trim(), family: fam.trim() })),
    };
    if (f.hf_token.value) patch.hf_token = f.hf_token.value;
    if (f.civitai_token.value) patch.civitai_token = f.civitai_token.value;
    try {
      await call("/config", { method: "POST", body: patch });
      toast("success", "Settings saved", "", 2000);
      mountSettings(root);
    } catch (e) {
      toast("error", "Not saved", e.message);
    }
  };
  const clearTok = (k) => h("button.smf-btn.small.ghost", {
    onclick: async () => { await call("/config", { method: "POST", body: { [k]: "" } }); mountSettings(root); },
  }, "Remove");

  const destRows = Object.entries(st.destinations).map(([k, v]) =>
    h("tr", h("td", k), h("td.small", v.path), h("td", v.shared ? pill("SM shared", "ok") : pill("ComfyUI only", "warn"))));

  clear(root,
    h("div.smf-settings",
      h("section",
        h("h3", "API keys"),
        field("CivitAI API key", h("div.smf-row", f.civitai_token, c.has_civitai_token ? clearTok("civitai_token") : null),
          h("span", "civitai.com → Account settings → API Keys. Needed for many downloads and for metadata lookups.")),
        field("HuggingFace token", h("div.smf-row", f.hf_token, c.has_hf_token ? clearTok("hf_token") : null),
          h("span", "huggingface.co/settings/tokens (read access). Needed for gated models like FLUX.1-dev — accept the license on the model page first.")),
        h("div.smf-dim.small", "Keys are stored server-side in ComfyUI's user folder and never sent back to the browser. The env vars CIVITAI_API_KEY / HF_TOKEN also work.")),
      h("section",
        h("h3", "GPU"),
        h("div.smf-row", field("VRAM (GB)", f.vram_gb), field("Keep free (GB)", f.headroom_gb, "for activations/latents"),
          field("Parallel downloads", f.max_concurrent)),
        h("div.smf-dim.small", `Models larger than ${(c.vram_gb - c.headroom_gb).toFixed(1)} GB get a “Find GGUF” suggestion.`)),
      h("section",
        h("h3", "Behaviour"),
        h("div.smf-row", chk("auto_check_on_load", "Check every workflow for missing models when it's opened"),
          f.auto_check_action = h("select.smf-select", {},
            h("option", { value: "notify", selected: c.auto_check_action !== "open" }, "and show a notice"),
            h("option", { value: "open", selected: c.auto_check_action === "open" }, "and open this window"))),
        chk("fix_workflows_after_moves", "Repoint saved workflows after Organize / Undo (backups are kept)"),
        chk("write_sm_metadata", "Write Stability Matrix metadata (.cm-info.json) for downloaded / identified models"),
        chk("download_previews", "Save preview images next to models (<name>.preview.*)"),
        chk("nsfw_previews", "Allow NSFW preview images (otherwise the first SFW image is used)"),
        chk("blur_nsfw", "Blur NSFW models in the Library")),
      h("section",
        h("h3", "Organizer folder names"),
        h("div.smf-dim.small", "Leave blank to use the family name. Existing folders with common aliases (IL, PDXL, SD15, WAN, zimage…) are recognised automatically."),
        famGrid,
        field("Extra detection rules", rules, "Checked before the built-in rules, against CivitAI base model and file names.")),
      h("section",
        h("h3", "Stability Matrix"),
        h("div", "Detection: ", pill(st.sm.mode, st.sm.mode === "none" ? "warn" : "ok"), " ", h("span.smf-dim.small", st.sm.models_root || "")),
        h("table.smf-table", destRows),
        h("div.smf-dim.small", "ComfyUI-GGUF: ", st.gguf_installed ? pill("installed", "ok") : pill("not installed", "warn"),
          "  LoRA Manager: ", st.lm_installed ? pill("installed", "ok") : pill("not installed", "dim"))),
      partialsSection(),
      h("section",
        h("h3", "Shared data"),
        chk("share_data", "Share the registry, hash cache, undo history and settings with every ComfyUI that uses these Stability Matrix folders"),
        h("div", "Data folder: ", c.data_shared ? pill("shared", "ok") : pill("this install only", "warn"), " ",
          h("code.small", c.data_dir)),
        h("div.smf-dim.small", "API keys always stay in this install's user folder. When sharing turns on, this install's existing data is merged in; the local copies are kept as a backup.",
          !c.data_shared && c.share_data ? " Stability Matrix shared folders weren't found, so data stays local." : "")),
      h("div.smf-toolbar", h("span.smf-spacer"), h("button.smf-btn.primary", { onclick: save }, "Save settings"))));
}
