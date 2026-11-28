#!/usr/bin/env python3
"""
Builds the website in public/ from:
  data/news/*.json   - daily news briefs (news.py)
  data/library.json  - concall summaries (concalls.py)
The site is plain HTML/JS: it works on GitHub Pages and also opened straight from the folder.
Data is written as small .js files (not .json) so it also loads from file:// on a laptop or tablet.
"""
import datetime as dt
import json
import re
import shutil
import webbrowser

import concalls as C

PUBLIC = C.BASE / "public"
WEB = C.BASE / "web"
BRIEFS = C.DATA / "news"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def _js(var, key, obj):
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    if key is None:
        return f"window.{var}={data};\n"
    return f"window.{var}=window.{var}||{{}};window.{var}[{json.dumps(key)}]={data};\n"


def concall_data():
    lib = C.load_lib()
    calls = []
    for c in C.latest_per_company([c for c in lib["calls"].values() if c.get("summary")]):
        f = C.here(c["summary"])
        if not f.exists():
            continue
        t = f.read_text(encoding="utf-8")
        t = re.sub(r"^# .*\n(\*Filed.*\*\n)?", "", t)
        t = re.sub(r"\*\*Quarter:\*\*.*\n", "", t)
        t = t.split("\n---\n")[0]
        bad = c.get("unverified")
        if bad is None:
            src = C.TXT_DIR / f"{c['id']}.txt"
            bad = C.unverified_numbers(t, src.read_text(encoding="utf-8")) if src.exists() else []
        html = C.md(t)
        if bad:
            pat = re.compile(r"(?<![\w.,])(" + "|".join(re.escape(b) for b in bad) + r")(?![\w])")
            html = re.sub(r">([^<]+)<", lambda m: ">" + pat.sub(
                r'<mark title="Not found word-for-word in the transcript - check it">\1</mark>', m.group(1)) + "<",
                html)
        prev = C.find_prev(lib, c)
        calls.append({"metrics": c.get("metrics") or {}, "unchecked": c.get("metrics_unchecked") or [],
                      "prev_tone": (prev or {}).get("tone", "") if prev and prev.get("summary") else "",
                      "company": c["company"], "code": c["code"], "sector": C.sector_of(lib, c), "id": c["id"],
                      "ind": (lib.get("industries") or {}).get(c["code"], ""),
                      "quarter": c["quarter"], "date": c["date"], "tone": c.get("tone", ""),
                      "compared": bool(c.get("compared")), "checks": bad, "bse": [f for f in (c.get("bse_flags") or []) if f.get("slip")],  # BSE's table is standalone: show unit slips only
                      "ex": c.get("expect") or {}, "dl": c.get("delivery") or {}, "ft": c.get("ft") or {},
                      "draft": "lite" in (c.get("model") or "lite").lower(),
                      "pdf": c.get("pdf_url", C.BSE_PDF[0] + c["pdf"]), "html": html})
    overviews = []
    import direction
    for o in lib["overviews"].values():
        f = C.here(o["file"])
        if f.exists():
            try:  # shifts named by the overview, and how many companies talked about each, quarter by quarter (code)
                shifts = direction.momentum(lib, o["sector"], o.get("industry") or None, o.get("shifts") or [])
            except Exception:
                shifts = []
            overviews.append({"sector": o["sector"], "ind": o.get("industry", ""), "quarter": o["quarter"], "companies": o["companies"],
                              "draft": "lite" in (o.get("model") or "lite"), "shifts": shifts,
                              "html": C.md(f.read_text(encoding="utf-8"))})
    return {"calls": calls, "overviews": overviews}


_R = None


def canon(items, name="company", code="code", sec="sector"):
    """One sector per company everywhere: an item naming a listed company gets that company's code and its own
    sector (concall library first, then the BSE directory) - never the sector an AI guessed for the item."""
    global _R
    if _R is None:
        import names
        _R = names.Resolver()
    fixed = 0
    for it in items or []:
        if not isinstance(it, dict) or not it.get(name):
            continue
        c = str(it.get(code) or "") or _R.resolve(it[name])[1]
        if not c:
            continue
        it[code] = c
        s = _R.sectors.get(c)
        if s and sec in it and it[sec] != s:
            it[sec] = s
            fixed += 1
        elif s and sec not in it:
            it[sec] = s
    return fixed


