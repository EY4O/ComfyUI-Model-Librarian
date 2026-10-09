import { call, ctx, h, clear, fmtSize, toast, lmRescan } from "./util.js";

const listeners = new Set();
let timer = null;
let lastJobs = [];
let trayEl = null;
const announced = new Set();
let firstPoll = true;

export function onJobsChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function jobs() {
  return lastJobs;
}

export async function startDownload(payload) {
  const { job } = await call("/download", { method: "POST", body: payload });
  poll();
  return job;
}

export async function poll() {
  clearTimeout(timer);
  try {
    const { jobs } = await call("/jobs");
    if (firstPoll) {
      firstPoll = false;
      jobs.filter((j) => ["done", "error"].includes(j.status)).forEach((j) => announced.add(j.id));
    }
    const finishedNow = jobs.filter(
      (j) => ["done", "error"].includes(j.status) && !announced.has(j.id)
    );
    lastJobs = jobs;
    for (const j of finishedNow) {
      announced.add(j.id);
      if (j.status === "done") toast("success", "Downloaded", j.rel, 3000);
      else toast("error", "Download failed", `${j.rel}: ${j.error}`, 8000);
    }
    const doneNow = finishedNow.filter((j) => j.status === "done");
    if (doneNow.length) {
      lmRescan(doneNow.map((j) => j.folder));
      try {
        await ctx.app.refreshComboInNodes?.();
      } catch (e) {
        console.warn(e);
      }
    }
    renderTray();
    listeners.forEach((fn) => fn(jobs, finishedNow));
    const active = jobs.some((j) => ["queued", "downloading", "verifying"].includes(j.status));
    timer = setTimeout(poll, active ? 1000 : 5000);
  } catch (e) {
    timer = setTimeout(poll, 5000);
  }
}

export function stopPolling() {
  clearTimeout(timer);
}

export function mountTray(el) {
  trayEl = el;
  renderTray();
}

function renderTray() {
  if (!trayEl) return;
  const isActive = (j) => ["queued", "downloading", "verifying"].includes(j.status);
  const shown = lastJobs.filter(isActive).concat(lastJobs.filter((j) => !isActive(j)).slice(0, 3));
  if (!shown.length) {
    clear(trayEl);
    trayEl.style.display = "none";
    return;
  }
  trayEl.style.display = "";
  clear(
    trayEl,
    h("div.smf-tray-head",
      h("b", "Downloads"),
      h("button.smf-btn.small", { onclick: async () => { await call("/jobs/clear", { method: "POST" }); poll(); } }, "Clear finished")
    ),
    shown.map((j) => {
      const pct = j.total ? Math.min(100, (100 * j.done) / j.total) : 0;
      const active = ["queued", "downloading", "verifying"].includes(j.status);
      return h("div.smf-job." + j.status,
        h("div.smf-job-row",
          h("span.smf-job-name", { title: j.dest }, j.rel),
          h("span.smf-job-meta",
            j.status === "downloading"
              ? `${fmtSize(j.done)} / ${j.total ? fmtSize(j.total) : "?"} · ${fmtSize(j.speed)}/s`
              : j.status === "error" ? "Failed" : j.status),
          active ? h("button.smf-btn.small.ghost", { onclick: () => call(`/jobs/${j.id}/cancel`, { method: "POST" }).then(poll) }, "Cancel") : null
        ),
        h("div.smf-bar", h("div", { style: { width: (j.status === "done" ? 100 : pct) + "%" } })),
        j.error ? h("div.smf-job-err", j.error) : null
      );
    })
  );
}
