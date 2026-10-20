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

// Ko-fi support banner: shown at the top of Settings once per browser session;
// closing it hides it until the next session.
const KOFI_URL = "https://ko-fi.com/looneth";
const KOFI_KEY = "smf-kofi-banner-dismissed";

function kofiBanner() {
  try {
    if (sessionStorage.getItem(KOFI_KEY)) return null;
  } catch {}
  const el = h("div.smf-kofi-banner", { role: "note" },
    h("div.smf-kofi-text", h("b", "☕ Enjoying Model Librarian?"), " It's free and open source — if it saves you time or disk space, you can support its development on Ko-fi."),
    h("a.smf-kofi-link", { href: KOFI_URL, target: "_blank", rel: "noopener noreferrer" }, "Support on Ko-fi"),
    h("button.smf-kofi-x", {
      title: "Hide for this session", "aria-label": "Hide for this session",
      onclick: () => {
        try { sessionStorage.setItem(KOFI_KEY, "1"); } catch {}
        el.remove();
      },
    }, "×"));
  return el;
}

const field = (label, input, help) => h("div.smf-field", h("label", label), input, help ? h("div.smf-dim.small", help) : null);

// SSD/HDD storage tiers (see the Storage tab)
function tiersSection(c, f, st) {
  f.archive_dir = h("input.smf-input", { value: c.archive_dir || "", placeholder: "e.g. F:\\SMF-Archive", style: { minWidth: "320px" } });
  f.archive_after_days = h("input.smf-input.small", { type: "number", min: "1", value: c.archive_after_days ?? 60 });
  f.restore_on_use = h("input", { type: "checkbox", checked: c.restore_on_use !== false });
  f.free_goal_gb = h("input.smf-input.small", { type: "number", min: "0", step: "10", value: c.free_goal_gb ?? 0 });
  f.protect_days = h("input.smf-input.small", { type: "number", min: "0", value: c.protect_days ?? 14 });
  f.archive_sections = {};
  const secs = h("div.smf-row.wrap", Object.entries(st.sections || {}).map(([k, label]) => {
    f.archive_sections[k] = h("input", { type: "checkbox", checked: (c.archive_sections || []).includes(k) });
    return h("label.smf-check", f.archive_sections[k], " ", label);
  }));
  const lmBtn = st.lm_installed && c.archive_dir ? h("button.smf-btn.small", {
    title: "LoRA Manager reads its folder list at startup; archived LoRAs need the archive in its extra folders",
    onclick: async () => {
      try {
        const { extra_folder_paths: add } = await call("/tiering/lm-paths");
        const cur = (await (await ctx.api.fetchApi("/lm/settings")).json())?.settings?.extra_folder_paths || {};
        const merged = { ...cur };
        for (const [k, v] of Object.entries(add)) merged[k] = [...new Set([...(cur[k] || []), ...v])];
        const r = await (await ctx.api.fetchApi("/lm/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ extra_folder_paths: merged }) })).json();
        if (!r?.success) throw new Error(r?.error || "LoRA Manager didn't accept the setting");
        toast("success", "LoRA Manager", "Archive folders added to its extra folders. Restart ComfyUI so LoRA Manager picks them up.", 9000);
      } catch (e) {
        toast("error", "LoRA Manager", e.message, 8000);
      }
    },
  }, "Add archive folders to LoRA Manager") : null;
  return h("section",
    h("h3", "Storage tiers (SSD / HDD)"),
    h("div.smf-dim.small", "Models unused for a while are suggested for this archive folder (Storage tab). It mirrors your Stability Matrix layout and is added to ComfyUI's model folders, so archived models keep their names — they just load more slowly. Leave empty to turn this off."),
    field("Archive folder", f.archive_dir),
    h("div.smf-row.top", field("Suggest after (days unused)", f.archive_after_days),
      field("Keep free on the SSD (GB)", f.free_goal_gb, "0 = off. Below it, the least recently used models are suggested too"),
      field("Never suggest models used in the last (days)", f.protect_days)),
    field("Model types to consider", secs),
    h("label.smf-check", f.restore_on_use, " Bring a model back to the SSD after a workflow uses it (once the queue is idle)"),
    lmBtn ? h("div.smf-row", lmBtn, h("span.smf-dim.small", "so LoRA Manager's loaders see archived LoRAs")) : null);
}

// Leftovers of unfinished downloads: our .smf-part files, other apps' partial
// files (browsers, HuggingFace, aria2) and .safetensors files cut short.
const KIND_LABEL = {
  partial: (p) => p.retryable ? pill("can resume", "ok", "A failed/interrupted download in the tray can still resume from this file") : pill("partial", "dim", "Model Librarian's partial download"),
  leftover: () => pill("leftover", "dim", "Left by an interrupted hard-link step"),
  other: (p) => pill(`partial · ${p.app}`, "warn", `A partial download, usually from ${p.app}; untouched for over 30 minutes`),
  truncated: () => pill("incomplete model", "bad", "Shorter than its own header says: it won't load. Delete it and download it again (Workflow → Find source)."),
};

function partialsSection() {
  const box = h("div");
  const find = async () => {
    clear(box, h("span.smf-dim", "Looking…"));
    try {
      const { partials } = await call("/partials");
      if (!partials.length) return clear(box, h("span.smf-dim.small", "No leftovers from unfinished downloads."));
      // pre-tick only our own files that nothing can resume; other apps' files and models are your call
      const sel = new Set(partials.filter((p) => p.kind === "partial" && !p.retryable || p.kind === "leftover").map((p) => p.path));
      const total = () => partials.filter((p) => sel.has(p.path)).reduce((a, p) => a + p.size, 0);
      const btn = h("button.smf-btn.warn");
      const label = () => { btn.textContent = `Delete ${sel.size} (${fmtSize(total())})`; btn.disabled = !sel.size; };
      btn.onclick = async () => {
        const models = partials.filter((p) => sel.has(p.path) && p.kind === "truncated").length;
        if (!confirm(`Delete ${sel.size} file(s), ${fmtSize(total())}?` + (models ? `\n\n${models} of them are incomplete model files: they don't load, but check they aren't still being copied.` : "") + "\n\nPartial downloads can't be resumed afterwards.")) return;
        const r = await call("/partials/delete", { method: "POST", body: { paths: [...sel] } });
        toast(r.errors.length ? "warn" : "success", "Leftover downloads", `${r.deleted} deleted, ${fmtSize(r.freed)} freed` + (r.errors.length ? ` · ${r.errors[0]}` : ""), 6000);
        find();
      };
      label();
      clear(box,
        h("table.smf-table", partials.map((p) => h("tr",
          h("td", h("input", { type: "checkbox", checked: sel.has(p.path), onchange: (e) => { e.target.checked ? sel.add(p.path) : sel.delete(p.path); label(); } })),
          h("td.small", { title: p.path }, p.path.split(/[\\/]/).slice(-2).join("/")),
          h("td.small", fmtSize(p.size)),
          h("td.small.smf-dim", `${p.age_days} days old`),
          h("td", (KIND_LABEL[p.kind] || KIND_LABEL.partial)(p))))),
        h("div.smf-toolbar", btn));
    } catch (e) {
      clear(box, h("span.err", e.message));
    }
  };
  return h("section",
    h("h3", "Leftover downloads"),
    h("div.smf-dim.small", "Unfinished downloads in your model folders: Model Librarian's .smf-part files (ones a download in the tray can still resume start unticked), partial files from browsers and other downloaders, and .safetensors files that were cut short and won't load."),
    h("div", h("button.smf-btn", { onclick: find }, "Find leftover downloads")),
    box);
}

// Once per session, when leftovers take real space (or a model file is incomplete).
export async function checkLeftovers() {
  try {
    if (sessionStorage.getItem("smf-leftovers-told")) return;
    const s = await call("/partials/summary");
    if (!s.truncated && (s.count - s.resumable === 0 || s.size < 512 * 1024 ** 2)) return;
    sessionStorage.setItem("smf-leftovers-told", "1");
    toast("info", "Leftover downloads", (s.truncated ? `${s.truncated} incomplete model file(s) won't load. ` : "") +
      `${s.count} leftover file(s), ${fmtSize(s.size)} — Library → Settings → Leftover downloads.`, 12000);
  } catch {}
}

// ================================================================ Settings
export async function mountSettings(root) {
  const st = await refreshStatus();
  const c = st.config;
  const f = {};
  // field() is defined at module level
  f.hf_token = h("input.smf-input", { type: "password", placeholder: c.has_hf_token ? "saved ✓ (type to replace)" : "hf_…", autocomplete: "off" });
  f.civitai_token = h("input.smf-input", { type: "password", placeholder: c.has_civitai_token ? "saved ✓ (type to replace)" : "CivitAI API key", autocomplete: "off" });
  f.vram_gb = h("input.smf-input", { type: "number", step: "0.5", min: "2", value: c.vram_gb });
  f.models_root = h("input.smf-input", { value: c.models_root || "", placeholder: st.sm?.models_root ? `found: ${st.sm.models_root}` : "e.g. E:\\Comfy-Desktop\\ComfyUI-Shared\\models" });
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
      fix_workflows_after_moves: f.fix_workflows_after_moves.checked,
      archive_dir: f.archive_dir.value.trim(), archive_after_days: f.archive_after_days.value || 60,
      free_goal_gb: f.free_goal_gb.value || 0, protect_days: f.protect_days.value || 0,
      restore_on_use: f.restore_on_use.checked,
      archive_sections: Object.entries(f.archive_sections).filter(([, el]) => el.checked).map(([k]) => k), nsfw_previews: f.nsfw_previews.checked,
      blur_nsfw: f.blur_nsfw.checked, share_data: f.share_data.checked, models_root: f.models_root.value.trim(), recipes_mirror_lm: f.recipes_mirror_lm.checked, check_updates: f.check_updates.checked, use_civarchive: f.use_civarchive.checked,
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
    h("tr", h("td", k), h("td.small", v.path), h("td", v.shared ? pill("shared folder", "ok") : pill("this install only", "warn"))));

  clear(root,
    h("div.smf-settings",
      kofiBanner(),
      h("section",
        h("h3", "API keys"),
        field("CivitAI API key", h("div.smf-row", f.civitai_token, c.has_civitai_token ? clearTok("civitai_token") : null),
          h("span", "civitai.com → Account settings → API Keys. Needed for many downloads and for metadata lookups.")),
        field("HuggingFace token", h("div.smf-row", f.hf_token, c.has_hf_token ? clearTok("hf_token") : null),
          h("span", "huggingface.co/settings/tokens (read access). Needed for gated models like FLUX.1-dev — accept the license on the model page first.")),
        h("div.smf-dim.small", "Keys are stored server-side in ComfyUI's user folder and never sent back to the browser. The env vars CIVITAI_API_KEY / HF_TOKEN also work.")),
      h("section",
        h("h3", "GPU"),
        h("div.smf-row.top", field("VRAM (GB)", f.vram_gb), field("Keep free (GB)", f.headroom_gb, "for activations/latents"),
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
        chk("blur_nsfw", "Blur NSFW models in the Library"),
        chk("recipes_mirror_lm", "Also save new recipes to LoRA Manager (when it's installed)"),
        chk("check_updates", "Check CivitAI for newer versions of my models once a day"),
        chk("use_civarchive", "Ask CivArchive about models CivitAI doesn't have (removed ones): details, and copies to download")),
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
      tiersSection(c, f, st),
      partialsSection(),
      h("section",
        h("h3", "Shared models and data"),
        h("div.smf-dim.small", "Models folder: ",
          st.sm?.models_root ? [h("code.small", st.sm.models_root), " ",
            pill({ manual: "set here", desktop: "Comfy Desktop", config: "Stability Matrix", "symlink-or-detected": "Stability Matrix" }[st.sm.mode] || st.sm.mode, "dim")]
            : pill("not found", "warn")),
        field("Models folder (leave blank to find it)", f.models_root,
          "Only needed if Model Librarian doesn't find your shared models folder by itself (Stability Matrix's, or the one Comfy Desktop uses). Applies to this install."),
        chk("share_data", "Share the registry, hash cache, undo history and settings with every ComfyUI that uses this models folder"),
        h("div", "Data folder: ", c.data_shared ? pill("shared", "ok") : pill("this install only", "warn"), " ",
          h("code.small", c.data_dir)),
        h("div.smf-dim.small", "API keys always stay in this install's user folder. When sharing turns on, this install's existing data is merged in; the local copies are kept as a backup.",
          !c.data_shared && c.share_data ? " No shared models folder was found, so data stays local." : "")),
      h("div.smf-toolbar", h("span.smf-spacer"), h("button.smf-btn.primary", { onclick: save }, "Save settings"))));
}
