#!/usr/bin/env python3
"""
Trackers built on top of the news brief, kept between runs in data/:
  trackers.json  - quarterly results, order wins, brokerage calls, dated events (from the news, by AI),
                   plus the results calendar (board meetings filed on BSE)
  markets.json   - daily prices for indices, commodities, the rupee and yields (free, from Yahoo Finance)
  weekly.json    - the Sunday "week in review"
AI cost: one extraction request per ~50 NEW market stories (stories already read are remembered),
and one request a week for the review. Prices and the BSE calendar use no AI.
"""
import datetime as dt
import json
import re
import time

import concalls as C

say = C.say
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
TRACK_FILE = C.DATA / "trackers.json"
MARKET_FILE = C.DATA / "markets.json"
WEEKLY_FILE = C.DATA / "weekly.json"
KEEP_DAYS = 120

CANDIDATE = re.compile(
    r"result|profit|revenue|net loss|ebitda|\bq[1-4]\b|quarter|order|contract|bags|wins|\bbid\b|tender|target"
    r"|\bbuy\b|\bsell\b|upgrade|downgrade|initiat|overweight|underweight|outperform|brokerage|rating"
    r"|\bipo\b|policy|meeting|\bcpi\b|\bgdp\b|inflation|next week|scheduled|record date|to announce|due on"
    r"|board meet|\bfed\b|budget|auction|listing", re.I)

EXTRACT_PROMPT = """You read Indian market news and pull out hard facts into a fixed format. Today is {today}.
Below are news stories, each with an id in brackets, a headline and sometimes a short description.

For each story that contains one of these facts, write one line in exactly one of these formats
(fields separated by " | ", use - when a field isn't stated):

RESULT | id | company | quarter (like Q2 FY27) | revenue Rs crore | revenue YoY % | net profit Rs crore | profit YoY % | read: strong / weak / mixed / in-line
ORDER | id | company | order value Rs crore | client or awarding body | what the order is for (max 8 words)
CALL | id | brokerage | company | rating (Buy / Sell / Hold / Add / Reduce / Neutral) | target price Rs | action (upgrade / downgrade / initiate / maintain / raise target / cut target)
EVENT | id | date YYYY-MM-DD | what happens (max 10 words: RBI policy, CPI data, IPO opens, Fed decision, results of a company...)

Rules:
- Only facts the story states. Never guess numbers. A company name must be the listed company.
- Convert amounts to Rs crore (1 lakh crore = 100000 crore; USD at Rs {fx}/$, EUR at Rs {eur}/EUR).
- Numbers only in number fields (no "Rs", "cr" or "%"). A loss is a negative profit.
- EVENT only for things happening on or after today with a clear date.
- A story can give several lines (e.g. two brokerages). Stories with none of these facts: write nothing.
- Output only the lines, nothing else.

STORIES:
"""

REVIEW_PROMPT = """You are a senior Indian equity strategist. Below are the "big picture" notes from each morning brief
of the past week ({start} to {end}), oldest first. Write the WEEK IN REVIEW in Markdown, using only these notes.

**The week in one line:** <...>
### What moved markets
(4-6 bullets)
### Stories that developed during the week
(bullets: how each big story evolved from first report to now)
### Sectors: who gained, who lost
(bullets)
### Into next week
(bullets: what to watch)

NOTES:
"""


def num(x):
    if x is None:
        return None
    t = str(x).replace(",", "").replace("Rs", "").replace("₹", "").replace("%", "").replace("cr", "").strip()
    t = t.replace("crore", "").strip()
    m = re.match(r"^[+-]?\d+(?:\.\d+)?$", t)
    return float(t) if m else None


