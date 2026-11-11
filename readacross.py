"""Read-across: what big companies' concalls signal for smaller listed players.

A large company says a trend out loud (TCS: "AI deals are picking up") and smaller companies exposed to it
re-rate (Datamatics). For each new concall of a large company, the AI pulls out its read-across signals:
the trend, tailwind or headwind, who it touches, and words a smaller exposed company would use.
The exposed companies are then found in OUR data - same industry, or their own concall summaries mention the
same thing - so the AI never invents a list of stocks. Each match carries the line from its own summary.

Later, the matched stocks' move since the signal is compared with the Nifty (does the read-across work?).

  data/readacross.json  {"done": {call id: date}, "items": [...], "px": {symbol: {date: close}}}
"""
import datetime as dt
import json
import re
import time

import concalls as C
import industries as I
from concalls import say

FILE = C.DATA / "readacross.json"

# Nifty 100 and industry leaders - the companies whose concalls set the tone for their space
LEADERS = """Reliance Industries|HDFC Bank|ICICI Bank|Infosys|Tata Consultancy Services|Bharti Airtel|ITC|State Bank of India|
Larsen & Toubro|Kotak Mahindra Bank|Axis Bank|Hindustan Unilever|Bajaj Finance|Bajaj Finserv|Maruti Suzuki|Mahindra & Mahindra|
Sun Pharmaceutical|HCL Technologies|Titan Company|Asian Paints|UltraTech Cement|NTPC|Power Grid Corporation|Tata Motors|Tata Steel|
JSW Steel|Hindalco Industries|Oil & Natural Gas Corporation|Coal India|Adani Ports|Adani Enterprises|Nestle India|Wipro|Tech Mahindra|
Cipla|Dr Reddys Laboratories|Grasim Industries|Eicher Motors|Hero MotoCorp|Bajaj Auto|Shriram Finance|Trent|Bharat Electronics|
SBI Life Insurance|HDFC Life Insurance|Apollo Hospitals|Tata Consumer Products|IndusInd Bank|Jio Financial Services|Eternal|
InterGlobe Aviation|Max Healthcare|Hindustan Aeronautics|Vedanta|Hindustan Zinc|DLF|Avenue Supermarts|Varun Beverages|Godrej Consumer|
Britannia Industries|Pidilite Industries|Siemens|ABB India|Divis Laboratories|LTIMindtree|Persistent Systems|Coforge|Mphasis|
Adani Green Energy|Adani Power|Tata Power|Bank of Baroda|Punjab National Bank|Canara Bank|Life Insurance Corporation|Dabur India|
Marico|Colgate Palmolive|Havells India|Polycab India|Dixon Technologies|Cummins India|Bharat Heavy Electricals|Bharat Forge|
TVS Motor|Samvardhana Motherson|Bosch|MRF|Ambuja Cements|Shree Cement|Info Edge|Zydus Lifesciences|Lupin|Torrent Pharmaceuticals|
Aurobindo Pharma|Indian Hotels|Godrej Properties|Lodha|Indian Oil Corporation|Bharat Petroleum|GAIL|Cholamandalam Investment|
Muthoot Finance|ICICI Lombard|PB Fintech|Kaynes Technology|Waaree Energies|Premier Energies|Suzlon Energy|Inox Wind|
Solar Industries|Bharat Dynamics|Mazagon Dock|Cochin Shipyard|KPIT Technologies|Tata Elxsi|Page Industries|United Spirits|
Jubilant FoodWorks|Zomato|Nykaa|Paytm|Delhivery|Container Corporation|Astral|Supreme Industries|APL Apollo Tubes|
JSW Energy|NHPC|SJVN|Torrent Power|CG Power|Hitachi Energy|GE Vernova T&D|Thermax|KEI Industries""".replace("\n", "")
LEADERS = [x.strip() for x in LEADERS.split("|") if x.strip()]

