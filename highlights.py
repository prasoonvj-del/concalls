#!/usr/bin/env python3
"""
Top 10 developments: companies (or industries) where several independent threads line up - news flow, turning
points (capacity, approvals, strategy), orders, results, broker calls, government decisions, what management said
on the concall and whether earlier events followed through, read-across from bigger companies' calls.

How it stays cheap: the linking is done in code. Every company's last ~45 days are scored from data Market Desk
already keeps (data/timeline.json, the concall library, the follow-through file, read-across, the news briefs);
the strongest ~40 "confluences" (2+ different kinds of evidence) go to ONE full-model request a day, which picks
the ten that matter most, groups companies into an industry thread where they show the same thing, and writes the
thread with dated evidence. Only the evidence given can be used.

  data/highlights.json  {"days": {date: [items]}, "at": ...}  (30 days kept: each item knows how many days running
  it has been on the list - a thread that keeps building is itself a signal)
"""
import datetime as dt
import json
import re
import time

import concalls as C

say = C.say
FILE = C.DATA / "highlights.json"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
WINDOW = 45
KEEP_DAYS = 30


def load():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    except ValueError:
        d = {}
    d.setdefault("days", {})
    return d


def today_ist():
    return dt.datetime.now(IST).date().isoformat()


# ============================================================================ evidence, in code

def _pct(t):
    m = re.search(r"\(([+-]?\d+(?:\.\d+)?)%\)", t)
    return float(m.group(1)) if m else None


# news that only reports what the price already did is the market's reaction, not a development
PRICE_NEWS = re.compile(
    r"(?i)\b(shares?|stocks?|scrip)\b.{0,40}\b(fall|falls|fell|drop|drops|slump|slumps|tank|tanks|plunge|plunges|crash|"
    r"rise|rises|rose|jump|jumps|surge|surges|soar|soars|rally|rallies|gain|gains|climb|climbs|zoom|zooms|extend|"
    r"hit|hits|upper circuit|lower circuit|52-week|record high|all-time high)\b|\btop (gainers|losers)\b|"
    r"\bstocks? (to buy|to watch|in focus|in news)\b|\bbuzzing stocks?\b|\bmarket (live|today)\b")
# signals that tend to come BEFORE the numbers (and the price) move
EARLY = {"pivot", "order", "policy", "read-across", "guidance", "initiation", "follow-through"}


def _fresh(d, today):
    age = (today - dt.date.fromisoformat(d[:10])).days
    return 1.0 if age <= 14 else 0.6 if age <= 30 else 0.35