def load(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default
    except ValueError:
        return default


# ============================================================================ news extraction

def parse_lines(text, ids):
    out = []
    for line in text.splitlines():
        parts = [p.strip() for p in line.strip().lstrip("-* ").split("|")]
        if len(parts) < 4:
            continue
        kind = parts[0].upper()
        sid = re.sub(r"\D", "", parts[1])
        if kind not in ("RESULT", "ORDER", "CALL", "EVENT") or not sid or int(sid) not in ids:
            continue
        out.append([kind, int(sid)] + parts[2:])
    return out


def extract(stories, pool, cache):
    """Sends only stories not read before; remembers the lines per story."""
    known = cache.setdefault("extract", {})
    fx = market_fx()
    todo = [s for s in stories if s["key"] not in known and CANDIDATE.search(s["title"] + " " + s.get("desc", ""))]
    for s in stories:
        if s["key"] not in known and s not in todo:
            known[s["key"]] = []
    if todo:
        say(f"\nPulling results, orders, broker calls and dates out of {len(todo)} new stories ...")
    today = dt.datetime.now(IST).strftime("%Y-%m-%d (%A)")
    for i in range(0, len(todo), 50):
        batch = todo[i:i + 50]
        rows = "\n".join(f"[{s['id']}] {s['title']}" + (f" - {s['desc'][:220]}" if s.get("desc") else "")
                         for s in batch)
        try:
            text, _ = pool.ask(EXTRACT_PROMPT.format(today=today, fx=fx["usd"], eur=fx["eur"]) + rows,
                               label=f"extracting facts {i + 1}-{i + len(batch)} of {len(todo)}")
        except C.QuotaOver as e:
            say(f"  {e}")
            break
        except C.AIError as e:
            say(f"  extraction failed: {e}")
            continue
        got = parse_lines(text, {s["id"] for s in batch})
        for s in batch:
            known[s["key"]] = [g[:1] + g[2:] for g in got if g[1] == s["id"]]
        time.sleep(pool.pause)


def sector_for(story, lib_sectors_by_name, company):
    if story["category"] in C.SECTORS:
        return story["category"]
    return lib_sectors_by_name.get(C.norm(company), "")


def update(stories, pool, cache, now_utc):
    extract(stories, pool, cache)
    data = load(TRACK_FILE, {})
    for k in ("results", "orders", "calls", "events", "calendar"):
        data.setdefault(k, [])
    lib = C.load_lib()
    by_name = {}
    for c in lib["calls"].values():
        sec = lib["sectors"].get(c["code"])
        if sec:
            by_name[C.norm(c["company"])] = sec
    idx = {k: {r["uid"]: r for r in data[k]} for k in ("results", "orders", "calls", "events")}
    added = 0
    for s in stories:
        lines = cache["extract"].get(s["key"]) or []
        if not lines:
            continue
        base = {"date": s["when"].astimezone(IST).strftime("%Y-%m-%d"), "title": s["title"][:200],
                "link": s["sources"][0]["link"] if s["sources"] else ""}
        for p in lines:
            p = p + ["-"] * 8
            kind = p[0]
            if kind == "RESULT":
                co = p[1]
                rec = dict(base, company=co, quarter=p[2] if p[2] != "-" else "", revenue=num(p[3]),
                           rev_yoy=num(p[4]), profit=num(p[5]), pat_yoy=num(p[6]),
                           read=p[7].lower().replace("read:", "").strip() if p[7] != "-" else "",
                           sector=sector_for(s, by_name, co))
                uid = f"R|{C.norm(co)}|{rec['quarter'].lower().replace(' ', '')}"
                if all(rec[k] is None for k in ("revenue", "rev_yoy", "profit", "pat_yoy")):
                    continue
                old = idx["results"].get(uid)
                if old:  # fill gaps from a later story
                    for k, v in rec.items():
                        if old.get(k) in (None, "") and v not in (None, ""):
                            old[k] = v
                    continue
            elif kind == "ORDER":
                co = p[1]
                rec = dict(base, company=co, value=num(p[2]), client=p[3] if p[3] != "-" else "",
                           what=p[4] if p[4] != "-" else "", sector=sector_for(s, by_name, co))
                uid = f"O|{C.norm(co)}|{rec['value']}|{base['date']}"
                if any(u.startswith(f"O|{C.norm(co)}|{rec['value']}|") for u in idx["orders"]) and rec["value"]:
                    continue
            elif kind == "CALL":
                co = p[2]
                rec = dict(base, broker=p[1], company=co, rating=p[3].title() if p[3] != "-" else "",
                           target=num(p[4]), action=p[5].lower() if p[5] != "-" else "",
                           sector=sector_for(s, by_name, co))
                uid = f"C|{C.norm(p[1])}|{C.norm(co)}|{base['date']}"
            else:  # EVENT
                d = p[1]
                if not re.match(r"^\d{4}-\d{2}-\d{2}$", d):
                    continue
                rec = dict(base, when=d, what=p[2] if p[2] != "-" else "")
                uid = f"E|{d}|{re.sub(r'[^a-z0-9]', '', rec['what'].lower())[:40]}"
                if not rec["what"]:
                    continue
            if uid in idx[{"RESULT": "results", "ORDER": "orders", "CALL": "calls", "EVENT": "events"}[kind]]:
                continue
            rec["uid"] = uid
            idx[{"RESULT": "results", "ORDER": "orders", "CALL": "calls", "EVENT": "events"}[kind]][uid] = rec
            added += 1
    cutoff = (now_utc.astimezone(IST) - dt.timedelta(days=KEEP_DAYS)).strftime("%Y-%m-%d")
    today = now_utc.astimezone(IST).strftime("%Y-%m-%d")
    for k in ("results", "orders", "calls"):
        data[k] = sorted([r for r in idx[k].values() if r["date"] >= cutoff], key=lambda r: r["date"], reverse=True)
    past = (now_utc.astimezone(IST) - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    data["events"] = sorted([r for r in idx["events"].values() if r["when"] >= past], key=lambda r: r["when"])
    say(f"  trackers: {added} new facts · {len(data['results'])} results, {len(data['orders'])} orders, "
        f"{len(data['calls'])} broker calls, {len([e for e in data['events'] if e['when'] >= today])} upcoming events")
    data["updated"] = now_utc.astimezone(IST).isoformat(timespec="minutes")
    C.DATA.mkdir(parents=True, exist_ok=True)
    TRACK_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


# ============================================================================ results calendar (BSE)

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def meeting_date(text):
    t = re.sub(r"\s+", " ", text)
    m = re.search(r"(?:held|scheduled|convened|on|dated)\s*(?:on\s*)?(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})", t, re.I)
    if m:
        d, mo, y = map(int, m.groups())
        try:
            return dt.date(y, mo, d)
        except ValueError:
            return None
    m = re.search(r"(?:held|scheduled|convened|\bon)\s*(?:on\s*)?(?:\w+day,?\s*)?(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]{3,9}),?\s+(\d{4})",
                  t, re.I)
    if m and m.group(2)[:3].lower() in MONTHS:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"(?:held|scheduled|\bon)\s*(?:on\s*)?(?:\w+day,?\s*)?([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})", t, re.I)
    if m and m.group(1)[:3].lower() in MONTHS:
        try:
            return dt.date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2)))
        except ValueError:
            return None
    return None


