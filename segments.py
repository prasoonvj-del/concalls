"""Business mix: how each company's revenue splits (by segment, customer type, geography), read from what it said.

Why: peers in one industry can look alike and still earn very different margins and returns - Thyrocare is a B2B
pathology franchise model, Vijaya Diagnostic a B2C pathology + radiology chain in one region. Putting the mixes side by
side next to margins and ROE explains much of the gap. The mixes come from the concall summary (and the company's
'story so far' business profile when there is one); every share must be a figure the material states (a remainder,
e.g. 100 - 37, is allowed and marked). Then, per industry, one short read on why margins / returns differ.

data/segments.json: {"cos": {code: {...}}, "reads": {"<sector>|<industry>": {...}}}
"""
from __future__ import annotations

import hashlib
import json
import re
import time

import concalls as C

FILE = C.DATA / "segments.json"
SAY = C.say

PROMPT = """From the material below about {company} ({sector} / {industry}), extract how its REVENUE splits.

Return JSON only:
{{"basis": "<what the shares are of, e.g. 'Q2 FY27 revenue' or 'FY26 revenue'>",
  "dims": [
    {{"dim": "segment" | "product" | "customer" | "channel" | "geography",
      "parts": [{{"n": "<short name>", "pct": <share of revenue % if stated, else null>,
                 "rev": <its revenue in Rs crore if stated, else null>, "growth": <YoY growth % or null>,
                 "margin": <segment EBIT/EBITDA margin % or null>,
                 "was": <its share % in an EARLIER period if the material states one, else null>,
                 "was_rev": <its revenue in that earlier period, Rs crore, if stated, else null>}}],
      "was_period": "<that earlier period, e.g. 'Q2 FY26' or 'FY24', or null>"}}
  ],
  "model": "<one sentence: how this company makes money, e.g. 'B2B pathology via ~X franchisees, low capex per test'>"}}

Rules: copy figures exactly as the material states them - shares (%) or the parts' revenue (Rs crore); do not
calculate anything yourself. Include a dimension when the material gives shares or revenue for at least two of its
parts. Revenue figures of different periods must not be mixed in one dimension. If nothing usable: {{"dims": []}}.
"model" may be written from the material even without numbers.

MATERIAL:
{material}"""

READ_PROMPT = """These are listed Indian peers in {sector} / {industry}: their revenue mix (from their own calls and decks),
how it is moving, and their margins and returns. In 3-5 short bullets, explain what the MIX explains about why some earn
higher margins or returns than others (customer type, product mix, geography, capital intensity, scale), and which
companies' mix is shifting toward higher- or lower-margin business (a shift like that can change how the market values
a stock). Name the companies and use the numbers given; say so where the mix does NOT explain a gap. No investment
advice. Plain Markdown bullets only.

{table}"""


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"cos": {}, "reads": {}}


def _decks(code, decks):
    """The company's latest investor-deck summaries (they usually carry the revenue split, often for several years)."""
    mine = sorted((k for k in decks if k.split("_")[0] == str(code) and (decks[k] or {}).get("html")), reverse=True)[:2]
    return "\n\n".join("INVESTOR DECK SUMMARY:\n" + re.sub(r"<[^>]+>", " ", decks[k]["html"])[:3500] for k in mine)


def _material(c, lib, stories, decks=None):
    try:
        t = C.here(c["summary"]).read_text(encoding="utf-8").split("\n---\n")[0]
    except OSError:
        return ""
    st = stories.get(c["code"]) or {}
    biz = re.sub(r"<[^>]+>", " ", st.get("biz") or "")
    dk = _decks(c["code"], decks or {}) if c.get("_with_decks", True) else ""
    return (t[:9000] + ("\n\nBUSINESS PROFILE:\n" + biz[:4000] if biz.strip() else "") + ("\n\n" + dk if dk else "")).strip()


def _digits(x):
    return re.sub(r"[^\d.]", "", str(x)).rstrip(".")