def candidates(lib, limit=40):
    import timeline
    tl = timeline.load()
    cos, names = tl.get("companies", {}), tl.get("names", {})
    today = dt.date.today()
    cut = (today - dt.timedelta(days=WINDOW)).isoformat()
    early_cut = (today - dt.timedelta(days=30)).isoformat()
    cc_cut = (today - dt.timedelta(days=120)).isoformat()
    inds = lib.get("industries") or {}
    latest = {c["code"]: c for c in C.latest_call_each(list(lib["calls"].values())) if c.get("code")}

    # read-across: a bigger company's call pointing at this one
    ra = {}
    try:
        import readacross
        for r in readacross.load().get("items", []):
            if r.get("date", "") >= cut:
                for m in r.get("matches", []):
                    ra.setdefault(m.get("code"), []).append(
                        (r["date"], f"Read-across from {r['src']} ({r['dir']}): {r['trend']} - its own call: {m.get('why', '')[:120]}"))
    except Exception:
        pass
    # news: the last 7 days' briefs, important stories naming the company - not stories about the price itself
    news = {}
    try:
        from names import Resolver
        R = Resolver()
        files = sorted((C.DATA / "news").glob("*.json"))[-7:]
        seen = set()
        for f in files:
            for s in json.loads(f.read_text(encoding="utf-8")).get("stories", []):
                if s.get("imp", 0) < 3 or s.get("sent") not in ("+", "-") or len(s.get("companies") or []) > 2:
                    continue
                if PRICE_NEWS.search(s["title"]):
                    continue
                for nm in s.get("companies") or []:
                    code = R.resolve(nm)[1]
                    k = (code, s["title"][:60])
                    if code and k not in seen:
                        seen.add(k)
                        news.setdefault(code, []).append((s["when"][:10], f"News ({'+' if s['sent'] == '+' else '-'}): {s['title'][:150]}"))
    except Exception:
        pass
    try:
        import watch
        ft = watch.load()["items"]
    except Exception:
        ft = {}

    out = []
    for key in set(cos) | set(news) | set(ra):
        ev, kinds, score, newest_early = [], set(), 0.0, ""
        cnt = {}

        def early(kind, d, w):
            nonlocal score, newest_early
            score += w * _fresh(d, today)
            kinds.add(kind)
            if d >= early_cut:
                newest_early = max(newest_early, d)

        for e in cos.get(key, []):
            if e["d"] < cut or e["k"] in ("concall", "story"):
                continue
            k = e["k"]
            cnt[k] = cnt.get(k, 0) + 1
            if cnt[k] > {"pivot": 3, "order": 2, "deck": 1, "broker": 2}.get(k, 2):
                continue
            if k in ("pivot", "order", "policy"):
                w = {"pivot": 3, "order": 2.5, "policy": 2.5}[k]
                if k == "pivot":  # what kind of turning point: new capacity or a new market leads; a debt repayment doesn't
                    th = e["t"].split(":", 1)[0].lower()
                    w = (3 if re.search(r"capacity|approval|product|launch|order|contract|m&a|acqui|demand|export|market|technology", th)
                         else 1.2 if re.search(r"fund|debt|ipo|qip|raise|legal|management|board|dividend|buyback|rating", th) else 2)
                early(k, e["d"], w)
            elif k == "broker":
                if re.search(r"(?i)initiat|upgrade", e["t"]):
                    early("initiation", e["d"], 1.5)
                else:
                    score += 0.3
                    kinds.add("broker")
            elif k == "result":  # results are reported after the quarter: they confirm, they rarely lead
                p = _pct(e["t"])
                score += (1 if (p is not None and p >= 25) or "strong" in e["t"] else 0.4) * _fresh(e["d"], today)
                kinds.add("result")
            elif k == "deck":
                kinds.add("deck")
            ev.append((e["d"], f"{k.capitalize()}: {e['t'][:170]}"))
            rec = ft.get(e["u"])
            if rec:
                c = watch.latest(rec)
                if c and c["v"] in ("showed", "partly", "reversed"):
                    early("follow-through", c["cd"], 1.5 if c["v"] == "showed" else 0.5)
                    ev.append((c["cd"], f"Follow-through on the {c['q']} call ({c['v']}): {c.get('x', '')[:140]}"))
        c = latest.get(key)
        if c and c["date"] >= cc_cut:
            bits = [f"Concall {c.get('quarter', '')} ({c.get('tone') or '?'})"]
            if c.get("tone") == "Positive":
                score += 0.5
            g = (c.get("metrics") or {}).get("guidance")
            if g in ("raised", "initiated"):
                early("guidance", c["date"], 2.5)
                bits.append(f"guidance {g}")
            ex, dl = (c.get("expect") or {}), (c.get("delivery") or {})
            if ex.get("v"):
                bits.append(f"vs market: {ex['v']} - {ex.get('line', '')[:100]}")
            if dl.get("v"):
                bits.append(f"said vs did: {dl['v']}")
                score += 0.5 if dl["v"] == "delivered" else 0
            one = ""
            for e in cos.get(key, []):
                if e["k"] == "concall" and e["d"] == c["date"]:
                    one = e["t"].split(":", 1)[-1].strip()[:200]
            ev.append((c["date"], " · ".join(bits) + (f": {one}" if one else "")))
            kinds.add("concall")
        for d, t in ra.get(key, [])[:2]:
            early("read-across", d, 2.5)
            ev.append((d, t))
        for i, (d, t) in enumerate(sorted(news.get(key, []), reverse=True)[:3]):
            score += 0.5 if i == 0 else 0  # being in the news a lot is coverage, not a development
            kinds.add("news")
            ev.append((d, t))
        if not newest_early or len(kinds - {"deck"}) < 2:
            continue  # nothing early in the last month, or a single headline: not a thread to get ahead of
        score += 1.5 * (len(kinds & EARLY) - 1) + 0.3 * len(kinds - EARLY - {"deck"})
        name = names.get(key) or (c["company"] if c else key.replace("n:", ""))
        name = re.sub(r"[\s\-$]+$", "", name or "")
        if len(name) < 2:
            continue
        sector = C.sector_of(lib, c) if c else (lib.get("sectors") or {}).get(key, "")
        ev.sort(reverse=True)
        out.append({"key": key, "name": name, "sector": sector or "", "ind": inds.get(key, ""), "score": round(score, 1),
                    "kinds": sorted(kinds), "early": sorted(kinds & EARLY), "since": newest_early, "ev": ev[:9]})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


