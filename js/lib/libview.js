// Library filtering and sorting, without the DOM (tested under Node).

export const SORTS = {
  folder: "Folder",
  name: "Name",
  used: "Most used",
  recent: "Recently used",
  rating: "My rating",
  size: "Size",
  newest: "Newest file",
};

export const sourceOf = (e) => (e.model_id ? "civitai" : e.hf ? "hf" : "none");

// v.folder, v.family, v.onlyMissing, v.onlyUpdates, v.onlyUnused + unused (Set), v.source,
// v.minRating, v.search; multiRoot: whether folder paths start with the root name
export function filterEntries(entries, v, { unused = null, multiRoot = false } = {}) {
  const q = (v.search || "").toLowerCase();
  return entries.filter((e) => {
    if (v.folder) {
      const full = (multiRoot ? e.root_name + "/" : "") + e.rel;
      if (!full.startsWith(v.folder + "/")) return false;
    }
    if (v.family === "__unknown" && e.family) return false;
    if (v.family && v.family !== "__unknown" && e.family !== v.family) return false;
    if (v.onlyMissing && e.has_meta) return false;
    if (v.onlyUpdates && !e.update) return false;
    if (v.onlyUnused && unused && !unused.has(e.id)) return false;
    if (v.source === "removed") {
      if (!e.removed) return false;
    } else if (v.source && sourceOf(e) !== v.source) return false;
    if (v.minRating && (e.notes?.rating || 0) < v.minRating) return false;
    if (q) {
      const hay = [e.name, e.title, ...(e.trained_words || []), e.base_label, e.hf?.repo, ...(e.hf?.tags || []),
        e.notes?.note, ...(e.notes?.tags || [])].filter(Boolean).join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
}

const byName = (a, b) => (a.title || a.name).localeCompare(b.title || b.name, undefined, { sensitivity: "base" });

export function sortEntries(list, sort) {
  const out = [...list];
  const desc = (f) => (a, b) => (f(b) - f(a)) || byName(a, b);
  if (sort === "used") out.sort(desc((e) => e.use_count || 0));
  else if (sort === "recent") out.sort(desc((e) => e.last_used || 0));
  else if (sort === "rating") out.sort(desc((e) => e.notes?.rating || 0));
  else if (sort === "size") out.sort(desc((e) => e.size || 0));
  else if (sort === "newest") out.sort(desc((e) => e.mtime || 0));
  else if (sort === "name") out.sort(byName);
  else out.sort((a, b) => a.rel.localeCompare(b.rel, undefined, { sensitivity: "base" }));
  return out;
}

export const stars = (n) => "★".repeat(n || 0) + "☆".repeat(5 - (n || 0));

// "today", "yesterday", "12 days ago", "never"
export function ago(t, now = Date.now() / 1000) {
  if (!t) return "never";
  const d = Math.floor((now - t) / 86400);
  return d <= 0 ? "today" : d === 1 ? "yesterday" : `${d} days ago`;
}
