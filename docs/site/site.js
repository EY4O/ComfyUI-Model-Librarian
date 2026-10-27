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
  mask.setAttribute("x", "0");  // the default region starts at -10%, which would clip the page's right-hand tenth
  mask.setAttribute("y", "0");
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

  // a polyline with its corners rounded (radius r, smaller where a segment is short)
  function rounded(pts, r) {
    let d = `M${pts[0][0]},${pts[0][1]}`;
    for (let i = 1; i < pts.length - 1; i++) {
      const [px, py] = pts[i - 1], [x, y] = pts[i], [nx, ny] = pts[i + 1];
      const k = Math.min(r, Math.hypot(x - px, y - py) / 2, Math.hypot(nx - x, ny - y) / 2);
      const ux = Math.sign(x - px), uy = Math.sign(y - py), vx = Math.sign(nx - x), vy = Math.sign(ny - y);
      d += ` L${x - ux * k},${y - uy * k} Q${x},${y} ${x + vx * k},${y + vy * k}`;
    }
    const [lx, ly] = pts[pts.length - 1];
    return d + ` L${lx},${ly}`;
  }

  // back-links that share a column on phones (everything stacks) get separate lanes so their verticals don't overlap
  const backLanes = new Map([["p-ckpt-vaep-dec-vae", 1]]);

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
        p.dataset.from = from;
        p.dataset.to = to;
        wireGroup.appendChild(p);
        paths.set(from + to, p);
      }
      p.style.display = "";
      if ((kind === "hero" || narrow) && b.x < a.x + 40) {
        // the target sits below or left of the source (same column): a curve would run behind both nodes,
        // so go round them through the gaps, like ComfyUI's straight links. Each back-link gets its own lane.
        const lane = backLanes.get(from + to) || 0, off = (narrow ? 14 : 18) + lane * 8;
        const gapY = nodeOf(to).getBoundingClientRect().top - main.getBoundingClientRect().top - (narrow ? 11 : 12);
        p.setAttribute("d", rounded([[a.x, a.y], [a.x + off, a.y], [a.x + off, gapY], [b.x - off, gapY], [b.x - off, b.y], [b.x, b.y]], 8));
      } else {
        // like ComfyUI's own wires: out to the right, in from the left, but never looping off the page
        const dx = Math.min(narrow ? 44 : 160, Math.max(narrow ? 36 : 70, Math.abs(b.x - a.x) * 0.45));
        p.setAttribute("d", `M${a.x},${a.y} C${a.x + dx},${a.y} ${b.x - dx},${b.y} ${b.x},${b.y}`);
      }
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
  let nudged = false;

  function reveal() {
    if (reduce) return;
    for (const p of paths.values()) {
      if (p.dataset.kind !== "flow" || drawn.has(p)) continue;
      const node = nodeOf(p.dataset.to);
      if (node && onScreen(node, 0.85)) {
        drawn.add(p);
        p.classList.add("drawing");
        p.addEventListener("transitionend", (e) => {
          if (e.propertyName !== "stroke-dashoffset") return;
          document.getElementById(p.dataset.to)?.animate([{ transform: "scale(1)" }, { transform: "scale(1.6)" }, { transform: "scale(1)" }],
            { duration: 360, easing: "cubic-bezier(0.23, 1, 0.32, 1)" });
        }, { once: true });
        requestAnimationFrame(() => { p.style.strokeDashoffset = 0; });
      }
    }
    // the sample workflow waits for the reader; when the panel is on screen its button glows, again and again until
    // it's first played in this browser, once on a visit after that
    if (state === "missing" && !nudged && onScreen(panel, 0.8)) {
      nudged = true;
      setTimeout(() => { if (state === "missing") runBtn.classList.add(played() ? "nudge" : "beckon"); }, 900);
    }
  }
  addEventListener("scroll", () => requestAnimationFrame(reveal), { passive: true });

  // ---------------------------------------------------------------- the top bar's current tab follows the reader
  const tabs = [...document.querySelectorAll('.tabs a[href^="#"]')];
  const sections = ["gallery", "install"].map((id) => document.getElementById(id)).filter(Boolean);  // (in page order, after the workflow)
  function currentTab() {
    if (!sections.length) return;
    const past = sections.filter((s) => s.getBoundingClientRect().top < innerHeight * 0.5);  // the last one reached
    const at = past.length ? `#${past[past.length - 1].id}` : "#top";
    for (const t of tabs) t.getAttribute("href") === at ? t.setAttribute("aria-current", "location") : t.removeAttribute("aria-current");
  }
  addEventListener("scroll", () => requestAnimationFrame(currentTab), { passive: true });
  addEventListener("hashchange", currentTab);
  currentTab();

  // ---------------------------------------------------------------- the sample workflow
  const graph = document.getElementById("graph");
  const panel = graph.querySelector(".g-panel"); // watched instead of the whole graph: stacked on a phone it is taller than the screen
  const runBtn = document.getElementById("run");
  const status = document.getElementById("run-status");
  const count = document.getElementById("ml-count");
  const ksBar = document.getElementById("ks-bar");
  let state = "missing"; // missing | running | done
  graph.classList.add("armed"); // without this script the sample picture simply shows
  const PLAYED = "ml-site-played"; // (this browser has played the sample workflow: its button stops beckoning)
  const played = () => { try { return localStorage.getItem(PLAYED) === "1"; } catch { return false; } };

  // a loader's wires light as soon as its model is in place; the rest light when the workflow can run
  function heroWires() {
    for (const p of paths.values()) {
      if (p.dataset.kind !== "hero") continue;
      const from = nodeOf(p.dataset.from);
      p.classList.toggle("dim", from.hasAttribute("data-missing") ? from.classList.contains("is-missing") : state !== "done");
    }
  }

  const wait = (ms) => new Promise((done) => setTimeout(done, ms));
  // steady progress, like a real download; started by the reader, so it plays under reduced motion too
  const tween = (ms, step) => new Promise((done) => {
    const t0 = performance.now();
    const tick = (t) => {
      const k = Math.min(1, (t - t0) / ms);
      step(k);
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
      row.classList.remove("verifying");
      const size = row.querySelector(".size");
      row.querySelector(".bar-fill").style.transform = "scaleX(0)";
      size.textContent = `0 of ${size.dataset.size}`;
    });
    ksBar.style.transform = "scaleX(0)";
    count.textContent = "2 missing";
    heroWires();
  }

  async function run() {
    if (state === "running") return;
    if (state === "done") reset();
    state = "running";
    runBtn.disabled = true;
    runBtn.classList.remove("nudge", "beckon");
    try { localStorage.setItem(PLAYED, "1"); } catch {}
    status.textContent = "Downloading from CivitAI into checkpoints and loras…";
    // both download side by side; each is checked, then its loader node comes good on its own
    await Promise.all([...graph.querySelectorAll("[data-row]")].map(async (row) => {
      const size = row.querySelector(".size"), fill = row.querySelector(".bar-fill");
      const [num, unit] = size.dataset.size.split(" ");
      const total = parseFloat(num), dp = unit === "GB" ? 2 : 0;
      await tween(+row.dataset.ms, (k) => {
        fill.style.transform = `scaleX(${k})`;
        size.textContent = `${(total * k).toFixed(dp)} of ${size.dataset.size}`;
      });
      row.classList.add("verifying");
      await wait(800);
      row.classList.remove("verifying");
      setPill(row.querySelector("[data-pill]"), true);
      const node = document.getElementById(row.dataset.node);
      node.classList.remove("is-missing");
      setPill(node.querySelector("[data-pill]"), true);
      count.textContent = `${graph.querySelectorAll("[data-row] [data-pill].missing").length} missing`;
      heroWires();
    }));
    state = "done";
    heroWires();
    status.textContent = "Both in place and checked. Queueing the workflow…";
    await wait(400);
    await tween(2200, (k) => { ksBar.style.transform = `scaleX(${k})`; });
    graph.classList.add("done");
    status.textContent = "Done: the workflow runs.";
    runBtn.disabled = false;
    runBtn.classList.add("ran");
  }

  runBtn.addEventListener("click", run);

  // ---------------------------------------------------------------- copy buttons
  document.querySelectorAll("[data-copy]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const code = document.getElementById(btn.dataset.copy);
      const label = btn.lastChild;
      const say = document.getElementById("copy-status");
      try { await navigator.clipboard.writeText(code.textContent); label.textContent = "Copied"; if (say) say.textContent = "Install command copied"; }
      catch { getSelection().selectAllChildren(code); label.textContent = "Selected"; if (say) say.textContent = "Install command selected; press Ctrl+C to copy"; }
      setTimeout(() => { label.textContent = "Copy"; }, 1600);
    });
  });

  // ---------------------------------------------------------------- videos play only while visible
  document.querySelectorAll("video[data-autoplay]").forEach((v) => {
    if (v.dataset.posterNarrow && matchMedia("(max-width: 720px)").matches) {
      v.poster = v.dataset.posterNarrow;
      [v.width, v.height] = v.dataset.narrowSize.split("x").map(Number);
    }
    if (reduce || !("IntersectionObserver" in window)) { v.controls = true; v.preload = "metadata"; return; }
    // a loop longer than five seconds needs a way to stop it (WCAG 2.2.2)
    const toggle = v.parentElement.querySelector(".media-toggle");
    let held = false;
    const show = () => {
      toggle.setAttribute("aria-pressed", String(held));
      toggle.querySelector("use").setAttribute("href", held ? "#i-resume" : "#i-pause");
      toggle.querySelector("span").textContent = held ? "Play" : "Pause";
    };
    if (toggle) {
      toggle.hidden = false;
      toggle.addEventListener("click", () => { held = !held; held ? v.pause() : v.play().catch(() => {}); show(); });
    }
    new IntersectionObserver(([e]) => {
      if (e.isIntersecting && !held) v.play().catch(() => { v.controls = true; });
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
