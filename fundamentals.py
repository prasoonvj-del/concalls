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
    "pe": ("pe", "peratio", "pettm", "pe_ratio", "ttmpe"),
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
            if v is not None:
                row[name] = round(v, 2)
                break
    return row


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
    return out


def step(lib=None, limit=250, budget=150):
    lib = lib or C.load_lib()
    d = load()
    today = dt.date.today()
    cut = (today - dt.timedelta(days=FRESH_DAYS)).isoformat()
    codes = sorted({c["code"] for c in C.latest_call_each(list(lib["calls"].values())) if str(c.get("code", "")).isdigit()},
                   key=lambda k: (d.get(k) or {}).get("at", ""))
    todo = [k for k in codes if (d.get(k) or {}).get("at", "") < cut][:limit]
    if not todo:
        return 0
    stop, n, empty = time.time() + budget, 0, 0
    sample = C.DATA / "bse_ratio_sample.json"
    for code in todo:
        if time.time() > stop:
            break
        res = fetch_one(code)
        if res and not sample.exists():  # one raw reply kept, to check BSE's field names
            sample.write_text(json.dumps(res, ensure_ascii=False, indent=1)[:20000], encoding="utf-8")
        row = parse(*res)
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
