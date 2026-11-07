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
                      "company": c["company"], "code": c["code"], "sector": C.sector_of(lib, c),
                      "quarter": c["quarter"], "date": c["date"], "tone": c.get("tone", ""),
                      "compared": bool(c.get("compared")), "checks": bad,
                      "pdf": c.get("pdf_url", C.BSE_PDF[0] + c["pdf"]), "html": html})
    overviews = []
    for o in lib["overviews"].values():
        f = C.here(o["file"])
        if f.exists():
            overviews.append({"sector": o["sector"], "quarter": o["quarter"], "companies": o["companies"],
                              "html": C.md(f.read_text(encoding="utf-8"))})
    return {"calls": calls, "overviews": overviews}


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
            st["sources"] = st.get("sources", [])[:6]  # the count stays in "outlets"; keeps the page light
        (data / f"brief-{b['date']}.js").write_text(_js("DESK_BRIEFS", b["date"], b), encoding="utf-8")
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
    # summaries are split out: the index (small) loads everywhere, each summary only when it's opened
    (data / "cc").mkdir(exist_ok=True)
    text = {}
    for i, c in enumerate(cc["calls"]):
        c["k"] = i
        plain = re.sub(r"<[^>]+>", " ", c["html"])
        plain = re.sub(r"\s+", " ", plain).strip()
        m = re.search(r"<(?:li|p)>(.*?)</(?:li|p)>", c["html"], re.S)
        one = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1) if m else plain)).strip()
        one = re.sub(r"^Tone:\s*\w+\s*[-–—:]\s*", "", one)
        c["one"] = one[:257] + "…" if len(one) > 260 else one
        text[i] = plain.lower()
        (data / "cc" / f"{i}.js").write_text(_js("DESK_CCH", i, c.pop("html")), encoding="utf-8")
    for j, o in enumerate(cc["overviews"]):
        o["k"] = j
        (data / "cc" / f"ov{j}.js").write_text(_js("DESK_OVH", j, o.pop("html")), encoding="utf-8")
    (data / "cctext.js").write_text(_js("DESK_CCTEXT", None, text), encoding="utf-8")
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
    (data / "presentations.js").write_text(_js("DESK_PRES", None, pres), encoding="utf-8")
    import backstory as BS
    (data / "bs").mkdir(exist_ok=True)
    have = []
    for code, b in BS.load().items():
        if b.get("status") == "ok":
            (data / "bs" / f"{code}.js").write_text(_js("DESK_BS", code, b), encoding="utf-8")
            have.append(code)
    (data / "bsindex.js").write_text(_js("DESK_BSIDX", None, have), encoding="utf-8")
    import trackers as TK
    track = {"trackers": TK.load(TK.TRACK_FILE, {}), "markets": TK.load(TK.MARKET_FILE, {"series": []}),
             "weekly": TK.load(TK.WEEKLY_FILE, {"reviews": []})}
    (data / "trackers.js").write_text(_js("DESK_TRACK", None, track), encoding="utf-8")
    tabs = []
    if files:
        tabs = [t["name"] for t in json.loads(files[-1].read_text(encoding="utf-8")).get("tabs", []) if t.get("stories")]
    meta = {"briefs": index, "tabs": tabs, "updated": dt.datetime.now(IST).isoformat(timespec="minutes"),
            "concalls": len(cc["calls"]), "overviews": len(cc["overviews"]), "presentations": len(pres)}
    (data / "index.js").write_text(_js("DESK_INDEX", None, meta), encoding="utf-8")
    # cache-busting: every build gets new file addresses, so a refresh always shows the latest edition
    stamp = dt.datetime.now(IST).strftime("%Y%m%d%H%M")
    page = (PUBLIC / "index.html").read_text(encoding="utf-8")
    for name in ("app.css", "app.js", "data/index.js"):
        page = page.replace(f'"{name}"', f'"{name}?v={stamp}"')
    page = page.replace("<head>", '<head>\n<meta http-equiv="Cache-Control" content="no-cache">', 1)
    (PUBLIC / "index.html").write_text(page, encoding="utf-8")
    js = (PUBLIC / "app.js").read_text(encoding="utf-8")
    js = js.replace('"data/brief-" + date + ".js"', '"data/brief-" + date + ".js?v=' + stamp + '"')
    js = js.replace('loadScript("data/concalls.js")', 'loadScript("data/concalls.js?v=' + stamp + '")')
    js = js.replace('const CCV = ""', 'const CCV = "?v=' + stamp + '"')
    js = js.replace('loadScript("data/bsindex.js")', 'loadScript("data/bsindex.js?v=' + stamp + '")')
    js = js.replace('loadScript("data/conews.js")', 'loadScript("data/conews.js?v=' + stamp + '")')
    js = js.replace('loadScript("data/trackers.js")', 'loadScript("data/trackers.js?v=' + stamp + '")')
    js = js.replace('loadScript("data/presentations.js")', 'loadScript("data/presentations.js?v=' + stamp + '")')
    (PUBLIC / "app.js").write_text(js, encoding="utf-8")
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