# ============================================================================ has the price already moved?

def add_moves(cands, store):
    """1-month move vs the Nifty for each candidate (Yahoo daily closes, cached for the day). A thread the price has
    already run with ranks lower than the same thread before the move."""
    import requests
    from backstory import find_symbol
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0"
    today = dt.date.today().isoformat()
    syms, px = store.setdefault("sym", {}), store.setdefault("px", {})
    if px.get("_day") != today:
        px.clear()
        px["_day"] = today

    def ret1m(sym):
        if sym in px:
            return px[sym]
        r = None
        try:
            j = sess.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}",
                         params={"range": "2mo", "interval": "1d"}, timeout=15).json()["chart"]["result"][0]
            cl = [x for x in j["indicators"]["quote"][0]["close"] if x]
            if len(cl) > 22:
                r = round(100 * (cl[-1] / cl[-22] - 1), 1)
        except Exception:
            pass
        px[sym] = r
        time.sleep(0.3)
        return r

    nifty = ret1m("^NSEI")
    for x in cands:
        code = x["key"]
        if not code.isdigit():
            continue
        if code not in syms:
            try:
                syms[code] = find_symbol(sess, x["name"], code)
            except Exception:
                syms[code] = None
        r = ret1m(syms[code]) if syms.get(code) else None
        if r is None or nifty is None:
            continue
        rel = round(r - nifty, 1)
        x["move"] = rel
        x["score"] = round(x["score"] * (0.65 if rel >= 20 else 0.8 if rel >= 12 else 1.15 if abs(rel) <= 6 else 1.0), 1)
    cands.sort(key=lambda x: -x["score"])
    say(f"  price check: {sum(1 for x in cands if 'move' in x)} of {len(cands)} candidates (Nifty 1 month: {nifty})")
    return cands


def move_txt(m):
    if m is None:
        return ""
    if m >= 12:
        return f"already moved {m:+.0f}% vs Nifty in a month"
    if m <= -12:
        return f"down {m:+.0f}% vs Nifty in a month"
    return f"not moved yet ({m:+.0f}% vs Nifty in a month)"


# ============================================================================ looking ahead

MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


AHEAD_WORDS = re.compile(r"(?i)\b(expect|target|plan|schedul|by\s|to (start|begin|commence|launch|complete|close)|will|likely|"
                         r"commissioning|go[- ]live|due|upcoming|pipeline|awaiting|pending|anticipat)")
DONE = re.compile(r"(?i)\b(commenced|started|began|received|completed|achieved|launched|acquired|restarted|commissioned|"
                  r"operational|secured|won|bagged)\b")


def company_dues(cos, today, back=150, horizon_days=95):
    """What each company itself said is due (plant, approval, launch, deal closing), from its turning points:
    {code: [(date, text), ...]} for dates from today to the horizon."""
    out = {}
    horizon = today + dt.timedelta(days=horizon_days)
    since = (today - dt.timedelta(days=back)).isoformat()
    for key, lst in cos.items():
        for e in lst:
            if e["k"] != "pivot" or e["d"] < since:
                continue
            if DONE.search(e["t"]) and not AHEAD_WORDS.search(e["t"]):
                continue  # it already happened ("commenced", "received approvals")
            due = _due(e["t"])
            if due and today <= due <= horizon:
                out.setdefault(key, []).append((due, re.split(r"\s+-\s+", re.sub(r"\s*\[[^\]]*\]$", "", e["t"]))[0][:150]))
    return out


def _due(text):
    """A date the text says something is due by: "by March 2027", "Dec 2026", "Q4 FY27", "H2 FY27" -> month end."""
    t = text.lower()
    m = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*[\s,'-]*(20\d\d|'?\d\d)\b", t)
    if m:
        y = int(m.group(2).strip("'"))
        y = y + 2000 if y < 100 else y
        mo = MONTHS[m.group(1)]
    else:
        m = re.search(r"\b(q[1-4]|h[12])\s*fy\s*'?(\d{2,4})\b", t)
        if not m:
            return None
        fy = int(m.group(2)[-2:]) + 2000
        mo, y = {"q1": (6, fy - 1), "q2": (9, fy - 1), "q3": (12, fy - 1), "q4": (3, fy), "h1": (9, fy - 1), "h2": (3, fy)}[m.group(1)]
    try:
        nxt = dt.date(y + (mo == 12), mo % 12 + 1, 1)
        return nxt - dt.timedelta(days=1)
    except ValueError:
        return None


