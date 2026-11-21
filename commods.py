#!/usr/bin/env python3
"""
Global -> India commodity board: data, not news, and no AI.

  * LME base metals (copper, aluminium, zinc, nickel, lead, tin): official cash price and LME warehouse stocks,
    from Westmetall's free market-data page (one page a day; the history is kept here, so it builds up)
  * the rest comes from the Markets tab's Yahoo series (Brent, gas, iron ore, steel, gold, silver, cotton, sugar...)

Rules flag only moves that matter - a big price move in a week or a month, or LME stocks drawing / building
sharply - and each flag names the Indian stocks that gain and the ones whose costs rise.

  data/commods.json  {"lme": {metal: {"px": [[date, $/t]], "stk": [[date, t]]}}, "flags": [...], "at": ...}
"""
import datetime as dt
import json
import re

import concalls as C

say = C.say
FILE = C.DATA / "commods.json"
URL = "https://www.westmetall.com/en/markdaten.php"
METALS = ["Copper", "Aluminium", "Zinc", "Nickel", "Lead", "Tin"]

# what a move means for Indian stocks: (gain when the price rises, hurt when it rises)
INDIA = {
    "Copper": ("Hindustan Copper, Vedanta", "cables & wires (Polycab, KEI, Finolex Cables), consumer electricals, ACs"),
    "Aluminium": ("Hindalco, Nalco, Vedanta", "auto components, packaging, cable makers using aluminium"),
    "Zinc": ("Hindustan Zinc, Vedanta", "galvanisers and steel-pipe makers (APL Apollo)"),
    "Nickel": ("", "stainless steel makers (Jindal Stainless), battery chain"),
    "Lead": ("Hindustan Zinc", "battery makers (Exide, Amara Raja)"),
    "Tin": ("", "electronics makers (solder)"),
    "Iron ore": ("NMDC, Lloyds Metals", "steelmakers without captive mines (JSW Steel)"),
    "Steel (US hot-rolled coil)": ("Tata Steel, JSW Steel, SAIL, JSPL", "autos, capital goods, consumer durables"),
    "Brent crude": ("ONGC, Oil India", "OMCs (IOC, BPCL, HPCL), paints, tyres, aviation, chemicals"),
    "Natural gas (US)": ("", "fertilisers, city gas (IGL, MGL), gas-based power"),
    "Gold": ("gold-loan NBFCs (Muthoot, Manappuram: collateral values), Titan (inventory)", "jewellery demand"),
    "Silver": ("Hindustan Zinc", "solar & electronics makers"),
    "Cotton": ("", "spinners & textile makers (cotton is their main raw material)"),
    "Sugar": ("sugar mills (export realisations)", "FMCG & beverage makers"),
    "Wheat": ("", "flour-based food makers"),
    "Coffee": ("coffee plantation companies (CCL, Tata Consumer)", ""),
}
MOVE_W, MOVE_M = 5.0, 10.0      # % price move in a week / a month worth a flag
STOCK_M = 15.0                  # % change in LME stocks in a month worth a flag


def load():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    except ValueError:
        d = {}
    d.setdefault("lme", {})
    return d


def _num(t):
    t = t.strip().replace(",", "")
    try:
        return float(t)
    except ValueError:
        return None


