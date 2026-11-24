#!/usr/bin/env python3
"""
"Where the industry is heading" - added to the industry (and sector) overview request, so no extra AI requests.

The overview already sees every company's latest concall summary. Here it also gets, for the same companies:
  * their turning points of the last 12 months (capacity, new businesses, approvals, M&A, strategy) with the source
    each was taken from (concall, investor deck, news) - Market Desk's timeline
  * government decisions for the industry (PLI, duties, rules) - decided and pending - from the decisions tracker
and writes three parts, each claim tagged with where it comes from:
  1. the business model so far ("Background" - the one place general knowledge is allowed, and labelled so)
  2. the shifts underway, the companies acting on each and their evidence, and how far along each shift is
  3. what the government is pushing and what it rewards
plus a machine-readable list of the shifts and the words that signal each, so code can count, quarter by quarter, how
many of the industry's companies talked about or acted on each shift (momentum, no AI).
"""
import datetime as dt
import re

import concalls as C

DIR_V = 1  # overviews written before this version get the section when next due

PROMPT_ADD = """

ALSO add this section right after "Big picture" - it must be specific and sourced, not generic:
## Where the industry is heading
**Business model so far** - how this industry in India has made money until now and the big model changes of the
last ~5 years (e.g. owning assets -> managing them, dealers -> direct/online). 3-4 lines. This is the ONLY place you may
use general knowledge; end it with [Background].
**Shifts underway** - one bullet per shift that THIS evidence supports (2-5 shifts; fewer is fine): the shift in
plain words, its stage (early / scaling / mainstream), the companies acting on it with their concrete evidence
(numbers, plants, launches, shares of revenue), and why it matters for earnings. Every bullet must carry its sources in
square brackets, e.g. [Hero MotoCorp concall Q2 FY27; Ather deck Nov 2026]. Prefer the company's own word
(concall, deck, filing) over news reports; cite a news report with its date. A shift with no evidence below is left out.
**Government push** - schemes, duties, rules and pending decisions from the list below that reward or force these
shifts, what each rewards, and which companies benefit; tag each [Govt: <body>, <Mon YYYY>]. Long-running schemes not in the list (e.g. a PLI
scheme) may be named only by scheme name and launch year, with no figures, tagged [Background]. Skip if none apply.

Then, at the very end of your answer, add this block (one line per shift you described; nothing else inside):
```shifts
<shift name, 2-5 words> | <early / scaling / mainstream> | <4-8 words or short phrases that signal it in a concall, comma-separated>
```
{context}"""


# words government decisions use for an industry that its sector name doesn't contain
ALIAS = {
    "automobile": "auto vehicle vehicles electric two-wheeler wheeler tractor", "auto": "vehicle vehicles electric",
    "hotel": "tourism tourist travel aviation", "travel": "tourism aviation airline",
    "fmcg": "food consumer edible dairy tobacco alcohol beverage", "food": "edible dairy sugar",
    "pharma": "drug drugs medical health", "hospital": "health healthcare medical insurance",
    "power": "electricity solar renewable energy coal", "metal": "steel aluminium copper zinc mining",
    "electrical": "electronics semiconductor solar", "textile": "cotton apparel garment", "telecom": "spectrum",
    "chemical": "chemicals", "fertiliser": "urea fertilizer subsidy", "defence": "defense military",
    "bank": "rbi banking credit", "nbfc": "rbi credit lending", "oil": "petroleum crude fuel", "cement": "construction",
    "real": "housing realty", "logistic": "shipping port railway", "retail": "consumer ecommerce",
}


def _words(s):
    return {w for w in re.findall(r"[a-z]{4,}", (s or "").lower())}