def look_ahead(lib, cands):
    """Results due soon with what industry peers already said; government decisions awaited; plants, approvals and
    launches the company itself said are due within ~3 months."""
    import timeline
    import trackers
    tl = timeline.load()
    cos, names = tl.get("companies", {}), tl.get("names", {})
    today = dt.date.today()
    inds = lib.get("industries") or {}
    T = trackers.load(trackers.TRACK_FILE, {})
    latest = {c["code"]: c for c in C.latest_call_each(list(lib["calls"].values())) if c.get("code")}
    q_cut = (today - dt.timedelta(days=50)).isoformat()

    # 1. results due in the next 3 weeks, and what peers in the same industry have already said this season
    ahead = []
    for r in T.get("calendar", []):
        when = r.get("when", "")
        if not (today.isoformat() <= when <= (today + dt.timedelta(days=21)).isoformat()):
            continue
        ind = inds.get(r["code"])
        if not ind:
            continue
        peers = [c for code, c in latest.items() if code != r["code"] and inds.get(code) == ind and c["date"] >= q_cut]
        if len(peers) < 2:
            continue
        peers.sort(key=lambda c: c["date"], reverse=True)
        tones = [c.get("tone") or "" for c in peers]
        lines = []
        for c in peers[:4]:
            one = next((e["t"].split(":", 1)[-1].strip() for e in cos.get(c["code"], []) if e["k"] == "concall" and e["d"] == c["date"]), "")
            lines.append(f"{c['company']} ({c.get('tone') or '?'}): {one[:150]}")
        ahead.append({"code": r["code"], "name": r["company"], "when": when, "ind": ind, "n": len(peers),
                      "pos": tones.count("Positive"), "neg": tones.count("Negative") + tones.count("Cautious"), "peers": lines})
    ahead.sort(key=lambda a: a["when"])

    cal = []
    for a in ahead:
        cal.append({"d": a["when"], "k": "results", "name": a["name"], "code": a["code"],
                    "t": f"{a['ind']}: {a['pos']} of {a['n']} peers positive, {a['neg']} cautious so far this season"})
    # 2. government decisions awaited (the last three weeks' pending ones)
    pend_cut = (today - dt.timedelta(days=21)).isoformat()
    for p in T.get("policy", []):
        if p.get("status") == "pending" and p.get("date", "") >= pend_cut:
            body = p["body"] if p.get("body") and "ministry name" not in p["body"].lower() else "Govt"
            cal.append({"d": "", "k": "decision", "name": body, "t": f"{p['what']}" + (f" ({p['sectors']})" if p.get("sectors") else "")
                        + (f" - {p['when_txt']}" if p.get("when_txt") else ""), "cos": p.get("cos") or []})
    # 3. what companies said is due: plants, approvals, launches within ~3 months
    horizon = today + dt.timedelta(days=95)
    keys = {x["key"] for x in cands}
    for key, lst in cos.items():
        for e in lst:
            if e["k"] != "pivot" or e["d"] < (today - dt.timedelta(days=150)).isoformat():
                continue
            if DONE.search(e["t"]) and not AHEAD_WORDS.search(e["t"]):
                continue  # it already happened ("commenced", "received approvals")
            due = _due(e["t"])
            if due and today <= due <= horizon:
                cal.append({"d": due.isoformat(), "k": "due", "name": re.sub(r"[\s\-$]+$", "", names.get(key, key)), "code": key,
                            "t": re.split(r"\s+-\s+", re.sub(r"\s*\[[^\]]*\]$", "", e["t"]))[0][:150], "hot": key in keys})
    cal.sort(key=lambda x: (x["k"] == "decision", x["d"] or "9999", not x.get("hot")))
    # keep it readable: every results line, the decisions, and the nearest dues (the company's thread first)
    res = [x for x in cal if x["k"] == "results"][:12]
    dec = [x for x in cal if x["k"] == "decision"][:8]
    due = sorted([x for x in cal if x["k"] == "due"], key=lambda x: (not x.get("hot"), x["d"]))[:12]
    return ahead, res + sorted(due, key=lambda x: x["d"]) + dec


# ============================================================================ one request a day

