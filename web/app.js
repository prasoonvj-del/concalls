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
  async function getPres() {
    if (!window.DESK_PRES) {
      try { await loadScript("data/presentations.js"); } catch (e) { window.DESK_PRES = []; }
    }
    return window.DESK_PRES;
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
        const html = r.tip || `<b>${esc(r.label)}</b><br>${plural(r.total, "story")}<br>` +
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
        const dot = el("circle", { cx: X(p.x), cy: Y(p.y), r: 5, fill: p.color || cssv("--s1"), stroke: cssv("--surface"), "stroke-width": 2, style: "cursor:pointer" }, s);
        const hit = el("circle", { cx: X(p.x), cy: Y(p.y), r: 12, fill: "transparent", style: "cursor:pointer" }, s);
        const html = `<b>${esc(p.label)}</b><br>${esc(xl)}: ${p.x}<br>${esc(yl)}: ${p.y}${p.note ? "<br>" + p.note : ""}<br><span class="m">Tap to open</span>`;
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
        el("path", { d: barPath(zero, end, by, barH), fill: r.color || cssv("--s1") }, g);
        el("text", { x: r.value >= 0 ? end + 5 : end - 5, y: by + barH - 3, "text-anchor": r.value >= 0 ? "start" : "end", class: "val" }, g,
          (Math.round(r.value * 10) / 10) + (r.flag ? " ⚠" : ""));
        const hit = el("rect", { x: 0, y, width: W, height: rowH, class: "hit" }, g);
        const html = `<b>${esc(r.label)}</b><br>${Math.round(r.value * 100) / 100} ${esc(unit)}${r.note ? "<br>" + r.note : ""}${r.flag ? "<br>⚠ not stated word-for-word in the transcript (likely calculated)" : ""}`;
        hit.addEventListener("mousemove", (e) => showTip(html, e));
        hit.addEventListener("mouseleave", hideTip);
        hit.addEventListener("click", () => { hideTip(); r.onclick && r.onclick(); });
      });
      h.appendChild(s);
    });
  }

  /** Lines on a free (non-zero) scale, e.g. prices rebased to 100. */
  function indexChart(host, xs, series, unit) {
    mount(host, (h, W) => {
      const H = 260, L = 44, R = 14, T = 10, B = 26;
      const s = svg(W, H);
      const all = series.flatMap((se) => se.values.filter((v) => v != null));
      let lo = Math.min(...all), hi = Math.max(...all);
      const padv = (hi - lo) * 0.08 || 1; lo -= padv; hi += padv;
      const x = (i) => L + (xs.length === 1 ? (W - L - R) / 2 : (i * (W - L - R)) / (xs.length - 1));
      const y = (v) => T + (H - T - B) * (1 - (v - lo) / (hi - lo));
      for (let k = 0; k <= 4; k++) {
        const v = lo + ((hi - lo) * k) / 4, yy = y(v);
        el("line", { x1: L, x2: W - R, y1: yy, y2: yy, class: "gridl" }, s);
        el("text", { x: L - 6, y: yy + 4, "text-anchor": "end" }, s, Math.round(v));
      }
      if (lo < 100 && hi > 100 && unit === "index") el("line", { x1: L, x2: W - R, y1: y(100), y2: y(100), class: "axis" }, s);
      const every = Math.ceil(xs.length / Math.max(2, Math.floor((W - L - R) / 70)));
      xs.forEach((d, i) => {
        if (i % every === 0 || i === xs.length - 1)
          el("text", { x: x(i), y: H - 6, "text-anchor": "middle" }, s, d.slice(8) + "/" + d.slice(5, 7));
      });
      series.forEach((se) => {
        let path = "", pen = false;
        se.values.forEach((v, i) => {
          if (v == null) { pen = false; return; }
          path += (pen ? "L" : "M") + x(i).toFixed(1) + "," + y(v).toFixed(1); pen = true;
        });
        el("path", { d: path, fill: "none", stroke: se.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, s);
        let li = se.values.length - 1; while (li > 0 && se.values[li] == null) li--;
        el("circle", { cx: x(li), cy: y(se.values[li]), r: 4, fill: se.color, stroke: cssv("--surface"), "stroke-width": 2 }, s);
      });
      const cross = el("line", { x1: 0, x2: 0, y1: T, y2: H - B, stroke: cssv("--text-2"), "stroke-width": 1, "stroke-dasharray": "3 3", visibility: "hidden" }, s);
      const ov = el("rect", { x: L, y: T, width: W - L - R, height: H - T - B, fill: "transparent" }, s);
      const at = (e) => {
        const r = s.getBoundingClientRect();
        const px = ((e.clientX - r.left) / r.width) * W;
        return Math.max(0, Math.min(xs.length - 1, Math.round(((px - L) / (W - L - R)) * (xs.length - 1))));
      };
      ov.addEventListener("mousemove", (e) => {
        const i = at(e);
        cross.setAttribute("x1", x(i)); cross.setAttribute("x2", x(i)); cross.setAttribute("visibility", "visible");
        const rows = series.map((se) => [se, se.values[i]]).filter((r) => r[1] != null).sort((a, b) => b[1] - a[1]);
        showTip(`<b>${esc(xs[i])}</b><br>` + rows.map(([se, v]) =>
          `<span class="sw" style="background:${se.color}"></span>${esc(se.name)}: ${Math.round(v * 10) / 10}${se.raw ? " <span class='m'>(" + se.raw[i] + ")</span>" : ""}`).join("<br>"), e);
      });
      ov.addEventListener("mouseleave", () => { cross.setAttribute("visibility", "hidden"); hideTip(); });
      h.appendChild(s);
    });
  }
  /** Tiny inline trend line for tiles. */
  function spark(vals, color, w = 110, h = 30) {
    const v = vals.filter((x) => x != null);
    if (v.length < 2) return "";
    const lo = Math.min(...v), hi = Math.max(...v), d = hi - lo || 1;
    const pts = v.map((x, i) => `${((i / (v.length - 1)) * (w - 4) + 2).toFixed(1)},${(h - 3 - ((x - lo) / d) * (h - 6)).toFixed(1)}`).join(" ");
    return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" aria-hidden="true"><polyline points="${pts}" fill="none" stroke="${color}" stroke-width="1.6" stroke-linejoin="round"/></svg>`;
  }
  const pct = (v) => (v == null ? "–" : (v > 0 ? "+" : "") + (Math.round(v * 10) / 10) + "%");
  const pctCls = (v) => (v == null ? "m" : v >= 0 ? "up" : "dn");
  const PAL = ["--s1", "--s2", "--s3", "--s4", "--s5"];
  async function getTrack() {
    if (!window.DESK_TRACK) {
      try { await loadScript("data/trackers.js"); } catch (e) { window.DESK_TRACK = { trackers: {}, markets: { series: [] }, weekly: { reviews: [] } }; }
    }
    return window.DESK_TRACK;
  }
  const median = (a) => { const b = a.slice().sort((p, q) => p - q), m = b.length >> 1; return b.length ? (b.length % 2 ? b[m] : (b[m - 1] + b[m]) / 2) : null; };
  const isWatch = (name) => watchlist().some((w) => sameCo(name, w) || String(name).toLowerCase().includes(w.toLowerCase()));
  const legend = (items) => `<div class="legend">${items.map(([n, c]) => `<span><i style="background:${c}"></i>${esc(n)}</span>`).join("")}</div>`;

  /* ------------------------------------------------------------ company context (concall + deck + trackers in one place) */
  let ctxReady = null;
  const loadCtx = () => (ctxReady = ctxReady || Promise.all([getConcalls(), getPres(), getTrack()]));
  // the investor deck that goes with a concall: same company, filed within ~2 months of the call
  function deckFor(call) {
    const P = window.DESK_PRES || [];
    const t = new Date(call.date).getTime();
    let best = null, bd = 1e18;
    P.forEach((d) => {
      if (d.code !== call.code && !sameCo(d.company, call.company)) return;
      const dd = Math.abs(new Date(d.when).getTime() - t);
      if (dd < 61 * 864e5 && dd < bd) { best = d; bd = dd; }
    });
    return best;
  }
  function ctxOf(name) {
    const cc = window.DESK_CONCALLS || { calls: [] }, P = window.DESK_PRES || [], TK = (window.DESK_TRACK || {}).trackers || {};
    const call = cc.calls.filter((c) => sameCo(c.company, name)).sort((a, b) => (a.date < b.date ? 1 : -1))[0];
    const deck = call ? deckFor(call) || P.find((d) => d.code === call.code) : P.find((d) => sameCo(d.company, name));
    const res = (TK.results || []).find((r) => sameCo(r.company, name));
    const brk = (TK.calls || []).find((r) => sameCo(r.company, name));
    if (!call && !deck && !res && !brk) return null;
    return { name: call ? call.company : name, call, deck, res, brk };
  }
  // one compact line: "Concall Q2 FY27 · Positive · Deck · Results: PAT +29%"
  function ctxLine(name) {
    const x = ctxOf(name);
    if (!x) return "";
    const bits = [];
    if (x.call) bits.push(`<a href="#companies/${encodeURIComponent(x.call.company)}">concall ${esc(x.call.quarter)}</a>${x.call.tone ? ` <span class="tone ${esc(x.call.tone)}">${esc(x.call.tone)}</span>` : ""}`);
    if (x.res) bits.push(`results: profit <span class="${pctCls(x.res.pat_yoy)}">${pct(x.res.pat_yoy)}</span>`);
    if (x.brk) bits.push(`${esc(x.brk.broker)}: ${esc(x.brk.rating)}`);
    if (x.deck) bits.push(`<a href="${esc(x.deck.pdf)}" target="_blank" rel="noopener">deck</a>`);
    return `<div class="ctx"><b>${esc(name)}</b> · ${bits.join(" · ")}</div>`;
  }
  // richer block for the story popover
  function ctxCard(name) {
    const x = ctxOf(name);
    if (!x) return "";
    const c = x.call, m = c ? c.metrics || {} : {};
    const ks = c ? colsFor(c.sector).filter((k) => typeof m[k] === "number").slice(0, 4) : [];
    return `<div class="ctxc"><div><a href="#companies/${encodeURIComponent(x.name)}" data-go="#companies/${encodeURIComponent(x.name)}"><b>${esc(x.name)}</b></a>
        ${c ? `<span class="m"> · ${esc(c.sector)}</span>` : ""}</div>
      ${c ? `<div>Last concall <b>${esc(c.quarter)}</b>${c.tone ? ` <span class="tone ${esc(c.tone)}">${esc(c.tone)}</span>` : ""}${c.prev_tone && c.prev_tone !== c.tone ? ` <span class="m">(was ${esc(c.prev_tone)})</span>` : ""}
        ${ks.length ? `<div class="m">${ks.map((k) => `${esc(MET[k][0])} ${fmtM(m[k])}${MET[k][1].startsWith("%") || MET[k][1] === "%" ? "%" : " " + esc(MET[k][1])}`).join(" · ")}</div>` : ""}</div>` : ""}
      ${x.res ? `<div>Results ${esc(x.res.quarter)}: revenue <span class="${pctCls(x.res.rev_yoy)}">${pct(x.res.rev_yoy)}</span>, profit <span class="${pctCls(x.res.pat_yoy)}">${pct(x.res.pat_yoy)}</span></div>` : ""}
      ${x.brk ? `<div>${esc(x.brk.broker)}: ${esc(x.brk.rating)}${x.brk.target ? ", target Rs " + fmt(Math.round(x.brk.target)) : ""} <span class="m">${esc(x.brk.date.slice(5))}</span></div>` : ""}
      <div class="m">${c ? `<a href="#companies/${encodeURIComponent(x.name)}" data-go="#companies/${encodeURIComponent(x.name)}">concall summary</a>` : ""}${c && x.deck ? " · " : ""}${x.deck ? `<a href="${esc(x.deck.pdf)}" target="_blank" rel="noopener">investor deck</a>` : ""}</div></div>`;
  }

  /* ------------------------------------------------------------ story popover */
  const pop = $("#pop"), popCard = $("#pop-card");
  async function openStory(id) {
    await loadCtx();
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
      ${s.companies.slice(0, 3).map(ctxCard).join("")}
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
    await loadCtx();
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
          ${s.companies.slice(0, 3).map(ctxLine).join("")}
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
    // "Stocks in focus": company names open the company page, with what we know about them
    view.querySelectorAll(".md table tr td:first-child").forEach((td) => {
      const name = td.textContent.replace(/\*/g, "").trim();
      if (!name || td.querySelector("a")) return;
      const x = ctxOf(name);
      const known = x || b.stories.some((st2) => st2.companies.some((c) => sameCo(c, name)));
      if (!known) return;
      td.innerHTML = `<a href="#companies/${encodeURIComponent(x ? x.name : name)}">${esc(name)}</a>` +
        (x && x.call && x.call.tone ? `<div><span class="tone ${esc(x.call.tone)}" title="Tone of the last concall (${esc(x.call.quarter)})">${esc(x.call.tone)}</span></div>` : "");
    });
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

  // repeat headlines (same story from several outlets / days) -> one line with "+n similar"
  function groupNews(items) {
    const words = (t) => new Set(t.toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter((w) => w.length > 3));
    const groups = [];
    items.forEach((x) => {
      const w = words(x.s.title);
      const g = groups.find((gr) => { let n = 0; w.forEach((v) => { if (gr.w.has(v)) n++; }); return n / Math.max(1, Math.min(w.size, gr.w.size)) >= 0.5; });
      if (g) { g.more.push(x); w.forEach((v) => g.w.add(v)); } else groups.push({ x, w, more: [] });
    });
    return groups;
  }
  const firstLine = (html) => {
    const d = document.createElement("div"); d.innerHTML = html || "";
    const el1 = d.querySelector("li, p");
    const t = (el1 ? el1.textContent : d.textContent).trim();
    return t.length > 260 ? t.slice(0, 257) + "…" : t;
  };

  async function pageCompanies(name) {
    const cc = await getConcalls();
    await loadCtx();
    const P = window.DESK_PRES || [], TK = (window.DESK_TRACK || {}).trackers || {};
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
    const known = new Set(cc.calls.map((c) => c.code));
    P.forEach((d) => { if (!known.has(d.code) && !Object.keys(mentions).some((m) => sameCo(m, d.company))) mentions[d.company] = []; });
    const latestCall = (n) => cc.calls.filter((c) => sameCo(c.company, n)).sort((a, c) => (a.date < c.date ? 1 : -1))[0];

    if (!name) {
      const rows = Object.keys(mentions).map((n) => {
        const m = mentions[n], call = latestCall(n);
        const deck = call ? deckFor(call) || P.find((d) => d.code === call.code) : P.find((d) => sameCo(d.company, n));
        const res = (TK.results || []).find((r) => sameCo(r.company, n));
        return { n, m: m.length, pos: m.filter((x) => x.s.sent === "+").length, neg: m.filter((x) => x.s.sent === "-").length,
          call, deck, res, sector: call ? call.sector : (deck && deck.sector) || (res && res.sector) || ((m.find((x) => !/Markets|Macro|Economy|Policy|Global|IPO/i.test(x.s.cat)) || {}).s || {}).cat || "" };
      });
      const secs = [...new Set(rows.map((r) => r.sector).filter(Boolean))].sort();
      const st = store.get("colist", { q: "", sec: "", sort: "news", has: "" });
      view.innerHTML = `<h1>Companies</h1><div class="sub">${plural(rows.length, "company")} · news from the last ${plural(briefs.length, "brief")}, concall summaries, decks and results in one row each</div>
        <div class="filters"><input type="search" id="cq" placeholder="Search a company" value="${esc(st.q)}">
          <select id="cs"><option value="">All sectors</option>${secs.map((x) => `<option ${x === st.sec ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
          <select id="ch"><option value="">Everything</option><option value="call" ${st.has === "call" ? "selected" : ""}>With a concall summary</option>
            <option value="deck" ${st.has === "deck" ? "selected" : ""}>With an investor deck</option><option value="res" ${st.has === "res" ? "selected" : ""}>With results this season</option></select>
          <select id="co"><option value="news">Most in the news</option><option value="az" ${st.sort === "az" ? "selected" : ""}>A–Z</option>
            <option value="pos" ${st.sort === "pos" ? "selected" : ""}>Most positive news</option><option value="neg" ${st.sort === "neg" ? "selected" : ""}>Most negative news</option>
            <option value="call" ${st.sort === "call" ? "selected" : ""}>Latest concall first</option></select></div>
        <div class="card tw"><table class="tt co" id="cl"></table></div>`;
      const draw = () => {
        Object.assign(st, { q: $("#cq").value, sec: $("#cs").value, has: $("#ch").value, sort: $("#co").value }); store.set("colist", st);
        const q = st.q.toLowerCase();
        const sorters = { news: (a, b) => b.m - a.m || a.n.localeCompare(b.n), az: (a, b) => a.n.localeCompare(b.n), pos: (a, b) => b.pos - a.pos || b.m - a.m,
          neg: (a, b) => b.neg - a.neg || b.m - a.m, call: (a, b) => ((b.call ? b.call.date : "") > (a.call ? a.call.date : "") ? 1 : -1) };
        const list = rows.filter((r) => (!q || r.n.toLowerCase().includes(q)) && (!st.sec || r.sector === st.sec)
          && (!st.has || (st.has === "call" ? r.call : st.has === "deck" ? r.deck : r.res))).sort(sorters[st.sort] || sorters.news);
        const bar = (r) => r.m ? `<span class="mb" title="${r.pos} positive, ${r.neg} negative, ${r.m - r.pos - r.neg} neutral"><i style="width:${(100 * r.pos) / r.m}%;background:var(--pos)"></i><i style="width:${(100 * r.neg) / r.m}%;background:var(--neg)"></i></span>` : "";
        $("#cl").innerHTML = `<tr><th>Company</th><th>News</th><th>Concall</th><th>Results</th><th>Deck</th></tr>` + list.slice(0, shown).map((r) => `<tr>
          <td><a href="#companies/${encodeURIComponent(r.n)}">${isWatch(r.n) ? "★ " : ""}${esc(r.n)}</a><div class="m">${esc(r.sector || "")}</div></td>
          <td>${r.m ? `${r.m} ${bar(r)}` : `<span class="m">–</span>`}</td>
          <td>${r.call ? `${esc(r.call.quarter)} ${r.call.tone ? `<span class="tone ${esc(r.call.tone)}">${esc(r.call.tone)}</span>` : ""}` : `<span class="m">–</span>`}</td>
          <td>${r.res ? `profit <span class="${pctCls(r.res.pat_yoy)}">${pct(r.res.pat_yoy)}</span>` : `<span class="m">–</span>`}</td>
          <td>${r.deck ? `<a href="${esc(r.deck.pdf)}" target="_blank" rel="noopener">PDF</a>${r.deck.one ? " ✦" : ""}` : `<span class="m">–</span>`}</td></tr>`).join("")
          + (list.length ? "" : `<tr><td colspan="5" class="m">No match.</td></tr>`)
          + (list.length > shown ? `<tr><td colspan="5"><button id="cmore">Show ${Math.min(100, list.length - shown)} more of ${list.length - shown}</button></td></tr>` : "");
        const mb = $("#cmore"); if (mb) mb.onclick = () => { shown += 100; draw(); };
      };
      let shown = 60;
      ["cq", "cs", "ch", "co"].forEach((id) => $("#" + id).addEventListener(id === "cq" ? "input" : "change", () => { shown = 60; draw(); })); draw();
      return;
    }

    const key = Object.keys(mentions).find((m) => sameCo(m, name)) || name;
    const seenT = new Set();
    const items = (mentions[key] || []).sort((a, c) => (a.s.when < c.s.when ? 1 : -1))
      .filter((x) => { const k = x.s.title.toLowerCase().replace(/\W+/g, ""); if (seenT.has(k)) return false; seenT.add(k); return true; });
    const groups = groupNews(items);
    const call = latestCall(name);
    const tk = ["results", "orders", "calls"].map((k) => (TK[k] || []).filter((r) => sameCo(r.company, name)));
    const decks = P.filter((d) => sameCo(d.company, name) || (call && d.code === call.code)).slice(0, 6);
    const nextRes = (TK.calendar || []).find((r) => (sameCo(r.company, name) || (call && r.code === call.code)) && r.when >= new Date().toISOString().slice(0, 10));
    const sector = call ? call.sector : (decks[0] && decks[0].sector) || (items[0] ? items[0].s.cat : "");
    const pz = items.filter((x) => x.s.sent === "+").length, nz = items.filter((x) => x.s.sent === "-").length;
    const res = tk[0][0], brk = tk[2][0], ord = tk[1][0];
    const chips = [
      call && call.tone ? `<span class="chip">Concall ${esc(call.quarter)}: <span class="tone ${esc(call.tone)}">${esc(call.tone)}</span>${call.prev_tone && call.prev_tone !== call.tone ? ` <span class="m">was ${esc(call.prev_tone)}</span>` : ""}</span>` : "",
      res ? `<span class="chip">Results ${esc(res.quarter)}: revenue <span class="${pctCls(res.rev_yoy)}">${pct(res.rev_yoy)}</span> · profit <span class="${pctCls(res.pat_yoy)}">${pct(res.pat_yoy)}</span></span>` : "",
      brk ? `<span class="chip">${esc(brk.broker)}: ${esc(brk.rating)}${brk.target ? " · Rs " + fmt(Math.round(brk.target)) : ""}${tk[2].length > 1 ? ` <span class="m">+${tk[2].length - 1} more</span>` : ""}</span>` : "",
      ord ? `<span class="chip">Order${ord.value ? " Rs " + fmtM(ord.value) + " cr" : ""}${ord.client ? " · " + esc(ord.client) : ""}</span>` : "",
      nextRes ? `<span class="chip">Results due ${esc(new Date(nextRes.when + "T00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short" }))}</span>` : "",
      items.length ? `<span class="chip">News: ${pz}▲ ${nz}▼ of ${items.length}</span>` : "",
    ].filter(Boolean).join("");
    // key figures: concall metrics, else the results tracker
    let figs = "";
    if (call && Object.keys(call.metrics || {}).length) figs = keyFigures(call);
    else if (res) figs = `<div class="tiles" style="margin:6px 0">${[["Revenue", res.revenue, "Rs cr"], ["Revenue growth", res.rev_yoy, "% YoY"], ["Net profit", res.profit, "Rs cr"], ["Profit growth", res.pat_yoy, "% YoY"]]
      .filter((x) => x[1] != null).map((x) => `<div class="tile"><div class="v" style="font-size:19px">${fmtM(x[1])}</div><div class="k">${x[0]} · ${x[2]}</div></div>`).join("")}</div>`;
    const deckSum = decks.find((d) => d.one || d.html);
    const tabs = [["ov", "Overview"], call ? ["cc", "Concall " + call.quarter] : null, decks.length ? ["dk", plural(decks.length, "deck")] : null,
      items.length ? ["nw", `News (${groups.length})`] : null, (tk[0].length + tk[1].length + tk[2].length) > 1 ? ["tk", "Results & calls"] : null].filter(Boolean);
    let tab = store.get("cotab", "ov"); if (!tabs.some((t) => t[0] === tab)) tab = "ov";
    view.innerHTML = `<div class="cohead"><h1>${esc(key)}</h1>
        <div class="sub"><a href="#companies">All companies</a>${sector ? ` · <a href="#sectors/${encodeURIComponent(sector)}">${esc(sector)}</a>` : ""}${call ? ` · <a href="#peers/${encodeURIComponent(call.sector)}">peers</a> · <a href="${esc(call.pdf)}" target="_blank" rel="noopener">transcript</a>` : ""}${decks[0] ? ` · <a href="${esc(decks[0].pdf)}" target="_blank" rel="noopener">latest deck</a>` : ""}</div>
        ${chips ? `<div class="chips">${chips}</div>` : ""}${figs}</div>
      <div class="cotabs">${tabs.map(([k, l]) => `<button data-t="${k}" class="${k === tab ? "on" : ""}">${esc(l)}</button>`).join("")}</div>
      <div id="cobody"></div>`;
    const newsLine = (g) => `<li class="nl"><div class="t" data-story-date="${g.x.date}" data-sid="${g.x.s.id}">${esc(g.x.s.title)}</div>
        <div class="src">${sentChip(g.x.s.sent)} · ${impDots(g.x.s.imp)} · ${when(g.x.s.when)}${g.more.length ? ` · <details class="sim"><summary>+${g.more.length} similar</summary>${g.more.map((m) => `<div class="t" data-story-date="${m.date}" data-sid="${m.s.id}">${esc(m.s.title)}</div>`).join("")}</details>` : ""}</div></li>`;
    const deckBlock = (d, open) => `<details class="sum" ${open ? "open" : ""}><summary><span class="n">${esc((d.title || "Investor presentation").slice(0, 110))}</span><span class="m">${when(d.when)}</span>
        <span class="r2">${d.one ? `<span class="badge">summary</span>` : d.scan ? `<span class="badge w" title="Image-only slides - no text for the AI to read">images only</span>` : ""}</span></summary>
        <div class="b md">${d.one ? `<p><b>${esc(d.one)}</b></p>` : ""}${d.html || (d.scan ? `<div class="m">The slides are images, so there's no text to summarise.</div>` : `<div class="m">Summary not written yet - it'll appear after a coming update.</div>`)}
        <p><a href="${esc(d.pdf)}" target="_blank" rel="noopener">Open the deck (PDF)</a></p></div></details>`;
    const trackerList = () => `<ul class="list">
        ${tk[0].map((r) => `<li><div class="t">Results ${esc(r.quarter)}: revenue ${r.revenue == null ? "–" : "Rs " + fmtM(r.revenue) + " cr"} (<span class="${pctCls(r.rev_yoy)}">${pct(r.rev_yoy)}</span>), net profit ${r.profit == null ? "–" : "Rs " + fmtM(r.profit) + " cr"} (<span class="${pctCls(r.pat_yoy)}">${pct(r.pat_yoy)}</span>)${r.read ? " · " + esc(r.read) : ""}</div><div class="src">${esc(r.date)} · <a href="${esc(r.link)}" target="_blank" rel="noopener">source</a></div></li>`).join("")}
        ${tk[1].map((r) => `<li><div class="t">Order: ${r.value == null ? "" : "Rs " + fmtM(r.value) + " cr "}${esc(r.client ? "from " + r.client : "")} ${esc(r.what)}</div><div class="src">${esc(r.date)} · <a href="${esc(r.link)}" target="_blank" rel="noopener">source</a></div></li>`).join("")}
        ${tk[2].map((r) => `<li><div class="t">${esc(r.broker)}: ${esc(r.rating)}${r.target ? ", target Rs " + fmt(Math.round(r.target)) : ""}${r.action ? " (" + esc(r.action) + ")" : ""}</div><div class="src">${esc(r.date)} · <a href="${esc(r.link)}" target="_blank" rel="noopener">source</a></div></li>`).join("")}</ul>`;
    const drawTab = () => {
      redraws.length = 0;
      const body = $("#cobody");
      if (tab === "ov") {
        const takes = [
          call ? `<li><b>Concall ${esc(call.quarter)}:</b> ${esc(firstLine(call.html))} <a href="#" data-jump="cc">more</a></li>` : "",
          deckSum ? `<li><b>Investor deck:</b> ${esc(deckSum.one || firstLine(deckSum.html))} <a href="#" data-jump="dk">more</a></li>` : "",
          res ? `<li><b>Results ${esc(res.quarter)}:</b> revenue ${res.revenue == null ? "" : "Rs " + fmtM(res.revenue) + " cr "}(${pct(res.rev_yoy)}), net profit ${res.profit == null ? "" : "Rs " + fmtM(res.profit) + " cr "}(${pct(res.pat_yoy)})${res.read ? " - " + esc(res.read) : ""}</li>` : "",
          brk ? `<li><b>Brokers:</b> ${tk[2].slice(0, 3).map((r) => `${esc(r.broker)} ${esc(r.rating)}${r.target ? " (Rs " + fmt(Math.round(r.target)) + ")" : ""}`).join(" · ")}</li>` : "",
          ord ? `<li><b>Orders:</b> ${tk[1].slice(0, 3).map((r) => `${r.value ? "Rs " + fmtM(r.value) + " cr" : ""} ${esc(r.client || r.what)}`).join(" · ")}</li>` : "",
        ].filter(Boolean).join("");
        const perDay = briefs.map((b) => { const xs = items.filter((x) => x.date === b.date); return { label: b.date.slice(5), pos: xs.filter((x) => x.s.sent === "+").length, neg: xs.filter((x) => x.s.sent === "-").length, neu: xs.filter((x) => x.s.sent !== "+" && x.s.sent !== "-").length }; })
          .map((r) => Object.assign(r, { total: r.pos + r.neg + r.neu, tip: `<b>${r.label}</b><br>${r.pos} positive · ${r.neg} negative · ${r.neu} neutral` }));
        body.innerHTML = `<div class="grid g2" style="align-items:start">
          <div class="card"><h2>Takeaways</h2>${takes ? `<ul class="tk">${takes}</ul>` : `<div class="m">No concall, deck or results on file yet - see the news.</div>`}</div>
          <div class="card"><h2>Latest news <span class="m">${groups.length > 6 ? `<a href="#" data-jump="nw">all ${groups.length}</a>` : ""}</span></h2>
            ${groups.length ? `<ul class="list">${groups.slice(0, 6).map(newsLine).join("")}</ul>` : `<div class="m">No news in recent briefs.</div>`}
            ${items.length >= 4 ? `<div class="m" style="margin-top:8px">News tone by day</div><div id="cod"></div>` : ""}</div></div>`;
        if (items.length >= 4) divergingChart($("#cod"), perDay.filter((r) => r.total));
      } else if (tab === "cc") {
        body.innerHTML = `<div class="card md"><div style="margin-bottom:8px"><span class="badge">${esc(call.quarter)}</span>
          ${call.tone ? `<span class="tone ${esc(call.tone)}">${esc(call.tone)}</span>` : ""} ${call.compared ? `<span class="badge">vs last quarter</span>` : ""}
          ${call.checks.length ? `<span class="badge w">⚠ ${call.checks.length} to check</span>` : ""} <span class="m">· filed ${esc(call.date)}</span></div>
          ${call.checks.length ? `<div class="warn">Highlighted figures weren't found word-for-word in the transcript - check them in the PDF.</div>` : ""}
          ${call.html}<p><a href="${esc(call.pdf)}" target="_blank" rel="noopener">Original transcript (PDF)</a>${deckFor(call) ? ` · <a href="${esc(deckFor(call).pdf)}" target="_blank" rel="noopener">Investor deck (PDF)</a>` : ""}</p></div>`;
      } else if (tab === "dk") {
        body.innerHTML = `<div class="card">${decks.map((d, i) => deckBlock(d, i === 0)).join("")}</div>`;
      } else if (tab === "nw") {
        body.innerHTML = `<div class="card"><ul class="list">${groups.map(newsLine).join("")}</ul></div>`;
      } else {
        body.innerHTML = `<div class="card">${trackerList()}</div>`;
      }
      body.querySelectorAll("[data-sid]").forEach((d) => d.addEventListener("click", async () => {
        currentBrief = await getBrief(d.dataset.storyDate); current = currentBrief.date; openStory(d.dataset.sid);
      }));
      body.querySelectorAll("[data-jump]").forEach((a) => a.addEventListener("click", (e) => { e.preventDefault(); setTab(a.dataset.jump); }));
    };
    const setTab = (t) => { tab = t; store.set("cotab", t); view.querySelectorAll(".cotabs button").forEach((b) => b.classList.toggle("on", b.dataset.t === t)); drawTab(); };
    view.querySelectorAll(".cotabs button").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.t)));
    drawTab();
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
    await loadCtx();
    if (!cc.calls.length) { view.innerHTML = empty("No concall summaries yet."); return; }
    const sectors = [...new Set(cc.calls.map((c) => c.sector))].sort();
    const quarters = [...new Set(cc.calls.map((c) => c.quarter))].sort((a, b) => (a.slice(-2) + a[1] < b.slice(-2) + b[1] ? 1 : -1));
    const latestQ = quarters[0];
    const keys = [["Positive", "--pos"], ["Mixed", "--neu"], ["Cautious", "--caution"], ["Negative", "--neg"]].map(([k, v]) => ({ key: k, color: cssv(v) }));
    const nDeck = (window.DESK_PRES || []).length;
    view.innerHTML = `<h1>Concalls</h1><div class="sub">${plural(cc.calls.length, "summary", )} · ${plural(cc.overviews.length, "sector overview")}${nDeck ? ` · <a href="#presentations">${plural(nDeck, "investor deck")} filed recently →</a>` : ""}</div>
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
          <span class="r2">${deckFor(c) ? `<span class="badge" title="An investor deck was filed with this call">deck</span>` : ""}${c.compared ? `<span class="badge" title="Includes what changed vs last quarter">vs last qtr</span>` : ""}
          ${c.checks.length ? `<span class="badge w" title="Figures not found word-for-word in the transcript">⚠ ${c.checks.length}</span>` : ""}
          ${c.tone ? `<span class="tone ${esc(c.tone)}">${esc(c.tone)}</span>` : ""}</span></summary>
          <div class="b md">${c.checks.length ? `<div class="warn">Highlighted figures weren't found word-for-word in the transcript - they may be calculated by the AI or misread.</div>` : ""}
          ${c.html}<p><a href="${esc(c.pdf)}" target="_blank" rel="noopener">Original transcript (PDF)</a>${(() => { const d = deckFor(c); return d ? ` · <a href="${esc(d.pdf)}" target="_blank" rel="noopener">Investor deck (PDF)</a>` : ""; })()} · <a href="#companies/${encodeURIComponent(c.company)}">News, results &amp; broker calls on ${esc(c.company)}</a></p></div></details>`).join("") ||
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

  /* ------------------------------------------------------------ markets */
  async function pageMarkets() {
    const D = await getTrack();
    const M = (D.markets && D.markets.series) || [], T = D.trackers || {}, WK = (D.weekly && D.weekly.reviews) || [];
    const PER = { "1W": 7, "1M": 30, "3M": 91, "6M": 182, "1Y": 366 };
    let per = store.get("mkper", "3M"); if (!PER[per]) per = "3M";
    const known = new Set(M.map((x) => x.sym));
    let sel = store.get("mksel", ["^NSEI", "BZ=F", "CT=F", "INR=X"]).filter((x) => known.has(x));
    const lastDate = M.reduce((a, x) => (x.pts.length && x.pts[x.pts.length - 1][0] > a ? x.pts[x.pts.length - 1][0] : a), "");
    const startOf = () => { const d = new Date(lastDate || Date.now()); d.setDate(d.getDate() - PER[per]); return d.toISOString().slice(0, 10); };
    const baseAt = (se, from) => { let b = se.pts[0]; for (const p of se.pts) { if (p[0] <= from) b = p; else break; } return b; };
    const chg = (se, from) => { const b = baseAt(se, from), l = se.pts[se.pts.length - 1]; return b && l && b[1] ? (l[1] / b[1] - 1) * 100 : null; };
    const day = (se) => { const n = se.pts.length; return n > 1 ? (se.pts[n - 1][1] / se.pts[n - 2][1] - 1) * 100 : null; };
    const fmtP = (v) => (Math.abs(v) >= 1000 ? fmt(Math.round(v)) : Math.abs(v) >= 10 ? (Math.round(v * 10) / 10).toLocaleString("en-IN") : (Math.round(v * 100) / 100).toString());
    const today = new Date().toISOString().slice(0, 10);
    const groups = [...new Set(M.map((x) => x.group))];

    const ahead = new Date(); ahead.setDate(ahead.getDate() + 14);
    const aheadS = ahead.toISOString().slice(0, 10);
    const ev = (T.events || []).filter((e) => e.when >= today && e.when <= aheadS);
    const cal = (T.calendar || []).filter((e) => e.when >= today && e.when <= aheadS);
    const daysA = [...new Set(ev.map((e) => e.when).concat(cal.map((e) => e.when)))].sort();

    view.innerHTML = `<h1>Markets</h1>
      <div class="sub">Indices, commodities, the rupee and yields${D.markets && D.markets.updated ? " · prices as of " + esc(D.markets.updated.replace("T", " ")) : ""} · tap any tile to add it to the comparison</div>
      <div class="filters seg" id="per">${Object.keys(PER).map((k) => `<button class="${k === per ? "on" : ""}" data-p="${k}">${k}</button>`).join("")}</div>
      ${M.length ? `<div class="card"><h2>Compare <span class="m">rebased to 100 at the start of the period</span></h2><div id="mleg"></div><div id="mc"></div></div>
      <div class="card"><h2>Indian sector indices <span class="m">change over ${per} · tap to see that sector's peers</span></h2><div id="ms"></div></div>
      ${groups.filter((g) => g !== "India indices").map((g) => `<div class="card"><h2>${esc(g)}</h2><div class="tiles mk" data-g="${esc(g)}"></div></div>`).join("")}
      <div class="card"><h2>India indices</h2><div class="tiles mk" data-g="India indices"></div></div>` : `<div class="card m">Prices haven't been collected yet - they arrive with the next update.</div>`}
      <div class="card"><h2>Week ahead <span class="m">next two weeks: results board meetings (BSE) and dated events from the news</span></h2>
        ${cal.length ? `<div id="calc"></div>` : ""}
        ${daysA.length ? daysA.map((d) => {
          const e1 = ev.filter((e) => e.when === d), c1 = cal.filter((e) => e.when === d).sort((a, b) => isWatch(b.company) - isWatch(a.company) || a.company.localeCompare(b.company));
          const nice = new Date(d + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short" });
          return `<div class="wa"><div class="wd">${nice}</div><div>
            ${e1.map((e) => `<div>• ${esc(e.what)} <a class="m" href="${esc(e.link)}" target="_blank" rel="noopener">source</a></div>`).join("")}
            ${c1.length ? `<details><summary>${plural(c1.length, "company")} ${c1.length === 1 ? "reports" : "report"} results${c1.some((c) => isWatch(c.company)) ? " · ★ watchlist" : ""}</summary>
              <div class="m">${c1.map((c) => `${isWatch(c.company) ? "★ " : ""}<a href="#companies/${encodeURIComponent(c.company)}">${esc(c.company)}</a>${c.sector ? " (" + esc(c.sector) + ")" : ""}`).join(" · ")}</div></details>` : ""}
          </div></div>`;
        }).join("") : `<div class="m">Nothing dated yet - the calendar fills as companies file board-meeting notices and the news mentions dates.</div>`}</div>
      ${WK.length ? `<div class="card md"><h2>Week in review <span class="m">${esc(WK[0].start)} to ${esc(WK[0].end)}</span></h2>
        ${WK[0].one ? `<p><b>${esc(WK[0].one)}</b></p>` : ""}${WK[0].html}
        ${WK.length > 1 ? `<details><summary>Earlier weeks</summary>${WK.slice(1).map((w) => `<h3>${esc(w.start)} to ${esc(w.end)}</h3>${w.one ? `<p><b>${esc(w.one)}</b></p>` : ""}${w.html}`).join("")}</details>` : ""}</div>` : ""}`;

    if (cal.length) {
      const byDay = {};
      cal.forEach((c) => { byDay[c.when] = (byDay[c.when] || 0) + 1; });
      barChart($("#calc"), Object.keys(byDay).sort().map((d) => ({
        label: new Date(d + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short" }), value: byDay[d],
        note: cal.filter((c) => c.when === d).slice(0, 8).map((c) => esc(c.company)).join(", ") + (byDay[d] > 8 ? " …" : "") })), "board meeting");
    }
    $("#per").onclick = (e) => { const b = e.target.closest("button"); if (b) { store.set("mkper", b.dataset.p); route(); } };
    if (!M.length) return;
    const from = startOf();
    const color = (i) => cssv(PAL[i % PAL.length]);
    const drawCompare = () => {
      const ss = sel.map((sym) => M.find((x) => x.sym === sym)).filter(Boolean);
      $("#mleg").innerHTML = ss.length ? legend(ss.map((se, i) => [se.name, color(i)])) : `<div class="m">Tap tiles below to compare up to 5 series.</div>`;
      if (!ss.length) { $("#mc").innerHTML = ""; return; }
      const xs = [...new Set(ss.flatMap((se) => se.pts.filter((p) => p[0] >= from).map((p) => p[0])))].sort();
      const series = ss.map((se, i) => {
        const b = baseAt(se, from)[1]; let j = 0, last = null; const raw = [];
        const values = xs.map((d) => {
          while (j < se.pts.length && se.pts[j][0] <= d) { last = se.pts[j][1]; j++; }
          raw.push(last == null ? "" : fmtP(last) + " " + se.unit);
          return last == null ? null : (last / b) * 100;
        });
        return { name: se.name, color: color(i), values, raw };
      });
      indexChart($("#mc"), xs, series, "index");
    };
    drawCompare();
    const idx = M.filter((x) => x.group === "India indices").map((se) => ({ se, v: chg(se, from) })).filter((r) => r.v != null).sort((a, b) => b.v - a.v);
    rankChart($("#ms"), idx.map(({ se, v }) => ({ label: se.name, value: Math.round(v * 10) / 10, color: cssv(v >= 0 ? "--pos" : "--neg"),
      note: se.note ? esc(se.note) : "", onclick: se.note ? () => go("#peers/" + encodeURIComponent(se.note)) : null })), "% over " + per);
    view.querySelectorAll(".tiles.mk").forEach((box) => {
      box.innerHTML = M.filter((x) => x.group === box.dataset.g).map((se) => {
        const c = chg(se, from), d1 = day(se), last = se.pts[se.pts.length - 1];
        const vals = se.pts.filter((p) => p[0] >= from).map((p) => p[1]);
        return `<button class="tile mt ${sel.includes(se.sym) ? "on" : ""}" data-sym="${esc(se.sym)}" title="${esc(se.note || se.name)}">
          <div class="k">${esc(se.name)}</div>
          <div class="v" style="font-size:18px">${fmtP(last[1])} <span class="m" style="font-size:11px">${esc(se.unit)}</span></div>
          <div class="ch"><span class="${pctCls(d1)}">${pct(d1)} 1D</span> · <span class="${pctCls(c)}">${pct(c)} ${per}</span></div>
          ${spark(vals, cssv(c == null || c >= 0 ? "--pos" : "--neg"))}
          ${se.note ? `<div class="nt">${esc(se.note)}</div>` : ""}</button>`;
      }).join("");
    });
    view.querySelectorAll(".tile.mt").forEach((t) => t.addEventListener("click", () => {
      const sym = t.dataset.sym;
      sel = sel.includes(sym) ? sel.filter((x) => x !== sym) : sel.concat(sym).slice(-5);
      store.set("mksel", sel);
      view.querySelectorAll(".tile.mt").forEach((x) => x.classList.toggle("on", sel.includes(x.dataset.sym)));
      redraws.length = 0; drawCompare();
      rankChart($("#ms"), idx.map(({ se, v }) => ({ label: se.name, value: Math.round(v * 10) / 10, color: cssv(v >= 0 ? "--pos" : "--neg"),
        note: se.note ? esc(se.note) : "", onclick: se.note ? () => go("#peers/" + encodeURIComponent(se.note)) : null })), "% over " + per);
    }));
  }

  /* ------------------------------------------------------------ trackers */
  async function pageTrackers(which) {
    const D = await getTrack();
    const T = D.trackers || {};
    which = ["results", "orders", "calls"].includes(which) ? which : "results";
    const names = { results: "Results", orders: "Order wins", calls: "Broker calls" };
    const rows0 = T[which] || [];
    const secs = [...new Set(rows0.map((r) => r.sector || "Other"))].sort();
    const st = store.get("trk-" + which, { q: "", sec: "", w: false, days: 30 });
    view.innerHTML = `<h1>Trackers</h1>
      <div class="sub">Pulled from the news by AI and kept for four months${T.updated ? " · updated " + esc(T.updated.replace("T", " ")) : ""} · check figures in the linked story before acting</div>
      <div class="card secnav">${Object.keys(names).map((k) => `<a href="#trackers/${k}" class="${k === which ? "on" : ""}">${names[k]} <span class="m">${(T[k] || []).length}</span></a>`).join("")}</div>
      <div class="filters"><input type="search" id="kq" placeholder="Search company" value="${esc(st.q)}">
        <select id="ks"><option value="">All sectors</option>${secs.map((x) => `<option ${x === st.sec ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
        <select id="kd">${[7, 30, 90, 120].map((d) => `<option value="${d}" ${d === st.days ? "selected" : ""}>Last ${d} days</option>`).join("")}</select>
        <label class="m"><input type="checkbox" id="kw" ${st.w ? "checked" : ""}> Watchlist only</label></div>
      <div id="kbody"></div>`;
    const draw = () => {
      redraws.length = 0;
      Object.assign(st, { q: $("#kq").value, sec: $("#ks").value, w: $("#kw").checked, days: Number($("#kd").value) });
      store.set("trk-" + which, st);
      const cut = new Date(); cut.setDate(cut.getDate() - st.days); const cutS = cut.toISOString().slice(0, 10);
      const rows = rows0.filter((r) => r.date >= cutS && (!st.q || r.company.toLowerCase().includes(st.q.toLowerCase()))
        && (!st.sec || (r.sector || "Other") === st.sec) && (!st.w || isWatch(r.company)));
      const body = $("#kbody");
      const open = (c) => () => go("#companies/" + encodeURIComponent(c));
      const src = (r) => `<a class="m" href="${esc(r.link)}" target="_blank" rel="noopener" title="${esc(r.title)}">source</a>`;
      if (!rows.length) { body.innerHTML = empty("Nothing here yet for these filters."); return; }
      if (which === "results") {
        const both = rows.filter((r) => r.rev_yoy != null && r.pat_yoy != null);
        const clamp = (v) => Math.max(-100, Math.min(300, v));
        const RC = { strong: "--pos", weak: "--neg", mixed: "--s4", "in-line": "--neu" };
        const bySec = {};
        rows.filter((r) => r.pat_yoy != null).forEach((r) => { (bySec[r.sector || "Other"] = bySec[r.sector || "Other"] || []).push(r.pat_yoy); });
        const secRows = Object.entries(bySec).filter(([, v]) => v.length >= 2).map(([k, v]) => ({ k, m: median(v), n: v.length })).sort((a, b) => b.m - a.m);
        body.innerHTML = `${both.length >= 3 ? `<div class="card"><h2>Sales growth vs profit growth <span class="m">YoY %, one dot per company · dashed lines = medians</span></h2>
            ${legend([["Strong", cssv("--pos")], ["Weak", cssv("--neg")], ["Mixed", cssv("--s4")], ["In line / not stated", cssv("--neu")]])}<div id="kr1"></div>
            <div class="help">Top-right of the dashed lines: sales and profit both growing faster than the typical company. High sales growth with low profit growth points to margin pressure. Values beyond -100% / +300% are drawn at the edge. Tap a dot to open the company.</div></div>` : ""}
          ${secRows.length ? `<div class="card"><h2>Median profit growth by sector <span class="m">YoY %, sectors with 2+ results</span></h2><div id="kr2"></div></div>` : ""}
          <div class="card"><h2>${plural(rows.length, "result")}</h2><div class="tw"><table class="tt"><tr><th>Company</th><th>Qtr</th><th>Revenue Rs cr</th><th>YoY</th><th>Net profit Rs cr</th><th>YoY</th><th>Read</th><th>Date</th></tr>
            ${rows.map((r) => `<tr><td>${isWatch(r.company) ? "★ " : ""}<a href="#companies/${encodeURIComponent(r.company)}">${esc(r.company)}</a><div class="m">${esc(r.sector || "")}</div></td>
              <td>${esc(r.quarter)}</td><td>${r.revenue == null ? "–" : fmtM(r.revenue)}</td><td class="${pctCls(r.rev_yoy)}">${pct(r.rev_yoy)}</td>
              <td>${r.profit == null ? "–" : fmtM(r.profit)}</td><td class="${pctCls(r.pat_yoy)}">${pct(r.pat_yoy)}</td>
              <td>${r.read ? `<span class="rd ${esc(r.read.replace(/\W/g, ""))}">${esc(r.read)}</span>` : ""}</td><td>${esc(r.date.slice(5))} ${src(r)}</td></tr>`).join("")}</table></div></div>`;
        if (both.length >= 3) scatterChart($("#kr1"), both.map((r) => ({ label: r.company + (r.quarter ? " · " + r.quarter : ""), x: clamp(r.rev_yoy), y: clamp(r.pat_yoy),
          color: cssv(RC[r.read] || "--neu"), note: r.read ? "Read: " + esc(r.read) : "", onclick: open(r.company) })), "Revenue growth YoY %", "Profit growth YoY %");
        if (secRows.length) rankChart($("#kr2"), secRows.map((x) => ({ label: x.k, value: Math.round(x.m * 10) / 10, color: cssv(x.m >= 0 ? "--pos" : "--neg"),
          note: plural(x.n, "company"), onclick: () => { $("#ks").value = x.k; draw(); } })), "% median profit growth");
      } else if (which === "orders") {
        const val = rows.filter((r) => r.value != null).sort((a, b) => b.value - a.value);
        const bySec = {};
        val.forEach((r) => { const k = r.sector || "Other"; bySec[k] = (bySec[k] || 0) + r.value; });
        body.innerHTML = `${val.length ? `<div class="card"><h2>Biggest orders <span class="m">Rs crore</span></h2><div id="ko1"></div></div>
          <div class="card"><h2>Order value by sector <span class="m">Rs crore, total in the period</span></h2><div id="ko2"></div></div>` : ""}
          <div class="card"><h2>${plural(rows.length, "order")}</h2><div class="tw"><table class="tt"><tr><th>Company</th><th>Rs cr</th><th>Client</th><th>For</th><th>Date</th></tr>
          ${rows.map((r) => `<tr><td>${isWatch(r.company) ? "★ " : ""}<a href="#companies/${encodeURIComponent(r.company)}">${esc(r.company)}</a><div class="m">${esc(r.sector || "")}</div></td>
            <td>${r.value == null ? "–" : fmtM(r.value)}</td><td>${esc(r.client)}</td><td>${esc(r.what)}</td><td>${esc(r.date.slice(5))} ${src(r)}</td></tr>`).join("")}</table></div></div>`;
        if (val.length) {
          barChart($("#ko1"), val.slice(0, 15).map((r) => ({ label: r.company, value: Math.round(r.value), note: esc([r.client, r.what].filter(Boolean).join(" · ")), onclick: open(r.company) })), "Rs crore");
          barChart($("#ko2"), Object.entries(bySec).sort((a, b) => b[1] - a[1]).slice(0, 15).map(([k, v]) => ({ label: k, value: Math.round(v), onclick: () => { $("#ks").value = k; draw(); } })), "Rs crore");
        }
      } else {
        const posA = (r) => /upgrade|initiate|raise/.test(r.action) && !/sell|reduce|underweight/i.test(r.rating) || (/buy|add|outperform|overweight/i.test(r.rating) && !/downgrade|cut/.test(r.action));
        const negA = (r) => /downgrade|cut/.test(r.action) || /sell|reduce|underperform|underweight/i.test(r.rating);
        const bySec = {};
        rows.forEach((r) => { const k = r.sector || "Other"; const o = bySec[k] = bySec[k] || { pos: 0, neg: 0, neu: 0 }; if (negA(r)) o.neg++; else if (posA(r)) o.pos++; else o.neu++; });
        const cnt = {};
        rows.forEach((r) => { cnt[r.company] = (cnt[r.company] || 0) + 1; });
        body.innerHTML = `<div class="card"><h2>Brokers' tilt by sector <span class="m">bullish calls → · ← bearish calls</span></h2><div id="kc1"></div></div>
          <div class="card"><h2>Most-discussed stocks <span class="m">number of broker calls</span></h2><div id="kc2"></div></div>
          <div class="card"><h2>${plural(rows.length, "call")}</h2><div class="tw"><table class="tt"><tr><th>Company</th><th>Broker</th><th>Rating</th><th>Target Rs</th><th>Action</th><th>Date</th></tr>
          ${rows.map((r) => `<tr><td>${isWatch(r.company) ? "★ " : ""}<a href="#companies/${encodeURIComponent(r.company)}">${esc(r.company)}</a><div class="m">${esc(r.sector || "")}</div></td>
            <td>${esc(r.broker)}</td><td class="${negA(r) ? "dn" : posA(r) ? "up" : ""}">${esc(r.rating)}</td><td>${r.target == null ? "–" : fmt(Math.round(r.target))}</td>
            <td>${esc(r.action)}</td><td>${esc(r.date.slice(5))} ${src(r)}</td></tr>`).join("")}</table></div></div>`;
        divergingChart($("#kc1"), Object.entries(bySec).sort((a, b) => (b[1].pos + b[1].neg) - (a[1].pos + a[1].neg)).slice(0, 15).map(([k, o]) => ({
          label: k, pos: o.pos, neg: o.neg, neu: o.neu, total: o.pos + o.neg + o.neu,
          tip: `<b>${esc(k)}</b><br>${o.pos} bullish · ${o.neg} bearish · ${o.neu} neutral<br><span class="m">Tap to filter</span>`,
          onclick: () => { $("#ks").value = k; draw(); } })));
        barChart($("#kc2"), Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([k, v]) => ({ label: k, value: v,
          note: esc(rows.filter((r) => r.company === k).map((r) => r.broker + ": " + r.rating).slice(0, 5).join("<br>")), onclick: open(k) })), "call");
      }
    };
    ["kq", "ks", "kw", "kd"].forEach((id) => { $("#" + id).addEventListener(id === "kq" ? "input" : "change", draw); });
    draw();
  }

  async function pagePresentations() {
    const all = await getPres();
    await loadCtx();
    const hasCall = (d) => (window.DESK_CONCALLS.calls || []).some((c) => c.code === d.code);
    if (!all.length) { view.innerHTML = empty("No investor presentations collected yet - they're picked up from BSE on every update."); return; }
    const wl = watchlist();
    const isW = (d) => wl.some((w) => sameCo(d.company, w) || d.company.toLowerCase().includes(w.toLowerCase()));
    const secs = [...new Set(all.map((d) => d.sector || "Unsorted"))].sort();
    const days = [...new Set(all.map((d) => d.when.slice(0, 10)))];
    const perDay = days.slice(0, 14).reverse().map((d) => ({ label: d.slice(5), value: all.filter((x) => x.when.startsWith(d)).length }));
    view.innerHTML = `<div class="sub"><a href="#concalls">← Concalls</a></div><h1>Investor presentations</h1>
      <div class="sub">Filed by companies on BSE · ${plural(all.length, "deck")} over the last ${plural(days.length, "day")} · newest first${wl.length ? " · ★ = your watchlist" : ""}</div>
      <div class="card"><h2>Decks filed per day</h2><div id="pd"></div></div>
      <div class="card"><div class="filters"><input type="search" id="pq" placeholder="Search company or title">
        <select id="ps"><option value="">All sectors</option>${secs.map((x) => `<option>${esc(x)}</option>`).join("")}</select>
        <label class="m"><input type="checkbox" id="pw"> Watchlist only</label></div>
        <ul class="list" id="pl"></ul></div>`;
    const box = $("#pd");
    const W = Math.max(280, box.clientWidth || 600), H = 120, bw = W / perDay.length;
    const mx = Math.max(1, ...perDay.map((r) => r.value));
    box.innerHTML = `<svg viewBox="0 0 ${W} ${H + 18}" width="100%" role="img" aria-label="Decks per day">${perDay.map((r, i) => {
      const h = (r.value / mx) * H;
      return `<rect x="${i * bw + 3}" y="${H - h}" width="${bw - 6}" height="${h}" rx="3" fill="var(--s1)"><title>${r.label}: ${r.value}</title></rect>
        <text x="${i * bw + bw / 2}" y="${H + 14}" text-anchor="middle" class="lab" style="font-size:10px">${r.label}</text>`;
    }).join("")}</svg>`;
    const draw = () => {
      const q = $("#pq").value.toLowerCase(), sec = $("#ps").value, wo = $("#pw").checked;
      const rows = all.filter((d) => (!q || (d.company + " " + d.title).toLowerCase().includes(q))
        && (!sec || (d.sector || "Unsorted") === sec) && (!wo || isW(d)))
        .sort((a, b) => (isW(b) - isW(a)) || (a.when < b.when ? 1 : -1));
      $("#pl").innerHTML = rows.slice(0, 400).map((d) => `<li>
        <div class="t">${isW(d) ? "★ " : ""}<a href="#companies/${encodeURIComponent(d.company)}">${esc(d.company)}</a> ·
          <a href="${esc(d.pdf)}" target="_blank" rel="noopener">open deck (PDF)</a>${hasCall(d) ? ` · <a href="#companies/${encodeURIComponent(d.company)}">concall summary</a>` : ""}</div>
        <div class="src">${esc(d.sector || "Unsorted")} · ${when(d.when)}${d.title ? " · " + esc(d.title.slice(0, 140)) : ""}</div></li>`).join("")
        || `<li class="m">Nothing matches.</li>`;
    };
    $("#pq").oninput = draw; $("#ps").onchange = draw; $("#pw").onchange = draw; draw();
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
    const key = tab === "tab" ? "tab-" + arg : tab === "presentations" ? "concalls" : tab;
    document.querySelectorAll("#tabs a").forEach((a) => a.classList.toggle("on", a.dataset.tab === key));
    try {
      if (tab === "today") await pageToday(arg || null);
      else if (tab === "sectors") await pageSectors(arg || null);
      else if (tab === "companies") await pageCompanies(arg || null);
      else if (tab === "concalls") await pageConcalls(arg || null);
      else if (tab === "peers") await pagePeers(arg || null);
      else if (tab === "presentations") await pagePresentations();
      else if (tab === "markets") await pageMarkets();
      else if (tab === "trackers") await pageTrackers(arg || null);
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