def update_calendar(days=10):
    """Board meetings called to approve results, from BSE filings. Once every ~6 hours."""
    data = load(TRACK_FILE, {})
    data.setdefault("calendar", [])
    now = dt.datetime.now(IST)
    last = data.get("calendar_fetched", "")
    if last and now.isoformat() < (dt.datetime.fromisoformat(last) + dt.timedelta(hours=6)).isoformat():
        return
    to = now.date()
    rows = C.bse_query(to - dt.timedelta(days=days), to, "-1", cat="Board Meeting")
    lib = C.load_lib()
    seen = {r["uid"]: r for r in data["calendar"]}
    for row in rows:
        text = " ".join(str(row.get(k) or "") for k in ("NEWSSUB", "HEADLINE", "MORE"))
        if not re.search(r"result", text, re.I):
            continue
        d = meeting_date(text)
        if not d or d < to - dt.timedelta(days=3) or d > to + dt.timedelta(days=60):
            continue
        code = str(row.get("SCRIP_CD"))
        uid = f"{code}|{d}"
        seen[uid] = {"uid": uid, "code": code, "company": (row.get("SLONGNAME") or "").strip() or code,
                     "when": d.isoformat(), "sector": lib["sectors"].get(code, "")}
    keep = (to - dt.timedelta(days=3)).isoformat()
    data["calendar"] = sorted([r for r in seen.values() if r["when"] >= keep], key=lambda r: (r["when"], r["company"]))
    data["calendar_fetched"] = now.isoformat(timespec="minutes")
    TRACK_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    say(f"  results calendar: {len([r for r in data['calendar'] if r['when'] >= to.isoformat()])} upcoming board meetings")