PROMPT = """You are an Indian equity analyst. Below are concall summaries of LARGE companies. Market participants
read such calls for READ-ACROSS: a trend the big company describes that will help or hurt SMALLER listed companies
(e.g. TCS says AI deal wins are rising -> smaller AI / data / automation IT firms; Maruti says rural demand is
recovering -> tractor, two-wheeler and rural lenders; a cement major says prices are falling -> smaller cement makers).

For each company give up to 3 signals, only from what the summary says (no general knowledge), only if the trend
plausibly matters for OTHER listed companies (skip company-specific events like a plant fire or a CEO change):
SIG | <id> | tailwind/headwind | <the trend, with the big company's own number if any, max 20 words> | <who else it touches, in plain words, max 14 words> | <industries it touches: 1-4 names copied EXACTLY from the INDUSTRIES list, separated by ;> | <4-8 SPECIFIC lowercase phrases a smaller exposed company would itself use in its concall (e.g. "genai", "ai deals", "data centre", "titanium dioxide") - never generic words like "raw material", "demand", "costs", "growth", "automation">

No other text.

INDUSTRIES:
{inds}

SUMMARIES:
{items}
"""

SECTIONS = ("Highlights", "Demand & industry commentary", "Guidance & outlook", "Costs, margins & raw materials",
            "Capex, capacity & expansion", "Notable analyst Q&A")


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"done": {}, "items": [], "px": {}}


def save(d):
    FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _section(md, name, cap):
    m = re.search(r"###\s*" + re.escape(name) + r"[^\n]*\n(.*?)(?=\n###\s|\n---|\Z)", md, re.S | re.I)
    return m.group(1).strip()[:cap] if m else ""


def _read(call):
    f = C.here(call["summary"]) if call.get("summary") else None
    return f.read_text(encoding="utf-8") if f and f.exists() else ""


def is_leader(name):
    from names import same
    return any(same(name, x) for x in LEADERS)


GENERIC_KW = {"raw material", "raw materials", "demand", "costs", "cost", "growth", "automation", "margins", "margin",
              "input costs", "pricing", "price hike", "capex", "orders", "revenue", "volume", "volumes", "digital", "technology"}
GENERIC = {"companies", "company", "firms", "players", "smaller", "small", "sector", "sectors", "industry", "industries",
            "other", "listed", "services", "products", "makers", "manufacturers", "suppliers", "related", "&"}


def _words(t):
    return set(re.findall(r"[a-z][a-z0-9&\-]{3,}", t.lower()))


def match(lib, sig, src_code, texts, inds):
    """Smaller companies exposed to a signal: their own latest concall mentions the same thing, or same industry.
    Each match keeps the sentence from its own summary as evidence."""
    kws = [k.strip().lower() for k in sig["keywords"] if len(k.strip()) >= 3][:8]
    out = []
    for code, (call, text) in texts.items():
        if code == src_code or is_leader(call["company"]):
            continue
        low = text.lower()
        hits = [k for k in kws if re.search(r"(?<![a-z])" + re.escape(k) + r"(?![a-z])", low)]
        ind = inds.get(code, "")
        # in an industry the signal touches AND its own call talks about the same thing
        # (an insurer saying "genai" isn't an IT read-across; an IT firm that never mentions AI isn't either)
        if ind not in sig["inds"] or not hits:
            continue
        score = 2 * len(hits) + 1
        why = ""
        for k in hits:
            m = re.search(r"[^.\n]*" + re.escape(k) + r"[^.\n]*", text, re.I)
            if m:
                why = re.sub(r"[*#>`]", "", m.group(0)).strip()[:180]
                break
        out.append({"company": call["company"], "code": code, "kw": hits[:3], "ind": ind, "why": why,
                    "q": call.get("quarter", ""), "score": score})
    out.sort(key=lambda m: -m["score"])
    return out[:8]