def _date(t):
    for f in ("%d. %B %Y", "%d %B %Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(t.strip(), f).date().isoformat()
        except ValueError:
            pass
    return None


def parse_westmetall(html):
    """Latest LME cash prices and LME stocks from the market-data page."""
    txt = re.sub(r"<[^>]+>", "|", html)
    txt = re.sub(r"&nbsp;|&#160;", " ", txt)
    txt = re.sub(r"\|\s*\|+", "|", txt)
    px, stk, d_px, d_stk = {}, {}, None, None
    m = re.search(r"Official LME-Prices[^|]*\|\s*([0-9]{1,2}\. [A-Za-z]+ 20\d\d)", txt)
    if m:
        d_px = _date(m.group(1))
    m2 = re.search(r"LME Stocks[^|]*\|\s*([0-9]{1,2}\. [A-Za-z]+ 20\d\d)", txt)
    if m2:
        d_stk = _date(m2.group(1))
    a = txt.find("Official LME-Prices")
    b = txt.find("LME Stocks")
    e = txt.find("EUR/USD", b if b > 0 else 0)
    for metal in METALS:
        if a >= 0:
            m = re.search(rf"\|\s*{metal}\s*\|\s*([0-9.,]+)\s*\|", txt[a:b if b > a else None])
            if m:
                px[metal] = _num(m.group(1))
        if b >= 0:
            m = re.search(rf"\|\s*{metal}\s*\|\s*([0-9.,]+)\s*\|", txt[b:e if e > b else None])
            if m:
                stk[metal] = _num(m.group(1))
    return d_px, px, d_stk, stk


SYM = {"Copper": "Cu", "Aluminium": "Al", "Zinc": "Zn", "Nickel": "Ni", "Lead": "Pb", "Tin": "Sn"}


def backfill(d, sess):
    """Once: the last months of prices and stocks from Westmetall's per-metal history tables, so the 1-month
    changes work from day one."""
    if d.get("backfilled", 0) >= 2:
        return
    got = 0
    for metal, sym in SYM.items():
        rec = d["lme"].setdefault(metal, {"px": [], "stk": []})
        for key, field in (("px", f"LME_{sym}_cash"), ("stk", f"LME_{sym}_stock")):
            try:
                r = sess.get(URL, params={"action": "table", "field": field}, timeout=30)
                if r.status_code != 200:
                    continue
                txt = re.sub(r"<[^>]+>", "|", r.text)
                rows = re.findall(r"\|\s*([0-9]{1,2}\. [A-Za-z]+ 20\d\d)\s*\|+\s*([0-9][0-9.,]*)\s*\|", txt)
                pts = {}
                for day, val in rows:
                    dd, v = _date(day), _num(val)
                    if dd and v and dd >= (dt.date.today() - dt.timedelta(days=400)).isoformat():
                        pts[dd] = v
                if pts:
                    have = {x[0]: x[1] for x in rec[key]}
                    have.update({k: v for k, v in pts.items() if k not in have})
                    rec[key] = sorted([[k, v] for k, v in have.items()])[-400:]
                    got += 1
            except Exception:
                continue
    d["backfilled"] = d.get("backfilled", 0) + 1 if not got else 2
    say(f"  LME history: {got} of 12 tables read")


def fetch_lme(d):
    try:
        sess = C.cffi.Session(impersonate="chrome") if getattr(C, "cffi", None) is not None else None
        if sess is None:
            import requests
            sess = requests.Session()
            sess.headers["User-Agent"] = "Mozilla/5.0"
        r = sess.get(URL, timeout=30)
        if r.status_code != 200:
            say(f"  LME prices: HTTP {r.status_code}")
            return 0
        d_px, px, d_stk, stk = parse_westmetall(r.text)
        backfill(d, sess)
    except Exception as e:
        say(f"  LME prices: {str(e)[:100]}")
        return 0
    n = 0
    for metal in METALS:
        rec = d["lme"].setdefault(metal, {"px": [], "stk": []})
        for key, day, val in (("px", d_px, px.get(metal)), ("stk", d_stk, stk.get(metal))):
            if day and val:
                rows = [x for x in rec[key] if x[0] != day] + [[day, val]]
                rec[key] = sorted(rows)[-400:]
                n += 1
    say(f"  LME prices & stocks: {len(px)} prices ({d_px}), {len(stk)} stock levels ({d_stk})")
    return n


def _chg(rows, days):
    """% change over ~days calendar days, from the latest point."""
    if len(rows) < 2:
        return None
    last_d, last = rows[-1]
    target = (dt.date.fromisoformat(last_d) - dt.timedelta(days=days)).isoformat()
    old = [r for r in rows if r[0] <= target]
    if not old:
        return None
    base = old[-1][1]
    return round(100 * (last / base - 1), 1) if base else None


def flags(d, markets):
    out = []

    def add(name, wk, mo, extra="", stk_mo=None):
        gain, hurt = INDIA.get(name, ("", ""))
        if not (gain or hurt):
            return
        big_w = wk is not None and abs(wk) >= MOVE_W
        big_m = mo is not None and abs(mo) >= MOVE_M
        big_s = stk_mo is not None and abs(stk_mo) >= STOCK_M
        if not (big_w or big_m or big_s):
            return
        up = (mo if big_m else wk if big_w else 0) or 0
        tight = None
        if big_s:
            tight = stk_mo < 0  # stocks drawing = tightening
        if up > 0 or (up == 0 and tight):
            read = (f"helps {gain}" if gain else "") + ("; " if gain and hurt else "") + (f"costs up for {hurt}" if hurt else "")
            tone = "+"
        else:
            read = (f"hurts {gain}" if gain else "") + ("; " if gain and hurt else "") + (f"relief for {hurt}" if hurt else "")
            tone = "-"
        bits = []
        if wk is not None:
            bits.append(f"{wk:+.1f}% in a week")
        if mo is not None:
            bits.append(f"{mo:+.1f}% in a month")
        if stk_mo is not None and big_s:
            bits.append(f"LME stocks {stk_mo:+.0f}% in a month ({'drawing - tightening' if stk_mo < 0 else 'building - loosening'})")
        out.append({"name": name, "move": ", ".join(bits), "read": read, "tone": tone, "extra": extra,
                    "score": max(abs(wk or 0) / MOVE_W, abs(mo or 0) / MOVE_M, abs(stk_mo or 0) / STOCK_M if big_s else 0)})

    for metal, rec in d["lme"].items():
        add(metal, _chg(rec["px"], 7), _chg(rec["px"], 30), stk_mo=_chg(rec["stk"], 30))
    seen = {f["name"] for f in out} | set(d["lme"])
    for s in markets.get("series", []):
        if s.get("name") in INDIA and s["name"] not in seen and s.get("name") not in ("Copper", "Aluminium"):
            pts = s.get("pts") or s.get("data") or []
            if pts and isinstance(pts[0], list):
                add(s["name"], _chg(pts, 7), _chg(pts, 30))
    out.sort(key=lambda f: -f["score"])
    return out[:8]


def board(d, markets):
    """Rows for the board: LME metals (price, week, month, stocks, stock change) - the inventory view."""
    rows = []
    for metal in METALS:
        rec = d["lme"].get(metal)
        if not rec or not rec["px"]:
            continue
        rows.append({"name": metal, "px": rec["px"][-1][1], "d": rec["px"][-1][0], "wk": _chg(rec["px"], 7),
                     "mo": _chg(rec["px"], 30), "stk": rec["stk"][-1][1] if rec["stk"] else None,
                     "stk_wk": _chg(rec["stk"], 7), "stk_mo": _chg(rec["stk"], 30), "days": len(rec["px"]),
                     "gain": INDIA.get(metal, ("", ""))[0], "hurt": INDIA.get(metal, ("", ""))[1]})
    return rows


def step():
    d = load()
    fetch_lme(d)
    try:
        import trackers
        markets = trackers.load(trackers.MARKET_FILE, {"series": []})
    except Exception:
        markets = {"series": []}
    d["flags"] = flags(d, markets)
    d["board"] = board(d, markets)
    d["at"] = dt.datetime.now().isoformat(timespec="minutes")
    FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    say(f"  commodity flags: {len(d['flags'])}" + (": " + "; ".join(f"{f['name']} {f['move']}" for f in d["flags"][:4]) if d["flags"] else ""))
    return d


if __name__ == "__main__":
    step()
