// librarian.eternalpose.io: wires between node pins, the sample workflow's "Download all", copy buttons,
// and videos that play only while they're on screen. The page reads fine without any of it.
(() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const main = document.querySelector("main");
  const svg = document.querySelector("svg.wires");
  const NS = "http://www.w3.org/2000/svg";
  const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();

  // from pin, to pin, wire colour (ComfyUI slot-type colours: a link only joins slots of one type), kind: "hero" wires wait for the models; "flow" wires draw as you reach them
  const WIRES = [
    ["p-ckpt-model", "p-lora-in", "--w-model", "hero"],
    ["p-lora-model", "p-ks-in", "--w-model", "hero"],
    ["p-ks-out", "p-dec-samples", "--w-latent", "hero"],
    ["p-ckpt-vae", "p-dec-vae", "--w-vae", "hero"],
    ["p-dec-out", "p-save-in", "--w-image", "hero"],
    ["p-panel-out", "p-wf-in", "--w-model", "flow"],
    ["p-wf-out", "p-ext-in", "--w-model", "flow"],
    ["p-ext-out", "p-lib-in", "--w-model", "flow"],
    ["p-lib-out", "p-st-in", "--w-library", "flow"],
    ["p-st-out", "p-rec-in", "--w-library", "flow"],
    ["p-rec-out", "p-info-in", "--w-image", "flow"],
    ["p-info-out", "p-gal-in", "--w-image", "flow"],
  ];
  const paths = new Map();
  const drawn = new Set();

  function point(id) {
    const el = document.getElementById(id);
    if (!el || !el.offsetParent) return null;
    const r = el.getBoundingClientRect(), m = main.getBoundingClientRect();
    return { x: r.left + r.width / 2 - m.left, y: r.top + r.height / 2 - m.top };
  }

  const wireGroup = document.createElementNS(NS, "g");
  const mask = document.createElementNS(NS, "mask");
  mask.id = "wire-cut";
  mask.setAttribute("maskUnits", "userSpaceOnUse");
  const defs = document.createElementNS(NS, "defs");
  defs.appendChild(mask);
  svg.append(defs, wireGroup);
  wireGroup.setAttribute("mask", "url(#wire-cut)");

  function cutAroundText() {
    const m = main.getBoundingClientRect(), pad = 14;
    const rects = [`<rect x="0" y="0" width="${main.scrollWidth}" height="${main.scrollHeight}" fill="#fff"/>`];
    // one column (under 960px) puts text between the nodes a wire joins; side by side, wires only ever pass the caption
    const cut = innerWidth < 960 ? ".step-text, .graph .caption" : ".graph .caption";
    document.querySelectorAll(cut).forEach((el) => {
      const r = el.getBoundingClientRect();
      if (!r.width) return;
      rects.push(`<rect x="${r.left - m.left - pad}" y="${r.top - m.top - pad}" width="${r.width + pad * 2}" height="${r.height + pad * 2}" rx="12" fill="#000"/>`);
    });
    mask.setAttribute("width", main.scrollWidth);
    mask.setAttribute("height", main.scrollHeight);
    mask.innerHTML = rects.join("");
  }

  function layout() {
    svg.setAttribute("width", main.scrollWidth);
    svg.setAttribute("height", main.scrollHeight);
    cutAroundText();
    const narrow = innerWidth < 720;
    for (const [from, to, colour, kind] of WIRES) {
      const a = point(from), b = point(to);
      let p = paths.get(from + to);
      if (!a || !b) { if (p) p.style.display = "none"; continue; }
      if (!p) {
        p = document.createElementNS(NS, "path");
        p.setAttribute("stroke", css(colour));
        p.dataset.kind = kind;
        p.dataset.to = to;
        wireGroup.appendChild(p);
        paths.set(from + to, p);
      }
      p.style.display = "";
      // like ComfyUI's own wires: out to the right, in from the left, but never looping off the page
      const dx = Math.min(narrow ? 44 : 160, Math.max(narrow ? 36 : 70, Math.abs(b.x - a.x) * 0.45));
      p.setAttribute("d", `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`);
      if (kind === "flow" && !reduce) {
        const len = p.getTotalLength();
        p.style.strokeDasharray = len;
        if (!drawn.has(p)) p.style.strokeDashoffset = len;
      }
    }
    heroWires();
    reveal();
  }

  // ---------------------------------------------------------------- flow wires draw when their target node comes up the screen
  // (a plain scroll check: it also holds on phones, where the page is many screens tall)
  const nodeOf = (pinId) => document.getElementById(pinId)?.closest(".node");
  const onScreen = (el, at) => { const r = el.getBoundingClientRect(); return r.top < innerHeight * at && r.bottom > 0; };
  let autoTimer = 0;

  function reveal() {
    if (reduce) return;
    for (const p of paths.values()) {
      if (p.dataset.kind !== "flow" || drawn.has(p)) continue;
      const node = nodeOf(p.dataset.to);
      if (node && onScreen(node, 0.85)) {
        drawn.add(p);
        p.classList.add("drawing");
        requestAnimationFrame(() => { p.style.strokeDashoffset = 0; });
      }
    }
    // the sample workflow fixes itself the first time its panel is on screen
    if (state === "missing" && !autoTimer && onScreen(panel, 0.8)) autoTimer = setTimeout(run, 1400);
  }
  addEventListener("scroll", () => requestAnimationFrame(reveal), { passive: true });

  // ---------------------------------------------------------------- the sample workflow
  const graph = document.getElementById("graph");
  const panel = graph.querySelector(".g-panel"); // watched instead of the whole graph: stacked on a phone it is taller than the screen
  const runBtn = document.getElementById("run");
  const status = document.getElementById("run-status");
  const count = document.getElementById("ml-count");
  const ksBar = document.getElementById("ks-bar");
  let state = "missing"; // missing | running | done
  graph.classList.add("armed"); // without this script the sample picture simply shows

  function heroWires() {
    for (const p of paths.values()) if (p.dataset.kind === "hero") p.classList.toggle("dim", state !== "done");
  }

  const tween = (ms, step) => new Promise((done) => {
    if (reduce || ms === 0) { step(1); return done(); }
    const t0 = performance.now();
    const tick = (t) => {
      const k = Math.min(1, (t - t0) / ms);
      step(1 - Math.pow(1 - k, 3));
      k < 1 ? requestAnimationFrame(tick) : done();
    };
    requestAnimationFrame(tick);
  });

  function setPill(pill, ok) {
    pill.classList.toggle("missing", !ok);
    pill.classList.toggle("ok", ok);
    pill.textContent = ok ? "OK" : "Missing";
  }

  function reset() {
    state = "missing";
    graph.classList.remove("done");
    graph.querySelectorAll("[data-missing]").forEach((n) => n.classList.add("is-missing"));
    graph.querySelectorAll("[data-pill]").forEach((p) => setPill(p, false));
    graph.querySelectorAll("[data-row]").forEach((row) => {
      const size = row.querySelector(".size");
      row.querySelector(".bar-fill").style.width = "0";
      size.textContent = `0 of ${size.dataset.size}`;
    });
    ksBar.style.width = "0";
    count.textContent = "2 missing";
    heroWires();
  }

  async function run() {
    if (state === "running") return;
    if (state === "done") reset();
    state = "running";
    runBtn.disabled = true;
    status.textContent = "Downloading into checkpoints and loras…";
    await Promise.all([...graph.querySelectorAll("[data-row]")].map((row) => {
      const size = row.querySelector(".size"), fill = row.querySelector(".bar-fill");
      const [num, unit] = size.dataset.size.split(" ");
      const total = parseFloat(num), dp = unit === "GB" ? 2 : 0;
      return tween(+row.dataset.ms, (k) => {
        fill.style.width = `${k * 100}%`;
        size.textContent = `${(total * k).toFixed(dp)} of ${size.dataset.size}`;
      }).then(() => setPill(row.querySelector("[data-pill]"), true));
    }));
    graph.querySelectorAll("[data-missing]").forEach((n) => {
      n.classList.remove("is-missing");
      setPill(n.querySelector("[data-pill]"), true);
    });
    count.textContent = "0 missing";
    state = "done";
    heroWires();
    status.textContent = "Both in place and checked. Queueing the workflow…";
    await tween(900, (k) => { ksBar.style.width = `${k * 100}%`; });
    graph.classList.add("done");
    status.textContent = "Done: the workflow runs.";
    runBtn.disabled = false;
    runBtn.lastChild.textContent = "Run again";
  }

  runBtn.addEventListener("click", () => { clearTimeout(autoTimer); autoTimer = -1; run(); });

  // ---------------------------------------------------------------- copy buttons
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const code = document.getElementById(btn.dataset.copy);
      const label = btn.lastChild;
      try { await navigator.clipboard.writeText(code.textContent); label.textContent = "Copied"; }
      catch { getSelection().selectAllChildren(code); label.textContent = "Selected"; }
      setTimeout(() => { label.textContent = "Copy"; }, 1600);
    });
  });

  // ---------------------------------------------------------------- videos play only while visible
  document.querySelectorAll("video[data-autoplay]").forEach((v) => {
    if (v.dataset.posterNarrow && matchMedia("(max-width: 720px)").matches) {
      v.poster = v.dataset.posterNarrow;
      v.width = 492;
      v.height = 530;
    }
    if (reduce || !("IntersectionObserver" in window)) { v.controls = true; v.preload = "metadata"; return; }
    new IntersectionObserver(([e]) => {
      if (e.isIntersecting) v.play().catch(() => { v.controls = true; });
      else v.pause();
    }, { threshold: 0.4 }).observe(v);
  });

  // ---------------------------------------------------------------- keep the wires on their pins
  let raf = 0;
  const relayout = () => { cancelAnimationFrame(raf); raf = requestAnimationFrame(layout); };
  new ResizeObserver(relayout).observe(main);
  addEventListener("load", relayout);
  if (document.fonts) document.fonts.ready.then(relayout);
  layout();
})();