def _clean(js, material):
    """Shares the material supports: stated %, or worked out here from stated revenue (or as the one remainder)."""
    have = set(re.findall(r"\d+(?:\.\d+)?", material.replace(",", "")))
    said = lambda x: x is not None and any(_digits(v) in have for v in (x, round(float(x), 1), int(float(x))))  # noqa: E731
    num = lambda x: float(x) if isinstance(x, (int, float)) or (isinstance(x, str) and re.fullmatch(r"[\d.]+", x)) else None  # noqa: E731
    dims = []
    for d in js.get("dims") or []:
        raw = []
        for p in d.get("parts") or []:
            pct, rev = num(p.get("pct")), num(p.get("rev"))
            was, wrev = num(p.get("was")), num(p.get("was_rev"))
            raw.append({"n": str(p.get("n", ""))[:40], "pct": pct if pct and 0 < pct <= 100 and said(pct) else None,
                        "rev": rev if rev and rev > 0 and said(rev) else None, "g": num(p.get("growth")), "m": num(p.get("margin")),
                        "was": was if was and 0 < was <= 100 and said(was) else None,
                        "wrev": wrev if wrev and wrev > 0 and said(wrev) else None})
        if len(raw) >= 2 and all(r["wrev"] for r in raw) and not all(r["was"] for r in raw):
            wt = sum(r["wrev"] for r in raw)  # earlier-period shares from that period's revenue
            for r in raw:
                r["was"] = round(r["wrev"] / wt * 100, 1)
        parts = []
        if len(raw) >= 2 and all(r["rev"] for r in raw) and sum(1 for r in raw if r["pct"]) < len(raw):
            tot = sum(r["rev"] for r in raw)  # every part's revenue given: shares worked out from them
            parts = [dict(r, pct=round(r["rev"] / tot * 100, 1), calc=True) for r in raw]
        else:
            known = [r for r in raw if r["pct"]]
            missing = [r for r in raw if not r["pct"]]
            if len(missing) == 1 and len(known) >= 1 and sum(r["pct"] for r in known) < 100:
                missing[0] = dict(missing[0], pct=round(100 - sum(r["pct"] for r in known), 1), calc=True)
                known.append(missing[0])
            parts = known
        tot = sum(p["pct"] for p in parts)
        if len(parts) >= 2 and 60 <= tot <= 103:
            out = []
            for p in sorted(parts, key=lambda p: -p["pct"]):
                q = {"n": p["n"], "pct": p["pct"]}
                if p.get("g") is not None:
                    q["g"] = p["g"]
                if p.get("m") is not None:
                    q["m"] = p["m"]
                if p.get("calc"):
                    q["calc"] = True
                if p.get("was") is not None:
                    q["was"] = p["was"]
                out.append(q)
            dd = {"dim": str(d.get("dim", "segment"))[:12], "parts": out}
            if any("was" in q for q in out) and d.get("was_period"):
                dd["was_period"] = str(d.get("was_period"))[:20]
            elif any("was" in q for q in out) and js.get("was_period"):
                dd["was_period"] = str(js.get("was_period"))[:20]
            dims.append(dd)
    return dims


def step(lib, pool, limit=60, deadline=None, reads=10):
    """Mixes for companies whose summary is new or changed (biggest first), then the industry reads."""
    import backstory
    import decks as D
    data = load()
    cos, stories = data.setdefault("cos", {}), backstory.load()
    decks = {k: v for k, v in D.load().items() if isinstance(v, dict)}
    try:
        import fundamentals
        F = fundamentals.load()
    except Exception:
        F = {}
    latest = [c for c in C.latest_call_each(list(lib["calls"].values())) if c.get("summary") and c.get("code")]
    def key(c):
        st = stories.get(c["code"]) or {}
        dk = sorted(k for k in decks if k.split("_")[0] == str(c["code"]))[-1:]
        return hashlib.md5(f"v3|{c['summary']}|{c.get('model')}|{bool(st.get('biz'))}|{dk}".encode()).hexdigest()[:10]
    todo = [c for c in latest if (cos.get(c["code"]) or {}).get("k") != key(c)]
    todo.sort(key=lambda c: -((F.get(c["code"]) or {}).get("mcap") or 0))
    SAY(f"\nBusiness mix: {len(todo)} companies to read, up to {limit} this update ...")
    done = 0
    for c in todo[:limit]:
        if deadline and time.time() > deadline:
            break
        try:
            js, mat = _extract(c, lib, stories, decks, pool)
        except C.QuotaOver as e:
            SAY(f"  {e}")
            break
        except C.AIError as e:
            SAY(f"  {c['company']}: {str(e)[:100]}")
            continue
        if js is None:
            continue
        old = cos.get(c["code"]) or {}
        hist = old.get("hist") or {}
        dims = _clean(js, mat)
        if dims:
            hist[c.get("quarter", "")] = dims
        # last quarter's mix too, from its own call (once), so a shift shows even when this call gives no 'earlier' share
        prev = C.find_prev(lib, c)
        if dims and prev and prev.get("summary") and prev.get("quarter") not in hist and done < limit - 1:
            try:
                pjs, pmat = _extract(dict(prev, _with_decks=False), lib, {}, {}, pool)
                pd_ = _clean(pjs or {}, pmat or "")
                hist[prev["quarter"]] = pd_ or []
                done += 1
            except C.AIError:
                pass
        cos[c["code"]] = {"k": key(c), "company": c["company"], "q": c.get("quarter", ""),
                          "basis": str(js.get("basis", ""))[:60], "model": str(js.get("model", ""))[:240],
                          "dims": dims, "hist": dict(sorted(hist.items())[-8:])}
        cos[c["code"]]["shift"] = shifts(cos[c["code"]])
        done += 1
        if done % 10 == 0:
            FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    SAY(f"  business mix: {done} read, {sum(1 for v in cos.values() if v.get('dims'))} companies with a mix")
    _reads(lib, pool, data, F, limit=reads, deadline=deadline)