def why_file(tl, stories):
    """Per company: sector, the story in one line, the latest concall (tone, management rating, vs market, said vs did),
    the last dated events (turning points, orders, results, broker calls, govt decisions) and today's top-10 rank."""
    lib = C.load_lib()
    today = dt.date.today()
    cut = (today - dt.timedelta(days=120)).isoformat()
    latest = {c["code"]: c for c in C.latest_call_each(list(lib["calls"].values())) if c.get("code")}
    inds = lib.get("industries") or {}
    top = {}
    try:
        import highlights as HL
        H = HL.load()
        day = max(H["days"]) if H["days"] else None
        for rank, it in enumerate(H["days"].get(day, []) if day else [], 1):
            keys = [it["key"]] if not it["key"].startswith("IND|") else []
            for k in keys:
                top[k] = {"r": rank, "h": it.get("head", ""), "d": it.get("dir", ""), "day": day, "st": it.get("stage", "")}
        sday = max(H.get("short") or {}) if H.get("short") else None
        short = {x["key"]: x for x in (H["short"][sday] if sday else [])}
    except Exception:
        H, short = None, {}
    # ---- catalysts for breakout alerts (TradeCharts): what's coming in the next 45 days, and the industry's shifts
    horizon = today + dt.timedelta(days=45)
    try:
        import highlights as HL2
        dues = HL2.company_dues(tl.get("companies", {}), today, horizon_days=45)
    except Exception:
        dues = {}
    try:
        T = json.loads((C.DATA / "trackers.json").read_text(encoding="utf-8"))
    except Exception:
        T = {}
    res_dates = {}
    for e in T.get("calendar", []) or []:
        if e.get("code") and today.isoformat() <= (e.get("when") or "") <= horizon.isoformat():
            res_dates.setdefault(str(e["code"]), e["when"])
    monthly = {}
    try:
        for ln in (C.BASE / "monthly_data.txt").read_text(encoding="utf-8").splitlines():
            p = [x.strip() for x in ln.split("|")]
            if ln.strip().startswith("#") or len(p) < 3 or not p[1].isdigit():
                continue
            d = today.replace(day=min(int(p[1]), 28))
            if d < today:
                d = (d.replace(day=1) + dt.timedelta(days=32)).replace(day=min(int(p[1]), 28))
            kws = [k.strip().lower() for k in (p[3] if len(p) > 3 else "").split(",") if k.strip()]
            monthly.setdefault(p[0], []).append((d, p[2], kws))
    except Exception:
        pass
    pend = [p for p in T.get("policy", []) or [] if p.get("status") == "pending"]
    shifts_by, texts = {}, {}
    try:
        import direction
        for o in lib.get("overviews", {}).values():
            if o.get("shifts"):
                key = (o["sector"], o.get("industry") or "")
                if key not in shifts_by or C.quarter_key(o["quarter"]) > C.quarter_key(shifts_by[key][0]):
                    shifts_by[key] = (o["quarter"], o["shifts"])
        # each company's own words (latest concall + recent events), and which shift keywords are specific enough to
        # mean something: a word most concalls use ("revenue", "volume", "capex") says nothing about a shift
        for code_, c_ in latest.items():
            try:
                t_ = C.here(c_["summary"]).read_text(encoding="utf-8").lower() if c_.get("summary") else ""
            except OSError:
                t_ = ""
            texts[code_] = t_ + " " + " ".join(e["t"].lower() for e in tl.get("companies", {}).get(code_, []) if e["d"] >= cut)
        STOP = {"and", "the", "for", "with", "shift", "growth", "scaling", "expansion", "profitability", "aggressive",
                "focus", "strategy", "business", "led", "driven", "new", "towards", "from", "into", "reduction", "rise"}
        cands = {w for _, sh in shifts_by.values() for x in sh
                 for w in list(x.get("kw") or []) + re.findall(r"[a-z0-9&\-]{2,}", x["name"].lower()) if w not in STOP}
        n_ = max(1, len(texts))
        bags = [set(re.findall(r"[a-z0-9&\-]+", t_)) for t_ in texts.values()]
        df = {}
        for w in cands:
            if " " in w:
                df[w] = sum(1 for t_ in texts.values() if w in t_) / n_
            else:
                df[w] = sum(1 for b_ in bags if w in b_ or w + "s" in b_) / n_
        momentum = {}
        for key, (q, sh) in shifts_by.items():
            sh2 = []
            for x in sh:
                kw = [w for w in dict.fromkeys(list(x.get("kw") or []) + re.findall(r"[a-z0-9&\-]{2,}", x["name"].lower()))
                      if w in df and 0 < df[w] <= 0.12]
                if kw:
                    sh2.append(dict(x, kw=kw))
            momentum[key] = direction.momentum(lib, key[0], key[1] or None, sh2)
    except Exception:
        momentum = {}

    GENERIC = {"goods", "capital", "services", "products", "engineering", "others", "other", "industries", "industry",
               "materials", "building", "consumer", "financial", "health", "healthcare", "equipment", "infrastructure"}

    def ahead_of(code, sector, industry, text):
        out_ = []
        if code in res_dates:
            out_.append([res_dates[code], "results", "board meeting for results"])
        for d, t in sorted(dues.get(code, []))[:3]:
            out_.append([d.isoformat(), "due", t])
        seen_ = set()
        for sec_, rows_ in monthly.items():  # its sector's monthly data, or another sector's it clearly talks about
            for d, t, kws in rows_:
                if (sec_ == sector or sum(len(re.findall(r"(?<![a-z0-9])" + re.escape(k) + r"(?![a-z0-9])", text)) for k in kws) >= 3) and t not in seen_:
                    seen_.add(t)
                    out_.append([d.isoformat(), "data", "around this date: " + t])
        words = {w for w in re.findall(r"[a-z]{4,}", (sector + " " + industry).lower())} - GENERIC
        for p in pend:
            if words & set(re.findall(r"[a-z]{4,}", (p.get("sectors") or "").lower())):
                out_.append(["", "decision", f"{p.get('body') or 'Govt'}: {p.get('what', '')}"[:160]])
                if sum(1 for x in out_ if x[1] == "decision") >= 2:
                    break
        return sorted(out_, key=lambda x: x[0] or "9999")

    def shifts_of(sector, industry, mine):
        """Its own industry's shifts, and any other industry's shift its own concall / news clearly talks about
        (only specific keywords count, see above)."""
        hits = lambda x: sum(1 for w in x["kw"] if re.search(r"\b" + re.escape(w) + r"s?\b", mine)) if mine else 0
        rows, seen_ = [], set()
        own = momentum.get((sector, industry)) or []
        others = [x for k, m in momentum.items() if k != (sector, industry) for x in m]
        for x in own + sorted(others, key=hits, reverse=True):
            h = hits(x)
            if x in own or h >= 2:
                if x["name"] in seen_:
                    continue
                seen_.add(x["name"])
                ser = x.get("series") or []
                rows.append({"n": x["name"], "st": x.get("stage", ""), "s": [[q, n, t] for q, n, t in ser[-2:]], "me": h >= 1,
                             "own": x in own})
        return [r for r in rows if r["me"]][:3] + [r for r in rows if not r["me"]][:max(0, 3 - sum(r["me"] for r in rows))]

    try:
        import segments
        seg = segments.load().get("cos", {})
    except Exception:
        seg = {}
    out = {}
    for code in set(latest) | {k for k in tl.get("companies", {}) if not k.startswith("n:")}:
        c = latest.get(code)
        ev = [[e["d"], e["k"], e["t"][:200]] for e in tl.get("companies", {}).get(code, [])
              if e["d"] >= cut and e["k"] in ("pivot", "order", "result", "broker", "policy", "deck")][:8]
        st = stories.get(code) or {}
        row = {"n": re.sub(r"[\s\-$]+$", "", tl.get("names", {}).get(code) or (c["company"] if c else code)),
               "s": (C.sector_of(lib, c) if c else "") or "", "i": inds.get(code, "")}
        if st.get("status") == "ok" and st.get("one"):
            row["story"] = st["one"]
        if c:
            tone = c.get("tone") or ""
            ex, dl, g = (c.get("expect") or {}).get("v"), (c.get("delivery") or {}).get("v"), (c.get("metrics") or {}).get("guidance")
            score = ({"Positive": 3, "Mixed": 2, "Cautious": 1, "Negative": 0}.get(tone, 1.5) + {"addressed": 2, "partly": 1, "gap": 0}.get(ex, 1)
                     + {"delivered": 2, "partly": 1, "missed": 0}.get(dl, 1) + {"raised": 1, "cut": -1, "initiated": 0.5}.get(g, 0))
            row["call"] = {"q": c.get("quarter", ""), "d": c["date"], "tone": tone, "rate": round(score, 1),
                           "vs": ex or "", "did": dl or "", "guid": g or "", "draft": "lite" in (c.get("model") or "lite")}
        mv = (seg.get(code) or {}).get("shift") or []
        if c and mv and abs(mv[0]["pp"]) >= 3:  # the business mix is moving - a possible re-rating story
            x = mv[0]
            ev = [[c["date"], "pivot", f"Mix shift: {x['n']} {x['then']:g}% -> {x['now']:g}% of revenue since {x['since']}"]] + ev
            row["mix"] = mv[:3]
        if ev:
            row["ev"] = ev
        if code in top:
            row["top"] = top[code]
        if code in short:  # on Market Desk's early-signal shortlist today
            x = short[code]
            row["early"] = {"s": x["s"], "k": x["k"], "since": x["since"], "move": x.get("move")}
        if c:  # covered by Market Desk: what's coming, and its industry's direction
            mine = texts.get(code, "")
            ah = ahead_of(code, row["s"], row["i"], mine)
            if ah:
                row["ahead"] = ah
            sh = shifts_of(row["s"], row["i"], mine)
            if sh:
                row["shifts"] = sh
        if len(row) > 3:  # something beyond the name and sector
            out[code] = row
    return {"at": dt.datetime.now().isoformat(timespec="minutes"), "n": len(out), "cos": out}


