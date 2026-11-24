#!/usr/bin/env python3
"""
Valuation and return ratios for the company page's peer table - from BSE's own free JSON (no AI):
market cap, P/E, P/B, ROE, EPS, operating and net margin.

A few hundred companies are refreshed per update, oldest first, so every company is about a week fresh at most.

  data/fundamentals.json  {code: {"at": date, "mcap": Rs cr, "pe", "pb", "roe", "eps", "opm", "npm"}}
"""
import datetime as dt
import json
import re
import time

import concalls as C

say = C.say
FILE = C.DATA / "fundamentals.json"
API = "https://api.bseindia.com/BseIndiaAPI/api"
FRESH_DAYS = 7

# BSE's field names vary between its endpoints; any of these spellings counts
KEYS = {
    "mcap": ("mktcapfull", "mktcap", "marketcap", "mcapfull", "mcap", "fullmktcap", "mktcapfullcr"),
    "pe": ("conpe", "pe", "peratio", "pettm", "pe_ratio", "ttmpe"),  # consolidated P/E first
    "pb": ("pb", "pbratio", "pbv", "pricetobook"),
    "roe": ("roe", "ronw"),
    "eps": ("eps", "epsttm", "ttmeps"),
    "opm": ("opm",),
    "npm": ("npm",),
}


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    except ValueError:
        return {}


def _val(v):
    if isinstance(v, dict):
        v = v.get("value", v.get("Value"))
    if v is None:
        return None
    s = str(v).replace(",", "").strip()
    m = re.match(r"^-?\d+(\.\d+)?$", s)
    return float(s) if m else None


def _flat(obj, out=None):
    out = {} if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)) and not (isinstance(v, dict) and ("value" in v or "Value" in v)):
                _flat(v, out)
            else:
                out.setdefault(re.sub(r"[^a-z]", "", str(k).lower()), v)
    elif isinstance(obj, list):
        for x in obj:
            _flat(x, out)
    return out


def parse(*responses):
    flat = {}
    for r in responses:
        _flat(r, flat)
    row = {}
    for name, keys in KEYS.items():
        for k in keys:
            v = _val(flat.get(k))
            if v is not None and not (k.startswith("con") and v == 0):  # 0.00 = not reported on a consolidated basis
                row[name] = round(v, 2)
                break
    return row