PROMPT = """You are the research head of an Indian equity desk. The goal is to catch developments BEFORE the share
price reflects them. Below are {n} listed companies where early signals from the last month (new capacity, orders,
approvals, government decisions, guidance raised, broker initiations, read-across from a bigger company's call,
earlier events now showing up) line up with other evidence. Each comes with how far its share price has already moved
against the Nifty in the past month.
Pick the TEN developments that most deserve attention NOW:
- favour what is still EARLY - building but not yet in the numbers, and not yet in the price
- a name that has already moved 12%+ against the Nifty belongs only if the thread is clearly still building;
  say so in the Stage line
- prefer threads where different kinds of evidence confirm each other over a single big headline
- when several companies show the same thing, make it ONE industry item and name the companies
- you may also pick a company from REPORTING SOON whose peers have already shown a clear trend this season: what
  they said is the early read on its results
- risks that are building count too (dir: down)
{yesterday}
Use ONLY the evidence given; every thread line must carry its date. No price targets, no buy/sell advice. Results and
concalls already out are confirmation, not news: lead each thread with the earliest signal.
Reply with exactly ten blocks, most important first:

### <company name exactly as given, or an industry name> | <up / down / watch>
Headline: <the development in one line, specific>
Stage: <early / building / late> - <one line: what is and isn't in the numbers and the price yet>
Thread:
- <date>: <evidence>
- <date>: <evidence>
(3-5 lines, oldest first, from different kinds of evidence)
Cooking: <what may be building and why it matters for earnings or the valuation - 2 sentences>
Next trigger: <the next dated event that would confirm it - results date, plant start, decision, order>
Risk: <what would break it>
Companies: <for an industry item: the companies, comma-separated; otherwise ->

EVIDENCE:
{body}
{ahead}
"""


def _body(cands):
    rows = []
    for x in cands:
        head = (f"## {x['name']} ({x['sector']}{' / ' + x['ind'] if x['ind'] else ''}) - early: {', '.join(x['early'])}; "
                f"also: {', '.join(k for k in x['kinds'] if k not in x['early'])}; price: {move_txt(x.get('move')) or 'n/a'}")
        rows.append(head + "\n" + "\n".join(f"- {d}: {t}" for d, t in x["ev"]))
    return "\n\n".join(rows)


def _ahead_body(ahead):
    if not ahead:
        return ""
    rows = ["\nREPORTING SOON - what industry peers already said this season:"]
    for a in ahead[:10]:
        rows.append(f"## {a['name']} - results {a['when']} ({a['ind']}: {a['pos']} of {a['n']} peers positive, {a['neg']} cautious)\n"
                    + "\n".join(f"- {p}" for p in a["peers"]))
    return "\n".join(rows)


def parse(text, cands, ahead=()):
    by = {C.norm(x["name"]): x for x in cands}
    for a in ahead:
        by.setdefault(C.norm(a["name"]), {"key": a["code"], "name": a["name"], "sector": "", "move": None})
    items = []
    for block in re.split(r"(?m)^###\s*", text)[1:]:
        head, _, rest = block.partition("\n")
        p = [x.strip(" *") for x in head.split("|")]
        name = re.sub(r"^\d+[.)]\s*", "", p[0]).strip()
        d = (p[1].lower() if len(p) > 1 else "watch")
        d = "up" if d.startswith("up") else "down" if d.startswith("down") else "watch"

        def field(f):
            m = re.search(rf"(?im)^\s*\**{f}\**\s*:\s*\**\s*(.+)$", rest)
            return m.group(1).strip() if m else ""

        th = re.search(r"(?ims)^\s*\**Thread\**\s*:\s*\**\s*\n(.*?)(?=^\s*\**(?:Cooking|Confirm|Risk|Companies)\**\s*:)", rest)
        thread = [re.sub(r"^\s*[-*•]\s*", "", ln).strip() for ln in (th.group(1).splitlines() if th else []) if ln.strip()]
        comps = [c.strip() for c in field("Companies").split(",")
                 if c.strip() and c.strip().lower().strip(".") not in ("-", "none", "n/a", "na", "nil", "—")]
        x = by.get(C.norm(name))
        if x and all(C.norm(c) == C.norm(name) or C.norm(c) == C.norm(x["name"]) for c in comps):
            comps = []  # the company named itself: a company item, not an industry one
        if not x:  # an industry item, or a slightly different spelling
            x = next((v for k, v in by.items() if k and (k in C.norm(name) or C.norm(name) in k)), None)
        if not x and not comps:
            continue  # not from the evidence
        if not x:
            known = [by.get(C.norm(c)) or next((v for k, v in by.items() if k and (k in C.norm(c) or C.norm(c) in k)), None) for c in comps]
            if not any(known):
                continue
        items.append({"name": x["name"] if x and not comps else name, "key": x["key"] if x and not comps else "IND|" + C.norm(name),
                      "sector": x["sector"] if x else "", "dir": d, "head": field("Headline"), "thread": thread[:6],
                      "cooking": field("Cooking"), "confirm": field("Next trigger") or field("Confirm"), "risk": field("Risk"),
                      "stage": field("Stage"), "move": x.get("move") if x and not comps else None, "cos": comps[:8]})
    return items[:10]


