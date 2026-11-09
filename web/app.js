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
  const CCV = "";
  const BUILD = "";
  // a summary is only shown if it belongs to the company asked for
  async function ccHtml(c) {
    window.DESK_CCH = window.DESK_CCH || {};
    if (window.DESK_CCH[c.k] == null) { try { await loadScript("data/cc/" + c.k + ".js" + CCV); } catch (e) { staleCheck(true); return ""; } }
    const x = window.DESK_CCH[c.k];
    if (!x || typeof x !== "object" || x.c !== c.company) { staleCheck(true); return ""; }
    return x.h || "";
  }
  async function ovHtml(o) {
    window.DESK_OVH = window.DESK_OVH || {};
    if (window.DESK_OVH[o.k] == null) { try { await loadScript("data/cc/" + o.k + ".js" + CCV); } catch (e) { staleCheck(true); return ""; } }
    const x = window.DESK_OVH[o.k];
    if (!x || typeof x !== "object" || x.c !== o.sector) { staleCheck(true); return ""; }
    return x.h || "";
  }
  // the site is rebuilt several times a day; a page left open (tablet!) reloads itself when it is out of date
  let staleBusy = false;
  async function staleCheck(force) {
    if (!BUILD || staleBusy) return;
    staleBusy = true;
    try {
      await loadScript("data/build.js?t=" + Date.now());
      if (window.DESK_BUILD_NOW && window.DESK_BUILD_NOW !== BUILD) {
        const b = document.createElement("div"); b.className = "updbar"; b.textContent = "The site has just been updated - loading the new version…";
        document.body.appendChild(b);
        setTimeout(() => location.reload(), force ? 300 : 1200);
      }
    } catch (e) { /* offline - try later */ }
    staleBusy = false;
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden) staleCheck(); });
  setInterval(() => { if (!document.hidden) staleCheck(); }, 10 * 60 * 1000);
  async function ccText() {
    if (!window.DESK_CCTEXT) { try { await loadScript("data/cctext.js" + CCV); } catch (e) { window.DESK_CCTEXT = {}; } }
    return window.DESK_CCTEXT;
  }
  async function getBsIdx() {
    if (!window.DESK_BSIDX || Array.isArray(window.DESK_BSIDX)) { try { await loadScript("data/bsindex.js"); } catch (e) { /* none yet */ } }
    if (!window.DESK_BSIDX || Array.isArray(window.DESK_BSIDX)) window.DESK_BSIDX = { have: {}, meta: {} };
    return window.DESK_BSIDX;
  }
  async function getTimeline(codes, name) {
    if (!window.DESK_TLIDX) { try { await loadScript("data/tlindex.js"); } catch (e) { window.DESK_TLIDX = {}; } }
    const I = window.DESK_TLIDX;
    const keys = Object.keys(I).filter((k) => (I[k].code && codes.includes(I[k].code)) || (!I[k].code && I[k].name && sameCo(I[k].name, name)));
    window.DESK_TL = window.DESK_TL || {};
    let all = [];
    for (const k of keys) {
      if (!window.DESK_TL[k]) { try { await loadScript("data/tl/" + k + ".js" + CCV); } catch (e) { /* none */ } }
      all = all.concat(window.DESK_TL[k] || []);
    }
    const seen = new Set();
    return all.filter((e) => !seen.has(e.u) && seen.add(e.u)).sort((a, b) => (a.d < b.d ? 1 : -1));
  }
  const TLK = { concall: ["Concall", "--s1"], deck: ["Deck", "--s3"], pivot: ["Pivot", "--s5"], result: ["Results", "--s2"],
    order: ["Order", "--s4"], broker: ["Broker", "--neu"], story: ["Price story", "--caution"] };
  function timelineHtml(list) {
    let month = "";
    return list.map((e) => {
      const m = new Date(e.d + "T00:00").toLocaleDateString("en-IN", { month: "short", year: "numeric" });
      const head = m !== month ? `<div class="tlm">${m}</div>` : ""; month = m;
      const [lbl, col] = TLK[e.k] || [e.k, "--neu"];
      return `${head}<div class="tle"><span class="m tld">${esc(e.d.slice(8))}</span><span class="kc" style="background:var(${e.s === "-" ? "--neg" : col})">${lbl}</span>
        <span>${esc(e.t)}${e.l ? ` <a class="m" href="${esc(e.l)}" target="_blank" rel="noopener">source</a>` : ""}</span></div>`;
    }).join("");
  }
  async function getDir() {
    if (!window.DESK_DIR) { try { await loadScript("data/directory.js"); } catch (e) { window.DESK_DIR = []; } }
    return window.DESK_DIR;
  }
  const screenerLink = (code) => `https://www.screener.in/company/${code}/`;
  const concallRequestLink = (code, name) => `https://github.com/prasoonvj-del/concalls/issues/new?title=${encodeURIComponent("Concall: " + code + " " + name)}&body=${encodeURIComponent("Requested from the Market Desk website. Just press Submit - the latest concall is found on BSE and summarised within about 10 minutes; this issue closes itself.")}`;
  const REPO = "prasoonvj-del/concalls";
  const requestLink = (code, name) => `https://github.com/${REPO}/issues/new?title=${encodeURIComponent("Story: " + code + " " + name)}&body=${encodeURIComponent("Requested from the Market Desk website. Just press Submit - the story is written within about 10 minutes and this issue closes itself.")}`;
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
  // same rules as names.py: a name may only extend another by a generic tail ("Prestige Estates" = "Prestige Estates
  // Projects"), never by a business word ("Mahindra & Mahindra" is not "Mahindra & Mahindra Financial Services")
  const GENERIC_TAIL = new Set(["projects", "industries", "industry", "india", "corporation", "corp", "company", "co", "inc", "group",
    "andspecialeconomiczone", "specialeconomiczone", "sez", "technologies", "technology", "tech", "enterprise", "international",
    "global", "incorporated", "indiaprivate", "indialimited", "infra"]);
  const ALIAS = { mandm: "mahindraandmahindra", mahindra: "mahindraandmahindra", landt: "larsenandtoubro", lt: "larsenandtoubro",
    sbi: "statebankofindia", ril: "relianceindustries", reliance: "relianceindustries", tcs: "tataconsultancyservices",
    hul: "hindustanunilever", airtel: "bhartiairtel", infy: "infosys", hcltech: "hcltechnologies", maruti: "marutisuzukiindia",
    zomato: "eternal", indigo: "interglobeaviation", adaniports: "adaniportsandspecialeconomiczone", kotak: "kotakmahindrabank" };
  function sameCo(a, b) {
    let x = norm(a), y = norm(b);
    if (!x || !y) return false;
    x = ALIAS[x] || x; y = ALIAS[y] || y;
    if (x === y) return true;
    const [sh, lo] = x.length < y.length ? [x, y] : [y, x];
    return sh.length > 3 && lo.startsWith(sh) && GENERIC_TAIL.has(lo.slice(sh.length));
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
          el("text", { x: x(i), y: H - 6, "text-anchor": "middle" }, s, !/^\d{4}-\d\d-\d\d/.test(d) ? d : xs.length > 120 ? d.slice(5, 7) + "/" + d.slice(2, 4) : d.slice(8) + "/" + d.slice(5, 7));
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
  function indexChart(host, xs, series, unit, bands, height) {
    mount(host, (h, W) => {
      const H = height || 260, L = 44, R = 14, T = 10, B = 26;
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
      (bands || []).forEach((b) => {
        const r1 = el("rect", { x: x(b.i0), y: T, width: Math.max(3, x(b.i1) - x(b.i0)), height: H - T - B, fill: b.color, opacity: 0.16 }, s);
        if (b.label) el("text", { x: (x(b.i0) + x(b.i1)) / 2, y: T + 11, "text-anchor": "middle", style: "font-size:10px;font-weight:600", fill: b.color }, s, b.label);
        return r1;
      });
      const every = Math.ceil(xs.length / Math.max(2, Math.floor((W - L - R) / 70)));
      xs.forEach((d, i) => {
        if (i % every === 0 || i === xs.length - 1)
          el("text", { x: x(i), y: H - 6, "text-anchor": "middle" }, s, !/^\d{4}-\d\d-\d\d/.test(d) ? d : xs.length > 120 ? d.slice(5, 7) + "/" + d.slice(2, 4) : d.slice(8) + "/" + d.slice(5, 7));
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

  const PIVOT_LBL = { capacity: "Capacity", order: "Big order", legal: "Legal / case", approval: "Approval", strategy: "Strategy shift",
    "m&a": "M&A", funding: "Funding / debt", rating: "Rating", management: "Management" };
  const pivotLine = (r, showCo = true) => `<div class="pv"><span class="kc" style="background:var(${r.sent === "-" ? "--neg" : "--s1"})">${esc(PIVOT_LBL[r.type] || r.type || "Pivot")}</span>
    ${showCo ? `<a href="#companies/${encodeURIComponent(r.company)}"><b>${esc(r.company)}</b></a> - ` : ""}${esc(r.what)}
    ${r.theme ? ` <a class="thchip" href="#trackers/themes" onclick="localStorage.setItem('pivtheme', JSON.stringify(${esc(JSON.stringify(themeOf(r.theme)))}))">${esc(themeOf(r.theme))}</a>` : ""}${r.src ? ` <span class="m">(${esc(r.src)})</span>` : ""}
    ${r.why ? `<div class="m">→ ${esc(r.why)} · ${esc(r.date.slice(5))} · <a href="${esc(r.link)}" target="_blank" rel="noopener">source</a></div>` : `<div class="m">${esc(r.date.slice(5))} · <a href="${esc(r.link)}" target="_blank" rel="noopener">source</a></div>`}</div>`;
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
      ${b.big ? `<div class="card md"><h2>The big picture</h2><div id="bigp">${b.big}</div></div>` : ""}
      ${wl.length ? `<div class="card"><h2>Your watchlist <span class="m">${esc(wl.join(", "))}</span></h2>${
        wlStories.length ? `<div id="wlf"></div>` : `<div class="m">No news on your watchlist in this brief.</div>`}</div>` : ""}
      <div id="pivw"></div><div id="wah"></div>
      ${top.length ? `<h2 style="margin:18px 0 10px">Top stories, explained</h2><div class="grid g2" id="topx">${top.map((t, ti) => {
        const s = byId[t.id];
        return `<div class="card explain"><h3 class="t" data-story="${s.id}" style="cursor:pointer">${esc(s.title)}</h3>
          <div style="margin-bottom:6px">${sentChip(s.sent)} · ${impDots(s.imp)} · <span class="chip link" data-go="#sectors/${encodeURIComponent(s.cat)}">${esc(s.cat)}</span></div>
          ${t.why ? `<div class="row"><b>Why it matters:</b> ${esc(t.why)}</div>` : ""}
          ${t.context ? `<div class="row"><b>Context:</b> ${esc(t.context)}</div>` : ""}
          ${t.watch ? `<div class="row"><b>What to watch:</b> ${esc(t.watch)}</div>` : ""}
          <div class="ctxs" data-cos="${esc(JSON.stringify(s.companies.slice(0, 3)))}"></div>
          <div class="src" style="margin-top:6px">${plural(s.outlets, "outlet")}: ${esc(s.sources.slice(0, 4).map((x) => x.name).join(", "))}</div></div>`;
      }).join("")}</div>` : ""}
      <div class="grid g2" style="margin-top:14px">
        <div class="card"><h2>Sector mood <span class="m">stories by sentiment</span></h2>
          ${legend([["Negative", cssv("--neg")], ["Positive", cssv("--pos")]])}<div id="c-mood"></div><div id="t-mood"></div></div>
        <div class="card"><h2>News flow <span class="m">stories per day, busiest sectors</span></h2><div id="l-flow"></div><div id="c-flow"></div><div id="t-flow"></div></div>
      </div>
      <div class="card"><h2>Sector by sector <span class="m">tap a row for the full sector page</span></h2><div class="secs2">${b.sections.map((s) => `<div class="srow" data-go="#sectors/${encodeURIComponent(s.cat)}">
          <div><b>${esc(s.cat)}</b><div class="m">${s.ids.length} · ${s.pos}▲ ${s.neg}▼</div><span class="mb">${s.ids.length ? `<i style="width:${(100 * s.pos) / s.ids.length}%;background:var(--pos)"></i><i style="width:${(100 * s.neg) / s.ids.length}%;background:var(--neg)"></i>` : ""}</span></div>
          <div>${s.one ? `<div class="clamp md">${s.one}</div>` : `<span class="m">-</span>`}</div></div>`).join("")}</div></div>
      <div class="card"><h2>Most-mentioned companies <span class="m">tap a bar for everything on the company</span></h2><div id="c-comp"></div><div id="t-comp"></div></div>
      ${b.failed && b.failed.length ? `<details class="card"><summary class="m" style="cursor:pointer">${plural(b.failed.length, "feed")} didn't load this time</summary>
        <ul class="list">${b.failed.map((f) => `<li>${esc(f.name)} <span class="src">(${esc(f.folder)}) - ${esc(f.error)}</span></li>`).join("")}</ul></details>` : ""}`;
    $("#datesel").onchange = (e) => go("#today/" + e.target.value);
    if ($("#wlf")) storyFeed($("#wlf"), wlStories, { page: 6, ph: "Search watchlist news" });
    clampBlock($("#bigp"), 620, "bigpicture");
    clampBlock($("#topx"), 900, "explained");
    clampBlock(view.querySelector(".secs2"), 520, "sectors");
    loadCtx().then(() => {
      const PV = ((window.DESK_TRACK || {}).trackers || {}).pivots || [];
      const wk = new Date(b.date + "T00:00"); wk.setDate(wk.getDate() - 7);
      const recentP = PV.filter((r) => !/\b(drhp|ipo|public issue|sebi nod|listing on|lists on|files? (for|draft))\b/i.test(r.what) && r.date >= wk.toISOString().slice(0, 10) && r.date <= b.date)
        .sort((x, y) => (isWatch(y.company) - isWatch(x.company)) || (y.imp || 0) - (x.imp || 0) || (x.date < y.date ? 1 : -1)).slice(0, 10);
      if ($("#pivw") && recentP.length) {
        $("#pivw").innerHTML = `<div class="card"><h2>Pivots of the week <span class="m">company-changing news that can re-rate or de-rate a stock · <a href="#trackers/pivots">all ${PV.length}</a></span></h2>
          <div class="pvg" id="pvgw">${recentP.map((r) => pivotLine(r)).join("")}</div></div>`;
        clampBlock($("#pvgw"), 330, "pivots");
      }
      if ($("#wah")) { renderWeekAhead($("#wah")); clampBlock($("#wal"), 430, "weekahead"); }
      view.querySelectorAll(".ctxs").forEach((d) => { d.innerHTML = JSON.parse(d.dataset.cos).map(ctxLine).join(""); });
      // "Stocks in focus": company names open the company page, with the tone of their last concall
      const bp = $("#bigp");
      if (bp) bp.querySelectorAll("table tr td:first-child").forEach((td) => {
        const name = td.textContent.replace(/\*/g, "").trim();
        if (!name || td.querySelector("a")) return;
        const x = ctxOf(name);
        const known = x || b.stories.some((st2) => st2.companies.some((c) => sameCo(c, name)));
        if (!known) return;
        td.innerHTML = `<a href="#companies/${encodeURIComponent(x ? x.name : name)}">${esc(name)}</a>` +
          (x && x.call && x.call.tone ? `<div><span class="tone ${esc(x.call.tone)}" title="Tone of the last concall (${esc(x.call.quarter)})">${esc(x.call.tone)}</span></div>` : "");
      });
    });

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
    const compRows = Object.entries(comp).sort((a, c) => c[1].length - a[1].length).slice(0, 10).map(([c, list]) => {
      const p = list.filter((s) => s.sent === "+").length, n = list.filter((s) => s.sent === "-").length;
      return { label: c, value: list.length, note: `${p}▲ ${n}▼`, onclick: () => go("#companies/" + encodeURIComponent(c)) };
    });
    if (compRows.length) {
      barChart($("#c-comp"), compRows, "story");
      $("#t-comp").innerHTML = tableView(["Company", "Stories"], compRows.map((r) => [r.label, r.value]));
    } else $("#c-comp").innerHTML = `<div class="m">No company-specific stories.</div>`;
  }

  /** A story list with search, filters, grouping of repeats and "show more" - used on every news page. */
  function storyFeed(host, stories, opts = {}) {
    const page = opts.page || 15, rated = stories.some((x) => x.imp);
    host.innerHTML = `<div class="filters"><input type="search" class="fq" placeholder="${esc(opts.ph || "Search these stories")}">
      ${rated ? `<select class="fs"><option value="">Any sentiment</option><option value="+">Positive</option><option value="-">Negative</option><option value="=">Neutral</option></select>
      <select class="fo"><option value="imp">Most important first</option><option value="new">Newest first</option></select>` : ""}</div>
      <ul class="list fl"></ul>`;
    let shown = page;
    const draw = () => {
      const q = host.querySelector(".fq").value.toLowerCase();
      const fs = rated ? host.querySelector(".fs").value : "", fo = rated ? host.querySelector(".fo").value : "new";
      const xs = stories.filter((x) => (!q || x.title.toLowerCase().includes(q)) && (!fs || x.sent === fs))
        .sort((a, b) => (rated ? (fo === "imp" ? (b.imp || 0) - (a.imp || 0) || (b.outlets || 0) - (a.outlets || 0) : 0) : (b.outlets || 0) - (a.outlets || 0)) || (a.when < b.when ? 1 : -1));
      const groups = groupNews(xs.map((x) => ({ s: x })));
      host.querySelector(".fl").innerHTML = groups.slice(0, shown).map(({ x, more }) => {
        const s1 = x.s, srcs = s1.sources.map((y) => y.name).filter((v, i, a) => a.indexOf(v) === i);
        return `<li class="nl"><div class="t" data-story="${s1.id}">${esc(s1.title)}</div>
          <div class="src">${s1.imp ? sentChip(s1.sent) + " · " + impDots(s1.imp) + " · " : ""}${esc(srcs.slice(0, 3).join(", "))}${srcs.length > 3 ? ` +${srcs.length - 3}` : ""} · ${when(s1.when)}${
          more.length ? ` · <details class="sim"><summary>+${more.length} similar</summary>${more.map((m) => `<div class="t" data-story="${m.s.id}">${esc(m.s.title)}</div>`).join("")}</details>` : ""}</div></li>`;
      }).join("") + (groups.length > shown ? `<li><button class="fmore">Show ${Math.min(page * 2, groups.length - shown)} more${groups.length - shown > page * 2 ? ` (${groups.length - shown} left)` : ""}</button></li>` : "")
        || `<li class="m">Nothing matches.</li>`;
      const mb = host.querySelector(".fmore");
      if (mb) mb.onclick = () => { shown += page * 2; draw(); };
    };
    host.querySelector(".fq").oninput = () => { shown = page; draw(); };
    if (rated) { host.querySelector(".fs").onchange = draw; host.querySelector(".fo").onchange = draw; }
    draw();
  }
  /** Show the first part of a long block, with one tap to see the rest (and to fold it back). */
  function clampBlock(el, px, key) {
    if (!el || el.scrollHeight <= px + 120) return;
    // remembered per section: once you choose "Show all", it stays open on every visit until you tap "Show less"
    const k = "open-" + (key || el.id || "block");
    const btn = document.createElement("button"); btn.className = "unclamp";
    const set = (open, save) => {
      el.classList.toggle("clamped", !open);
      el.style.maxHeight = open ? "none" : px + "px";
      btn.textContent = open ? "Show less ▴" : "Show all ▾";
      if (save) store.set(k, open);
    };
    btn.onclick = () => { const open = el.classList.contains("clamped"); set(open, true); if (!open) el.scrollIntoView({ block: "nearest" }); };
    el.after(btn);
    set(!!store.get(k, false), false);
  }
  /** Turn the h3 sections of a write-up into fold-outs; sections matching `keepOpen` stay open. */
  function foldSections(root, keepOpen) {
    root.querySelectorAll("h2, h3").forEach((h) => {
      const d = document.createElement("details"); d.className = "fold";
      if (keepOpen.test(h.textContent)) d.open = true;
      const sm = document.createElement("summary"); sm.textContent = h.textContent; d.appendChild(sm);
      let n = h.nextSibling;
      while (n && !(n.nodeType === 1 && /^H[23]$/.test(n.tagName))) { const nx = n.nextSibling; d.appendChild(n); n = nx; }
      h.replaceWith(d);
    });
  }
  const marketLine = (sector) => {
    const M = ((window.DESK_TRACK || {}).markets || {}).series || [];
    const se = M.find((x) => x.group === "India indices" && x.note === sector);
    if (!se || se.pts.length < 25) return "";
    const l = se.pts[se.pts.length - 1][1], m1 = se.pts[Math.max(0, se.pts.length - 22)][1], d1 = se.pts[se.pts.length - 2][1];
    return `<a class="mline" href="#markets">${esc(se.name)} ${spark(se.pts.slice(-66).map((p) => p[1]), cssv(l >= m1 ? "--pos" : "--neg"), 80, 20)}
      <span class="${pctCls(l / d1 - 1)}">${pct((l / d1 - 1) * 100)} 1D</span> · <span class="${pctCls(l / m1 - 1)}">${pct((l / m1 - 1) * 100)} 1M</span></a>`;
  };

  async function pageSectors(cat) {
    if (!IDX.briefs.length) { view.innerHTML = empty("No news brief yet."); return; }
    const b = currentBrief || (await getBrief(current || latest()));
    currentBrief = b; current = b.date;
    await loadCtx();
    const sec = b.sections.find((s) => s.cat === cat) || b.sections[0];
    if (!sec) { view.innerHTML = empty("No sectors in this brief."); return; }
    const byId = Object.fromEntries(b.stories.map((s) => [s.id, s]));
    const cc = await getConcalls();
    const ov = cc.overviews.filter((o) => o.sector === sec.cat).sort((a, c) => (a.quarter < c.quarter ? 1 : -1))[0];
    const calls = cc.calls.filter((c) => c.sector === sec.cat).sort((a, c) => (a.date < c.date ? 1 : -1))
      .filter((c, i, all) => all.findIndex((x) => x.code === c.code) === i);
    const T = (window.DESK_TRACK || {}).trackers || {};
    const res = (T.results || []).filter((r) => r.sector === sec.cat);
    view.innerHTML = `<h1>Sectors</h1><div class="sub">${esc(b.label)} · <a href="#today/${b.date}">back to the brief</a></div>
      <div class="side">
        <div class="card secnav">${b.sections.map((s) => `<a href="#sectors/${encodeURIComponent(s.cat)}" class="${s.cat === sec.cat ? "on" : ""}">
          <span>${esc(s.cat)}</span><span class="m">${s.ids.length}</span></a>`).join("")}</div>
        <div>
          <div class="card md"><h2>${esc(sec.cat)} <span class="m">${plural(sec.ids.length, "story")} · ${sec.pos}▲ ${sec.neg}▼ ${sec.neu}•</span></h2>
            ${marketLine(sec.cat)}
            ${sec.one ? `<p><b>${sec.one}</b></p>` : ""}<div id="sw">${sec.html || `<p class="m">Too few stories today for a write-up - see the list below.</p>`}</div></div>
          ${ov || calls.length || res.length ? `<div class="card"><h2>What managements said <span class="m">concalls${res.length ? " & results" : ""} in this sector</span></h2>
            ${ov ? `<div class="md"><div class="m">Sector overview · ${esc(ov.quarter)} · ${ov.companies.length} companies</div>${await ovHtml(ov)}</div>` : ""}
            ${calls.length ? `<div class="chips">${calls.slice(0, 30).map((c) => `<span class="chip link" data-go="#companies/${encodeURIComponent(c.company)}">${esc(c.company)}${c.tone ? ` <span class="tone ${esc(c.tone)}">${esc(c.tone)}</span>` : ""}</span>`).join("")}${calls.length > 30 ? `<a class="chip link" href="#concalls/${encodeURIComponent(sec.cat)}">all ${calls.length} →</a>` : ""}</div>` : ""}
            ${res.length ? `<div class="m" style="margin-top:8px">Results this season: ${res.slice(0, 12).map((r) => `<a href="#companies/${encodeURIComponent(r.company)}">${esc(r.company)}</a> <span class="${pctCls(r.pat_yoy)}">${pct(r.pat_yoy)}</span>`).join(" · ")}${res.length > 12 ? ` · <a href="#trackers/results">all →</a>` : ""}</div>` : ""}</div>` : ""}
          <div class="card"><h2>Stories</h2><div id="sl"></div></div>
        </div></div>`;
    storyFeed($("#sl"), sec.ids.map((i) => byId[i]).filter(Boolean), { ph: "Search " + sec.cat + " stories" });
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
    if (!window.DESK_CONEWS) { try { await loadScript("data/conews.js"); } catch (e) { window.DESK_CONEWS = {}; } }
    const briefs = IDX.briefs.slice(-7).map((x) => ({ date: x.date }));
    const mentions = {};
    Object.entries(window.DESK_CONEWS).forEach(([c, list]) => {
      const k = Object.keys(mentions).find((m) => sameCo(m, c)) || c;
      list.forEach((m) => (mentions[k] = mentions[k] || []).push({ s: { id: m.id, title: m.t, sent: m.s, imp: m.i, when: m.w, cat: m.c }, date: m.d }));
    });
    cc.calls.forEach((c) => { if (!Object.keys(mentions).some((m) => sameCo(m, c.company))) mentions[c.company] = mentions[c.company] || []; });
    const known = new Set(cc.calls.map((c) => c.code));
    P.forEach((d) => { if (!known.has(d.code) && !Object.keys(mentions).some((m) => sameCo(m, d.company))) mentions[d.company] = []; });
    const DIRL = await getDir();
    const dirByCode = new Map(DIRL.map((x) => [x[0], x]));
    const dirIdx = new Map(DIRL.map((x) => [norm(x[1]), x]));
    const dirFor = (n) => {
      const k0 = norm(n), k = ALIAS[k0] || k0;
      if (dirIdx.has(k)) return dirIdx.get(k);
      for (const t of GENERIC_TAIL) if (dirIdx.has(k + t)) return dirIdx.get(k + t);
      return null;
    };
    const latestCall = (n) => cc.calls.filter((c) => sameCo(c.company, n)).sort((a, c) => (a.date < c.date ? 1 : -1))[0];

    if (!name) {
      const BSI = await getBsIdx();
      // every listed company is in the list, even before we have anything on it
      const have = new Set([...cc.calls.map((c) => c.code), ...P.map((d) => d.code)]);
      const keyNames = Object.keys(mentions);
      const taken = new Set(keyNames.map((k) => (dirFor(k) || [null])[0]).filter(Boolean));
      DIRL.forEach((x) => { if (!have.has(x[0]) && !taken.has(x[0])) mentions[x[1]] = mentions[x[1]] || []; });
      const rows = Object.keys(mentions).map((n) => {
        const m = mentions[n], call = latestCall(n);
        const deck = call ? deckFor(call) || P.find((d) => d.code === call.code) : P.find((d) => sameCo(d.company, n));
        const res = (TK.results || []).find((r) => sameCo(r.company, n));
        return { n, m: m.length, pos: m.filter((x) => x.s.sent === "+").length, neg: m.filter((x) => x.s.sent === "-").length,
          story: (() => { const cd = call ? call.code : deck ? deck.code : (dirFor(n) || [])[0]; return cd && BSI.have[cd] ? BSI.have[cd] : null; })(),
          call, deck, res, sector: call ? call.sector : (deck && deck.sector) || (res && res.sector) || (dirFor(n) || [0, 0, ""])[2] || "" };
      });
      const secs = [...new Set(rows.map((r) => r.sector).filter(Boolean))].sort();
      const st = store.get("colist", { q: "", sec: "", sort: "news", has: "" });
      const BM = BSI.meta || {};
      view.innerHTML = `<h1>Companies</h1><div class="sub">${plural(rows.length, "company")} - every company listed on BSE · news from the last ${plural(briefs.length, "brief")}, concall summaries, decks and results in one row each</div>
        ${BM.total ? `<div class="card prog"><b>The story so far:</b> ${BM.done || 0} of ${BM.total} concall companies written
          <span class="pbar"><i style="width:${Math.round((100 * (BM.done || 0)) / BM.total)}%"></i></span>
          <span class="m">up to ${BM.per_update || 6} more each update${BM.next && BM.next.length ? " · next: " + BM.next.slice(0, 6).map(esc).join(", ") + (BM.next.length > 6 ? "…" : "") : ""}</span></div>` : ""}
        <div class="filters"><input type="search" id="cq" placeholder="Search a company" value="${esc(st.q)}">
          <select id="cs"><option value="">All sectors</option>${secs.map((x) => `<option ${x === st.sec ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
          <select id="ch"><option value="">All listed companies</option><option value="data" ${st.has === "data" ? "selected" : ""}>With anything on file</option><option value="call" ${st.has === "call" ? "selected" : ""}>With a concall summary</option>
            <option value="deck" ${st.has === "deck" ? "selected" : ""}>With an investor deck</option>
            <option value="story" ${st.has === "story" ? "selected" : ""}>With "the story so far"</option><option value="res" ${st.has === "res" ? "selected" : ""}>With results this season</option></select>
          <select id="co"><option value="news">Most in the news</option><option value="az" ${st.sort === "az" ? "selected" : ""}>A–Z</option>
            <option value="pos" ${st.sort === "pos" ? "selected" : ""}>Most positive news</option><option value="neg" ${st.sort === "neg" ? "selected" : ""}>Most negative news</option>
            <option value="call" ${st.sort === "call" ? "selected" : ""}>Latest concall first</option></select><button id="coclr" class="clr" hidden>✕ Clear filters</button></div>
        <div class="card tw"><table class="tt co" id="cl"></table></div>`;
      const draw = () => {
        Object.assign(st, { q: $("#cq").value, sec: $("#cs").value, has: $("#ch").value, sort: $("#co").value }); store.set("colist", st);
        $("#coclr").hidden = !(st.q || st.sec || st.has);
        const q = st.q.toLowerCase();
        const score = (r) => (r.call ? 4 : 0) + (r.deck ? 2 : 0) + (r.res ? 1 : 0);
        const sorters = { news: (a, b) => b.m - a.m || score(b) - score(a) || a.n.localeCompare(b.n), az: (a, b) => a.n.localeCompare(b.n), pos: (a, b) => b.pos - a.pos || b.m - a.m,
          neg: (a, b) => b.neg - a.neg || b.m - a.m, call: (a, b) => ((b.call ? b.call.date : "") > (a.call ? a.call.date : "") ? 1 : -1) };
        const list = rows.filter((r) => (!q || r.n.toLowerCase().includes(q)) && (!st.sec || r.sector === st.sec)
          && (!st.has || (st.has === "data" ? (r.m || r.call || r.deck || r.res) : st.has === "call" ? r.call : st.has === "deck" ? r.deck : st.has === "story" ? r.story : r.res))).sort(sorters[st.sort] || sorters.news);
        const bar = (r) => r.m ? `<span class="mb" title="${r.pos} positive, ${r.neg} negative, ${r.m - r.pos - r.neg} neutral"><i style="width:${(100 * r.pos) / r.m}%;background:var(--pos)"></i><i style="width:${(100 * r.neg) / r.m}%;background:var(--neg)"></i></span>` : "";
        $("#cl").innerHTML = `<tr><th>Company</th><th>News</th><th>Concall</th><th>Results</th><th>Deck</th><th>Story</th></tr>` + list.slice(0, shown).map((r) => `<tr>
          <td><a href="#companies/${encodeURIComponent(r.n)}">${isWatch(r.n) ? "★ " : ""}${esc(r.n)}</a><div class="m">${esc(r.sector || "")}</div></td>
          <td>${r.m ? `${r.m} ${bar(r)}` : `<span class="m">–</span>`}</td>
          <td>${r.call ? `${esc(r.call.quarter)} ${r.call.tone ? `<span class="tone ${esc(r.call.tone)}">${esc(r.call.tone)}</span>` : ""}` : `<span class="m">–</span>`}</td>
          <td>${r.res ? `profit <span class="${pctCls(r.res.pat_yoy)}">${pct(r.res.pat_yoy)}</span>` : `<span class="m">–</span>`}</td>
          <td>${r.deck ? `<a href="${esc(r.deck.pdf)}" target="_blank" rel="noopener">PDF</a>${r.deck.one ? " ✦" : ""}` : `<span class="m">–</span>`}</td>
          <td>${r.story ? `<a href="#companies/${encodeURIComponent(r.n)}">✓ ${esc(new Date(r.story + "T00:00").toLocaleDateString("en-IN", { day: "2-digit", month: "short" }))}</a>` : `<span class="m">–</span>`}</td></tr>`).join("")
          + (list.length ? "" : `<tr><td colspan="6" class="m">No match.</td></tr>`)
          + (list.length > shown ? `<tr><td colspan="6"><button id="cmore">Show ${Math.min(100, list.length - shown)} more of ${list.length - shown}</button></td></tr>` : "");
        const mb = $("#cmore"); if (mb) mb.onclick = () => { shown += 100; draw(); };
      };
      let shown = 60;
      $("#coclr").onclick = () => { ["cq", "cs", "ch"].forEach((id) => { $("#" + id).value = ""; }); shown = 60; draw(); };
      ["cq", "cs", "ch", "co"].forEach((id) => $("#" + id).addEventListener(id === "cq" ? "input" : "change", () => { shown = 60; draw(); })); draw();
      return;
    }

    const key = Object.keys(mentions).find((m) => sameCo(m, name)) || name;
    const dirE = dirFor(key);
    const seenT = new Set();
    const items = (mentions[key] || []).sort((a, c) => (a.s.when < c.s.when ? 1 : -1))
      .filter((x) => { const k = x.s.title.toLowerCase().replace(/\W+/g, ""); if (seenT.has(k)) return false; seenT.add(k); return true; });
    const groups = groupNews(items);
    const call = latestCall(name);
    const tk = ["results", "orders", "calls", "pivots"].map((k) => (TK[k] || []).filter((r) => sameCo(r.company, name)));
    const decks = P.filter((d) => sameCo(d.company, name) || (call && d.code === call.code)).slice(0, 6);
    const nextRes = (TK.calendar || []).find((r) => (sameCo(r.company, name) || (call && r.code === call.code)) && r.when >= new Date().toISOString().slice(0, 10));
    const sector = call ? call.sector : (decks[0] && decks[0].sector) || (dirE && dirE[2]) || (items[0] ? items[0].s.cat : "");
    const pz = items.filter((x) => x.s.sent === "+").length, nz = items.filter((x) => x.s.sent === "-").length;
    const res = tk[0][0], brk = tk[2][0], ord = tk[1][0];
    const chips = [
      call && call.tone ? `<span class="chip">Concall ${esc(call.quarter)}: <span class="tone ${esc(call.tone)}">${esc(call.tone)}</span>${call.prev_tone && call.prev_tone !== call.tone ? ` <span class="m">was ${esc(call.prev_tone)}</span>` : ""}</span>` : "",
      res ? `<span class="chip">Results ${esc(res.quarter)}:${res.rev_yoy != null ? ` revenue <span class="${pctCls(res.rev_yoy)}">${pct(res.rev_yoy)}</span>` : ""}${res.rev_yoy != null && res.pat_yoy != null ? " ·" : ""}${res.pat_yoy != null ? ` profit <span class="${pctCls(res.pat_yoy)}">${pct(res.pat_yoy)}</span>` : ""}</span>` : "",
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
    view.innerHTML = `<div class="cohead"><h1>${esc(key)}</h1>
        <div class="sub"><a href="#companies">All companies</a>${sector ? ` · <a href="#sectors/${encodeURIComponent(sector)}">${esc(sector)}</a>` : ""}${call ? ` · <a href="#peers/${encodeURIComponent(call.sector)}">peers</a> · <a href="${esc(call.pdf)}" target="_blank" rel="noopener">transcript</a>` : ""}${decks[0] ? ` · <a href="${esc(decks[0].pdf)}" target="_blank" rel="noopener">latest deck</a>` : ""}${(call || decks[0] || dirE) ? ` · <a href="${screenerLink(call ? call.code : decks[0] ? decks[0].code : dirE[0])}" target="_blank" rel="noopener">Screener</a>` : ""}</div>
        ${chips ? `<div class="chips">${chips}</div>` : ""}${figs}</div>
      <div id="cobody"></div>`;
    const newsLine = (g) => `<li class="nl"><div class="t" data-story-date="${g.x.date}" data-sid="${g.x.s.id}">${esc(g.x.s.title)}</div>
        <div class="src">${sentChip(g.x.s.sent)} · ${impDots(g.x.s.imp)} · ${when(g.x.s.when)}${g.more.length ? ` · <details class="sim"><summary>+${g.more.length} similar</summary>${g.more.map((m) => `<div class="t" data-story-date="${m.date}" data-sid="${m.s.id}">${esc(m.s.title)}</div>`).join("")}</details>` : ""}</div></li>`;
    const deckBlock = (d, open) => `<details class="sum" ${open ? "open" : ""}><summary><span class="n">${esc((d.title || "Investor presentation").slice(0, 110))}</span><span class="m">${when(d.when)}</span>
        <span class="r2">${d.one ? `<span class="badge">summary</span>` : d.scan ? `<span class="badge w" title="Image-only slides - no text for the AI to read">images only</span>` : ""}</span></summary>
        <div class="b md">${d.one ? `<p><b>${esc(d.one)}</b></p>` : ""}${d.html || (d.scan ? `<div class="m">The slides are images, so there's no text to summarise.</div>` : `<div class="m">Summary not written yet - it'll appear after a coming update.</div>`)}
        <p><a href="${esc(d.pdf)}" target="_blank" rel="noopener">Open the deck (PDF)</a></p></div></details>`;
    const trackerList = () => `${tk[3].length ? `<div class="pvg" style="margin-bottom:6px">${tk[3].map((r) => pivotLine(r, false)).join("")}</div>` : ""}<ul class="list">
        ${tk[0].map((r) => `<li><div class="t">Results ${esc(r.quarter)}: revenue ${r.revenue == null ? "–" : "Rs " + fmtM(r.revenue) + " cr"} (<span class="${pctCls(r.rev_yoy)}">${pct(r.rev_yoy)}</span>), net profit ${r.profit == null ? "–" : "Rs " + fmtM(r.profit) + " cr"} (<span class="${pctCls(r.pat_yoy)}">${pct(r.pat_yoy)}</span>)${r.read ? " · " + esc(r.read) : ""}</div><div class="src">${esc(r.date)} · <a href="${esc(r.link)}" target="_blank" rel="noopener">source</a></div></li>`).join("")}
        ${tk[1].map((r) => `<li><div class="t">Order: ${r.value == null ? "" : "Rs " + fmtM(r.value) + " cr "}${esc(r.client ? "from " + r.client : "")} ${esc(r.what)}</div><div class="src">${esc(r.date)} · <a href="${esc(r.link)}" target="_blank" rel="noopener">source</a></div></li>`).join("")}
        ${tk[2].map((r) => `<li><div class="t">${esc(r.broker)}: ${esc(r.rating)}${r.target ? ", target Rs " + fmt(Math.round(r.target)) : ""}${r.action ? " (" + esc(r.action) + ")" : ""}</div><div class="src">${esc(r.date)} · <a href="${esc(r.link)}" target="_blank" rel="noopener">source</a></div></li>`).join("")}</ul>`;
    const body = $("#cobody");
    const callHtml = call ? await ccHtml(call) : "";
    const tlist = await getTimeline([call && call.code, ...decks.map((d) => d.code)].filter(Boolean), key);
    const tlCard = tlist.length ? `<div class="card"><h2>Timeline <span class="m">everything on record for ${esc(key)} - kept for good · ${plural(tlist.length, "entry")}</span></h2><div id="tlb" class="tl">${timelineHtml(tlist)}</div></div>` : "";
    const bsCode = call ? call.code : decks[0] ? decks[0].code : dirE ? dirE[0] : null;
    await getBsIdx();
    let story = null;
    if (bsCode && window.DESK_BSIDX.have[bsCode]) {
      window.DESK_BS = window.DESK_BS || {};
      if (!window.DESK_BS[bsCode]) { try { await loadScript("data/bs/" + bsCode + ".js" + CCV); } catch (e) { /* none */ } }
      story = window.DESK_BS[bsCode] || null;
    }
    const perDay = briefs.map((b) => { const xs = items.filter((x) => x.date === b.date); return { label: b.date.slice(5), pos: xs.filter((x) => x.s.sent === "+").length, neg: xs.filter((x) => x.s.sent === "-").length, neu: xs.filter((x) => x.s.sent !== "+" && x.s.sent !== "-").length }; })
      .map((r) => Object.assign(r, { total: r.pos + r.neg + r.neu, tip: `<b>${r.label}</b><br>${r.pos} positive · ${r.neg} negative · ${r.neu} neutral` }));
    const hasTk = tk[0].length + tk[1].length + tk[2].length + tk[3].length > 0;
    const askCard = !call && bsCode ? `<div class="card"><h2>Concall</h2><div class="m">No concall summary for this company yet - it may file its transcript later, or under a heading we only started reading today.</div>
        <p><a class="btn" href="${concallRequestLink(bsCode, key)}" target="_blank" rel="noopener">Summarise its latest concall</a></p>
        <div class="m">Opens a one-line request on GitHub - press "Submit"; the transcript is found on BSE and summarised here in about 10 minutes.</div></div>` : "";
    const concallCard = call ? `<div class="card md"><h2>Concall ${esc(call.quarter)} <span class="m">filed ${esc(call.date)}</span></h2>
        <div style="margin-bottom:8px">${call.tone ? `<span class="tone ${esc(call.tone)}">${esc(call.tone)}</span>` : ""} ${call.compared ? `<span class="badge">vs last quarter</span>` : ""}
        ${call.checks.length ? `<span class="badge w">⚠ ${call.checks.length} to check</span>` : ""}</div>
        ${call.checks.length ? `<div class="warn">Highlighted figures weren't found word-for-word in the transcript - check them in the PDF.</div>` : ""}
        ${callHtml}<p><a href="${esc(call.pdf)}" target="_blank" rel="noopener">Original transcript (PDF)</a></p></div>` : "";
    const deckCard = decks.length ? `<div class="card md"><h2>Investor deck <span class="m">${when(decks[0].when)}</span></h2>
        ${decks[0].one ? `<p><b>${esc(decks[0].one)}</b></p>` : ""}${decks[0].html || (decks[0].scan ? `<div class="m">The slides are images, so there's no text to summarise.</div>` : `<div class="m">Summary not written yet - it'll appear after a coming update.</div>`)}
        <p><a href="${esc(decks[0].pdf)}" target="_blank" rel="noopener">Open the deck (PDF)</a></p>
        ${decks.length > 1 ? `<div class="m">Earlier decks: ${decks.slice(1).map((d) => `<a href="${esc(d.pdf)}" target="_blank" rel="noopener">${esc(d.when.slice(0, 10))}</a>${d.one ? ` - ${esc(d.one.slice(0, 120))}` : ""}`).join(" · ")}</div>` : ""}</div>` : "";
    const storyCard = story ? `<div class="card md"><h2>The story so far <span class="m">last 2 years · share price & what moved it</span></h2>
        ${story.one ? `<p><b>${esc(story.one)}</b></p>` : ""}<div id="bspx"></div>
        ${story.moves && story.moves.length ? `<div class="m" style="margin:2px 0 8px">Shaded: biggest 4-week moves - ${story.moves.map((m) => `<span class="${m.pct >= 0 ? "up" : "dn"}">${esc(m.from.slice(2, 7))} ${m.pct > 0 ? "+" : ""}${Math.round(m.pct)}%</span>`).join(" · ")}</div>` : ""}
        ${story.html}<div class="m">Researched on the web ${esc(story.at)}${story.sources ? " · sources: " + esc(story.sources) : ""} · price moves from real share-price data. Check before acting ·
        <a href="${requestLink(bsCode, story.company)}" target="_blank" rel="noopener">refresh it</a></div></div>`
      : bsCode ? `<div class="card"><h2>The story so far</h2><div class="m">Not written yet for this company${(() => { const M = window.DESK_BSIDX.meta || {}; const i = (M.next || []).findIndex((n) => sameCo(n, key)); return i >= 0 ? ` - it's number ${i + 1} in the queue` : ""; })()}.</div>
        <p><a class="btn" href="${requestLink(bsCode, call ? call.company : key)}" target="_blank" rel="noopener">Write it now</a></p>
        <div class="m">Opens a one-line request on GitHub - press "Submit" and the story appears here in about 10 minutes.</div></div>` : "";
    const myNotes = getNotes().filter((n2) => n2.company && sameCo(n2.company, key));
    const notesCard = `<div class="card"><h2>My notes <span class="m">${myNotes.length ? plural(myNotes.length, "note") : "only you see these"}</span></h2>
        ${myNotes.map((n2) => noteHtml(n2, false)).join("")}<button id="conote">✎ Add a note on ${esc(key)}</button></div>`;
    const sideCards = `${notesCard}${storyCard}${hasTk ? `<div class="card"><h2>Pivots, results, orders & broker calls</h2>${trackerList()}</div>` : ""}
      <div class="card"><h2>In the news <span class="m">${plural(items.length, "story")} · ${pz}▲ ${nz}▼</span></h2>
        ${items.length >= 4 ? `<div id="cod"></div>` : ""}
        ${groups.length ? `<ul class="list" id="conl">${groups.slice(0, 10).map(newsLine).join("")}</ul>${groups.length > 10 ? `<button id="conm">Show ${groups.length - 10} more</button>` : ""}` : `<div class="m">No news in recent briefs.</div>`}</div>`;
    body.innerHTML = call || decks.length
      ? `<div class="cogrid"><div>${concallCard}${deckCard}${tlCard}</div><div>${sideCards}</div></div>`
      : `<div class="grid g2" style="align-items:start"><div>${askCard}${tlCard}</div><div>${sideCards}</div></div>`;
    clampBlock($("#tlb"), 520, "timeline");
    if ($("#conote")) $("#conote").onclick = () => openNote({ company: key });
    bindNoteActions(body);
    if (items.length >= 4) divergingChart($("#cod"), perDay.filter((r) => r.total));
    if (story && story.pts) {
      const xs = story.pts.map((p) => p[0]), idxOf = (d) => Math.max(0, xs.findIndex((x) => x >= d));
      indexChart($("#bspx"), xs, [{ name: "Share price (Rs)", color: cssv("--s1"), values: story.pts.map((p) => p[1]) }], "Rs",
        (story.moves || []).map((m) => ({ i0: idxOf(m.from), i1: idxOf(m.to), color: cssv(m.pct >= 0 ? "--pos" : "--neg"), label: (m.pct > 0 ? "+" : "") + Math.round(m.pct) + "%" })), 200);
    }
    const more = $("#conm");
    if (more) more.onclick = () => { $("#conl").innerHTML = groups.map(newsLine).join(""); more.remove(); bindNews(); };
    const bindNews = () => body.querySelectorAll("[data-sid]").forEach((d) => { if (d.dataset.b) return; d.dataset.b = 1; d.addEventListener("click", async () => {
      currentBrief = await getBrief(d.dataset.storyDate); current = currentBrief.date; openStory(d.dataset.sid);
    }); });
    bindNews();
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
    const quarters = [...new Set(cc.calls.map((c) => c.quarter))].sort((a, b) => (a.slice(-2) + a[1] < b.slice(-2) + b[1] ? 1 : -1));
    const TONES = ["Positive", "Mixed", "Cautious", "Negative"], TC = { Positive: "--pos", Mixed: "--neu", Cautious: "--caution", Negative: "--neg" };
    const nDeck = (window.DESK_PRES || []).length;
    const st = { s: sector || "", q: "", f: "", t: "" };
    const bySec = {};
    cc.calls.forEach((c) => { const o = bySec[c.sector] = bySec[c.sector] || { n: 0 }; o.n++; const k = TONES.includes(c.tone) ? c.tone : "Mixed"; o[k] = (o[k] || 0) + 1; });
    const secs = Object.keys(bySec).sort((a, b) => bySec[b].n - bySec[a].n);
    const score = (o) => ((o.Positive || 0) * 3 + (o.Mixed || 0) * 2 + (o.Cautious || 0)) / o.n;
    view.innerHTML = `<h1>Concalls</h1><div class="sub">${plural(cc.calls.length, "summary")} · ${plural(cc.overviews.length, "sector overview")}${nDeck ? ` · <a href="#presentations">${plural(nDeck, "investor deck")} filed recently →</a>` : ""}</div>
      <div class="card"><h2>Management tone by sector <span class="m">tap a sector · bar = share of calls by tone</span></h2>
        ${legend(TONES.map((k) => [k, cssv(TC[k])]))}
        <div class="sgrid">${secs.map((k) => { const o = bySec[k]; return `<button class="stile" data-s="${esc(k)}"><span class="sn">${esc(k)}</span><span class="m">${o.n}</span>
          <span class="mb wide">${TONES.map((t) => o[t] ? `<i style="width:${(100 * o[t]) / o.n}%;background:var(${TC[t]})" title="${o[t]} ${t}"></i>` : "").join("")}</span></button>`; }).join("")}</div></div>
      <div class="filters"><select id="ks"><option value="">All sectors</option>${secs.slice().sort().map((x) => `<option>${esc(x)}</option>`).join("")}</select>
        <select id="kq"><option value="">All quarters</option>${quarters.map((q) => `<option>${esc(q)}</option>`).join("")}</select>
        <select id="kt"><option value="">Any tone</option>${TONES.map((t) => `<option>${t}</option>`).join("")}</select>
        <input type="search" id="kf" placeholder="Search company or any word (cotton, capex, tariff…)"><button id="cclr" class="clr" hidden>✕ Clear filters</button></div>
      <div id="kov"></div><div class="card" style="padding:4px 8px"><div id="kl"></div></div>`;
    let shown = 40, seq = 0;
    const draw = async () => {
      const my = ++seq;
      Object.assign(st, { s: $("#ks").value, q: $("#kq").value, t: $("#kt").value, f: $("#kf").value.toLowerCase() });
      $("#cclr").hidden = !(st.s || st.q || st.t || st.f);
      const TX = st.f ? await ccText() : {};
      if (my !== seq) return;
      view.querySelectorAll(".stile").forEach((b) => b.classList.toggle("on", b.dataset.s === st.s));
      const ov = st.s ? cc.overviews.filter((o) => o.sector === st.s && (!st.q || o.quarter === st.q)).sort((a, b) => (a.quarter < b.quarter ? 1 : -1))[0] : null;
      const qk = (q) => { const m = /Q(\d) FY(\d+)/.exec(q || ""); return m ? Number(m[2]) * 10 + Number(m[1]) : 0; };
      const pool = cc.calls.filter((c) => (!st.s || c.sector === st.s) && c.tone);
      const qs = [...new Set(pool.map((c) => c.quarter))].filter((q) => pool.filter((c) => c.quarter === q).length >= 3).sort((a, b) => qk(a) - qk(b));
      const trend = qs.length >= 2 ? `<div class="card"><h2>Management tone over time <span class="m">${esc(st.s || "all sectors")} · share of calls by quarter</span></h2>${legend([["Positive", cssv("--pos")], ["Cautious or negative", cssv("--neg")]])}<div id="ktr"></div></div>` : "";
      $("#kov").innerHTML = trend + (ov ? `<div class="card md"><h2>${esc(st.s)} - what managements are saying <span class="m">${esc(ov.quarter)} · ${ov.companies.length} companies</span></h2>${marketLine(st.s)}<div id="kovb">${await ovHtml(ov)}</div></div>` : "");
      if (qs.length >= 2) {
        const share = (q, f) => { const xs = pool.filter((c) => c.quarter === q); return (100 * xs.filter(f).length) / xs.length; };
        indexChart($("#ktr"), qs, [
          { name: "Positive", color: cssv("--pos"), values: qs.map((q) => share(q, (c) => c.tone === "Positive")) },
          { name: "Cautious or negative", color: cssv("--neg"), values: qs.map((q) => share(q, (c) => c.tone === "Cautious" || c.tone === "Negative")) },
        ], "%", null, 200);
      }
      if (my !== seq) return;
      const calls = cc.calls.filter((c) => (!st.s || c.sector === st.s) && (!st.q || c.quarter === st.q) && (!st.t || c.tone === st.t) &&
        (!st.f || c.company.toLowerCase().includes(st.f) || (TX[c.k] || "").toLowerCase().includes(st.f))).sort((a, b) => (a.date < b.date ? 1 : -1));
      $("#kl").innerHTML = calls.slice(0, shown).map((c) => `<div class="crow">
          <div class="ch"><a class="n" href="#companies/${encodeURIComponent(c.company)}">${esc(c.company)}</a><span class="m">${esc(c.quarter)}${st.s ? "" : " · " + esc(c.sector)} · ${esc(c.date.slice(5))}</span>
          <span class="r2">${deckFor(c) ? `<a class="badge" href="${esc(deckFor(c).pdf)}" target="_blank" rel="noopener" title="Investor deck filed with this call">deck</a>` : ""}${c.compared ? `<span class="badge" title="Includes what changed vs last quarter">vs last qtr</span>` : ""}
          ${c.checks.length ? `<span class="badge w" title="Figures not found word-for-word in the transcript">⚠ ${c.checks.length}</span>` : ""}
          ${c.tone ? `<span class="tone ${esc(c.tone)}">${esc(c.tone)}</span>` : ""}</span></div>
          <div class="cp">${esc(c.one || "")} <a href="#companies/${encodeURIComponent(c.company)}">full summary →</a></div></div>`).join("")
        + (calls.length > shown ? `<button id="kmore" style="margin:8px">Show ${Math.min(80, calls.length - shown)} more${calls.length - shown > 80 ? ` (${calls.length - shown} left)` : ""}</button>` : "")
        || empty("Nothing matches.");
      const mb = $("#kmore"); if (mb) mb.onclick = () => { shown += 80; draw(); };
    };
    $("#ks").value = st.s;
    view.querySelectorAll(".stile").forEach((b) => b.addEventListener("click", () => { $("#ks").value = $("#ks").value === b.dataset.s ? "" : b.dataset.s; shown = 40; draw(); }));
    ["ks", "kq", "kt"].forEach((id) => { $("#" + id).onchange = () => { shown = 40; draw(); }; });
    $("#kf").oninput = () => { shown = 40; draw(); };
    $("#cclr").onclick = () => { ["ks", "kq", "kt", "kf"].forEach((id) => { $("#" + id).value = ""; }); shown = 40; draw(); };
    draw();
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
      <div class="sub">${esc(b.label)} · ${fmt(t.stats.articles || 0)} articles from ${plural(t.stats.feeds || 0, "feed")} → ${plural(t.stats.stories || 0, "story")}</div>
      <div class="grid g2 tabg" style="align-items:start">
        ${t.html ? `<div class="card md">${t.one ? `<p><b>${t.one}</b></p>` : ""}<div id="tw">${t.html}</div></div>` : ""}
        <div class="card"><h2>Most-covered stories <span class="m">tap for all sources</span></h2><div id="tl"></div></div></div>`;
    storyFeed($("#tl"), t.stories, { ph: "Search " + t.name.toLowerCase() + " stories", page: 12 });
  }

  /** Week ahead: what can move Indian stocks in the next two weeks (shown on Today). */
  function renderWeekAhead(host) {
    const T = (window.DESK_TRACK || {}).trackers || {};
    const today = new Date().toISOString().slice(0, 10);
    const ahead = new Date(); ahead.setDate(ahead.getDate() + 14);
    const aheadS = ahead.toISOString().slice(0, 10);
    // agenda: India policy & data, global data, foreign companies with Indian links, big Indian companies
    const KIND = { "india-policy": ["India policy", "--s1"], "india-data": ["India data", "--s3"], global: ["Global", "--s2"],
      "global-co": ["Global company", "--s4"], company: ["Company", "--s5"] };
    const NIFTY = ["Reliance Industries", "HDFC Bank", "ICICI Bank", "Infosys", "Tata Consultancy Services", "Bharti Airtel", "ITC", "State Bank of India",
      "Larsen & Toubro", "Kotak Mahindra Bank", "Axis Bank", "Hindustan Unilever", "Bajaj Finance", "Bajaj Finserv", "Maruti Suzuki", "Mahindra & Mahindra",
      "Sun Pharmaceutical", "HCL Technologies", "Titan Company", "Asian Paints", "UltraTech Cement", "NTPC", "Power Grid Corporation", "Tata Motors",
      "Tata Steel", "JSW Steel", "Hindalco Industries", "Oil & Natural Gas", "ONGC", "Coal India", "Adani Ports", "Adani Enterprises", "Nestle India", "Wipro",
      "Tech Mahindra", "Cipla", "Dr. Reddy's Laboratories", "Dr Reddys Laboratories", "Grasim Industries", "Eicher Motors", "Hero MotoCorp", "Bajaj Auto",
      "Shriram Finance", "Trent", "Bharat Electronics", "SBI Life Insurance", "HDFC Life Insurance", "Apollo Hospitals", "Tata Consumer Products",
      "IndusInd Bank", "Jio Financial Services", "Eternal", "Zomato", "InterGlobe Aviation", "Max Healthcare", "Hindustan Aeronautics", "Bajaj Housing",
      "Vedanta", "Hindustan Zinc", "DLF", "Avenue Supermarts", "Varun Beverages", "Godrej Consumer", "Britannia Industries", "Pidilite", "Siemens", "ABB India",
      "Divi's Laboratories", "LTIMindtree", "Adani Green", "Adani Power", "Tata Power", "Bank of Baroda", "Punjab National Bank", "Canara Bank", "LIC", "Life Insurance Corporation"]
      .map((x) => norm(x));
    const big = (n) => isWatch(n) || NIFTY.some((x) => { const y = norm(n); return y === x || (y.startsWith(x) && /^(ltd|limited|corp|corporation|co|company|india)?$/.test(y.slice(x.length))); });
    const guessKind = (w) => /\b(rbi|sebi|gst|government|ministry|cabinet|parliament|budget|niti|irdai|trai|policy|auction|repo)\b/i.test(w) && !/\b(us|fed|ecb|usda|china|japan)\b/i.test(w) ? "india-policy"
      : /\b(fed|fomc|us |usda|ecb|boj|china|opec|nasdaq|wall street|treasury)\b/i.test(w + " ") ? "global"
      : /\b(cpi|wpi|inflation|gdp|iip|pmi|trade data|muhurat|holiday|expiry|trading session)\b/i.test(w) ? "india-data" : "company";
    const tok = (t) => new Set(t.toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter((w) => w.length > 2));
    const same = (a, b) => { const x = tok(a), y = tok(b); let n = 0; x.forEach((w) => { if (y.has(w)) n++; }); return n / Math.max(1, Math.min(x.size, y.size)) >= 0.6; };
    const items = [];
    (T.agenda || []).filter((e) => e.when >= today && e.when <= aheadS).forEach((e) => items.push(e));
    // news events: only things still ahead of the day they were reported (otherwise it's the news itself)
    (T.events || []).filter((e) => e.when >= today && e.when <= aheadS && e.what && e.when > (e.date || "")).forEach((e) => {
      if (e.kind === "company" && !big(e.what) && !(e.impact || "").length) return;
      if (!e.kind && /results?\b/i.test(e.what) && !big(e.what)) return;   // older facts: skip small-company results
      if (items.some((x) => x.when === e.when && same(x.what, e.what))) return;
      // the news confirms a usual-date release (e.g. "retail inflation data" = CPI): keep one line, now with a source
      const SYN = [/cpi|retail inflation|consumer price/i, /wpi|wholesale/i, /iip|industrial (output|production)/i, /trade (data|deficit)|exports/i, /gdp/i, /pmi/i, /auto sales/i];
      const g = SYN.find((r) => r.test(e.what));
      const u = g && /^india/.test(guessKind(e.what)) && items.find((x) => x.usual && x.when === e.when && g.test(x.what));
      if (u) { u.usual = false; u.link = e.link; return; }
      items.push(Object.assign({}, e, { kind: e.kind || guessKind(e.what) }));
    });
    const cal = (T.calendar || []).filter((e) => e.when >= today && e.when <= aheadS);
    const daysA = [...new Set(items.map((e) => e.when).concat(cal.map((e) => e.when)))].sort();
    const kf = store.get("wakind", "");
    host.innerHTML = `<div class="card"><h2>Week ahead <span class="m">next two weeks · what can move Indian stocks</span></h2>
        <div class="filters seg" id="wak">${[["", "All"], ["india", "India policy & data"], ["global", "Global"], ["co", "Companies"]].map(([k, l]) => `<button data-k="${k}" class="${k === kf ? "on" : ""}">${l}</button>`).join("")}</div>
        <div id="wal"></div></div>`;
    const drawAgenda = () => {
      const k = store.get("wakind", "");
      const keep = (e) => !k || (k === "india" ? /^india/.test(e.kind) : k === "global" ? e.kind === "global" : /co|company/.test(e.kind));
      const rows = daysA.map((d) => {
        const e1 = items.filter((e) => e.when === d && keep(e)).sort((a, b) => (a.time || "").localeCompare(b.time || ""));
        const c1 = !k || k === "co" ? cal.filter((e) => e.when === d) : [];
        const bigCos = c1.filter((c) => big(c.company)), rest = c1.length - bigCos.length;
        if (!e1.length && !bigCos.length) return "";
        const nice = new Date(d + "T00:00").toLocaleDateString("en-IN", { weekday: "short", day: "2-digit", month: "short" });
        return `<div class="wa"><div class="wd">${nice}</div><div>
          ${e1.map((e) => `<div class="ag"><span class="kc" style="background:var(${(KIND[e.kind] || KIND.company)[1]})">${(KIND[e.kind] || KIND.company)[0]}</span>
            <b>${esc(e.what)}</b>${e.time ? ` <span class="m">${esc(e.time)}</span>` : ""}${e.usual ? ` <span class="m" title="Usual release day - can shift by a day or two">(usual date)</span>` : ""}
            ${e.link ? ` <a class="m" href="${esc(e.link)}" target="_blank" rel="noopener">source</a>` : ""}
            ${e.impact ? `<div class="m">→ ${esc(e.impact)}</div>` : ""}</div>`).join("")}
          ${bigCos.length ? `<div class="ag"><span class="kc" style="background:var(--s5)">Results</span> <b>${bigCos.map((c) => `<a href="#companies/${encodeURIComponent(c.company)}">${esc(c.company)}</a>`).join(", ")}</b>${rest > 0 ? ` <span class="m">+ ${rest} smaller companies</span>` : ""}</div>` : ""}
        </div></div>`;
      }).join("");
      $("#wal").innerHTML = rows || `<div class="m">Nothing on the agenda for this filter yet.</div>`;
    };
    drawAgenda();
    $("#wak").onclick = (e) => { const b2 = e.target.closest("button"); if (!b2) return; store.set("wakind", b2.dataset.k);
      $("#wak").querySelectorAll("button").forEach((x) => x.classList.toggle("on", x === b2)); drawAgenda(); };
  }

  /** Week / month / quarter reviews - the long memory of the market story. */
  function renderReviews(host, W) {
    const sets = { week: (W.reviews || []).map((r) => ({ key: r.end, label: `${r.start} to ${r.end}`, one: r.one, html: r.html })),
      month: W.monthly || [], quarter: W.quarterly || [] };
    if (!sets.week.length && !sets.month.length) { host.innerHTML = ""; return; }
    let kind = store.get("revkind", "week"); if (!sets[kind].length) kind = "week";
    const draw = (i) => {
      const list = sets[kind], r = list[i] || list[0];
      host.innerHTML = `<div class="card md"><h2>In review</h2>
        <div class="filters seg" id="revk">${[["week", "Week"], ["month", "Month"], ["quarter", "Quarter"]].filter(([k]) => sets[k].length)
          .map(([k, l]) => `<button data-k="${k}" class="${k === kind ? "on" : ""}">${l} <span class="m">${sets[k].length}</span></button>`).join("")}
          ${list.length > 1 ? `<select id="revp">${list.map((x, j) => `<option value="${j}" ${j === i ? "selected" : ""}>${esc(x.label)}</option>`).join("")}</select>` : ""}</div>
        ${r ? `${r.one ? `<p><b>${esc(r.one)}</b></p>` : ""}${r.html}` : `<div class="m">None yet.</div>`}</div>`;
      $("#revk").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; kind = b.dataset.k; store.set("revkind", kind); draw(0); };
      if ($("#revp")) $("#revp").onchange = (e) => draw(Number(e.target.value));
    };
    draw(0);
  }

  /* ------------------------------------------------------------ notes (kept in this browser; export / import to move them) */
  const getNotes = () => store.get("notes", []);
  const putNotes = (list) => store.set("notes", list);
  let noteCtx = null, notePick = "";
  function pageContext() {
    const h = location.hash || "#today";
    const h1 = (view.querySelector("h1") || {}).textContent || "";
    let company = "";
    const m = /^#companies\/(.+)$/.exec(h);
    if (m) company = decodeURIComponent(m[1]);
    let label = h1, link = h;
    if (!pop.hidden) { const t = pop.querySelector("h2, .t, b"); if (t) label = "Story: " + t.textContent.trim().slice(0, 120); }
    return { label: label.trim() || h, link, company };
  }
  function openNote(prefill = {}) {
    noteCtx = Object.assign(pageContext(), prefill);
    $("#nctx").textContent = "From: " + noteCtx.label;
    const q = (prefill.quote != null ? prefill.quote : notePick).trim();
    $("#nquote").hidden = !q; $("#nquote").textContent = q;
    noteCtx.quote = q;
    $("#ntext").value = prefill.text || "";
    $("#nco").value = noteCtx.company || "";
    $("#notepanel").hidden = false;
    setTimeout(() => $("#ntext").focus(), 50);
  }
  function closeNote() { $("#notepanel").hidden = true; noteCtx = null; notePick = ""; }
  const grabSel = () => { const t = String(window.getSelection ? window.getSelection() : "").trim(); if (t) notePick = t.slice(0, 1500); };
  $("#notebtn").addEventListener("mousedown", grabSel);
  $("#notebtn").addEventListener("touchstart", grabSel, { passive: true });
  $("#notebtn").addEventListener("click", () => openNote());
  $("#ncancel").addEventListener("click", closeNote);
  $("#notepanel").addEventListener("click", (e) => { if (e.target.id === "notepanel") closeNote(); });
  $("#nsave").addEventListener("click", () => {
    const text = $("#ntext").value.trim();
    if (!text && !noteCtx.quote) { closeNote(); return; }
    const list = getNotes();
    if (noteCtx.id) {
      const n = list.find((x) => x.id === noteCtx.id);
      if (n) { n.text = text; n.company = $("#nco").value.trim(); n.edited = new Date().toISOString(); }
    } else {
      list.unshift({ id: Date.now().toString(36), at: new Date().toISOString(), text, quote: noteCtx.quote || "",
        label: noteCtx.label, link: noteCtx.link, company: $("#nco").value.trim() });
    }
    putNotes(list);
    closeNote();
    if (/^#(notes|companies\/)/.test(location.hash)) route();
  });
  const noteHtml = (n, showCo = true) => `<div class="note" data-id="${esc(n.id)}">
      <div class="m">${esc(new Date(n.at).toLocaleString("en-IN", { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }))}
        · <a href="${esc(n.link)}">${esc(n.label || n.link)}</a>${showCo && n.company && n.company !== n.label ? ` · <a href="#companies/${encodeURIComponent(n.company)}">${esc(n.company)}</a>` : ""}</div>
      ${n.quote ? `<blockquote>${esc(n.quote)}</blockquote>` : ""}${n.text ? `<div class="nt">${esc(n.text).replace(/\n/g, "<br>")}</div>` : ""}
      <div class="nact"><button data-edit="${esc(n.id)}">Edit</button> <button data-del="${esc(n.id)}">Delete</button></div></div>`;
  function bindNoteActions(root) {
    root.querySelectorAll("[data-edit]").forEach((b) => b.onclick = () => {
      const n = getNotes().find((x) => x.id === b.dataset.edit); if (!n) return;
      openNote({ id: n.id, text: n.text, quote: n.quote, company: n.company, label: n.label, link: n.link });
    });
    root.querySelectorAll("[data-del]").forEach((b) => b.onclick = () => {
      if (!confirm("Delete this note?")) return;
      putNotes(getNotes().filter((x) => x.id !== b.dataset.del)); route();
    });
  }
  function pageNotes() {
    const all = getNotes();
    const cos = [...new Set(all.map((n) => n.company).filter(Boolean))].sort();
    view.innerHTML = `<h1>Notes</h1><div class="sub">${plural(all.length, "note")} · saved in this browser - use Export / Import to move them between your tablet and laptop</div>
      <div class="filters"><input type="search" id="nq" placeholder="Search your notes">
        <select id="nc"><option value="">All companies</option>${cos.map((c) => `<option>${esc(c)}</option>`).join("")}</select>
        <button class="primary" id="nnew">✎ New note</button> <button id="nexp">Export</button> <button id="nmd">Copy as text</button>
        <label class="btnlike">Import<input type="file" id="nimp" accept=".json" hidden></label></div>
      <div class="card" id="nl"></div>`;
    const draw = () => {
      const q = $("#nq").value.toLowerCase(), c = $("#nc").value;
      const xs = all.filter((n) => (!c || n.company === c) && (!q || (n.text + " " + n.quote + " " + n.label + " " + n.company).toLowerCase().includes(q)));
      $("#nl").innerHTML = xs.map((n) => noteHtml(n)).join("") || `<div class="m">${all.length ? "Nothing matches." : "No notes yet. Tap ✎ Note (bottom right) on any page - select some text first to quote it."}</div>`;
      bindNoteActions($("#nl"));
    };
    $("#nq").oninput = draw; $("#nc").onchange = draw; draw();
    $("#nnew").onclick = () => openNote();
    $("#nexp").onclick = () => {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([JSON.stringify(getNotes(), null, 1)], { type: "application/json" }));
      a.download = "market-desk-notes-" + new Date().toISOString().slice(0, 10) + ".json"; a.click();
    };
    $("#nmd").onclick = async () => {
      const md = getNotes().map((n) => `## ${n.at.slice(0, 10)} · ${n.company || n.label}\n${n.quote ? "> " + n.quote.replace(/\n/g, "\n> ") + "\n\n" : ""}${n.text}`).join("\n\n");
      try { await navigator.clipboard.writeText(md); $("#nmd").textContent = "Copied ✓"; } catch (e) { alert("Couldn't copy - use Export instead."); }
    };
    $("#nimp").onchange = async (e) => {
      const f = e.target.files[0]; if (!f) return;
      try {
        const inc = JSON.parse(await f.text()), have = getNotes(), ids = new Set(have.map((n) => n.id));
        const merged = have.concat(inc.filter((n) => n && n.id && !ids.has(n.id))).sort((a, b) => (a.at < b.at ? 1 : -1));
        putNotes(merged); alert(`Imported ${merged.length - have.length} notes.`); route();
      } catch (err) { alert("That file isn't a Market Desk notes export."); }
    };
  }

  /* ------------------------------------------------------------ search & themes */
  async function getSearch() {
    if (!window.DESK_SEARCH) { try { await loadScript("data/search.js"); } catch (e) { window.DESK_SEARCH = { tl: [], themes: {} }; } }
    return window.DESK_SEARCH;
  }
  // a few words the market writes several ways
  const SYN = [["lfp", "lithium iron phosphate"], ["data centre", "data center", "datacenter"], ["ev", "electric vehicle"],
    ["capex", "capital expenditure"], ["semiconductor", "semicon", "chip"], ["green hydrogen", "electrolyser", "electrolyzer"],
    ["bess", "battery energy storage"], ["cdmo", "contract development"], ["glp-1", "glp1", "semaglutide", "obesity"],
    ["pli", "production linked incentive"], ["transformer", "transformers"], ["solar", "photovoltaic", "pv module"]];
  const expandQ = (q) => { const l = q.toLowerCase().trim(); const g = SYN.find((x) => x.includes(l)); return g ? g : [l]; };
  const THEME_KEYS = [["Battery materials & cells", /battery|lfp|cathode|anode|electrolyte|cell/i], ["EV & two-wheelers", /\bev\b|electric vehicle|two-wheeler/i],
    ["Solar manufacturing", /solar/i], ["Data centres & AI infrastructure", /data cent|ai infra/i], ["Semiconductors & electronics manufacturing", /semicon|electronics/i],
    ["Power T&D, transformers & cables", /t&d|transformer|cable|transmission/i], ["Defence", /defen[cs]e/i], ["Railways", /rail/i], ["Nuclear", /nuclear/i],
    ["Green hydrogen & ammonia", /hydrogen|ammonia/i], ["Specialty chemicals & fluorochemicals", /chemical|fluoro/i], ["Pharma CDMO, peptides & biologics", /cdmo|peptide|biolog/i],
    ["GLP-1 & obesity drugs", /glp|obesity/i], ["M&A & consolidation", /m&a|acqui|merger|consolidat/i], ["Debt reduction & fund-raising", /debt|fund/i],
    ["Legal & regulatory", /legal|regulat/i], ["Capacity expansion (other)", /capacity/i]];
  const themeOf = (t) => { if (!t) return ""; const m = /^other:\s*(.+)$/i.exec(t); if (m) return m[1].trim(); const k = THEME_KEYS.find(([, r]) => r.test(t)); return k ? k[0] : t; };
  const highlight = (txt, terms) => { let h = esc(txt); terms.forEach((w) => { if (w.length > 1) h = h.replace(new RegExp("(" + w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")", "ig"), "<mark>$1</mark>"); }); return h; };
  const snippet = (text, term, n = 160) => { const i = text.toLowerCase().indexOf(term); if (i < 0) return text.slice(0, n * 2); const a = Math.max(0, i - n); return (a ? "…" : "") + text.slice(a, i + term.length + n) + "…"; };

  async function pageSearch(q0) {
    q0 = q0 || store.get("lastq", "");
    view.innerHTML = `<h1>Search</h1><div class="sub">Everything on file: concall summaries, investor decks, pivots, results, orders, broker calls, company timelines and recent news</div>
      <div class="filters"><input type="search" id="sq" placeholder="e.g. LFP, data centre, transformer capacity, GLP-1, Bloom Energy" value="${esc(q0)}" style="flex:1"></div>
      <div id="sres"></div>`;
    const run = async () => {
      const q = $("#sq").value.trim(); store.set("lastq", q);
      if (q.length < 2) { $("#sres").innerHTML = `<div class="m">Type a word or phrase - a technology, product, customer, place or company.</div>`; return; }
      $("#sres").innerHTML = `<div class="m">Searching…</div>`;
      const terms = expandQ(q), hit = (t) => { const l = (t || "").toLowerCase(); return terms.find((w) => l.includes(w)); };
      const [S, cc, TX] = await Promise.all([getSearch(), getConcalls(), ccText()]);
      if (!window.DESK_CONEWS) { try { await loadScript("data/conews.js"); } catch (e) { window.DESK_CONEWS = {}; } }
      const P = window.DESK_PRES || (await getPres());
      const byCo = {};
      const add = (co, h) => { const k = Object.keys(byCo).find((x) => sameCo(x, co)) || co; (byCo[k] = byCo[k] || []).push(h); };
      // concall summaries (latest per company first)
      cc.calls.forEach((c) => { const t = TX[c.k] || ""; const w = hit(t) || hit(c.company); if (w) add(c.company, { k: "Concall " + c.quarter, d: c.date, s: snippet(t, w), l: "#companies/" + encodeURIComponent(c.company), w }); });
      // deck summaries
      P.forEach((d) => { const t = ((d.one || "") + " " + (d.html || "").replace(/<[^>]+>/g, " ")).replace(/&amp;/g, "&").replace(/\s+/g, " "); const w = hit(t); if (w) add(d.company, { k: "Deck", d: d.when.slice(0, 10), s: snippet(t, w), l: d.pdf, w }); });
      // timeline: pivots, results, orders, broker calls, stories - kept for good
      S.tl.forEach(([co, k, d, t, l]) => { if (k === "concall" || k === "deck") return; const w = hit(t); if (w) add(co, { k: { pivot: "Pivot", result: "Results", order: "Order", broker: "Broker", story: "Price story" }[k] || k, d, s: t, l, w }); });
      // recent news headlines
      Object.entries(window.DESK_CONEWS).forEach(([co, list]) => list.forEach((m) => { const w = hit(m.t); if (w) add(co, { k: "News", d: m.d, s: m.t, l: "", w }); }));
      const cos = Object.entries(byCo).map(([co, hs]) => {
        const seen = new Set(); hs = hs.filter((h) => { const key = h.k + h.s.slice(0, 60); if (seen.has(key)) return false; seen.add(key); return true; });
        return { co, hs: hs.sort((a, b) => (a.d < b.d ? 1 : -1)), kinds: new Set(hs.map((h) => h.k.split(" ")[0])).size, last: hs.reduce((m, h) => (h.d > m ? h.d : m), "") };
      }).sort((a, b) => b.kinds - a.kinds || (a.last < b.last ? 1 : -1));
      const th = Object.keys(S.themes || {}).filter((t) => terms.some((w) => t.toLowerCase().includes(w) || themeOf(t).toLowerCase().includes(w)));
      $("#sres").innerHTML = `<div class="sub">${plural(cos.length, "company")} mention <b>${esc(terms.join(" / "))}</b>${th.length ? ` · theme: ${th.map((t) => `<a href="#trackers/themes" data-theme="${esc(themeOf(t))}">${esc(themeOf(t))}</a>`).join(", ")}` : ""}</div>
        ${cos.length > 1 ? `<div class="card"><h2>Who's in it <span class="m">tap a name to jump</span></h2><div class="chips">${cos.slice(0, 60).map((c, i) => `<a class="chip link" href="#" data-jump="${i}">${esc(c.co)} <span class="m">${c.hs.length}</span></a>`).join("")}</div></div>` : ""}
        ${cos.slice(0, 80).map((c, i) => `<div class="card" id="sr${i}"><h2><a href="#companies/${encodeURIComponent(c.co)}">${esc(c.co)}</a> <span class="m">${plural(c.hs.length, "mention")}</span></h2>
          ${c.hs.slice(0, 8).map((h) => `<div class="sh"><span class="kc" style="background:var(${h.k === "Pivot" ? "--s5" : h.k.startsWith("Concall") ? "--s1" : h.k === "Deck" ? "--s3" : "--neu"})">${esc(h.k)}</span>
            <span class="m">${esc(h.d)}</span> ${highlight(h.s, terms)} ${h.l ? `<a class="m" href="${esc(h.l)}" ${h.l.startsWith("#") ? "" : 'target="_blank" rel="noopener"'}>open</a>` : ""}</div>`).join("")}
          ${c.hs.length > 8 ? `<div class="m">+ ${c.hs.length - 8} more on the <a href="#companies/${encodeURIComponent(c.co)}">company page</a></div>` : ""}</div>`).join("") || `<div class="card m">Nothing on file mentions that yet.</div>`}`;
      $("#sres").querySelectorAll("[data-jump]").forEach((a) => a.onclick = (e) => { e.preventDefault(); $("#sr" + a.dataset.jump).scrollIntoView({ behavior: "smooth" }); });
      $("#sres").querySelectorAll("[data-theme]").forEach((a) => a.onclick = () => store.set("pivtheme", a.dataset.theme));
    };
    let tmr; $("#sq").oninput = () => { clearTimeout(tmr); tmr = setTimeout(run, 350); };
    $("#sq").focus(); run();
  }

  async function renderThemes(body) {
    const S = await getSearch();
    const groups = {};
    Object.entries(S.themes || {}).forEach(([t, list]) => { const k = themeOf(t); (groups[k] = groups[k] || []).push(...list); });
    const rows = Object.entries(groups).map(([k, list]) => ({ k, list: list.sort((a, b) => (a.d < b.d ? 1 : -1)), cos: [...new Set(list.map((x) => x.c))] }))
      .sort((a, b) => b.cos.length - a.cos.length);
    if (!rows.length) { body.innerHTML = empty("No themes yet - they build up as pivots are recorded."); return; }
    let sel = store.get("pivtheme", rows[0].k); if (!groups[sel]) sel = rows[0].k;
    const draw = () => {
      const r = rows.find((x) => x.k === sel);
      const byCo = {}; r.list.forEach((x) => { (byCo[x.c] = byCo[x.c] || []).push(x); });
      body.innerHTML = `<div class="card"><h2>Themes <span class="m">where companies are putting money - tap a theme · kept for good</span></h2>
          <div class="sgrid">${rows.map((x) => `<button class="stile ${x.k === sel ? "on" : ""}" data-t="${esc(x.k)}"><span class="sn">${esc(x.k)}</span><span class="m">${x.cos.length}</span></button>`).join("")}</div></div>
        <div class="card"><h2>${esc(sel)} <span class="m">${plural(r.cos.length, "company")} · newest first · <a href="#search" id="thsearch">search all mentions →</a></span></h2>
          ${Object.entries(byCo).map(([co, xs]) => `<div class="thc"><a href="#companies/${encodeURIComponent(co)}"><b>${esc(co)}</b></a>
            ${xs.map((x) => `<div class="m">${esc(x.d)} · ${esc(x.t.replace(/^\w[\w&]*:\s*/, ""))}${x.l ? ` <a href="${esc(x.l)}" target="_blank" rel="noopener">source</a>` : ""}</div>`).join("")}</div>`).join("")}</div>`;
      body.querySelectorAll("[data-t]").forEach((b) => b.onclick = () => { sel = b.dataset.t; store.set("pivtheme", sel); draw(); });
      $("#thsearch").onclick = () => store.set("lastq", sel.split(/[ ,(&]/)[0]);
    };
    draw();
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

    view.innerHTML = `<h1>Markets</h1>
      <div class="sub">Indices, commodities, the rupee and yields${D.markets && D.markets.updated ? " · prices as of " + esc(D.markets.updated.replace("T", " ")) : ""} · tap any tile to add it to the comparison</div>
      <div class="filters seg" id="per">${Object.keys(PER).map((k) => `<button class="${k === per ? "on" : ""}" data-p="${k}">${k}</button>`).join("")}</div>
      ${M.length ? `<div class="card"><h2>Compare <span class="m">rebased to 100 at the start of the period</span></h2><div id="mleg"></div><div id="mc"></div></div>
      <div class="card"><h2>Indian sector indices <span class="m">change over ${per} · tap to see that sector's peers</span></h2><div id="ms"></div></div>
      ${groups.filter((g) => g !== "India indices").map((g) => `<div class="card"><h2>${esc(g)}</h2><div class="tiles mk" data-g="${esc(g)}"></div></div>`).join("")}
      <div class="card"><h2>India indices</h2><div class="tiles mk" data-g="India indices"></div></div>` : `<div class="card m">Prices haven't been collected yet - they arrive with the next update.</div>`}
      <div id="revw"></div>`;

    $("#per").onclick = (e) => { const b = e.target.closest("button"); if (b) { store.set("mkper", b.dataset.p); route(); } };
    renderReviews($("#revw"), D.weekly || {});
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
    which = ["pivots", "themes", "results", "orders", "calls"].includes(which) ? which : "pivots";
    const names = { pivots: "Pivots", themes: "Themes", results: "Results", orders: "Order wins", calls: "Broker calls" };
    const NOISE = /\b(drhp|ipo|public issue|sebi nod|listing on|lists on|files? (for|draft))\b/i;
    const rows0 = (T[which === "themes" ? "pivots" : which] || []).filter((r) => !/pivots|themes/.test(which) || !NOISE.test(r.what));
    const secs = [...new Set(rows0.map((r) => r.sector || "Other"))].sort();
    const st = store.get("trk-" + which, { q: "", sec: "", w: false, days: 30 });
    st.kind = "";
    view.innerHTML = `<h1>Trackers</h1>
      <div class="sub">Pulled from the news by AI and kept for four months${T.updated ? " · updated " + esc(T.updated.replace("T", " ")) : ""} · check figures in the linked story before acting</div>
      <div class="cotabs">${Object.keys(names).map((k) => `<button data-go="#trackers/${k}" class="${k === which ? "on" : ""}">${names[k]} ${k === "themes" ? "" : `<span class="m">${(T[k] || []).length}</span>`}</button>`).join("")}</div>
      <div class="filters"><input type="search" id="kq" placeholder="Search company" value="${esc(st.q)}">
        <select id="ks"><option value="">All sectors</option>${secs.map((x) => `<option ${x === st.sec ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>
        <select id="kd">${[7, 30, 90, 120].map((d) => `<option value="${d}" ${d === st.days ? "selected" : ""}>Last ${d} days</option>`).join("")}</select>
        <label class="m"><input type="checkbox" id="kw" ${st.w ? "checked" : ""}> Watchlist only</label>
        <button id="kclr" class="clr" hidden>✕ Clear filters</button></div>
      <div id="kbody"></div>`;
    const draw = () => {
      redraws.length = 0;
      Object.assign(st, { q: $("#kq").value, sec: $("#ks").value, w: $("#kw").checked, days: Number($("#kd").value) });
      store.set("trk-" + which, st);
      $("#kclr").hidden = !(st.q || st.sec || st.w || st.kind);
      const cut = new Date(); cut.setDate(cut.getDate() - st.days); const cutS = cut.toISOString().slice(0, 10);
      const allRows = rows0.filter((r) => r.date >= cutS && (!st.q || r.company.toLowerCase().includes(st.q.toLowerCase()))
        && (!st.sec || (r.sector || "Other") === st.sec) && (!st.w || isWatch(r.company)));
      const rows = allRows.filter((r) => !st.kind || (PIVOT_LBL[r.type] || "Other") === st.kind);
      const body = $("#kbody");
      const open = (c) => () => go("#companies/" + encodeURIComponent(c));
      const src = (r) => `<a class="m" href="${esc(r.link)}" target="_blank" rel="noopener" title="${esc(r.title)}">source</a>`;
      if (!rows.length) { body.innerHTML = empty("Nothing here yet for these filters."); return; }
      const full = rows; let lim = st.lim || 25;
      if (which === "themes") { $(".filters").style.display = "none"; renderThemes(body); return; }
      if (which === "pivots") {
        const byType = {}, bySec = {};
        allRows.forEach((r) => { const t = PIVOT_LBL[r.type] || "Other"; byType[t] = (byType[t] || 0) + 1; });
        rows.forEach((r) => { const k = r.sector || "Other"; bySec[k] = (bySec[k] || 0) + 1; });
        body.innerHTML = `<div class="grid g2" style="align-items:start"><div class="card"><h2>Pivots by kind <span class="m">tap to filter</span></h2><div id="kp1"></div></div>
            <div class="card"><h2>Pivots by sector <span class="m">tap to filter</span></h2><div id="kp2"></div></div></div>
          <div class="card"><h2>${plural(rows.length, "pivot")} ${st.kind || st.sec ? `<span class="chip link" id="kfil">${esc([st.kind, st.sec].filter(Boolean).join(" · "))} ✕</span>` : `<span class="m">strategy shifts, capacity, big orders, legal wins, approvals, M&A, funding, ratings</span>`}</h2>
          <div class="pvg">${rows.slice(0, lim).map((r) => pivotLine(r)).join("")}</div>${full.length > lim ? `<button class="kmore">Show all ${full.length}</button>` : ""}</div>`;
        barChart($("#kp1"), Object.entries(byType).sort((a, b) => b[1] - a[1]).map(([k, v]) => ({ label: k, value: v,
          onclick: () => { st.kind = st.kind === k ? "" : k; draw(); } })), "pivot");
        if ($("#kfil")) $("#kfil").onclick = () => { st.kind = ""; $("#ks").value = ""; draw(); };
        barChart($("#kp2"), Object.entries(bySec).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([k, v]) => ({ label: k, value: v, onclick: () => { $("#ks").value = k; draw(); } })), "pivot");
      } else if (which === "results") {
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
            ${rows.slice(0, lim).map((r) => `<tr><td>${isWatch(r.company) ? "★ " : ""}<a href="#companies/${encodeURIComponent(r.company)}">${esc(r.company)}</a><div class="m">${esc(r.sector || "")}</div></td>
              <td>${esc(r.quarter)}</td><td>${r.revenue == null ? "–" : fmtM(r.revenue)}</td><td class="${pctCls(r.rev_yoy)}">${pct(r.rev_yoy)}</td>
              <td>${r.profit == null ? "–" : fmtM(r.profit)}</td><td class="${pctCls(r.pat_yoy)}">${pct(r.pat_yoy)}</td>
              <td>${r.read ? `<span class="rd ${esc(r.read.replace(/\W/g, ""))}">${esc(r.read)}</span>` : ""}</td><td>${esc(r.date.slice(5))} ${src(r)}</td></tr>`).join("")}</table>${full.length > lim ? `<button class="kmore">Show all ${full.length}</button>` : ""}</div></div>`;
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
          ${rows.slice(0, lim).map((r) => `<tr><td>${isWatch(r.company) ? "★ " : ""}<a href="#companies/${encodeURIComponent(r.company)}">${esc(r.company)}</a><div class="m">${esc(r.sector || "")}</div></td>
            <td>${r.value == null ? "–" : fmtM(r.value)}</td><td>${esc(r.client)}</td><td>${esc(r.what)}</td><td>${esc(r.date.slice(5))} ${src(r)}</td></tr>`).join("")}</table>${full.length > lim ? `<button class="kmore">Show all ${full.length}</button>` : ""}</div></div>`;
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
          ${rows.slice(0, lim).map((r) => `<tr><td>${isWatch(r.company) ? "★ " : ""}<a href="#companies/${encodeURIComponent(r.company)}">${esc(r.company)}</a><div class="m">${esc(r.sector || "")}</div></td>
            <td>${esc(r.broker)}</td><td class="${negA(r) ? "dn" : posA(r) ? "up" : ""}">${esc(r.rating)}</td><td>${r.target == null ? "–" : fmt(Math.round(r.target))}</td>
            <td>${esc(r.action)}</td><td>${esc(r.date.slice(5))} ${src(r)}</td></tr>`).join("")}</table>${full.length > lim ? `<button class="kmore">Show all ${full.length}</button>` : ""}</div></div>`;
        divergingChart($("#kc1"), Object.entries(bySec).sort((a, b) => (b[1].pos + b[1].neg) - (a[1].pos + a[1].neg)).slice(0, 15).map(([k, o]) => ({
          label: k, pos: o.pos, neg: o.neg, neu: o.neu, total: o.pos + o.neg + o.neu,
          tip: `<b>${esc(k)}</b><br>${o.pos} bullish · ${o.neg} bearish · ${o.neu} neutral<br><span class="m">Tap to filter</span>`,
          onclick: () => { $("#ks").value = k; draw(); } })));
        barChart($("#kc2"), Object.entries(cnt).sort((a, b) => b[1] - a[1]).slice(0, 12).map(([k, v]) => ({ label: k, value: v,
          note: esc(rows.filter((r) => r.company === k).map((r) => r.broker + ": " + r.rating).slice(0, 5).join("<br>")), onclick: open(k) })), "call");
      }
    };
    ["kq", "ks", "kw", "kd"].forEach((id) => { $("#" + id).addEventListener(id === "kq" ? "input" : "change", () => { st.lim = 25; draw(); }); });
    $("#kclr").onclick = () => { $("#kq").value = ""; $("#ks").value = ""; $("#kw").checked = false; st.kind = ""; st.lim = 25; draw(); };
    $("#kbody").addEventListener("click", (e) => { if (e.target.closest(".kmore")) { st.lim = 100000; draw(); } });
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
        <label class="m"><input type="checkbox" id="pw"> Watchlist only</label><button id="pclr" class="clr" hidden>✕ Clear filters</button></div>
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
      $("#pclr").hidden = !(q || sec || wo);
      const rows = all.filter((d) => (!q || (d.company + " " + d.title).toLowerCase().includes(q))
        && (!sec || (d.sector || "Unsorted") === sec) && (!wo || isW(d)))
        .sort((a, b) => (isW(b) - isW(a)) || (a.when < b.when ? 1 : -1));
      $("#pl").innerHTML = rows.slice(0, shownP).map((d) => `<li>
        <div class="t">${isW(d) ? "★ " : ""}<a href="#companies/${encodeURIComponent(d.company)}">${esc(d.company)}</a> ·
          <a href="${esc(d.pdf)}" target="_blank" rel="noopener">open deck (PDF)</a>${hasCall(d) ? ` · <a href="#companies/${encodeURIComponent(d.company)}">concall summary</a>` : ""}</div>
        <div class="src">${esc(d.sector || "Unsorted")} · ${when(d.when)}${d.title ? " · " + esc(d.title.slice(0, 140)) : ""}</div>
        ${d.one ? `<div class="cp" style="font-size:13.5px;margin-top:2px">${esc(d.one)}</div>` : ""}</li>`).join("")
        + (rows.length > shownP ? `<li><button id="pmore">Show ${Math.min(100, rows.length - shownP)} more</button></li>` : "")
        || `<li class="m">Nothing matches.</li>`;
      const pm = $("#pmore"); if (pm) pm.onclick = () => { shownP += 100; draw(); };
    };
    let shownP = 50;
    $("#pclr").onclick = () => { $("#pq").value = ""; $("#ps").value = ""; $("#pw").checked = false; shownP = 50; draw(); };
    $("#pq").oninput = () => { shownP = 50; draw(); }; $("#ps").onchange = () => { shownP = 50; draw(); }; $("#pw").onchange = () => { shownP = 50; draw(); }; draw();
  }

  async function pageArchive() {
    if (!IDX.briefs.length) { view.innerHTML = empty("No briefs yet."); return; }
    if (!window.DESK_NEWSARCH) { try { await loadScript("data/newsarchive.js"); } catch (e) { window.DESK_NEWSARCH = []; } }
    const have = new Set(IDX.briefs.map((b) => b.date));
    const older = window.DESK_NEWSARCH.filter((a) => !have.has(a.date)).reverse();
    view.innerHTML = `<h1>Archive</h1><div class="sub">Full briefs for about three months; after that each day's big picture and top headlines are kept for good</div>
      <div class="card archive">${IDX.briefs.slice().reverse().map((b) => {
        const top = Object.entries(b.cats).sort((x, y) => y[1] - x[1]).slice(0, 3).map((x) => x[0]).join(", ");
        return `<a href="#today/${b.date}"><span><b>${esc(b.label)}</b><br><span class="m">${esc(top)}</span></span>
          <span class="m" style="text-align:right">${plural(b.stats.relevant, "story")}<br>${fmt(b.stats.articles)} articles</span></a>`;
      }).join("")}</div>
      ${older.length ? `<h2 style="margin:18px 0 8px">Older briefs</h2><div class="card">${older.map((a) => `<details class="sum"><summary><span class="n">${esc(a.label)}</span>
        <span class="m">${esc((a.top || [])[0] || "")}</span></summary><div class="b md">${a.big}
        ${(a.top || []).length ? `<h3>Top headlines</h3><ul>${a.top.map((t) => `<li>${esc(t)}</li>`).join("")}</ul>` : ""}</div></details>`).join("")}</div>` : ""}`;
  }

  function pageSettings() {
    view.innerHTML = `<h1>Settings</h1><div class="sub">Saved in this browser only - your watchlist is never published.</div>
      <div class="card"><h2>Watchlist</h2><p class="help">Companies to pull to the top of every brief. Separate with commas; part of a name is enough.</p>
        <input type="text" id="wl" style="width:100%" placeholder="e.g. Trident, Apollo Hospitals, KPR Mill" value="${esc(watchlist().join(", "))}">
        <div style="margin-top:10px"><button class="primary" id="wls">Save</button> <span class="m" id="wlm"></span></div></div>
      <div class="card"><h2>Appearance</h2><select id="th"><option value="auto">Match my device</option><option value="light">Light</option><option value="dark">Dark</option></select></div>
      <div class="card"><h2>Today page: show in full</h2><p class="help">Ticked sections always open in full; unticked ones show the first part with "Show all". Tapping "Show all" or "Show less" on the page changes this too.</p>
        ${[["bigpicture", "The big picture"], ["pivots", "Pivots of the week"], ["weekahead", "Week ahead"], ["explained", "Top stories, explained"], ["sectors", "Sector by sector"]]
          .map(([k, l]) => `<label style="display:block;margin:6px 0"><input type="checkbox" data-open="${k}" ${store.get("open-" + k, false) ? "checked" : ""}> ${l}</label>`).join("")}</div>
      <div class="card"><h2>Swiping between tabs</h2><p class="help">On a tablet or phone, swipe sideways anywhere on the page to move to the next or previous tab.</p>
        <select id="swd"><option value="right-next">Swipe right → next tab, swipe left → previous</option><option value="left-next">Swipe left → next tab, swipe right → previous</option></select></div>
      <div class="card help"><h2>About</h2>
        <p>The site is rebuilt automatically every morning: news from your RSS feeds (last 24 hours), and summaries of new concall transcripts filed on BSE.</p>
        <p>Last update: <b>${esc((IDX.updated || "").replace("T", " "))}</b> · ${plural(IDX.briefs.length, "brief")} · ${plural(IDX.concalls || 0, "concall summary")}.</p>
        <p>On a tablet or phone, use your browser's menu → <b>Add to Home screen</b> to open it like an app.</p>
        <p>Summaries are written by AI from headlines and transcripts. Check important figures against the linked sources.</p></div>`;
    $("#wls").onclick = () => {
      const v = $("#wl").value.split(",").map((x) => x.trim()).filter(Boolean);
      store.set("watchlist", v); $("#wlm").textContent = "Saved.";
    };
    view.querySelectorAll("[data-open]").forEach((c) => { c.onchange = () => store.set("open-" + c.dataset.open, c.checked); });
    $("#swd").value = store.get("swipe", "right-next");
    $("#swd").onchange = (e) => store.set("swipe", e.target.value);
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
    const on = document.querySelector("#tabs a.on");
    if (on) on.scrollIntoView({ block: "nearest", inline: "center" });
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
      else if (tab === "archive") await pageArchive();
      else if (tab === "notes") pageNotes();
      else if (tab === "search") await pageSearch(arg ? decodeURIComponent(arg) : "");
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

  /* ------------------------------------------------------------ swipe between tabs (tablet / phone) */
  const navTabs = () => [...document.querySelectorAll("#tabs a")].filter((a) => a.dataset.tab !== "settings");
  const scrollsSideways = (el) => {
    for (let n = el; n && n !== document.body; n = n.parentElement) {
      if (n.scrollWidth > n.clientWidth + 4) {
        const ox = getComputedStyle(n).overflowX;
        if (ox === "auto" || ox === "scroll") return true;
      }
    }
    return false;
  };
  let sw = null;
  addEventListener("touchstart", (e) => {
    if (e.touches.length !== 1 || !pop.hidden) { sw = null; return; }
    const t = e.target;
    if (t.closest("input, select, textarea, svg, #tabs") || scrollsSideways(t)) { sw = null; return; }
    sw = { x: e.touches[0].clientX, y: e.touches[0].clientY, at: Date.now() };
  }, { passive: true });
  addEventListener("touchend", (e) => {
    if (!sw) return;
    const dx = e.changedTouches[0].clientX - sw.x, dy = e.changedTouches[0].clientY - sw.y, ms = Date.now() - sw.at;
    sw = null;
    if (Math.abs(dx) < 80 || Math.abs(dy) > Math.abs(dx) * 0.6 || ms > 800) return;
    const tabs = navTabs(), i = tabs.findIndex((a) => a.classList.contains("on"));
    if (i < 0) return;
    // default: finger moving right -> next tab (can be flipped in Settings)
    const forward = store.get("swipe", "right-next") === "right-next" ? dx > 0 : dx < 0;
    const j = i + (forward ? 1 : -1);
    if (j < 0 || j >= tabs.length) return;
    view.classList.remove("slide-l", "slide-r"); void view.offsetWidth;
    view.classList.add(forward ? "slide-l" : "slide-r");
    location.hash = tabs[j].getAttribute("href");
  }, { passive: true });

  route();
})();
