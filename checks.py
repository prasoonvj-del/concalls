#!/usr/bin/env python3
"""
Blunder checks on concall summaries - no AI.

1. Units against the transcript. The figure check already makes sure every number in a summary appears in the
   transcript, but not in which unit: "INR 2,238 million" written as "Rs 2,238 crore" passes it and is 10x wrong.
   Here every "Rs N crore" is looked up in the transcript; if the transcript only ever says N million / lakh /
   billion, the summary is corrected (N million = N/10 crore) and says so in a note.
2. Against the company's own quarterly results filed on BSE (Rs crore). Consolidated (concall) vs standalone (BSE)
   can differ, so only gaps far beyond that are flagged; a 10x / 100x gap means a unit slip - the transcript is
   fetched again to confirm and the figure fixed, else the figure is flagged on the page with BSE's number.
3. A fix is carried everywhere the wrong figure was copied: overviews, business profiles, timeline, Top 10.
"""
import json
import re

import concalls as C

UNIT = {"million": 0.1, "mn": 0.1, "mln": 0.1, "millions": 0.1, "lakh": 0.01, "lakhs": 0.01, "lac": 0.01, "lacs": 0.01,
        "billion": 100, "bn": 100, "billions": 100}
CR_RE = re.compile(r"((?:Rs\.?|INR|₹)\s*)(\d[\d,]*(?:\.\d+)?)(\s*)(crores?|cr\b\.?)", re.I)
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
FIN = ("Banks", "NBFC & Financial Services", "Insurance", "Capital Markets & Wealth")
FILES = ["timeline.json", "backstories.json", "ic.json", "highlights.json", "readacross.json"]


def _digits(s):
    return s.replace(",", "").rstrip("0").rstrip(".") if "." in s else s.replace(",", "")


def _fmt(v):
    if v >= 100:
        s = f"{v:,.1f}"
    elif v >= 1:
        s = f"{v:,.2f}"
    else:
        s = f"{v:.3f}"
    return s.rstrip("0").rstrip(".") if "." in s else s


def units_in_transcript(num, transcript):
    """Units the transcript puts after this number (crore, million, lakh, billion...)."""
    d = _digits(num)
    whole, _, dec = d.partition(".")
    flex = r"\d{1,3}(?:,\d{2,3})*" if len(whole) > 3 else ""
    out = []
    for m in re.finditer(r"(?<![\d.,])(\d[\d,]*(?:\.\d+)?)\s*(?:\(?(?:INR|Rs\.?|₹)\)?\s*)?"
                         r"(crores?|cr\b|millions?|mn\b|mln\b|lakhs?|lacs?|billions?|bn\b)", transcript, re.I):
        if _digits(m.group(1)) == d:
            before = transcript[max(0, m.start() - 8):m.start()]
            foreign = re.search(r"(USD|US\$|\$|EUR|€|£|GBP|JPY|¥|AED|SGD)\s*$", before, re.I)
            out.append("foreign" if foreign else m.group(2).lower().rstrip("."))
    return out


def unit_fix(text, transcript):
    """Returns (text, [(old, new), ...]) with crore figures the transcript gives in another unit converted."""
    if not transcript:
        return text, []
    fixes = []

    def sub(m):
        num = m.group(2)
        units = units_in_transcript(num, transcript)
        if not units or any(u.startswith("cr") or u == "foreign" for u in units):
            return m.group(0)
        u = max(set(units), key=units.count)
        f = UNIT.get(u) or UNIT.get(u.rstrip("s"))
        if not f:
            return m.group(0)
        new = m.group(1) + _fmt(float(num.replace(",", "")) * f) + m.group(3) + m.group(4)
        fixes.append((m.group(0), new, f"{num} {u}"))
        return new
    body, sep, tail = text.partition("\n---\n")
    body = CR_RE.sub(sub, body)
    if fixes:
        note = "; ".join(f"the call said {w} = {n.strip()}" for o, n, w in dict(((f[0], f) for f in fixes)).values())
        body = body.rstrip() + f"\n\n_Units corrected by Market Desk's check: {note}._\n"
    return body + sep + tail, [(o, n) for o, n, _ in fixes]


def fix_metrics(metrics, fixes):
    if not metrics:
        return
    for o, n in fixes:
        ov = float(CR_RE.search(o).group(2).replace(",", ""))
        nv = float(CR_RE.search(n).group(2).replace(",", ""))
        for k, v in list(metrics.items()):
            if k.endswith("_cr") and isinstance(v, (int, float)) and abs(v - ov) < 1e-6:
                metrics[k] = nv