def context(lib, sector, industry, calls):
    """Turning points of these companies (12 months) and government decisions for the industry, as prompt text."""
    import timeline
    tl = timeline.load()
    cos = tl.get("companies", {})
    cut = (dt.date.today() - dt.timedelta(days=365)).isoformat()
    tps = []
    for c in calls:
        for e in cos.get(c.get("code"), []):
            if e["k"] in ("pivot", "order") and e["d"] >= cut:
                src = re.search(r"\[([^\]]+)\]\s*$", e["t"])
                tps.append((e["d"], c["company"], re.sub(r"\s*\[[^\]]*\]$", "", e["t"])[:200], src.group(1) if src else "news"))
    # company filings / concalls / decks first (they are the company's own word); news reports fill in, dated
    seen, first, news = set(), [], []
    for d, co, t, s in sorted(tps, reverse=True):
        k = (co, t[:60].lower())
        if k in seen:
            continue
        seen.add(k)
        if s.lower() == "news":
            news.append((d, co, t, "news report " + dt.date.fromisoformat(d).strftime("%d %b %Y")))
        else:
            first.append((d, co, t, s))
    pick = first[:32] + news[:max(8, 45 - len(first[:32]))]
    pick.sort(reverse=True)
    rows = [f"- {d} {co}: {t} (source: {s})" for d, co, t, s in pick]
    gov = []
    try:
        import watch
        import trackers
        stem = lambda ws: {w.replace("z", "s").rstrip("s") for w in ws if w not in ("other", "others", "products", "services")}
        want = stem(_words(sector) | _words(industry))
        for w in list(want):
            want |= stem(_words(ALIAS.get(w, "")))
        near = lambda ws: any(a == b or (len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a))) for a in ws for b in want)
        names = {C.norm(c["company"]) for c in calls}
        W = watch.load().get("policy", {})
        T = trackers.load(trackers.TRACK_FILE, {})
        items = [(v["d"], "decided", v.get("body"), v.get("what"), v.get("sectors"), v.get("cos") or []) for v in W.values()]
        items += [(p.get("date", ""), "pending", p.get("body"), p.get("what"), p.get("sectors"), p.get("cos") or [])
                  for p in T.get("policy", []) if p.get("status") == "pending"]
        for d, st, body, what, secs, cos_ in sorted(items, reverse=True):
            if near(stem(_words(secs))) or any(C.norm(x) in names for x in cos_):
                body = body if body and "ministry name" not in body.lower() else "Govt"
                gov.append(f"- {d} [{st}] {body}: {what} (affects: {secs})")
    except Exception:
        pass
    seen, gov2 = set(), []
    for g in gov:
        k = g[13:80]
        if k not in seen:
            seen.add(k)
            gov2.append(g)
    out = ""
    if rows:
        out += "\nTURNING POINTS OF THESE COMPANIES (last 12 months, newest first, with where each was reported):\n" + "\n".join(rows)
    if gov2:
        out += "\n\nGOVERNMENT DECISIONS FOR THIS INDUSTRY (decided and pending):\n" + "\n".join(gov2[:15])
    return out


def prompt_add(lib, sector, industry, calls):
    return PROMPT_ADD.format(context=context(lib, sector, industry, calls))


def parse(text):
    """Takes the ```shifts block out. Returns ([{name, stage, kw: [...]}, ...], text)."""
    m = re.search(r"```\s*shifts\s*\n(.*?)```", text, re.S | re.I)
    if not m:
        return [], text
    shifts = []
    for ln in m.group(1).splitlines():
        p = [x.strip(" *`-") for x in ln.split("|")]
        if len(p) >= 3 and p[0]:
            kw = [k.strip().lower() for k in p[2].split(",") if len(k.strip()) >= 3][:8]
            stage = p[1].lower().split()[0] if p[1] else ""
            if kw:
                shifts.append({"name": p[0][:60], "stage": stage if stage in ("early", "scaling", "mainstream") else "", "kw": kw})
    return shifts[:6], (text[:m.start()] + text[m.end():]).rstrip() + "\n"


def momentum(lib, sector, industry, shifts, quarters=4):
    """For each shift: per quarter, how many of the industry's companies with a call that quarter mentioned it."""
    if not shifts:
        return []
    inds = lib.get("industries") or {}
    calls = [c for c in lib["calls"].values() if C.sector_of(lib, c) == sector and c.get("summary")
             and (not industry or inds.get(c["code"]) == industry)]
    qs = sorted({c["quarter"] for c in calls}, key=C.quarter_key)[-quarters:]
    text = {}
    for c in calls:
        if c["quarter"] in qs:
            try:
                t = C.here(c["summary"]).read_text(encoding="utf-8").lower()
            except OSError:
                continue
            k = (c["quarter"], C.norm(c["company"]))
            text[k] = text.get(k, "") + " " + t
    out = []
    for s in shifts:
        pats = [re.compile(r"\b" + re.escape(w) + r"s?\b") for w in s["kw"]]
        series = []
        for q in qs:
            cos_q = [k for k in text if k[0] == q]
            n = sum(1 for k in cos_q if any(p.search(text[k]) for p in pats))
            series.append([q, n, len(cos_q)])
        out.append(dict(s, series=series))
    # a quarter with only a handful of the industry's calls in the library would read as a trend; leave those out
    top = max((t for x in out for _, _, t in x["series"]), default=0)
    for x in out:
        x["series"] = [r for r in x["series"] if r[2] >= max(3, 0.3 * top)]
    return out