def step(lib, pool, limit=12):
    """New read-across signals from large companies' latest calls (at most `limit` calls per run)."""
    d = load()
    latest = C.latest_per_company(list(lib["calls"].values()))
    todo = [c for c in latest if c.get("summary") and c["id"] not in d["done"] and is_leader(c["company"])]
    todo.sort(key=lambda c: c["date"], reverse=True)
    seen = set()
    todo = [c for c in todo if not (C.norm(c["company"]) in seen or seen.add(C.norm(c["company"])))]
    todo = todo[:limit]
    if not todo:
        return 0
    say(f"\nRead-across: reading {len(todo)} large-company calls ...")
    texts = {c["code"]: (c, _read(c)) for c in latest if c.get("summary")}
    inds = lib.get("industries", {})
    added = 0
    for i in range(0, len(todo), 4):
        part = todo[i:i + 4]
        items = "\n\n".join(f"=== id {n}: {c['company']} ({c.get('quarter', '')})\n" + "\n".join(
            f"[{s}]\n{_section(texts.get(c['code'], (c, ''))[1], s, 1200)}" for s in SECTIONS
            if _section(texts.get(c["code"], (c, ""))[1], s, 1200)) for n, c in enumerate(part, 1))
        try:
            out, ai = pool.ask(PROMPT.format(items=items, inds="; ".join(I.PARENT)), label="read-across", max_wait=60)
        except C.AIError as e:
            say(f"  stopped: {str(e)[:100]}")
            break
        for line in out.splitlines():
            p = [x.strip(" *`") for x in line.split("|")]
            if len(p) < 7 or p[0].upper() != "SIG" or p[2].lower() not in ("tailwind", "headwind"):
                continue
            try:
                c = part[int(re.sub(r"\D", "", p[1])) - 1]
            except (ValueError, IndexError):
                continue
            want = {x.strip().lower() for x in p[5].split(";")}
            sig = {"dir": p[2].lower(), "trend": p[3][:200], "who": p[4][:140],
                   "inds": [k for k in I.PARENT if k.lower() in want][:4],
                   "keywords": [k.strip() for k in p[6].split(",") if k.strip() and k.strip().lower() not in GENERIC_KW][:8]}
            if not sig["inds"]:
                continue
            ms = match(lib, sig, c["code"], texts, inds)
            uid = f"{c['id']}|{re.sub(r'[^a-z0-9]', '', sig['trend'].lower())[:30]}"
            if any(x["uid"] == uid for x in d["items"]):
                continue
            d["items"].append(dict(sig, uid=uid, date=c["date"], src=c["company"], src_code=c["code"],
                                   quarter=c.get("quarter", ""), sector=C.sector_of(lib, c), matches=ms))
            added += 1
        for c in part:
            d["done"][c["id"]] = c["date"]
        save(d)
    d["items"].sort(key=lambda x: x["date"], reverse=True)
    save(d)
    say(f"  read-across: {added} signals")
    return added


def outcomes(max_symbols=40):
    """How the matched stocks moved since each signal, against the Nifty (signals 1-90 days old)."""
    d = load()
    import requests
    from backstory import find_symbol
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0"
    today = dt.date.today()
    px, used = d.setdefault("px", {}), 0

    def closes(sym):
        nonlocal used
        got = px.get(sym)
        if got and got.get("_at") == today.isoformat():
            return got
        if used >= max_symbols:
            return got
        used += 1
        try:
            r = sess.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                         params={"range": "6mo", "interval": "1d"}, timeout=20)
            res = r.json()["chart"]["result"][0]
            cl = res["indicators"]["quote"][0]["close"]
            m = {dt.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d"): round(c, 2) for t, c in zip(res["timestamp"], cl) if c}
            m["_at"] = today.isoformat()
            px[sym] = m
            time.sleep(0.5)
            return m
        except Exception:
            return got

    def ret(m, since):
        if not m:
            return None
        days = sorted(k for k in m if k != "_at")
        start = next((k for k in days if k >= since), None)
        if not start or start == days[-1]:
            return None
        return round(100 * (m[days[-1]] / m[start] - 1), 1)

    nifty = closes("^NSEI")
    syms = d.setdefault("sym", {})
    for it in d["items"]:
        age = (today - dt.date.fromisoformat(it["date"])).days
        if not 1 <= age <= 90:
            continue
        it["nifty"] = ret(nifty, it["date"])
        for m in it["matches"]:
            if m["code"] not in syms:
                syms[m["code"]] = find_symbol(sess, m["company"], m["code"])
            r = ret(closes(syms[m["code"]]), it["date"])
            if r is not None:
                m["ret"] = r
    save(d)