# ============================================================================ prices (no AI)

# symbol, name, group, unit, sectors it matters for (and how)
SERIES = [
    ("^NSEI", "Nifty 50", "India indices", "pts", ""),
    ("^NSEBANK", "Nifty Bank", "India indices", "pts", "Banks"),
    ("^CNXIT", "Nifty IT", "India indices", "pts", "IT & Software"),
    ("^CNXAUTO", "Nifty Auto", "India indices", "pts", "Automobiles"),
    ("^CNXPHARMA", "Nifty Pharma", "India indices", "pts", "Pharma & Healthcare Products"),
    ("^CNXFMCG", "Nifty FMCG", "India indices", "pts", "FMCG & Food"),
    ("^CNXMETAL", "Nifty Metal", "India indices", "pts", "Metals & Mining"),
    ("^CNXREALTY", "Nifty Realty", "India indices", "pts", "Real Estate"),
    ("^CNXENERGY", "Nifty Energy", "India indices", "pts", "Oil & Gas"),
    ("^CNXINFRA", "Nifty Infra", "India indices", "pts", "Construction & Infrastructure"),
    ("^CNXPSUBANK", "Nifty PSU Bank", "India indices", "pts", "Banks"),
    ("NIFTY_MIDCAP_100.NS", "Nifty Midcap 100", "India indices", "pts", ""),
    ("^CNXSC", "Nifty Smallcap 100", "India indices", "pts", ""),
    ("BZ=F", "Brent crude", "Energy", "$/bbl", "Oil & Gas: refiners & OMCs gain when it falls; paints, tyres, aviation, chemicals use it as raw material"),
    ("NG=F", "Natural gas (US)", "Energy", "$/MMBtu", "Fertilisers & Agrochemicals, city gas, Power & Utilities"),
    ("CT=F", "Cotton", "Agri", "US¢/lb", "Textiles & Apparel: cotton is the main raw material for spinners"),
    ("SB=F", "Sugar", "Agri", "US¢/lb", "Agri & Sugar: export realisations of sugar mills"),
    ("ZW=F", "Wheat", "Agri", "US¢/bu", "FMCG & Food: flour-based food makers"),
    ("KC=F", "Coffee", "Agri", "US¢/lb", "FMCG & Food: coffee plantation & beverage companies"),
    ("HRC=F", "Steel (US hot-rolled coil)", "Metals", "$/t", "Metals & Mining (steel makers); Automobiles, Capital Goods, Consumer Durables use steel"),
    ("HG=F", "Copper", "Metals", "$/lb", "Metals & Mining (Hindustan Copper, Vedanta); Electrical & Electronics, cables, wires"),
    ("ALI=F", "Aluminium", "Metals", "$/t", "Metals & Mining (Hindalco, Nalco, Vedanta); Auto Components, packaging"),
    ("GC=F", "Gold", "Metals", "$/oz", "Jewellery retailers, gold-loan NBFCs (Muthoot, Manappuram)"),
    ("SI=F", "Silver", "Metals", "$/oz", "Hindustan Zinc; solar & electronics"),
    ("INR=X", "US dollar / rupee", "Currency & rates", "Rs per $", "IT & Software and Pharma export earnings rise with a weaker rupee; importers and Oil & Gas lose"),
    ("EURINR=X", "Euro / rupee", "Currency & rates", "Rs per €", "Exporters to Europe: textiles, auto components, chemicals"),
    ("DX-Y.NYB", "Dollar index", "Currency & rates", "index", "A strong dollar usually means FII outflows from India"),
    ("^TNX", "US 10-year yield", "Currency & rates", "%", "Higher US yields pull money out of emerging markets; IT valuations"),
    ("^GSPC", "S&P 500", "Global", "pts", "IT & Software (US clients), global risk mood"),
    ("^IXIC", "Nasdaq", "Global", "pts", "IT & Software"),
    ("^HSI", "Hang Seng", "Global", "pts", "China demand for metals & chemicals"),
]