def quarter_of(label):
    """BSE column label ('Sep-26', 'Sep 2026', '30-09-2026', 'Q2 FY27') -> 'Q2 FY27'."""
    s = (label or "").strip().lower()
    m = re.search(r"q\s*([1-4])\s*[-' ]*fy\s*'?(\d{2,4})", s)
    if m:
        return f"Q{m.group(1)} FY{int(m.group(2)) % 100:02d}"
    m = re.search(r"([a-z]{3})[a-z]*[\s\-'/.]*(\d{2,4})", s)
    mo = MONTHS.get(m.group(1)) if m else None
    yr = int(m.group(2)) % 100 if m else None
    if not mo:
        m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
        if not m:
            return ""
        mo, yr = int(m.group(2)), int(m.group(3)) % 100
    q = {6: 1, 9: 2, 12: 3, 3: 4}.get(mo)
    if not q:
        return ""
    return f"Q{q} FY{(yr + (0 if mo == 3 else 1)) % 100:02d}"


def quarter_end(q):
    import datetime as dt
    m = re.match(r"Q([1-4]) FY(\d\d)", q or "")
    if not m:
        return None
    n, fy = int(m.group(1)), 2000 + int(m.group(2))
    return {1: dt.date(fy - 1, 6, 30), 2: dt.date(fy - 1, 9, 30), 3: dt.date(fy - 1, 12, 31), 4: dt.date(fy, 3, 31)}[n]


def sane_quarter(call, q):
    """A call can't be about a quarter that hadn't ended when it was filed, or one that ended ~7+ months earlier
    (the AI misreading the fiscal year from comparisons in the transcript). Then the filing date decides."""
    import datetime as dt
    end = quarter_end(q)
    try:
        filed = dt.date.fromisoformat(call["date"])
    except (KeyError, ValueError):
        return q
    if end is None or end > filed or (filed - end).days > 215:
        return C.filing_quarter(call)
    return q


def fix_quarters(lib):
    n = 0
    for c in lib["calls"].values():
        if not c.get("summary") or not c.get("quarter"):
            continue
        q = sane_quarter(c, c["quarter"])
        if q != c["quarter"]:
            p = C.here(c["summary"])
            if p.exists():
                t = p.read_text(encoding="utf-8")
                p.write_text(re.sub(r"(\*\*Quarter:\*\*\s*).*", lambda m: m.group(1) + q, t, count=1), encoding="utf-8")
            C.say(f"    quarter fixed: {c['company']} {c['quarter']} -> {q} (filed {c['date']})")
            c["quarter"] = q
            n += 1
    return n


def _year_ago(q):
    m = re.match(r"Q([1-4]) FY(\d\d)", q or "")
    return f"Q{m.group(1)} FY{int(m.group(2)) - 1:02d}" if m else ""


def bse_quarter(fund, quarter):
    qt = (fund or {}).get("qt") or {}
    for i, lab in enumerate(qt.get("q") or []):
        if quarter_of(lab) == quarter:
            return {k: (qt.get(k) or [None] * 9)[i] for k in ("rev", "np", "opm")}
    return None


def _near_power(r):
    for p in (10, 100, 1000, 0.1, 0.01, 0.001):
        if abs(r / p - 1) < 0.12:
            return p
    return None


def bse_flags(call, sector, fund):
    """Figures far from what the company filed on BSE for the same quarter. [(key, said, bse, unit-slip?)]"""
    b = bse_quarter(fund, call.get("quarter"))
    m = call.get("metrics") or {}
    if not b:
        return None
    out = []
    pairs = [("pat_cr", "np", 3.0)] + ([] if sector in FIN else [("revenue_cr", "rev", 2.5)])
    for k, bk, lim in pairs:
        say, bv = m.get(k), b.get(bk)
        if not isinstance(say, (int, float)) or not isinstance(bv, (int, float)) or abs(bv) < 1 or abs(say) < 1:
            continue
        r = say / bv
        if r <= 0:
            continue  # profit vs loss: standalone vs consolidated can genuinely differ in sign
        p = _near_power(r)
        if p or r > lim or r < 1 / lim:
            out.append({"k": k, "say": say, "bse": bv, "slip": bool(p)})
    # growth: only when the revenue itself matches BSE (same basis), so standalone vs consolidated can't explain a gap
    ya = bse_quarter(fund, _year_ago(call.get("quarter")))
    g, rv = m.get("revenue_growth_yoy_pct"), m.get("revenue_cr")
    if sector not in FIN and ya and isinstance(g, (int, float)) and isinstance(rv, (int, float)) \
            and isinstance(b.get("rev"), (int, float)) and isinstance(ya.get("rev"), (int, float)) and ya["rev"] > 1 \
            and abs(rv / b["rev"] - 1) < 0.15:
        bg = round(100 * (b["rev"] / ya["rev"] - 1), 1)
        if abs(g - bg) > 25:
            out.append({"k": "revenue_growth_yoy_pct", "say": g, "bse": bg, "slip": False})
    if sector not in FIN and isinstance(m.get("ebitda_margin_pct"), (int, float)) and isinstance(b.get("opm"), (int, float)):
        if abs(m["ebitda_margin_pct"] - b["opm"]) > 25 and _near_power(m["ebitda_margin_pct"] / b["opm"] if b["opm"] else 0):
            out.append({"k": "ebitda_margin_pct", "say": m["ebitda_margin_pct"], "bse": b["opm"], "slip": True})
    return out


