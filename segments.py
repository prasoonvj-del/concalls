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
      "parts": [{{"n": "<short name>", "pct": <share of revenue, number>, "growth": <YoY growth % or null>,
                 "margin": <segment EBIT/EBITDA margin % or null>}}]}}
  ],
  "model": "<one sentence: how this company makes money, e.g. 'B2B pathology via ~X franchisees, low capex per test'>"}}

Rules: only figures the material states. A share may be worked out only as a remainder (e.g. radiology 37% -> pathology
63%) or from revenue figures given for each part; if worked out, add "calc": true to that part. Leave out a dimension
whose shares you can't get. Shares in one dimension must not add up to more than 100. If nothing usable: {{"dims": []}}.
"model" may be written from the material even without numbers.

MATERIAL:
{material}"""

READ_PROMPT = """These are listed Indian peers in {sector} / {industry}: their revenue mix (from their own calls), and their
margins and returns. In 3-5 short bullets, explain what the MIX explains about why some earn higher margins or returns
than others (customer type, product mix, geography, capital intensity, scale). Name the companies and use the numbers
given; say so where the mix does NOT explain a gap. No investment advice. Plain Markdown bullets only.

{table}"""


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"cos": {}, "reads": {}}


def _material(c, lib, stories):
    try:
        t = C.here(c["summary"]).read_text(encoding="utf-8").split("\n---\n")[0]
    except OSError:
        return ""
    st = stories.get(c["code"]) or {}
    biz = re.sub(r"<[^>]+>", " ", st.get("biz") or "")
    return (t[:9000] + ("\n\nBUSINESS PROFILE:\n" + biz[:4000] if biz.strip() else "")).strip()


def _digits(x):
    return re.sub(r"[^\d.]", "", str(x)).rstrip(".")


def _clean(js, material):
    """Keep only shares the material supports; drop dimensions that don't add up."""
    have = set(re.findall(r"\d+(?:\.\d+)?", material.replace(",", "")))
    dims = []
    for d in js.get("dims") or []:
        parts = []
        for p in d.get("parts") or []:
            try:
                pct = float(p.get("pct"))
            except (TypeError, ValueError):
                continue
            if not (0 < pct <= 100):
                continue
            stated = _digits(round(pct, 1)) in have or _digits(int(pct)) in have or _digits(pct) in have
            if not stated and not p.get("calc"):
                continue
            parts.append({"n": str(p.get("n", ""))[:40], "pct": round(pct, 1),
                          **({"g": p["growth"]} if isinstance(p.get("growth"), (int, float)) else {}),
                          **({"m": p["margin"]} if isinstance(p.get("margin"), (int, float)) else {}),
                          **({"calc": True} if p.get("calc") or not stated else {})})
        tot = sum(p["pct"] for p in parts)
        if len(parts) >= 2 and tot <= 103 and tot >= 60:
            dims.append({"dim": str(d.get("dim", "segment"))[:12], "parts": sorted(parts, key=lambda p: -p["pct"])})
    return dims


def step(lib, pool, limit=60, deadline=None, reads=10):
    """Mixes for companies whose summary is new or changed (biggest first), then the industry reads."""
    import backstory
    data = load()
    cos, stories = data.setdefault("cos", {}), backstory.load()
    try:
        import fundamentals
        F = fundamentals.load()
    except Exception:
        F = {}
    latest = [c for c in C.latest_call_each(list(lib["calls"].values())) if c.get("summary") and c.get("code")]
    def key(c):
        st = stories.get(c["code"]) or {}
        return hashlib.md5(f"{c['summary']}|{c.get('model')}|{bool(st.get('biz'))}".encode()).hexdigest()[:10]
    todo = [c for c in latest if (cos.get(c["code"]) or {}).get("k") != key(c)]
    todo.sort(key=lambda c: -((F.get(c["code"]) or {}).get("mcap") or 0))
    SAY(f"\nBusiness mix: {len(todo)} companies to read, up to {limit} this update ...")
    done = 0
    for c in todo[:limit]:
        if deadline and time.time() > deadline:
            break
        mat = _material(c, lib, stories)
        if len(mat) < 300:
            continue
        prompt = PROMPT.format(company=c["company"], sector=C.sector_of(lib, c),
                               industry=(lib.get("industries") or {}).get(c["code"], "") or "-", material=mat)
        try:
            out, _ = pool.ask(prompt, label="business mix")
        except C.QuotaOver as e:
            SAY(f"  {e}")
            break
        except C.AIError as e:
            SAY(f"  {c['company']}: {str(e)[:100]}")
            continue
        m = re.search(r"\{.*\}", out or "", re.S)
        try:
            js = json.loads(m.group(0)) if m else {}
        except json.JSONDecodeError:
            js = {}
        cos[c["code"]] = {"k": key(c), "company": c["company"], "q": c.get("quarter", ""),
                          "basis": str(js.get("basis", ""))[:60], "model": str(js.get("model", ""))[:240],
                          "dims": _clean(js, mat)}
        done += 1
        if done % 10 == 0:
            FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    SAY(f"  business mix: {done} read, {sum(1 for v in cos.values() if v.get('dims'))} companies with a mix")
    _reads(lib, pool, data, F, limit=reads, deadline=deadline)


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