def _session():
    if C.cffi is not None:
        return C.cffi.Session(impersonate="chrome")
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = C.BROWSER_HEADERS.get("User-Agent", "Mozilla/5.0")
    return s


def fetch_one(sess, sym):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
    for host in ("query1", "query2"):
        try:
            r = sess.get(url.replace("query1", host), params={"range": "1y", "interval": "1d"}, timeout=25)
            if r.status_code != 200:
                continue
            res = r.json()["chart"]["result"][0]
            ts = res.get("timestamp") or []
            closes = res["indicators"]["quote"][0].get("close") or []
            pts = [[dt.datetime.fromtimestamp(t, IST).strftime("%Y-%m-%d"), round(c, 4)]
                   for t, c in zip(ts, closes) if c is not None]
            if len(pts) > 5:
                return pts
        except Exception:
            continue
    return None


def update_markets():
    old = load(MARKET_FILE, {"series": []})
    prev = {s["sym"]: s for s in old.get("series", [])}
    sess = _session()
    out, ok = [], 0
    for sym, name, group, unit, note in SERIES:
        pts = fetch_one(sess, sym)
        if pts:
            ok += 1
        elif sym in prev:
            pts = prev[sym]["pts"]
        else:
            continue
        out.append({"sym": sym, "name": name, "group": group, "unit": unit, "note": note, "pts": pts})
        time.sleep(0.3)
    if ok:
        MARKET_FILE.write_text(json.dumps({"updated": dt.datetime.now(IST).isoformat(timespec="minutes"),
                                           "series": out}, ensure_ascii=False), encoding="utf-8")
    say(f"  prices: {ok} of {len(SERIES)} series refreshed")


def market_fx():
    d = load(MARKET_FILE, {"series": []})
    fx = {"usd": 88, "eur": 102}
    for s in d.get("series", []):
        if s["sym"] == "INR=X" and s["pts"]:
            fx["usd"] = round(s["pts"][-1][1])
        if s["sym"] == "EURINR=X" and s["pts"]:
            fx["eur"] = round(s["pts"][-1][1])
    return fx


# ============================================================================ week in review

def weekly_review(pool=None):
    """Once a week (first run on/after Sunday 18:00 IST): a review of the week's briefs."""
    now = dt.datetime.now(IST)
    data = load(WEEKLY_FILE, {"reviews": []})
    week_end = (now - dt.timedelta(days=(now.weekday() - 6) % 7)).date()  # the latest Sunday
    if now.weekday() == 6 and now.hour < 18:
        week_end -= dt.timedelta(days=7)
    if any(r["end"] == week_end.isoformat() for r in data["reviews"]):
        return
    start = week_end - dt.timedelta(days=6)
    notes = []
    for i in range(7):
        d = start + dt.timedelta(days=i)
        f = C.DATA / "news" / f"{d.isoformat()}.json"
        if f.exists():
            b = json.loads(f.read_text(encoding="utf-8"))
            text = re.sub(r"<[^>]+>", " ", b.get("big", ""))
            text = re.sub(r"\s+", " ", text).strip()
            if text:
                notes.append(f"### {b['label']}\n{text[:3500]}")
    if len(notes) < 3:
        return
    pool = pool or C.Pool()
    say("\nWriting the week in review ...")
    import news
    text = news.ask_fitted(pool, REVIEW_PROMPT.format(start=start.strftime("%d %b"), end=week_end.strftime("%d %b")),
                           notes, label="week in review")
    one = ""
    m = re.search(r"\*\*The week in one line:\*\*\s*(.+)", text)
    if m:
        one = m.group(1).strip()
        text = text.replace(m.group(0), "")
    data["reviews"] = ([{"end": week_end.isoformat(), "start": start.isoformat(), "one": one,
                         "html": C.md(text)}] + data["reviews"])[:12]
    WEEKLY_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def step(pool=None):
    """Everything here that doesn't depend on today's stories (called from daily.py)."""
    for name, fn in (("prices", update_markets), ("results calendar", update_calendar)):
        try:
            fn()
        except Exception as e:
            say(f"  {name} skipped: {str(e)[:150]}")
    try:
        weekly_review(pool)
    except Exception as e:
        say(f"  week in review skipped: {str(e)[:150]}")