def _cells(row):
    return [re.sub(r"<[^>]+>", "", c).replace("&nbsp;", " ").strip() for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", row, re.S)]


def parse_table(html):
    """BSE's results table (HTML) -> (column labels, {row title: [numbers]})."""
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", html or "", re.S)
    if not rows:
        return [], {}
    head = _cells(rows[0])[1:]
    out = {}
    for r in rows[1:]:
        c = _cells(r)
        if len(c) >= 2 and c[0] and c[0] not in out:
            out[c[0]] = [_val(x) for x in c[1:1 + len(head)]]
    return head, out


def annual(rep):
    """Five years of annual results (Rs cr) and the last few quarters, plus the comparisons the peer table needs."""
    if not isinstance(rep, dict):
        return {}
    yrs, A = parse_table(rep.get("AnninCr"))
    qs, Q = parse_table(rep.get("QtlyinCr"))
    if not yrs or "Revenue" not in A:
        return {}
    g = lambda k: A.get(k) or [None] * len(yrs)
    rev, np_, opm, npm, intr, pbt = g("Revenue"), g("Net Profit"), g("OPM %"), g("NPM %"), g("Interest"), g("PBT")

    def yoy(xs):
        return round(100 * (xs[0] / xs[1] - 1), 1) if len(xs) > 1 and xs[0] is not None and xs[1] and xs[1] > 0 else None

    def cagr(xs, n=3):
        if len(xs) > n and xs[0] and xs[n] and xs[0] > 0 and xs[n] > 0:
            return round(100 * ((xs[0] / xs[n]) ** (1 / n) - 1), 1)
        return None
    out = {"fy": yrs[0], "rev": rev[0], "rev_g": yoy(rev), "rev_cagr3": cagr(rev), "np": np_[0], "np_g": yoy(np_),
           "np_cagr3": cagr(np_), "opm_fy": opm[0], "npm_fy": npm[0],
           "hist": {"y": yrs, "rev": rev, "np": np_}}
    if intr[0] and pbt[0] is not None and abs(intr[0]) > 0:
        out["icr"] = round((pbt[0] + abs(intr[0])) / abs(intr[0]), 1)
    # trailing four quarters, when BSE lists them (the last column is the full year, not a quarter)
    qcols = [i for i, h in enumerate(qs) if not h.upper().startswith("FY")][:4]
    if len(qcols) == 4 and "Revenue" in Q:
        qr, qn = [Q["Revenue"][i] for i in qcols], [(Q.get("Net Profit") or [None] * 9)[i] for i in qcols]
        if all(v is not None for v in qr):
            out["ttm_rev"] = round(sum(qr), 1)
        if all(v is not None for v in qn):
            out["ttm_np"] = round(sum(qn), 1)
    # the quarterly table itself (Rs cr), so concall summaries can be checked against the company's own filing
    qc = [i for i, h in enumerate(qs) if not h.upper().startswith("FY")]
    if qc and "Revenue" in Q:
        col = lambda k: [(Q.get(k) or [None] * len(qs))[i] for i in qc]
        out["qt"] = {"q": [qs[i] for i in qc], "rev": col("Revenue"), "np": col("Net Profit"), "opm": col("OPM %")}
    return {k: v for k, v in out.items() if v is not None}


def fetch_one(code):
    out = []
    for ep, params in (("ComHeadernew/w", {"quotetype": "EQ", "scripcode": code, "seriesid": ""}),
                       ("StockTrading/w", {"flag": "", "quotetype": "EQ", "scripcode": code})):
        try:
            r = C.bse().get(f"{API}/{ep}", params=params, timeout=20)
            if r.status_code == 200 and r.text.strip().startswith(("{", "[")):
                out.append(r.json())
        except Exception:
            pass
        time.sleep(0.25)
    rep = None
    try:  # five years of annual results
        r = C.bse().get(f"{API}/GetReportNewFor_Result/w", params={"scripcode": code}, timeout=25)
        if r.status_code == 200 and r.text.strip().startswith("{"):
            rep = r.json()
    except Exception:
        pass
    return out, rep


def step(lib=None, limit=400, budget=330):
    lib = lib or C.load_lib()
    d = load()
    today = dt.date.today()
    cut = (today - dt.timedelta(days=FRESH_DAYS)).isoformat()
    codes = sorted({c["code"] for c in C.latest_call_each(list(lib["calls"].values())) if str(c.get("code", "")).isdigit()},
                   key=lambda k: (d.get(k) or {}).get("at", ""))
    todo = [k for k in codes if (d.get(k) or {}).get("at", "") < cut or "fy" not in (d.get(k) or {})
            or ("qt" not in (d.get(k) or {}) and (d.get(k) or {}).get("fy") != "-")][:limit]
    shown = False
    if not todo:
        return 0
    stop, n, empty = time.time() + budget, 0, 0
    for code in todo:
        if time.time() > stop:
            break
        res, rep = fetch_one(code)
        row = parse(*res)
        row.update(annual(rep))
        if row.get("qt") and not shown:
            say(f"  BSE quarterly columns look like: {row['qt']['q']}; results tables offered: {sorted((rep or {}).keys())[:20]}")
            shown = True
        row.setdefault("qt", {})
        row.setdefault("fy", "-")  # "-" = BSE has no annual table for it: not asked again until the weekly refresh
        if row:
            d[code] = dict(row, at=today.isoformat())
            n += 1
        else:
            empty += 1
            d.setdefault(code, {})["at"] = today.isoformat()  # try again in a week
        if empty >= 15 and not n:
            say("  ratios: BSE returned nothing usable for 15 companies - stopping for this run")
            break
    FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    say(f"  ratios (market cap, P/E, P/B, ROE): {n} companies refreshed, {len([k for k in d if d[k].get('pe') or d[k].get('mcap')])} have figures")
    return n


if __name__ == "__main__":
    step(limit=5)