def step(lib=None, force=False):
    d = load()
    day = today_ist()
    if d["days"].get(day) and not force and all("stage" in i for i in d["days"][day]) and (d.get("short") or {}).get(day):
        return  # (a list from before the forward-looking version is redone once)
    lib = lib or C.load_lib()
    cands = candidates(lib, limit=60)
    try:
        cands = add_moves(cands, d)
    except Exception as e:
        say(f"  (price check skipped: {e})")
    cands = cands[:40]
    try:
        ahead, cal = look_ahead(lib, cands)
    except Exception as e:
        say(f"  (look-ahead skipped: {e})")
        ahead, cal = [], []
    # the scored shortlist (before the AI picks ten) - published for TradeCharts' "fresh early signals" scans
    d.setdefault("short", {})[day] = [{"key": x["key"], "s": x["score"], "k": x["early"], "since": x["since"],
                                       "move": x.get("move")} for x in cands]
    d["short"] = {k: v for k, v in d["short"].items() if k >= (dt.date.fromisoformat(day) - dt.timedelta(days=7)).isoformat()}
    FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    if len(cands) < 10:
        say("  top developments: not enough connected evidence yet")
        return
    prev_day = max((k for k in d["days"] if k < day), default=None)
    yest = ""
    if prev_day:
        yest = ("\nYESTERDAY'S TEN (keep a thread if it is still building; drop it if nothing new supports it): "
                + "; ".join(i["name"] for i in d["days"][prev_day]) + "\n")
    say(f"\nTop developments: linking {len(cands)} companies with 2+ kinds of evidence ...")
    try:
        text, ai = C.Pool(quality=True).ask(PROMPT.format(n=len(cands), yesterday=yest, body=_body(cands), ahead=_ahead_body(ahead)),
                                            label="top developments", max_wait=120)
    except C.AIError as e:
        say(f"  top developments wait for a full-quality model: {str(e)[:100]}")
        return
    items = parse(text, cands, ahead)
    if len(items) < 5:
        say(f"  top developments: reply didn't parse ({len(items)} items) - trying again next run")
        return
    # how many days running each thread has been on the list
    for it in items:
        n, k = 1, it["key"]
        for prev in sorted((x for x in d["days"] if x < day), reverse=True):
            if any(p["key"] == k or C.norm(p["name"]) == C.norm(it["name"]) for p in d["days"][prev]):
                n += 1
            else:
                break
        it["days"] = n
    d["days"][day] = items
    if prev_day:  # the list's rhythm: what left it since the last list
        now_keys = {C.norm(i["name"]) for i in items} | {i["key"] for i in items}
        d.setdefault("dropped", {})[day] = [p["name"] for p in d["days"][prev_day]
                                            if p["key"] not in now_keys and C.norm(p["name"]) not in now_keys]
        d["dropped"] = {k: v for k, v in d["dropped"].items() if k >= (dt.date.fromisoformat(day) - dt.timedelta(days=KEEP_DAYS)).isoformat()}
    d.setdefault("cal", {})[day] = cal
    d["cal"] = {k: v for k, v in d["cal"].items() if k >= (dt.date.fromisoformat(day) - dt.timedelta(days=KEEP_DAYS)).isoformat()}
    d["at"] = dt.datetime.now(IST).isoformat(timespec="minutes")
    d["model"] = ai.model
    d["days"] = {k: v for k, v in d["days"].items() if k >= (dt.date.fromisoformat(day) - dt.timedelta(days=KEEP_DAYS)).isoformat()}
    FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    say(f"  top developments: {len(items)} written ({ai.model})")


if __name__ == "__main__":
    import sys
    if "--dry" in sys.argv:
        for x in candidates(C.load_lib())[:40]:
            print(x["score"], x["name"], x["kinds"])
    else:
        step(force=True)