def _extract(c, lib, stories, decks, pool):
    mat = _material(c, lib, stories, decks)
    if len(mat) < 300:
        return None, mat
    prompt = PROMPT.format(company=c["company"], sector=C.sector_of(lib, c),
                           industry=(lib.get("industries") or {}).get(c["code"], "") or "-", material=mat)
    out, _ = pool.ask(prompt, label="business mix")
    m = re.search(r"\{.*\}", out or "", re.S)
    try:
        return (json.loads(m.group(0)) if m else {}), mat
    except json.JSONDecodeError:
        return {}, mat


def _qkey(q):
    m = re.match(r"Q(\d) FY(\d+)", q or "")
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def shifts(v, min_pp=2.0):
    """How the mix moved: against an earlier share the company itself stated (deck / call), else against the share
    read from an earlier quarter's call. Each: dimension, part, now, then, since, change in percentage points."""
    out = []
    norm = lambda n: re.sub(r"[^a-z]", "", n.lower())[:14]  # noqa: E731
    hist = v.get("hist") or {}
    qs = sorted((q for q in hist if q != v.get("q") and hist[q]), key=_qkey)
    for d in v.get("dims") or []:
        for p in d["parts"]:
            then, since = None, ""
            if p.get("was") is not None:
                then, since = p["was"], d.get("was_period") or "earlier"
            else:
                for q in reversed(qs):  # the latest earlier quarter that gave this part
                    od = next((x for x in hist[q] if x["dim"] == d["dim"]), None)
                    op = next((x for x in (od or {}).get("parts", []) if norm(x["n"]) == norm(p["n"])), None)
                    if op:
                        then, since = op["pct"], q
                        break
            if then is not None and abs(p["pct"] - then) >= min_pp:
                out.append({"dim": d["dim"], "n": p["n"], "now": p["pct"], "then": then, "since": since,
                            "pp": round(p["pct"] - then, 1)})
    return sorted(out, key=lambda x: -abs(x["pp"]))[:6]


def _reads(lib, pool, data, F, limit, deadline):
    """Per industry (3+ peers with a mix): why margins / returns differ, as far as the mix explains it."""
    ind = lib.get("industries") or {}
    groups = {}
    for code, v in data["cos"].items():
        if v.get("dims"):
            groups.setdefault((C.sector_of(lib, {"code": code, "company": v["company"]}), ind.get(code, "")), []).append(code)
    calls = {c["code"]: c for c in C.latest_call_each(list(lib["calls"].values())) if c.get("code")}
    reads = data.setdefault("reads", {})
    made = 0
    for (sec, ii), codes in sorted(groups.items(), key=lambda x: -len(x[1])):
        if len(codes) < 3 or made >= limit or (deadline and time.time() > deadline):
            continue
        rows = []
        for code in codes[:14]:
            v, f = data["cos"][code], F.get(code) or {}
            m = calls.get(code, {}).get("metrics") or {}
            mix = "; ".join(f"{d['dim']}: " + ", ".join(f"{p['n']} {p['pct']:g}%" for p in d["parts"]) for d in v["dims"])
            if v.get("shift"):
                mix += " | mix moving: " + ", ".join(f"{x['n']} {x['then']:g}% -> {x['now']:g}% since {x['since']}" for x in v["shift"][:3])
            rows.append(f"- {v['company']}: {mix} | model: {v.get('model', '')} | EBITDA margin (call) "
                        f"{m.get('ebitda_margin_pct', 'n/a')}% | OPM FY {f.get('opm_fy', 'n/a')} | ROE {f.get('roe', 'n/a')}"
                        f" | revenue growth {m.get('revenue_growth_yoy_pct', 'n/a')}%")
        table = "\n".join(rows)
        k = hashlib.md5(table.encode()).hexdigest()[:10]
        gk = f"{sec}|{ii}"
        if (reads.get(gk) or {}).get("k") == k:
            continue
        try:
            out, ai = pool.ask(READ_PROMPT.format(sector=sec, industry=ii or "all", table=table), label="mix read")
        except C.AIError:
            break
        reads[gk] = {"k": k, "md": out.strip()[:2500], "html": C.md(out.strip()[:2500]), "n": len(codes),
                     "model": ai.model, "at": time.strftime("%Y-%m-%d")}
        made += 1
    FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    if made:
        SAY(f"  industry reads on business mix: {made} written")
