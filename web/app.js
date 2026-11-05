/* Market Desk - news brief + concall summaries. Plain JS, no dependencies. */
(function () {
  "use strict";
  const IDX = window.DESK_INDEX || { briefs: [], updated: "" };
  const $ = (s, el) => (el || document).querySelector(s);
  const view = $("#view");
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const cssv = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* storage unavailable */ } },
  };
  const theme = store.get("theme", "auto");
  if (theme !== "auto") document.documentElement.dataset.theme = theme;

  /* ------------------------------------------------------------ data */
  function loadScript(src) {
    return new Promise((res, rej) => {
      const s = document.createElement("script");
      s.src = src; s.onload = res; s.onerror = () => rej(new Error("Couldn't load " + src));
      document.head.appendChild(s);
    });
  }
  async function getBrief(date) {
    window.DESK_BRIEFS = window.DESK_BRIEFS || {};
    if (!window.DESK_BRIEFS[date]) await loadScript("data/brief-" + date + ".js");
    return window.DESK_BRIEFS[date];
  }
  async function getConcalls() {
    if (!window.DESK_CONCALLS) {
      try { await loadScript("data/concalls.js"); } catch (e) { window.DESK_CONCALLS = { calls: [], overviews: [] }; }
    }
    return window.DESK_CONCALLS;
  }
  const dates = () => IDX.briefs.map((b) => b.date);
  const latest = () => (IDX.briefs.length ? IDX.briefs[IDX.briefs.length - 1].date : null);
  let current = null;
  let currentBrief = null;

  /* ------------------------------------------------------------ helpers */
  const norm = (s) => String(s || "").toLowerCase().replace(/&/g, " and ").replace(/['.]/g, "")
    .replace(/\b(limited|ltd|the)\b/g, "").replace(/[^a-z0-9]+/g, "");
  function sameCo(a, b) {
    const x = norm(a), y = norm(b);
    return !!x && !!y && (x === y || (x.length > 3 && y.startsWith(x)) || (y.length > 3 && x.startsWith(y)));
  }
  const SENT = { "+": ["Positive", "p", "▲"], "-": ["Negative", "n", "▼"], "=": ["Neutral", "z", "•"] };
  const sentChip = (s) => { const t = SENT[s] || SENT["="]; return `<span class="sent ${t[1]}">${t[2]} ${t[0]}</span>`; };
  const impDots = (n) => `<span class="imp" title="Importance ${n} of 5">${"●".repeat(n)}${"○".repeat(5 - n)}</span>`;
  const when = (iso) => new Date(iso).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  const fmt = (n) => Number(n).toLocaleString("en-IN");
  const plural = (n, w) => `${fmt(n)} ${n === 1 ? w : /[^aeiou]y$/.test(w) ? w.slice(0, -1) + "ies" : w + "s"}`;
  const watchlist = () => store.get("watchlist", []);
  const go = (h) => { location.hash = h; };
  const empty = (msg) => `<div class="empty">${msg}</div>`;

  /* ------------------------------------------------------------ tooltip */
  const tip = $("#tip");
  function showTip(html, ev) { tip.innerHTML = html; tip.hidden = false; moveTip(ev); }
  function moveTip(ev) {
    const w = tip.offsetWidth, h = tip.offsetHeight;
    let x = ev.clientX + 14, y = ev.clientY + 14;
    if (x + w > innerWidth - 8) x = ev.clientX - w - 14;
    if (y + h > innerHeight - 8) y = ev.clientY - h - 14;
    tip.style.left = Math.max(8, x) + "px"; tip.style.top = Math.max(8, y) + "px";
  }
  function hideTip() { tip.hidden = true; }
  addEventListener("scroll", hideTip, { passive: true });

  /* ------------------------------------------------------------ charts (SVG) */
  const NS = "http://www.w3.org/2000/svg";
  const redraws = [];
  function svg(w, h) {
    const s = document.createElementNS(NS, "svg");
    s.setAttribute("viewBox", `0 0 ${w} ${h}`); s.setAttribute("width", w); s.setAttribute("height", h);
    s.setAttribute("class", "chart"); s.setAttribute("role", "img"); return s;
  }
  function el(name, attrs, parent, text) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (text != null) e.textContent = text;
    if (parent) parent.appendChild(e);
    return e;
  }
  // bar with only its data-end rounded (4px), anchored at x0
  function barPath(x0, x1, y, h) {
    const r = Math.min(4, Math.abs(x1 - x0), h / 2);
    if (Math.abs(x1 - x0) < 0.5) return "";
    if (x1 > x0) return `M${x0},${y}H${x1 - r}Q${x1},${y} ${x1},${y + r}V${y + h - r}Q${x1},${y + h} ${x1 - r},${y + h}H${x0}Z`;
    return `M${x0},${y}H${x1 + r}Q${x1},${y} ${x1},${y + r}V${y + h - r}Q${x1},${y + h} ${x1 + r},${y + h}H${x0}Z`;
  }
  function trunc(s, n) { return s.length > n ? s.slice(0, n - 1) + "…" : s; }
  function tableView(head, rows) {
    return `<details class="tablev"><summary>Show as table</summary><table><tr>${head.map((h) => `<th>${esc(h)}</th>`).join("")}</tr>` +
      rows.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join("")}</tr>`).join("") + "</table></details>";
  }
  function mount(host, draw) {
    const f = () => { host.innerHTML = ""; draw(host, Math.max(260, host.clientWidth)); };
    f(); redraws.push(f);
  }
  let rt;
  addEventListener("resize", () => { clearTimeout(rt); rt = setTimeout(() => redraws.forEach((f) => f()), 150); });

  /** Sector mood: negative stories to the left, positive to the right. */
  function divergingChart(host, rows) {
    mount(host, (h, W) => {
      const narrow = W < 520, labW = narrow ? 112 : 168, valW = 30, rowH = 30, barH = 16;
      const H = rows.length * rowH + 8;
      const s = svg(W, H);
      const mid = labW + (W - labW) / 2;
      const max = Math.max(1, ...rows.map((r) => Math.max(r.pos, r.neg)));
      const sc = ((W - labW) / 2 - valW - 4) / max;
      el("line", { x1: mid, x2: mid, y1: 0, y2: H, class: "axis" }, s);
      rows.forEach((r, i) => {
        const y = i * rowH + 4, by = y + (rowH - barH) / 2 - 2;
        const g = el("g", { class: "row" }, s);
        el("rect", { x: 0, y, width: W, height: rowH - 2, rx: 6, class: "hl", fill: "transparent" }, g);
        el("text", { x: labW - 10, y: by + barH - 3, "text-anchor": "end", class: "lab" }, g, trunc(r.label, narrow ? 15 : 24));
        if (r.neg) el("path", { d: barPath(mid - 1, mid - 1 - r.neg * sc, by, barH), fill: cssv("--neg") }, g);
        if (r.pos) el("path", { d: barPath(mid + 1, mid + 1 + r.pos * sc, by, barH), fill: cssv("--pos") }, g);
        if (r.neg) el("text", { x: mid - 6 - r.neg * sc, y: by + barH - 3, "text-anchor": "end", class: "val" }, g, r.neg);
        if (r.pos) el("text", { x: mid + 6 + r.pos * sc, y: by + barH - 3, class: "val" }, g, r.pos);
        const hit = el("rect", { x: 0, y, width: W, height: rowH, class: "hit" }, g);
        const html = `<b>${esc(r.label)}</b><br>${plural(r.total, "story")}<br>` +
          `<span class="sw" style="background:${cssv("--pos")}"></span>${r.pos} positive<br>` +
          `<span class="sw" style="background:${cssv("--neg")}"></span>${r.neg} negative<br>` +
          `<span class="sw" style="background:${cssv("--neu")}"></span>${r.neu} neutral<br><span class="m">Tap to open the sector</span>`;
        hit.addEventListener("mousemove", (e) => showTip(html, e));
        hit.addEventListener("mouseleave", hideTip);
        hit.addEventListener("click", () => { hideTip(); r.onclick && r.onclick(); });
      });
      h.appendChild(s);
    });
  }

  /** Horizontal bars, one series. */
  function barChart(host, rows, unit) {
    mount(host, (h, W) => {
      const narrow = W < 520, labW = narrow ? 120 : 170, rowH = 28, barH = 15;
      const H = rows.length * rowH + 6;
      const s = svg(W, H);
      const max = Math.max(1, ...rows.map((r) => r.value));
      const sc = (W - labW - 40) / max;
      rows.forEach((r, i) => {
        const y = i * rowH + 3, by = y + (rowH - barH) / 2 - 2;
        const g = el("g", { class: "row" }, s);
        el("rect", { x: 0, y, width: W, height: rowH - 2, rx: 6, class: "hl", fill: "transparent" }, g);
        el("text", { x: labW - 10, y: by + barH - 3, "text-anchor": "end", class: "lab" }, g, trunc(r.label, narrow ? 16 : 24));
        el("path", { d: barPath(labW, labW + r.value * sc, by, barH), fill: cssv("--s1") }, g);
        el("text", { x: labW + r.value * sc + 6, y: by + barH - 3, class: "val" }, g, r.value);
        const hit = el("rect", { x: 0, y, width: W, height: rowH, class: "hit" }, g);
        const html = `<b>${esc(r.label)}</b><br>${plural(r.value, unit)}${r.note ? "<br>" + r.note : ""}`;
        hit.addEventListener("mousemove", (e) => showTip(html, e));
        hit.addEventListener("mouseleave", hideTip);
        hit.addEventListener("click", () => { hideTip(); r.onclick && r.onclick(); });
      });
      h.appendChild(s);
    });
  }

  /** Lines over time with a crosshair tooltip. */
  function lineChart(host, xs, series) {
    mount(host, (h, W) => {
      const H = 230, L = 34, R = 14, T = 10, B = 26;
      const s = svg(W, H);
      const max = Math.max(1, ...series.flatMap((se) => se.values));
      const step = Math.pow(10, Math.floor(Math.log10(max)));
      const top = Math.ceil(max / step) * step;
      const x = (i) => L + (xs.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (xs.length - 1));
      const y = (v) => T + (H - T - B) * (1 - v / top);
      for (let k = 0; k <= 4; k++) {
        const v = (top * k) / 4, yy = y(v);
        el("line", { x1: L, x2: W - R, y1: yy, y2: yy, class: "gridl" }, s);
        el("text", { x: L - 6, y: yy + 4, "text-anchor": "end" }, s, Math.round(v));
      }
      const every = Math.ceil(xs.length / Math.max(2, Math.floor((W - L - R) / 70)));
      xs.forEach((d, i) => {
        if (i % every === 0 || i === xs.length - 1)
          el("text", { x: x(i), y: H - 6, "text-anchor": "middle" }, s, d.slice(8) + "/" + d.slice(5, 7));
      });
      series.forEach((se) => {
        const pts = se.values.map((v, i) => `${x(i)},${y(v)}`).join(" ");
        el("polyline", { points: pts, fill: "none", stroke: se.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, s);
        const li = se.values.length - 1;
        el("circle", { cx: x(li), cy: y(se.values[li]), r: 4, fill: se.color, stroke: cssv("--surface"), "stroke-width": 2 }, s);
      });
      const cross = el("line", { x1: 0, x2: 0, y1: T, y2: H - B, stroke: cssv("--text-2"), "stroke-width": 1, "stroke-dasharray": "3 3", visibility: "hidden" }, s);
      const ov = el("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" }, s);
      const at = (e) => {
        const r = s.getBoundingClientRect();
        const px = ((e.clientX - r.left) / r.width) * W;
        let best = 0;
        xs.forEach((_, i) => { if (Math.abs(x(i) - px) < Math.abs(x(best) - px)) best = i; });
        return best;
      };
      ov.addEventListener("mousemove", (e) => {
        const i = at(e);
        cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
        const rows = series.map((se) => [se, se.values[i]]).sort((a, b) => b[1] - a[1]);
        showTip(`<b>${esc(xs[i])}</b><br>` + rows.map(([se, v]) =>
          `<span class="sw" style="background:${se.color}"></span>${esc(se.name)}: ${v}`).join("<br>"), e);
      });
      ov.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
      h.appendChild(s);
    });
  }

  /** Stacked horizontal bars (concall tone mix per sector). */
  function stackChart(host, rows, keys) {
    mount(host, (h, W) => {
      const narrow = W < 520, labW = narrow ? 120 : 190, rowH = 28, barH = 15;
      const H = rows.length * rowH + 6;
      const s = svg(W, H);
      const max = Math.max(1, ...rows.map((r) => keys.reduce((a, k) => a + (r.parts[k.key] || 0), 0)));
      const sc = (W - labW - 40) / max;
      rows.forEach((r, i) => {
        const y = i * rowH + 3, by = y + (rowH - barH) / 2 - 2;
        const g = el("g", { class: "row" }, s);
        el("rect", { x: 0, y, width: W, height: rowH - 2, rx: 6, class: "hl", fill: "transparent" }, g);
        el("text", { x: labW - 10, y: by + barH - 3, "text-anchor": "end", class: "lab" }, g, trunc(r.label, narrow ? 16 : 26));
        let x0 = labW, tot = 0;
        keys.forEach((k, ki) => {
          const v = r.parts[k.key] || 0;
          if (!v) return;
          const w = v * sc - 2;
          const isLast = keys.slice(ki + 1).every((k2) => !(r.parts[k2.key] || 0));
          if (isLast) el("path", { d: barPath(x0, x0 + Math.max(1, w), by, barH), fill: k.color }, g);
          else el("rect", { x: x0, y: by, width: Math.max(1, w), height: barH, fill: k.color }, g);
          x0 += v * sc; tot += v;
        });
        el("text", { x: x0 + 4, y: by + barH - 3, class: "val" }, g, tot);
        const hit = el("rect", { x: 0, y, width: W, height: rowH, class: "hit" }, g);
        const html = `<b>${esc(r.label)}</b><br>` + keys.map((k) =>
          `<span class="sw" style="background:${k.color}"></span>${k.key}: ${r.parts[k.key] || 0}`).join("<br>");
        hit.addEventListener("mousemove", (e) => showTip(html, e));
        hit.addEventListener("mouseleave", hideTip);
        hit.addEventListener("click", () => { hideTip(); r.onclick && r.onclick(); });
      });
      h.appendChild(s);
    });
  }
  /** Scatter: one dot per company, dashed medians, hover + tap. */
  function scatterChart(host, pts, xl, yl) {
    mount(host, (h, W) => {
      const H = 300, L = 46, R = 16, T = 12, B = 40;
      const s = svg(W, H);
      const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
      const pad = (lo, hi) => { const d = (hi - lo) || Math.abs(hi) || 1; return [lo - d * 0.08, hi + d * 0.08]; };
      const [x0, x1] = pad(Math.min(0, ...xs), Math.max(...xs)), [y0, y1] = pad(Math.min(0, ...ys), Math.max(...ys));
      const X = (v) => L + ((v - x0) / (x1 - x0)) * (W - L - R), Y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
      for (let k = 0; k <= 4; k++) {
        const vy = y0 + ((y1 - y0) * k) / 4, vx = x0 + ((x1 - x0) * k) / 4;
        el("line", { x1: L, x2: W - R, y1: Y(vy), y2: Y(vy), class: "gridl" }, s);
        el("text", { x: L - 6, y: Y(vy) + 4, "text-anchor": "end" }, s, Math.round(vy * 10) / 10);
        el("text", { x: X(vx), y: H - B + 16, "text-anchor": "middle" }, s, Math.round(vx * 10) / 10);
      }
      if (x0 < 0) el("line", { x1: X(0), x2: X(0), y1: T, y2: H - B, class: "axis" }, s);
      if (y0 < 0) el("line", { x1: L, x2: W - R, y1: Y(0), y2: Y(0), class: "axis" }, s);
      const med = (a) => { const b = a.slice().sort((p, q) => p - q), m = b.length >> 1; return b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2; };
      const mx = med(xs), my = med(ys);
      el("line", { x1: X(mx), x2: X(mx), y1: T, y2: H - B, stroke: cssv("--muted"), "stroke-dasharray": "4 4", "stroke-width": 1 }, s);
      el("line", { x1: L, x2: W - R, y1: Y(my), y2: Y(my), stroke: cssv("--muted"), "stroke-dasharray": "4 4", "stroke-width": 1 }, s);
      el("text", { x: (L + W - R) / 2, y: H - 4, "text-anchor": "middle" }, s, xl);
      const yt = el("text", { x: 12, y: (T + H - B) / 2, "text-anchor": "middle", transform: `rotate(-90 12 ${(T + H - B) / 2})` }, s, yl);
      yt.setAttribute("class", "val");
      pts.forEach((p) => {
        const dot = el("circle", { cx: X(p.x), cy: Y(p.y), r: 5, fill: cssv("--s1"), stroke: cssv("--surface"), "stroke-width": 2, style: "cursor:pointer" }, s);
        const hit = el("circle", { cx: X(p.x), cy: Y(p.y), r: 12, fill: "transparent", style: "cursor:pointer" }, s);
        const html = `<b>${esc(p.label)}</b><br>${esc(xl)}: ${p.x}<br>${esc(yl)}: ${p.y}<br><span class="m">Tap to open</span>`;
        hit.addEventListener("mousemove", (e) => { dot.setAttribute("r", 7); showTip(html, e); });
        hit.addEventListener("mouseleave", () => { dot.setAttribute("r", 5); hideTip(); });
        hit.addEventListener("click", () => { hideTip(); p.onclick && p.onclick(); });
      });
      h.appendChild(s);
    });
  }

  /** Ranked bars that may be negative (growth, margin change). */
  function rankChart(host, rows, unit) {
    mount(host, (h, W) => {
      const narrow = W < 520, labW = narrow ? 120 : 190, rowH = 26, barH = 14;
      const H = rows.length * rowH + 6, s = svg(W, H);
      const hasNeg = rows.some((r) => r.value < 0);
      const lo = Math.min(0, ...rows.map((r) => r.value)), hi = Math.max(0, ...rows.map((r) => r.value));
      const span = W - labW - (hasNeg ? 90 : 50);
      const sc = span / ((hi - lo) || 1);
      const zero = labW + (hasNeg ? 40 : 0) + -lo * sc;
      if (hasNeg) el("line", { x1: zero, x2: zero, y1: 0, y2: H, class: "axis" }, s);
      rows.forEach((r, i) => {
        const y = i * rowH + 3, by = y + (rowH - barH) / 2 - 2;
        const g = el("g", { class: "row" }, s);
        el("rect", { x: 0, y, width: W, height: rowH - 2, rx: 6, class: "hl", fill: "transparent" }, g);
        el("text", { x: labW - 10, y: by + barH - 3, "text-anchor": "end", class: "lab" }, g, trunc(r.label, narrow ? 16 : 26));
        const end = zero + r.value * sc;
        el("path", { d: barPath(zero, end, by, barH), fill: cssv("--s1") }, g);
        el("text", { x: r.value >= 0 ? end + 5 : end - 5, y: by + barH - 3, "text-anchor": r.value >= 0 ? "start" : "end", class: "val" }, g,
          (Math.round(r.value * 10) / 10) + (r.flag ? " ⚠" : ""));
        const hit = el("rect", { x: 0, y, width: W, height: rowH, class: "hit" }, g);
        const html = `<b>${esc(r.label)}</b><br>${Math.round(r.value * 100) / 100} ${esc(unit)}${r.flag ? "<br>⚠ not stated word-for-word in the transcript (likely calculated)" : ""}`;
        hit.addEventListener("mousemove", (e) => showTip(html, e));
        hit.addEventListener("mouseleave", hideTip);
        hit.addEventListener("click", () => { hideTip(); r.onclick && r.onclick(); });
      });
      h.appendChild(s);
    });
  }
  const legend = (items) => `<div class="legend">${items.map(([n, c]) => `<span><i style="background:${c}"></i>${esc(n)}</span>`).join("")}</div>`;

  /* ------------------------------------------------------------ story popover */
  const pop = $("#pop"), popCard = $("#pop-card");
  function openStory(id) {
    const b = currentBrief;
    const all = b ? b.stories.concat(...(b.tabs || []).map((t) => t.stories)) : [];
    const s = all.find((x) => x.id === Number(id));
    if (!s) return;
    const ex = (b.top || []).find((t) => t.id === s.id);
    popCard.innerHTML = `<button class="x" aria-label="Close">×</button>
      <h3>${esc(s.title)}</h3>
      <div style="margin:6px 0 10px">${s.imp ? sentChip(s.sent) + " &nbsp; " + impDots(s.imp) + " &nbsp; " : ""}<span class="m">${when(s.when)}</span></div>
      <div><span class="chip link" data-go="${s.imp ? "#sectors/" : "#tab/"}${encodeURIComponent(s.cat)}">${esc(s.cat)}</span>${
        s.companies.map((c) => `<span class="chip link" data-go="#companies/${encodeURIComponent(c)}">${esc(c)}</span>`).join("")}</div>
      ${s.desc ? `<p>${esc(s.desc)}</p>` : ""}
      ${ex ? `<div class="explain card" style="padding:10px 14px;margin:10px 0">
        ${ex.context ? `<div class="row"><b>Context:</b> ${esc(ex.context)}</div>` : ""}
        ${ex.why ? `<div class="row"><b>Why it matters:</b> ${esc(ex.why)}</div>` : ""}
        ${ex.watch ? `<div class="row"><b>What to watch:</b> ${esc(ex.watch)}</div>` : ""}</div>` : ""}
      <div class="m">Covered by ${plural(s.outlets, "outlet")}:</div>
      <ul>${s.sources.map((x) => `<li><a href="${esc(x.link)}" target="_blank" rel="noopener">${esc(x.name)}</a></li>`).join("")}</ul>`;
    pop.hidden = false;
  }
  pop.addEventListener("click", (e) => {
    if (e.target === pop || e.target.closest(".x")) pop.hidden = true;
    const g = e.target.closest("[data-go]");
    if (g) { pop.hidden = true; go(g.dataset.go); }
  });
  addEventListener("keydown", (e) => { if (e.key === "Escape") pop.hidden = true; });
  document.addEventListener("click", (e) => {
    const r = e.target.closest("a.r");
    if (r && r.dataset.id) { e.preventDefault(); openStory(r.dataset.id); return; }
    const t = e.target.closest("[data-story]");
    if (t) { openStory(t.dataset.story); return; }
    const g = e.target.closest("[data-go]");
    if (g && !pop.contains(g)) go(g.dataset.go);
  });

  function storyItem(s) {
    return `<li><div class="t" data-story="${s.id}">${esc(s.title)}</div>
      <div class="src">${sentChip(s.sent)} · ${impDots(s.imp)} · ${esc(s.sources.map((x) => x.name).filter((v, i, a) => a.indexOf(v) === i).join(", "))} · ${when(s.when)}</div></li>`;
  }

  /* ------------------------------------------------------------ pages */
  function dateNav(date) {
    const ds = dates(), i = ds.indexOf(date);
    const prev = i > 0 ? ds[i - 1] : null, next = i >= 0 && i < ds.length - 1 ? ds[i + 1] : null;
    return `<div class="filters">
      <button ${prev ? `data-go="#today/${prev}"` : "disabled"}>← Earlier</button>
      <select id="datesel">${ds.slice().reverse().map((d) => `<option value="${d}" ${d === date ? "selected" : ""}>${
        esc(IDX.briefs.find((b) => b.date === d).label)}</option>`).join("")}</select>
      <button ${next ? `data-go="#today/${next}"` : "disabled"}>Later →</button></div>`;
  }

  async function pageToday(date) {
    if (!IDX.briefs.length) { view.innerHTML = empty("No news brief yet - it appears here after the first morning run."); return; }
    date = date || latest();
    const b = await getBrief(date);
    current = date; currentBrief = b;
    const st = b.stats;
    const pos = b.sections.reduce((a, s) => a + s.pos, 0), neg = b.sections.reduce((a, s) => a + s.neg, 0);
    const mood = pos + neg ? Math.round((100 * pos) / (pos + neg)) : 50;
    const topSec = b.sections[0];
    const wl = watchlist();
    const wlStories = wl.length ? b.stories.filter((s) => wl.some((w) =>
      s.title.toLowerCase().includes(w.toLowerCase()) || s.companies.some((c) => sameCo(c, w) || c.toLowerCase().includes(w.toLowerCase())))) : [];
    const byId = Object.fromEntries(b.stories.map((s) => [s.id, s]));
    const top = (b.top || []).filter((t) => byId[t.id]);
    view.innerHTML = `
      <h1>Morning brief</h1>
      <div class="sub">${esc(b.label)} · last ${b.hours}h · ${fmt(st.articles)} articles from ${plural(st.sources, "source")} → ${plural(st.relevant, "market story")} · built ${esc(b.built.slice(11, 16))}</div>
      ${dateNav(date)}
      <div class="tiles">
        <div class="tile"><div class="v">${fmt(st.relevant)}</div><div class="k">market stories</div></div>
        <div class="tile"><div class="v">${b.sections.length}</div><div class="k">sectors & topics in the news</div></div>
        <div class="tile"><div class="v" style="color:${mood >= 50 ? cssv("--pos") : cssv("--neg")}">${mood}%</div><div class="k">of sentiment-bearing stories positive (${pos}▲ ${neg}▼)</div></div>
        <div class="tile"><div class="v" style="font-size:18px">${esc(topSec ? topSec.cat : "-")}</div><div class="k">busiest sector (${topSec ? plural(topSec.ids.length, "story") : ""})</div></div>
      </div>
      ${b.big ? `<div class="card md"><h2>The big picture</h2>${b.big}</div>` : ""}
      ${wl.length ? `<div class="card"><h2>Your watchlist <span class="m">${esc(wl.join(", "))}</span></h2>${
        wlStories.length ? `<ul class="list">${wlStories.map(storyItem).join("")}</ul>` : `<div class="m">No news on your watchlist in this brief.</div>`}</div>` : ""}
      ${top.length ? `<h2 style="margin:18px 0 10px">Top stories, explained</h2><div class="grid g2" id="topx">${top.map((t, ti) => {
        const s = byId[t.id];
        return `<div class="card explain" ${ti >= 6 ? 'data-more hidden' : ""}><h3 class="t" data-story="${s.id}" style="cursor:pointer">${esc(s.title)}</h3>
          <div style="margin-bottom:6px">${sentChip(s.sent)} · ${impDots(s.imp)} · <span class="chip link" data-go="#sectors/${encodeURIComponent(s.cat)}">${esc(s.cat)}</span></div>
          ${t.context ? `<div class="row"><b>Context:</b> ${esc(t.context)}</div>` : ""}
          ${t.why ? `<div class="row"><b>Why it matters:</b> ${esc(t.why)}</div>` : ""}
          ${t.watch ? `<div class="row"><b>What to watch:</b> ${esc(t.watch)}</div>` : ""}
          <div class="src" style="margin-top:6px">${plural(s.outlets, "outlet")}: ${esc(s.sources.slice(0, 4).map((x) => x.name).join(", "))}</div></div>`;
      }).join("")}</div>${top.length > 6 ? `<button id="morex">Show ${top.length - 6} more explained stories</button>` : ""}` : ""}
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h2>Sector mood <span class="m">stories by sentiment</span></h2>
          ${legend([["Negative", cssv("--neg")], ["Positive", cssv("--pos")]])}<div id="c-mood"></div><div id="t-mood"></div></div>
        <div class="card"><h2>News flow <span class="m">stories per day, busiest sectors</span></h2><div id="l-flow"></div><div id="c-flow"></div><div id="t-flow"></div></div>
      </div>
      <div class="grid g2">
        <div class="card"><h2>Most-mentioned companies</h2><div id="c-comp"></div><div id="t-comp"></div></div>
        <div class="card"><h2>Sector by sector</h2><ul class="list">${b.sections.map((s) => `<li>
          <a href="#sectors/${encodeURIComponent(s.cat)}" style="text-decoration:none"><b>${esc(s.cat)}</b></a>
          <span class="m">${plural(s.ids.length, "story")} · ${s.pos}▲ ${s.neg}▼</span>
          ${s.one ? `<div class="md" style="font-size:14px">${s.one}</div>` : ""}</li>`).join("")}</ul></div>
      </div>
      ${b.failed && b.failed.length ? `<details class="card"><summary class="m" style="cursor:pointer">${plural(b.failed.length, "feed")} didn't load this time</summary>
        <ul class="list">${b.failed.map((f) => `<li>${esc(f.name)} <span class="src">(${esc(f.folder)}) - ${esc(f.error)}</span></li>`).join("")}</ul></details>` : ""}`;
    $("#datesel").onchange = (e) => go("#today/" + e.target.value);
    const mx = $("#morex");
    if (mx) mx.onclick = () => { view.querySelectorAll("[data-more]").forEach((d) => { d.hidden = false; }); mx.remove(); };

    const moodRows = b.sections.slice(0, 14).map((s) => ({ label: s.cat, pos: s.pos, neg: s.neg, neu: s.neu, total: s.ids.length,
      onclick: () => go("#sectors/" + encodeURIComponent(s.cat)) }));
    divergingChart($("#c-mood"), moodRows);
    $("#t-mood").innerHTML = tableView(["Sector", "Positive", "Negative", "Neutral"], moodRows.map((r) => [r.label, r.pos, r.neg, r.neu]));

    const hist = IDX.briefs.filter((x) => x.date <= date).slice(-14);
    if (hist.length < 2) {
      $("#c-flow").innerHTML = `<div class="m" style="padding:30px 0">The trend fills in after a few days of briefs.</div>`;
    } else {
      const totals = {};
      hist.forEach((x) => Object.entries(x.cats).forEach(([c, n]) => { totals[c] = (totals[c] || 0) + n; }));
      const topCats = Object.keys(totals).sort((a, c) => totals[c] - totals[a]).slice(0, 5);
      const colors = ["--s1", "--s2", "--s3", "--s4", "--s5"].map(cssv);
      const series = topCats.map((c, i) => ({ name: c, color: colors[i], values: hist.map((x) => x.cats[c] || 0) }));
      $("#l-flow").innerHTML = legend(series.map((se) => [se.name, se.color]));
      lineChart($("#c-flow"), hist.map((x) => x.date), series);
      $("#t-flow").innerHTML = tableView(["Date"].concat(topCats), hist.map((x, i) => [x.date].concat(series.map((se) => se.values[i]))));
    }

    const comp = {};
    b.stories.forEach((s) => s.companies.forEach((c) => { (comp[c] = comp[c] || []).push(s); }));
    const compRows = Object.entries(comp).sort((a, c) => c[1].length - a[1].length).slice(0, 12).map(([c, list]) => {
      const p = list.filter((s) => s.sent === "+").length, n = list.filter((s) => s.sent === "-").length;
      return { label: c, value: list.length, note: `${p}▲ ${n}▼`, onclick: () => go("#companies/" + encodeURIComponent(c)) };
    });
    if (compRows.length) {
      barChart($("#c-comp"), compRows, "story");
      $("#t-comp").innerHTML = tableView(["Company", "Stories"], compRows.map((r) => [r.label, r.value]));
    } else $("#c-comp").innerHTML = `<div class="m">No company-specific stories.</div>`;
  }

  async function pageSectors(cat) {
    if (!IDX.briefs.length) { view.innerHTML = empty("No news brief yet."); return; }
    const b = currentBrief || (await getBrief(current || latest()));
    currentBrief = b; current = b.date;
    const sec = b.sections.find((s) => s.cat === cat) || b.sections[0];
    if (!sec) { view.innerHTML = empty("No sectors in this brief."); return; }
    const byId = Object.fromEntries(b.stories.map((s) => [s.id, s]));
    const cc = await getConcalls();
    const ov = cc.overviews.filter((o) => o.sector === sec.cat).sort((a, c) => (a.quarter < c.quarter ? 1 : -1))[0];
    const calls = cc.calls.filter((c) => c.sector === sec.cat);
    view.innerHTML = `<h1>Sectors</h1><div class="sub">${esc(b.label)} · <a href="#today/${b.date}">back to the brief</a></div>
      <div class="side">
        <div class="card secnav">${b.sections.map((s) => `<a href="#sectors/${encodeURIComponent(s.cat)}" class="${s.cat === sec.cat ? "on" : ""}">
          <span>${esc(s.cat)}</span><span class="m">${s.ids.length}</span></a>`).join("")}</div>
        <div>
          <div class="card md"><h2>${esc(sec.cat)} <span class="m">${plural(sec.ids.length, "story")} · ${sec.pos}▲ ${sec.neg}▼ ${sec.neu}•</span></h2>
            ${sec.one ? `<p><b>${sec.one}</b></p>` : ""}${sec.html || `<p class="m">Too few stories today for a write-up - see the list below.</p>`}</div>
          <div class="card"><h2>All stories</h2>
            <div class="filters"><select id="fs"><option value="">Any sentiment</option><option value="+">Positive</option><option value="-">Negative</option><option value="=">Neutral</option></select>
            <select id="fi"><option value="1">Any importance</option><option value="3">Importance 3+</option><option value="4">Importance 4+</option></select></div>
            <ul class="list" id="sl"></ul></div>
          ${ov || calls.length ? `<div class="card"><h2>From the concalls <span class="m">what managements said</span></h2>
            ${ov ? `<details class="sum"><summary><span class="n">${esc(sec.cat)} - sector overview</span><span class="m">${esc(ov.quarter)} · ${ov.companies.length} companies</span></summary><div class="b md">${ov.html}</div></details>` : ""}
            <div>${calls.map((c) => `<span class="chip link" data-go="#companies/${encodeURIComponent(c.company)}">${esc(c.company)} ${c.tone ? "· " + esc(c.tone) : ""}</span>`).join("")}</div></div>` : ""}
        </div></div>`;
    const list = () => {
      const fs = $("#fs").value, fi = Number($("#fi").value);
      const items = sec.ids.map((i) => byId[i]).filter((s) => s && (!fs || s.sent === fs) && s.imp >= fi);
      $("#sl").innerHTML = items.map(storyItem).join("") || `<li class="m">Nothing matches.</li>`;
    };
    $("#fs").onchange = list; $("#fi").onchange = list; list();
  }

  async function pageCompanies(name) {
    const cc = await getConcalls();
    const recent = IDX.briefs.slice(-7);
    const briefs = [];
    for (const x of recent) { try { briefs.push(await getBrief(x.date)); } catch (e) { /* missing file */ } }
    if (!currentBrief && briefs.length) { currentBrief = briefs[briefs.length - 1]; current = currentBrief.date; }
    const mentions = {};
    briefs.forEach((b) => b.stories.forEach((s) => s.companies.forEach((c) => {
      const k = Object.keys(mentions).find((m) => sameCo(m, c)) || c;
      (mentions[k] = mentions[k] || []).push({ s, date: b.date });
    })));
    cc.calls.forEach((c) => { if (!Object.keys(mentions).some((m) => sameCo(m, c.company))) mentions[c.company] = mentions[c.company] || []; });
    if (!name) {
      const names = Object.keys(mentions).sort((a, c) => mentions[c].length - mentions[a].length || a.localeCompare(c));
      view.innerHTML = `<h1>Companies</h1><div class="sub">News mentions over the last ${plural(briefs.length, "brief")}, and concall summaries</div>
        <div class="filters"><input type="search" id="cq" placeholder="Search a company"></div>
        <div class="card"><ul class="list" id="cl"></ul></div>`;
      const draw = () => {
        const q = $("#cq").value.toLowerCase();
        $("#cl").innerHTML = names.filter((n) => !q || n.toLowerCase().includes(q)).slice(0, 300).map((n) => {
          const m = mentions[n], call = cc.calls.find((c) => sameCo(c.company, n));
          return `<li><a href="#companies/${encodeURIComponent(n)}" style="text-decoration:none"><b>${esc(n)}</b></a>
            <span class="m">${m.length ? plural(m.length, "story") : "no recent news"}</span>
            ${call ? `<span class="badge">concall ${esc(call.quarter)}</span> ${call.tone ? `<span class="tone ${esc(call.tone)}">${esc(call.tone)}</span>` : ""}` : ""}</li>`;
        }).join("") || `<li class="m">No match.</li>`;
      };
      $("#cq").oninput = draw; draw();
      return;
    }
    const key = Object.keys(mentions).find((m) => sameCo(m, name)) || name;
    const seenT = new Set();
    const items = (mentions[key] || []).sort((a, c) => (a.s.when < c.s.when ? 1 : -1))
      .filter((x) => { const k = x.s.title.toLowerCase().replace(/\W+/g, ""); if (seenT.has(k)) return false; seenT.add(k); return true; });
    const call = cc.calls.filter((c) => sameCo(c.company, name)).sort((a, c) => (a.date < c.date ? 1 : -1))[0];
    const p = items.filter((x) => x.s.sent === "+").length, n = items.filter((x) => x.s.sent === "-").length;
    view.innerHTML = `<h1>${esc(key)}</h1><div class="sub"><a href="#companies">All companies</a> · ${plural(items.length, "story")} in the last ${plural(briefs.length, "brief")} · ${p}▲ ${n}▼</div>
      <div class="grid g2">
        <div class="card"><h2>In the news</h2>${items.length ? `<ul class="list">${items.map(({ s, date }) => `<li>
          <div class="t" data-story-date="${date}" data-sid="${s.id}">${esc(s.title)}</div>
          <div class="src">${sentChip(s.sent)} · ${impDots(s.imp)} · ${esc(s.cat)} · ${when(s.when)}</div></li>`).join("")}</ul>` : `<div class="m">No news in recent briefs.</div>`}</div>
        <div class="card md"><h2>Latest concall</h2>${call ? `<div style="margin-bottom:8px"><span class="badge">${esc(call.quarter)}</span>
          ${call.tone ? `<span class="tone ${esc(call.tone)}">${esc(call.tone)}</span>` : ""} ${call.compared ? `<span class="badge">vs last quarter</span>` : ""}
          ${call.checks.length ? `<span class="badge w">⚠ ${call.checks.length} to check</span>` : ""} <span class="m">· ${esc(call.sector)} · filed ${esc(call.date)}</span></div>
          ${call.checks.length ? `<div class="warn">Highlighted figures weren't found word-for-word in the transcript - check them in the PDF.</div>` : ""}
          ${keyFigures(call)}${call.html}<p><a href="${esc(call.pdf)}" target="_blank" rel="noopener">Original transcript (PDF)</a></p>` : `<div class="m">No concall summary for this company yet.</div>`}</div>
      </div>`;
    view.querySelectorAll("[data-sid]").forEach((d) => d.addEventListener("click", async () => {
      currentBrief = await getBrief(d.dataset.storyDate); current = currentBrief.date; openStory(d.dataset.sid);
    }));
  }

  function keyFigures(c) {
    const m = c.metrics || {};
    const ks = colsFor(c.sector).filter((k) => typeof m[k] === "number");
    if (!ks.length) return "";
    return `<div class="tiles" style="margin:6px 0 4px">${ks.map((k) => `<div class="tile"><div class="v" style="font-size:19px">${fmtM(m[k])}${
      c.unchecked.includes(k) ? ' <span title="Not stated word-for-word in the transcript - likely calculated" style="font-size:13px">⚠</span>' : ""}</div>
      <div class="k">${esc(MET[k][0])} · ${esc(MET[k][1])}</div></div>`).join("")}</div>
      <div class="m" style="margin-bottom:6px"><a href="#peers/${encodeURIComponent(c.sector)}">Compare with ${esc(c.sector)} peers →</a></div>`;
  }

  async function pageConcalls(sector) {
    const cc = await getConcalls();
    if (!cc.calls.length) { view.innerHTML = empty("No concall summaries yet."); return; }
    const sectors = [...new Set(cc.calls.map((c) => c.sector))].sort();
    const quarters = [...new Set(cc.calls.map((c) => c.quarter))].sort((a, b) => (a.slice(-2) + a[1] < b.slice(-2) + b[1] ? 1 : -1));
    const latestQ = quarters[0];
    const keys = [["Positive", "--pos"], ["Mixed", "--neu"], ["Cautious", "--caution"], ["Negative", "--neg"]].map(([k, v]) => ({ key: k, color: cssv(v) }));
    view.innerHTML = `<h1>Concalls</h1><div class="sub">${plural(cc.calls.length, "summary", )} · ${plural(cc.overviews.length, "sector overview")}</div>
      <div class="card"><h2>Management tone by sector <span class="m">${esc(latestQ)} calls</span></h2>
        ${legend(keys.map((k) => [k.key, k.color]))}<div id="c-tone"></div><div id="t-tone"></div></div>
      <div class="filters"><select id="ks"><option value="">All sectors</option>${sectors.map((s) => `<option ${s === sector ? "selected" : ""}>${esc(s)}</option>`).join("")}</select>
        <select id="kq"><option value="">All quarters</option>${quarters.map((q) => `<option>${esc(q)}</option>`).join("")}</select>
        <input type="search" id="kf" placeholder="Search company or any word (cotton, capex, tariff…)"></div>
      <div id="kl"></div>`;
    const tones = {};
    cc.calls.filter((c) => c.quarter === latestQ).forEach((c) => {
      const t = tones[c.sector] = tones[c.sector] || {};
      const k = ["Positive", "Mixed", "Cautious", "Negative"].includes(c.tone) ? c.tone : "Mixed";
      t[k] = (t[k] || 0) + 1;
    });
    const toneRows = Object.entries(tones).sort((a, b) => Object.values(b[1]).reduce((x, y) => x + y, 0) - Object.values(a[1]).reduce((x, y) => x + y, 0))
      .map(([s, parts]) => ({ label: s, parts, onclick: () => { $("#ks").value = s; draw(); } }));
    stackChart($("#c-tone"), toneRows, keys);
    $("#t-tone").innerHTML = tableView(["Sector"].concat(keys.map((k) => k.key)), toneRows.map((r) => [r.label].concat(keys.map((k) => r.parts[k.key] || 0))));
    const draw = () => {
      const s = $("#ks").value, q = $("#kq").value, f = $("#kf").value.toLowerCase();
      const ovs = cc.overviews.filter((o) => (!s || o.sector === s) && (!q || o.quarter === q) && (!f || o.html.toLowerCase().includes(f)));
      const calls = cc.calls.filter((c) => (!s || c.sector === s) && (!q || c.quarter === q) &&
        (!f || (c.company + " " + c.html).toLowerCase().includes(f))).sort((a, b) => (a.date < b.date ? 1 : -1));
      $("#kl").innerHTML = ovs.map((o) => `<details class="sum" ${s ? "open" : ""}><summary><span class="n" style="color:var(--accent)">${esc(o.sector)} - sector overview</span>
          <span class="m">${esc(o.quarter)} · ${o.companies.length} companies</span></summary><div class="b md">${o.html}</div></details>`).join("") +
        calls.map((c) => `<details class="sum"><summary><span class="n">${esc(c.company)}</span><span class="m">${esc(c.quarter)} · ${esc(c.sector)} · filed ${esc(c.date)}</span>
          <span class="r2">${c.compared ? `<span class="badge" title="Includes what changed vs last quarter">vs last qtr</span>` : ""}
          ${c.checks.length ? `<span class="badge w" title="Figures not found word-for-word in the transcript">⚠ ${c.checks.length}</span>` : ""}
          ${c.tone ? `<span class="tone ${esc(c.tone)}">${esc(c.tone)}</span>` : ""}</span></summary>
          <div class="b md">${c.checks.length ? `<div class="warn">Highlighted figures weren't found word-for-word in the transcript - they may be calculated by the AI or misread.</div>` : ""}
          ${c.html}<p><a href="${esc(c.pdf)}" target="_blank" rel="noopener">Original transcript (PDF)</a> · <a href="#companies/${encodeURIComponent(c.company)}">News on ${esc(c.company)}</a></p></div></details>`).join("") ||
        empty("Nothing matches.");
    };
    $("#ks").onchange = draw; $("#kq").onchange = draw; $("#kf").oninput = draw; draw();
  }

  const FIN = ["Banks", "NBFC & Financial Services", "Insurance"];
  const MET = {
    revenue_cr: ["Revenue", "Rs cr"], revenue_growth_yoy_pct: ["Revenue growth", "% YoY"],
    ebitda_margin_pct: ["EBITDA margin", "%"], ebitda_margin_change_bps_yoy: ["Margin change", "bps YoY"],
    pat_cr: ["PAT", "Rs cr"], pat_growth_yoy_pct: ["PAT growth", "% YoY"], capacity_utilisation_pct: ["Utilisation", "%"],
    net_debt_cr: ["Net debt", "Rs cr (−=cash)"], capex_guidance_cr: ["Capex guidance", "Rs cr"],
    loan_book_or_aum_growth_yoy_pct: ["Loan/AUM growth", "% YoY"], nim_pct: ["NIM", "%"],
    gross_npa_pct: ["Gross NPA", "%"], credit_cost_pct: ["Credit cost", "%"],
  };
  const colsFor = (sector) => FIN.includes(sector)
    ? ["loan_book_or_aum_growth_yoy_pct", "nim_pct", "gross_npa_pct", "credit_cost_pct", "pat_cr", "pat_growth_yoy_pct"]
    : ["revenue_cr", "revenue_growth_yoy_pct", "ebitda_margin_pct", "ebitda_margin_change_bps_yoy", "pat_growth_yoy_pct",
       "capacity_utilisation_pct", "net_debt_cr", "capex_guidance_cr"];
  const TONE_N = { Positive: 3, Mixed: 2, Cautious: 1, Negative: 0 };
  const fmtM = (v) => (v == null ? "–" : Math.abs(v) >= 100 ? fmt(Math.round(v)) : String(Math.round(v * 10) / 10));

  async function pagePeers(sector) {
    const cc = await getConcalls();
    const byCo = {};
    cc.calls.forEach((c) => { const k = norm(c.company); if (!byCo[k] || c.date > byCo[k].date) byCo[k] = c; });
    const latest = Object.values(byCo);
    const withM = latest.filter((c) => Object.values(c.metrics || {}).some((v) => typeof v === "number"));
    if (!withM.length) { view.innerHTML = empty("Peer figures appear here as concalls are summarised."); return; }
    const counts = {};
    withM.forEach((c) => { counts[c.sector] = (counts[c.sector] || 0) + 1; });
    const sectors = Object.keys(counts).sort((a, b) => counts[b] - counts[a] || a.localeCompare(b));
    sector = sectors.includes(sector) ? sector : sectors[0];
    const rows = withM.filter((c) => c.sector === sector);
    // only columns that at least one company in this sector actually reported
    const cols = colsFor(sector).filter((k) => rows.some((c) => typeof c.metrics[k] === "number"));
    const fin = FIN.includes(sector);
    const xKey = fin ? "loan_book_or_aum_growth_yoy_pct" : "revenue_growth_yoy_pct";
    const yKey = fin ? "nim_pct" : "ebitda_margin_pct";

    // market-wide: guidance and tone shift by sector
    const guid = {}, shift = {};
    latest.forEach((c) => {
      const gd = (c.metrics || {}).guidance;
      if (gd && gd !== "none") { const g = guid[c.sector] = guid[c.sector] || {}; const k = gd === "initiated" ? "raised" : gd; g[k] = (g[k] || 0) + 1; }
      if (c.prev_tone && c.tone && c.prev_tone in TONE_N && c.tone in TONE_N) {
        const t = shift[c.sector] = shift[c.sector] || { pos: 0, neg: 0, neu: 0 };
        const d = TONE_N[c.tone] - TONE_N[c.prev_tone];
        if (d > 0) t.pos++; else if (d < 0) t.neg++; else t.neu++;
      }
    });

    view.innerHTML = `<h1>Peer comparison</h1>
      <div class="sub">Key figures from each company's latest concall · ⚠ = not stated word-for-word in the transcript (usually calculated) · tap a company for its summary</div>
      <div class="filters"><select id="ps">${sectors.map((s) => `<option ${s === sector ? "selected" : ""}>${esc(s)} (${counts[s]})</option>`).join("")}</select></div>
      <div class="card"><h2>${esc(sector)} <span class="m">${plural(rows.length, "company")}</span></h2>
        <div style="overflow-x:auto"><table class="peer" id="pt"></table></div></div>
      <div class="grid g2">
        <div class="card"><h2>${esc(MET[xKey][0])} vs ${esc(MET[yKey][0])} <span class="m">dashed lines = sector median</span></h2><div id="c-sc"></div></div>
        <div class="card"><h2>Rank by <select id="rk">${cols.map((k) => `<option value="${k}" ${k === yKey ? "selected" : ""}>${esc(MET[k][0])}</option>`).join("")}</select></h2><div id="c-rk"></div><div id="t-rk"></div></div>
      </div>
      <div class="grid g2">
        <div class="card"><h2>Guidance this quarter <span class="m">all sectors</span></h2>
          ${legend([["Raised", cssv("--pos")], ["Maintained", cssv("--neu")], ["Cut", cssv("--neg")]])}<div id="c-gd"></div><div id="t-gd"></div></div>
        <div class="card"><h2>Tone vs last quarter <span class="m">companies whose management sounded better / worse</span></h2>
          ${legend([["Worse", cssv("--neg")], ["Better", cssv("--pos")]])}<div id="c-sh"></div><div id="t-sh"></div></div>
      </div>`;
    $("#ps").onchange = (e) => go("#peers/" + encodeURIComponent(e.target.value.replace(/ \(\d+\)$/, "")));

    let sortKey = yKey, dir = -1;
    const drawTable = () => {
      const val = (c, k) => (k === "company" ? c.company : k === "tone" ? (TONE_N[c.tone] ?? -1) : k === "guidance" ? (c.metrics.guidance || "") : c.metrics[k]);
      const sorted = rows.slice().sort((a, b) => {
        const x = val(a, sortKey), y = val(b, sortKey);
        if (x == null) return 1; if (y == null) return -1;
        return (x > y ? 1 : x < y ? -1 : 0) * dir;
      });
      const th = (k, label, unit) => `<th data-k="${k}" title="Sort">${esc(label)}${unit ? `<br><span class="m">${esc(unit)}</span>` : ""}${sortKey === k ? (dir < 0 ? " ▼" : " ▲") : ""}</th>`;
      $("#pt").innerHTML = `<tr>${th("company", "Company")}${th("tone", "Tone")}${cols.map((k) => th(k, MET[k][0], MET[k][1])).join("")}${th("guidance", "Guidance")}</tr>` +
        sorted.map((c) => `<tr><td><a href="#companies/${encodeURIComponent(c.company)}">${esc(c.company)}</a><br><span class="m">${esc(c.quarter)}</span></td>
          <td>${c.tone ? `<span class="tone ${esc(c.tone)}">${esc(c.tone)}</span>` : "–"}${c.prev_tone && c.prev_tone !== c.tone ? `<br><span class="m">was ${esc(c.prev_tone)}</span>` : ""}</td>
          ${cols.map((k) => `<td class="num">${fmtM(c.metrics[k])}${c.unchecked.includes(k) && c.metrics[k] != null ? ' <span title="Not stated word-for-word in the transcript - likely calculated">⚠</span>' : ""}</td>`).join("")}
          <td>${esc(c.metrics.guidance && c.metrics.guidance !== "none" ? c.metrics.guidance : "–")}</td></tr>`).join("");
      $("#pt").querySelectorAll("th").forEach((t) => t.onclick = () => { const k = t.dataset.k; dir = sortKey === k ? -dir : -1; sortKey = k; drawTable(); });
    };
    drawTable();

    const pts = rows.filter((c) => typeof c.metrics[xKey] === "number" && typeof c.metrics[yKey] === "number")
      .map((c) => ({ label: c.company, x: c.metrics[xKey], y: c.metrics[yKey], onclick: () => go("#companies/" + encodeURIComponent(c.company)) }));
    if (pts.length >= 2) scatterChart($("#c-sc"), pts, MET[xKey][0] + " (" + MET[xKey][1] + ")", MET[yKey][0] + " (" + MET[yKey][1] + ")");
    else $("#c-sc").innerHTML = `<div class="m" style="padding:30px 0">Needs at least two companies with both figures.</div>`;

    const drawRank = () => {
      const k = $("#rk").value;
      const rr = rows.filter((c) => typeof c.metrics[k] === "number").sort((a, b) => b.metrics[k] - a.metrics[k])
        .map((c) => ({ label: c.company, value: c.metrics[k], flag: c.unchecked.includes(k), onclick: () => go("#companies/" + encodeURIComponent(c.company)) }));
      if (rr.length) { rankChart($("#c-rk"), rr, MET[k][1]); $("#t-rk").innerHTML = tableView(["Company", MET[k][0]], rr.map((r) => [r.label, r.value])); }
      else { $("#c-rk").innerHTML = `<div class="m">No company stated this figure.</div>`; $("#t-rk").innerHTML = ""; }
    };
    const drawMarket = () => {
      const gRows = Object.entries(guid).sort((a, b) => Object.values(b[1]).reduce((x, y) => x + y, 0) - Object.values(a[1]).reduce((x, y) => x + y, 0)).slice(0, 14)
        .map(([s, parts]) => ({ label: s, parts: { Raised: parts.raised || 0, Maintained: parts.maintained || 0, Cut: parts.cut || 0 }, onclick: () => go("#peers/" + encodeURIComponent(s)) }));
      const gKeys = [{ key: "Raised", color: cssv("--pos") }, { key: "Maintained", color: cssv("--neu") }, { key: "Cut", color: cssv("--neg") }];
      if (gRows.length) { stackChart($("#c-gd"), gRows, gKeys); $("#t-gd").innerHTML = tableView(["Sector", "Raised", "Maintained", "Cut"], gRows.map((r) => [r.label, r.parts.Raised, r.parts.Maintained, r.parts.Cut])); }
      else $("#c-gd").innerHTML = `<div class="m">No guidance changes recorded yet.</div>`;
      const sRows = Object.entries(shift).sort((a, b) => (b[1].pos + b[1].neg + b[1].neu) - (a[1].pos + a[1].neg + a[1].neu)).slice(0, 14)
        .map(([s, t]) => ({ label: s, pos: t.pos, neg: t.neg, neu: t.neu, total: t.pos + t.neg + t.neu, onclick: () => go("#peers/" + encodeURIComponent(s)) }));
      if (sRows.length) { divergingChart($("#c-sh"), sRows); $("#t-sh").innerHTML = tableView(["Sector", "Better", "Worse", "Same"], sRows.map((r) => [r.label, r.pos, r.neg, r.neu])); }
      else $("#c-sh").innerHTML = `<div class="m">Fills in as companies are compared with last quarter.</div>`;
    };
    $("#rk").onchange = drawRank;
    drawRank();
    drawMarket();
  }

  async function pageTab(name) {
    if (!IDX.briefs.length) { view.innerHTML = empty("Nothing yet."); return; }
    const b = currentBrief && currentBrief.date === (current || latest()) ? currentBrief : await getBrief(current || latest());
    currentBrief = b; current = b.date;
    const t = (b.tabs || []).find((x) => x.name === name);
    if (!t || !t.stories.length) { view.innerHTML = empty(`No ${esc(name)} stories in this edition.`); return; }
    view.innerHTML = `<h1>${esc(t.name)}</h1>
      <div class="sub">${esc(b.label)} · ${fmt(t.stats.articles || 0)} articles from ${plural(t.stats.feeds || 0, "feed")} → ${plural(t.stats.stories || 0, "story")} · top ${t.stories.length} by coverage</div>
      ${t.html ? `<div class="card md">${t.one ? `<p><b>${t.one}</b></p>` : ""}${t.html}</div>` : ""}
      <div class="card"><h2>Most-covered stories <span class="m">tap for all sources</span></h2>
        <div class="filters"><input type="search" id="tq" placeholder="Search ${esc(t.name.toLowerCase())} stories"></div>
        <ul class="list" id="tl"></ul></div>`;
    const draw = () => {
      const q = $("#tq").value.toLowerCase();
      $("#tl").innerHTML = t.stories.filter((s) => !q || s.title.toLowerCase().includes(q)).map((s) => `<li>
        <div class="t" data-story="${s.id}">${esc(s.title)}</div>
        <div class="src">${plural(s.outlets, "outlet")} · ${esc(s.sources.map((x) => x.name).filter((v, i, a) => a.indexOf(v) === i).slice(0, 4).join(", "))} · ${when(s.when)}</div></li>`).join("")
        || `<li class="m">Nothing matches.</li>`;
    };
    $("#tq").oninput = draw; draw();
  }

  function pageArchive() {
    if (!IDX.briefs.length) { view.innerHTML = empty("No briefs yet."); return; }
    view.innerHTML = `<h1>Archive</h1><div class="sub">Every morning brief (about three months are kept)</div>
      <div class="card archive">${IDX.briefs.slice().reverse().map((b) => {
        const top = Object.entries(b.cats).sort((x, y) => y[1] - x[1]).slice(0, 3).map((x) => x[0]).join(", ");
        return `<a href="#today/${b.date}"><span><b>${esc(b.label)}</b><br><span class="m">${esc(top)}</span></span>
          <span class="m" style="text-align:right">${plural(b.stats.relevant, "story")}<br>${fmt(b.stats.articles)} articles</span></a>`;
      }).join("")}</div>`;
  }

  function pageSettings() {
    view.innerHTML = `<h1>Settings</h1><div class="sub">Saved in this browser only - your watchlist is never published.</div>
      <div class="card"><h2>Watchlist</h2><p class="help">Companies to pull to the top of every brief. Separate with commas; part of a name is enough.</p>
        <input type="text" id="wl" style="width:100%" placeholder="e.g. Trident, Apollo Hospitals, KPR Mill" value="${esc(watchlist().join(", "))}">
        <div style="margin-top:10px"><button class="primary" id="wls">Save</button> <span class="m" id="wlm"></span></div></div>
      <div class="card"><h2>Appearance</h2><select id="th"><option value="auto">Match my device</option><option value="light">Light</option><option value="dark">Dark</option></select></div>
      <div class="card help"><h2>About</h2>
        <p>The site is rebuilt automatically every morning: news from your RSS feeds (last 24 hours), and summaries of new concall transcripts filed on BSE.</p>
        <p>Last update: <b>${esc((IDX.updated || "").replace("T", " "))}</b> · ${plural(IDX.briefs.length, "brief")} · ${plural(IDX.concalls || 0, "concall summary")}.</p>
        <p>On a tablet or phone, use your browser's menu → <b>Add to Home screen</b> to open it like an app.</p>
        <p>Summaries are written by AI from headlines and transcripts. Check important figures against the linked sources.</p></div>`;
    $("#wls").onclick = () => {
      const v = $("#wl").value.split(",").map((x) => x.trim()).filter(Boolean);
      store.set("watchlist", v); $("#wlm").textContent = "Saved.";
    };
    $("#th").value = store.get("theme", "auto");
    $("#th").onchange = (e) => {
      store.set("theme", e.target.value);
      if (e.target.value === "auto") delete document.documentElement.dataset.theme;
      else document.documentElement.dataset.theme = e.target.value;
    };
  }

  /* ------------------------------------------------------------ router */
  async function route() {
    hideTip(); pop.hidden = true; redraws.length = 0;
    const h = decodeURIComponent(location.hash.slice(1)) || "today";
    const [tab, ...rest] = h.split("/");
    const arg = rest.join("/");
    const key = tab === "tab" ? "tab-" + arg : tab;
    document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === key));
    try {
      if (tab === "today") await pageToday(arg || null);
      else if (tab === "sectors") await pageSectors(arg || null);
      else if (tab === "companies") await pageCompanies(arg || null);
      else if (tab === "concalls") await pageConcalls(arg || null);
      else if (tab === "peers") await pagePeers(arg || null);
      else if (tab === "tab") await pageTab(arg);
      else if (tab === "archive") pageArchive();
      else if (tab === "settings") pageSettings();
      else await pageToday(null);
    } catch (e) {
      view.innerHTML = empty("Something went wrong loading this page: " + esc(e.message));
    }
    if (!arg) scrollTo(0, 0);
  }
  // extra tabs (e.g. Tech, Auto) from the latest edition, placed before Archive
  const arch = document.querySelector('#tabs a[data-tab="archive"]');
  (IDX.tabs || []).forEach((n) => {
    const a = document.createElement("a");
    a.href = "#tab/" + encodeURIComponent(n); a.dataset.tab = "tab-" + n; a.textContent = n;
    arch.parentNode.insertBefore(a, arch);
  });
  addEventListener("hashchange", route);
  route();
})();