def _replace_near(text, names, old, new, js=False):
    """Replaces the rupee figure `old` (any of Rs/INR/₹, crore/cr) with `new`'s number, only where one of the
    company's names is within 400 characters before it."""
    on = CR_RE.search(old).group(2)
    nn = CR_RE.search(new).group(2)
    pat = re.compile(r"((?:Rs\.?|INR|₹|\\u20b9)\s*)" + re.escape(on) + r"(\s*(?:crores?|cr\b))", re.I)
    low = text.lower()
    n = 0

    def sub(m):
        nonlocal n
        if any(x in low[max(0, m.start() - 300):m.start()] for x in names):
            n += 1
            return m.group(1) + nn + m.group(2)
        return m.group(0)
    return pat.sub(sub, text), n


def _names(company):
    full = company.lower()
    core = re.sub(r"\b(ltd|limited|india|industries|the)\b\.?", "", full).strip()
    first = core.split()[0] if core.split() else full
    return {full, core, first} if len(first) >= 4 else {full, core}


def propagate(lib, call, fixes, sector):
    """Carries unit fixes into everything that copied the wrong figure."""
    names = _names(call["company"])
    n = 0
    folder = C.OUT_DIR / C.safe_name(sector)
    for f in folder.glob("_*OVERVIEW*.md") if folder.exists() else []:
        t = f.read_text(encoding="utf-8")
        t2 = t
        for o, nw in fixes:
            t2, k = _replace_near(t2, names, o, nw)
            n += k
        if t2 != t:
            f.write_text(t2, encoding="utf-8")
    for name in FILES:
        f = C.DATA / name
        if not f.exists():
            continue
        t = f.read_text(encoding="utf-8")
        t2 = t
        for o, nw in fixes:
            t2, k = _replace_near(t2, names, o, nw)
            n += k
        if t2 != t:
            try:
                json.loads(t2)
                f.write_text(t2, encoding="utf-8")
            except ValueError:
                pass
    return n


def apply_fix(lib, call, transcript):
    """Unit check of one saved summary against its transcript; fixes the file, metrics and copies. Returns n fixes."""
    p = C.here(call["summary"])
    t = p.read_text(encoding="utf-8")
    if "_Units corrected by Market Desk" in t:
        return 0
    t2, fixes = unit_fix(t, transcript)
    if not fixes:
        return 0
    p.write_text(t2, encoding="utf-8")
    fix_metrics(call.get("metrics"), fixes)
    news = {_digits(CR_RE.search(nw).group(2)) for _, nw in fixes}
    call["unverified"] = [x for x in (call.get("unverified") or []) if _digits(x) not in news]
    propagate(lib, call, fixes, C.sector_of(lib, call))
    C.say(f"    units fixed in {call['company']} {call['quarter']}: " + "; ".join(f"{o} -> {n}" for o, n in fixes))
    return len(fixes)


def step(lib, budget_dl=25, deadline=None):
    """Every latest summary: BSE cross-check; a suspected unit slip re-reads the transcript and fixes it."""
    import time
    import fundamentals
    fund = fundamentals.load()
    nq = fix_quarters(lib)
    latest = C.latest_per_company([c for c in lib["calls"].values() if c.get("summary")])
    checked = flagged = fixed = dl = 0
    for c in latest:
        if deadline and time.time() > deadline:
            break
        sec = C.sector_of(lib, c)
        flags = bse_flags(c, sec, fund.get(str(c.get("code"))))
        if flags is None:
            continue
        checked += 1
        if any(f["slip"] for f in flags) and dl < budget_dl and not c.get("unit_checked"):
            txt, prob = C.get_text(c)
            dl += 1
            c["unit_checked"] = True
            if txt and apply_fix(lib, c, txt):
                fixed += 1
                flags = bse_flags(c, sec, fund.get(str(c.get("code")))) or []
        if flags:
            c["bse_flags"] = flags
            flagged += 1
        else:
            c.pop("bse_flags", None)
    C.save_lib(lib)
    C.say(f"  figure check vs BSE results: {checked} summaries checked, {fixed} unit slips fixed, {flagged} flagged; "
          f"{nq} wrong quarters fixed")
    return fixed