def build(quiet=False):
    """(Re)builds public/. Safe to run any time."""
    if PUBLIC.exists():
        shutil.rmtree(PUBLIC)
    shutil.copytree(WEB, PUBLIC)
    data = PUBLIC / "data"
    data.mkdir(exist_ok=True)

    index = []
    files = sorted(BRIEFS.glob("*.json")) if BRIEFS.exists() else []
    for f in files[-90:]:
        b = json.loads(f.read_text(encoding="utf-8"))
        for st in b["stories"] + [x for t in b.get("tabs", []) for x in t.get("stories", [])]:
            st["sources"] = st.get("sources", [])[:3]  # the count stays in "outlets"; keeps the page light
        # Google News links: store just the article token (the site rebuilds the address) - about a third of the file
        for st in b["stories"] + [x for t in b.get("tabs", []) for x in t.get("stories", [])]:
            for src in st["sources"]:
                m = re.match(r"https://news\.google\.com/rss/articles/([^?]+)(\?oc=5)?$", src.get("link", ""))
                if m:
                    src["link"] = "g:" + m.group(1)
        # Tech / Auto / Sports go in their own file, loaded only when one of those tabs is opened
        tabs = b.pop("tabs", [])
        b["tabnames"] = [t["name"] for t in tabs]
        # outlet links are only needed when a story is opened: their own small file, fetched then
        links = {}
        for st in b["stories"]:
            links[st["id"]] = [src.get("link", "") for src in st["sources"]]
            st["sources"] = [{"name": src.get("name", "")} for src in st["sources"]]
        (data / f"links-{b['date']}.js").write_text(_js("DESK_LINKS", b["date"], links), encoding="utf-8")
        (data / f"brief-{b['date']}.js").write_text(_js("DESK_BRIEFS", b["date"], b), encoding="utf-8")
        (data / f"tabs-{b['date']}.js").write_text(_js("DESK_TABS", b["date"], tabs), encoding="utf-8")
        b["tabs"] = tabs
        comp = {}
        for s in b["stories"]:
            for n in s["companies"]:
                comp[n] = comp.get(n, 0) + 1
        index.append({"date": b["date"], "label": b["label"], "stats": b["stats"],
                      "cats": {s["cat"]: len(s["ids"]) for s in b["sections"]},
                      "mood": {s["cat"]: [s["pos"], s["neg"], s["neu"]] for s in b["sections"]},
                      "companies": dict(sorted(comp.items(), key=lambda kv: -kv[1])[:40])})
    # small per-company news index (last 7 briefs) so the Companies pages don't load whole briefs
    conews = {}
    for f in files[-7:]:
        b = json.loads(f.read_text(encoding="utf-8"))
        for s in b["stories"]:
            if not s["companies"]:
                continue
            mini = {"id": s["id"], "d": b["date"], "t": s["title"], "s": s.get("sent", "="), "i": s.get("imp", 0),
                    "w": s["when"], "c": s["cat"]}
            for n in s["companies"]:
                conews.setdefault(n, []).append(mini)
    (data / "conews.js").write_text(_js("DESK_CONEWS", None, conews), encoding="utf-8")
    cc = concall_data()
    # which of its industry's shifts each company's own latest summary talks about (company page: "acting on it")
    latest_sh = {}
    for o in cc["overviews"]:
        if o.get("shifts"):
            key = (o["sector"], o.get("ind", ""))
            if C.quarter_key(o["quarter"]) >= C.quarter_key(latest_sh.get(key, {}).get("quarter", "Q1 FY00")):
                latest_sh[key] = o
    for c in cc["calls"]:
        o = latest_sh.get((c["sector"], c.get("ind", ""))) or latest_sh.get((c["sector"], ""))
        if not o or "html" not in c:
            continue
        t = re.sub(r"<[^>]+>", " ", c["html"]).lower()
        hit = [x["name"] for x in o["shifts"] if any(re.search(r"\b" + re.escape(w) + r"s?\b", t) for w in x["kw"])]
        if hit:
            c["sh"] = hit
    # summaries are split out: the index (small) loads everywhere, each summary only when it's opened
    (data / "cc").mkdir(exist_ok=True)
    text = {}
    # each summary lives in a file named after its own call (never a position in a list), and carries its company
    # name - so a page left open across an update can never show one company's summary on another's page
    for c in cc["calls"]:
        k = re.sub(r"[^A-Za-z0-9_-]", "", c.pop("id"))[:80]
        c["k"] = k
        plain = re.sub(r"<[^>]+>", " ", c["html"])
        plain = re.sub(r"\s+", " ", plain).strip()
        m = re.search(r"<(?:li|p)>(.*?)</(?:li|p)>", c["html"], re.S)
        one = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1) if m else plain)).strip()
        one = re.sub(r"^Tone:\s*\w+\s*[-–—:]\s*", "", one)
        c["one"] = one[:257] + "…" if len(one) > 260 else one
        text[k] = plain.replace("&amp;", "&")
        (data / "cc" / f"{k}.js").write_text(_js("DESK_CCH", k, {"c": c["company"], "h": c.pop("html")}), encoding="utf-8")
    for o in cc["overviews"]:
        k = "ov_" + re.sub(r"[^a-z0-9]+", "_", (o["sector"] + "_" + o.get("ind", "") + "_" + o["quarter"]).lower()).strip("_")
        o["k"] = k
        (data / "cc" / f"{k}.js").write_text(_js("DESK_OVH", k, {"c": o["sector"] + o.get("ind", ""), "h": o.pop("html")}), encoding="utf-8")
    for c in cc["calls"]:  # empty fields and blank metrics only cost the phone time to read
        c["metrics"] = {k: v for k, v in (c.get("metrics") or {}).items() if v is not None}
        for k in ("unchecked", "checks", "bse", "ex", "dl", "ft", "prev_tone", "ind"):
            if not c.get(k):
                c.pop(k, None)
    (data / "concalls.js").write_text(_js("DESK_CONCALLS", None, cc), encoding="utf-8")
    pres = json.loads(C.PRES_FILE.read_text(encoding="utf-8")) if C.PRES_FILE.exists() else []
    import decks as DK
    sums = DK.load()
    for d in pres:
        x = sums.get(d["id"])
        if x and x.get("status") == "ok":
            d["one"], d["html"] = x.get("one", ""), x.get("html", "")
        elif x and x.get("status") == "no-text":
            d["scan"] = True
    # each deck's summary in a file of its own (opened with the deck); its text joins the search text
    (data / "deck").mkdir(exist_ok=True)
    for d in pres:
        h = d.pop("html", "")
        if h:
            k = re.sub(r"[^A-Za-z0-9_-]", "", d["id"])[:80]
            d["k"] = k
            (data / "deck" / f"{k}.js").write_text(_js("DESK_DECKH", k, {"c": d["company"], "h": h}), encoding="utf-8")
            text["d:" + k] = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", (d.get("one") or "") + " " + h)).replace("&amp;", "&").strip()
    (data / "cctext.js").write_text(_js("DESK_CCTEXT", None, text), encoding="utf-8")
    nfix = canon(pres)
    (data / "presentations.js").write_text(_js("DESK_PRES", None, pres), encoding="utf-8")
    try:  # business mix per company (by BSE code) and per-industry reads on why margins differ
        import segments
        S = segments.load()
        (data / "segments.js").write_text(_js("DESK_SEG", None, {
            "cos": {k: {kk: v[kk] for kk in ("q", "basis", "model", "dims", "shift") if v.get(kk)} for k, v in S.get("cos", {}).items()
                    if v.get("dims") or v.get("model")},
            "reads": {k: {"html": v["html"], "n": v["n"], "at": v.get("at", "")} for k, v in S.get("reads", {}).items()}}),
            encoding="utf-8")
    except Exception as e:
        C.say(f"  (business mix not added: {e})")
    try:  # top 10 developments: one small file per day, and the list of days
        import highlights as HL
        H = HL.load()
        (data / "hl").mkdir(exist_ok=True)
        for day, items in H["days"].items():
            canon(items, name="name")
            (data / "hl" / f"{day}.js").write_text(_js("DESK_HL", day, items) + "\n" + _js("DESK_HLCAL", day, (H.get("cal") or {}).get(day, []))
                                                   + "\n" + _js("DESK_HLDROP", day, (H.get("dropped") or {}).get(day, [])),
                                                   encoding="utf-8")
        (data / "hlindex.js").write_text(_js("DESK_HLIDX", None, {"days": sorted(H["days"]), "at": H.get("at", ""),
                                                                  "model": H.get("model", "")}), encoding="utf-8")
    except Exception as e:
        print(f"  (top developments not built: {e})")
    import backstory as BS
    (data / "bs").mkdir(exist_ok=True)
    have = {}
    for code, b in BS.load().items():
        if b.get("status") == "ok" and b.get("v", 0) >= 4:  # only the web-researched version
            (data / "bs" / f"{code}.js").write_text(_js("DESK_BS", code, b), encoding="utf-8")
            have[code] = b["at"]
    meta = json.loads(BS.META.read_text(encoding="utf-8")) if BS.META.exists() else {}
    (data / "bsindex.js").write_text(_js("DESK_BSIDX", None, {"have": have, "meta": meta}), encoding="utf-8")
    import timeline as TL
    tl = TL.load()
    (data / "tl").mkdir(exist_ok=True)
    tlidx = {}
    for k, lst in tl.get("companies", {}).items():
        if not lst:
            continue
        fk = re.sub(r"[^a-z0-9]", "_", k.lower())
        (data / "tl" / f"{fk}.js").write_text(_js("DESK_TL", fk, lst), encoding="utf-8")
        tlidx[fk] = {"name": tl.get("names", {}).get(k, ""), "code": k if not k.startswith("n:") else "", "n": len(lst)}
    (data / "tlindex.js").write_text(_js("DESK_TLIDX", None, tlidx), encoding="utf-8")
    try:  # for TradeCharts: "why is it moving" in one plain JSON file, keyed by BSE code
        (data / "why.json").write_text(json.dumps(why_file(tl, BS.load()), ensure_ascii=False, separators=(",", ":")),
                                       encoding="utf-8")
    except Exception as e:
        print(f"  (why.json not built: {e})")
    # search index (every timeline entry, compact) and the themes companies are moving into
    search, themes = [], {}
    for k, lst in tl.get("companies", {}).items():
        nm = tl.get("names", {}).get(k, "")
        for e in lst:
            search.append([nm, e["k"], e["d"], e["t"], e.get("l", "")])
            if e["k"] == "pivot" and e.get("th"):
                themes.setdefault(e["th"], []).append({"c": nm, "d": e["d"], "t": e["t"], "l": e.get("l", "")})
    import directory as DIR
    dr = DIR.load()
    (data / "directory.js").write_text(_js("DESK_DIR", None, [[k, v["n"], v.get("s", ""), v.get("id", "")] for k, v in dr.items() if k != "_meta"]), encoding="utf-8")
    (data / "search.js").write_text(_js("DESK_SEARCH", None, {"tl": search, "themes": themes}), encoding="utf-8")
    import trackers as TK
    track = {"trackers": TK.load(TK.TRACK_FILE, {}), "markets": TK.load(TK.MARKET_FILE, {"series": []}),
             "weekly": TK.load(TK.WEEKLY_FILE, {"reviews": []})}
    for k in ("results", "orders", "calls", "pivots", "calendar"):
        nfix += canon(track["trackers"].get(k))
    C.say(f"  sectors made consistent: {nfix} items re-tagged to their company's own sector")
    # lighter file: Google News links as their article token only (the page rebuilds them), no repeated pivot headline
    for k in ("results", "orders", "calls", "pivots", "events", "policy"):
        for it in track["trackers"].get(k) or []:
            m = re.match(r"https://news\.google\.com/rss/articles/([^?]+)(\?oc=5)?$", it.get("link") or "")
            if m:
                it["link"] = "g:" + m.group(1)
            elif (it.get("link") or "").startswith("https://www.bseindia.com/xml-data/corpfiling/AttachLive/"):
                it["link"] = it["link"].rsplit("/", 1)[1]  # the page rebuilds BSE filing links from the file name
            if k == "pivots" and it.get("what"):
                it.pop("title", None)
            it.pop("uid", None)
    arch_path = C.DATA / "news_archive.json"
    arch = json.loads(arch_path.read_text(encoding="utf-8")) if arch_path.exists() else []
    (data / "newsarchive.js").write_text(_js("DESK_NEWSARCH", None, arch), encoding="utf-8")
    (data / "trackers.js").write_text(_js("DESK_TRACK", None, track), encoding="utf-8")
    try:  # market cap and ratios by BSE code, for the company page's peer table
        import fundamentals
        keep = ("mcap", "pe", "pb", "roe", "fy", "rev", "rev_g", "rev_cagr3", "np", "np_g", "np_cagr3", "opm_fy", "npm_fy", "icr",
                "ttm_rev", "ttm_np", "hist")
        F = {k: {x: v[x] for x in keep if v.get(x) not in (None, "-")} for k, v in fundamentals.load().items()}
        (data / "fund.js").write_text(_js("DESK_FUND", None, {k: v for k, v in F.items() if v}), encoding="utf-8")
    except Exception as e:
        C.say(f"  (ratios not built: {e})")
    try:  # global -> India: the commodity board and its flags (small file, for the Today page)
        import commods
        G = commods.load()
        (data / "global.js").write_text(_js("DESK_GLOBAL", None, {"flags": G.get("flags", []), "board": G.get("board", []),
                                                                   "at": G.get("at", "")}), encoding="utf-8")
    except Exception as e:
        C.say(f"  (commodity board not built: {e})")
    try:  # build season progress (Concalls page): how complete the site is
        import season
        import direction
        S = season.load()
        L = C.load_lib()
        calls = [c for c in L["calls"].values() if c.get("summary")]
        latest = C.latest_per_company(calls)
        quarters = {}
        for c in calls:
            quarters.setdefault(c["code"], set()).add(C.filing_quarter(c))
        ovs = list(L.get("overviews", {}).values())
        try:
            import backstory
            bm = json.loads(backstory.META.read_text(encoding="utf-8"))
        except Exception:
            bm = {}
        S["prog"] = [["Concall summaries by a full model", sum(1 for c in latest if "lite" not in (c.get("model") or "lite")), len(latest)],
                     ["Companies with last quarter to compare", sum(1 for c in latest if len(quarters.get(c["code"], ())) > 1), len(latest)],
                     ["Overviews with 'where the industry is heading'", sum(1 for o in ovs if o.get("dir_v", 0) >= direction.DIR_V and "lite" not in (o.get("model") or "lite")), len(ovs)],
                     ["Company stories written", bm.get("done", 0), bm.get("total", 0)]]
        (data / "season.js").write_text(_js("DESK_SEASON", None, S), encoding="utf-8")
    except Exception as e:
        C.say(f"  (season progress not built: {e})")
    try:  # analysis & deep dives (titles, links and the model's own takeaways - never the article text)
        import analysis
        (data / "reads.js").write_text(_js("DESK_READS", None, analysis.site_data()), encoding="utf-8")
    except Exception as e:
        C.say(f"  (analysis not built: {e})")
    try:  # initiating coverage notes, last 12 months
        import ic
        cut = (dt.date.today() - dt.timedelta(days=365)).isoformat()
        track["ic"] = [r for r in ic.load().get("items", []) if r["date"] >= cut]
        canon(track["ic"])
        import readacross
        cut2 = (dt.date.today() - dt.timedelta(days=200)).isoformat()
        track["ra"] = [r for r in readacross.load().get("items", []) if r["date"] >= cut2 and r.get("matches")]
        # small file of its own: the Concalls and Sectors pages need it without the whole trackers file
        (data / "readacross.js").write_text(_js("DESK_RA", None, track.pop("ra")), encoding="utf-8")
        (data / "trackers.js").write_text(_js("DESK_TRACK", None, track), encoding="utf-8")
    except Exception as e:
        C.say(f"  (initiating coverage notes not added: {e})")
    tabs = []
    if files:
        tabs = [t["name"] for t in json.loads(files[-1].read_text(encoding="utf-8")).get("tabs", []) if t.get("stories")]
    meta = {"briefs": index, "tabs": tabs, "updated": dt.datetime.now(IST).isoformat(timespec="minutes"),
            "concalls": len(cc["calls"]), "overviews": len(cc["overviews"]), "presentations": len(pres)}
    (data / "index.js").write_text(_js("DESK_INDEX", None, meta), encoding="utf-8")
    # cache-busting: every build gets new file addresses, so a refresh always shows the latest edition
    stamp = dt.datetime.now(IST).strftime("%Y%m%d%H%M")
    js = (PUBLIC / "app.js").read_text(encoding="utf-8")
    import hashlib
    vh = lambda rel: hashlib.md5((PUBLIC / rel).read_bytes()).hexdigest()[:10] if (PUBLIC / rel).exists() else stamp  # noqa: E731
    # each file's address carries a fingerprint of its content: a file that didn't change keeps its address, so the
    # browser keeps using its saved copy after an update instead of downloading it again
    js = js.replace('"data/brief-" + date + ".js"', '"data/brief-" + date + ".js?v=' + stamp + '"')
    js = js.replace('"data/tabs-" + date + ".js"', '"data/tabs-" + date + ".js?v=' + stamp + '"')
    js = js.replace('const CCV = ""', 'const CCV = "?v=' + stamp + '"')
    js = js.replace('const BUILD = ""', 'const BUILD = "' + stamp + '"')
    (data / "build.js").write_text(f'window.DESK_BUILD_NOW = "{stamp}";', encoding="utf-8")
    for f in ("concalls", "readacross", "newsarchive", "directory", "search", "tlindex", "bsindex", "conews",
              "trackers", "presentations", "segments"):
        js = js.replace(f'loadScript("data/{f}.js")', f'loadScript("data/{f}.js?v={vh("data/" + f + ".js")}")')
    for f in ("cctext", "reads", "global", "hlindex"):
        js = js.replace(f'"data/{f}.js" + CCV', f'"data/{f}.js?v={vh("data/" + f + ".js")}"')
    (PUBLIC / "app.js").write_text(js, encoding="utf-8")
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    for name in ("app.css", "app.js", "data/index.js"):
        page = page.replace(f'"{name}"', f'"{name}?v={hashlib.md5((PUBLIC / name).read_bytes()).hexdigest()[:10]}"')
    page = page.replace("<head>", '<head>\n<meta http-equiv="Cache-Control" content="no-cache">', 1)
    (PUBLIC / "index.html").write_text(page, encoding="utf-8")
    if not quiet:
        C.say(f"Website built: {PUBLIC / 'index.html'}  ({len(index)} briefs, {len(cc['calls'])} concall summaries)")
    return PUBLIC / "index.html"


def open_site(anchor=""):
    page = PUBLIC / "index.html"
    if not page.exists():
        build()
    if C.IS_TABLET:
        C.open_on_tablet("public/index.html" + anchor)
    else:
        webbrowser.open(page.as_uri() + anchor)


if __name__ == "__main__":
    import sys
    build(quiet="--quiet" in sys.argv)
    if "--no-open" not in sys.argv:
        open_site()
