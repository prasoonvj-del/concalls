#!/usr/bin/env python3
"""
"The story so far" for each company: the last ~2 years of re-rating / de-rating factors, pivots and how
the share price reacted -> data/backstories.json (one entry per BSE code).

Grounded, not guessed: the AI gets
  * the weekly share price for 2 years (Yahoo Finance, BSE code) with the big up/down moves and their dates
  * ~80 dated headlines about the company spread over those 2 years (Google News search, 4 half-year windows)
  * our own concall summaries (tone + one line per quarter), latest deck summary, tracker facts
and is told to link a price move to news only when the dates line up.

AI: Groq's "compound" system (an LLM that does its own web searches) on the Groq key, so Gemini stays free.
Free tier allows ~250 such requests a day; we use about 50.
Each company is written once and refreshed only after ~45 days or when a new concall arrives.
"""
import datetime as dt
import json
import re
import time
from urllib.parse import quote_plus

import concalls as C

say = C.say
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
STORE = C.DATA / "backstories.json"
REFRESH_DAYS = 45
ALLOWANCE = {"full": (12, 12), "news": (6, 7), "request": (5, 8)}  # (companies, minutes) per update

PROMPT = """Research the Indian listed company {company} (BSE {code}{sym}, sector: {sector}) using web search, then
explain the last two years of its share price to an investor who wants to learn WHICH KIND OF NEWS RE-RATES OR
DE-RATES THIS STOCK. Search for its results, management commentary, capacity / order / legal / regulatory news,
pivots and analyst views from {start} to today.

The REAL weekly share price (use these numbers for price moves, not numbers from the web):
{price}

Our notes from its recent earnings calls:
{concalls}

Write Markdown, 250-350 words, plain and specific (dates, Rs, %). No filler, no "cause unclear" lines - if you
can't explain a move, leave it out.

**In one line:** <the stock's story in one sentence: re-rated / de-rated / round trip, from Rs X to Rs Y, because ...>
### How the story unfolded
(3-5 phases in time order. Each: **<Mon YYYY - Mon YYYY>: <short phase title>** - what changed in the business or
the news, and what the stock did in that phase, using the real price data above)
### What re-rated it
(2-4 bullets: the triggers the market rewarded)
### What de-rated it
(1-3 bullets: what the market punished. Skip the section if nothing.)
### News that moves this stock
(2-3 bullets: the kind of announcement to watch for next, e.g. "large defence orders", "USFDA clearances")

End with one line: Sources: <3-5 site names you used>
"""


def load():
    try:
        return json.loads(STORE.read_text(encoding="utf-8")) if STORE.exists() else {}
    except ValueError:
        return {}


def short_name(name):
    n = re.sub(r"\b(ltd|limited|ltd\.|pvt|private|corporation|corp|company|co)\b\.?", "", name, flags=re.I)
    n = re.sub(r"[-$]+$", "", n)
    return re.sub(r"\s+", " ", n).strip(" .,-")


LAST_HTTP = {"status": None}


def find_symbol(sess, name, code):
    """Yahoo ticker for a BSE company: search by name (NSE first, then BSE); numeric BSE code as a last resort."""
    q = short_name(name)
    for host in ("query2", "query1"):
        try:
            r = sess.get(f"https://{host}.finance.yahoo.com/v1/finance/search",
                         params={"q": q, "quotesCount": 6, "newsCount": 0}, timeout=20)
            if r.status_code != 200:
                continue
            quotes = [x for x in r.json().get("quotes", []) if x.get("quoteType") == "EQUITY"]
        except Exception:
            continue
        want = C.norm(q)
        def same(x):
            got = C.norm(short_name(x.get("longname") or x.get("shortname") or ""))
            return got and (got.startswith(want[:12]) or want.startswith(got[:12]))
        for suffix in (".NS", ".BO"):
            for x in quotes:
                if x.get("symbol", "").endswith(suffix) and same(x):
                    return x["symbol"]
        break
    return f"{code}.BO"


def prices(sess, sym):
    """Weekly closes for 2 years. Returns None if Yahoo has nothing; raises RuntimeError if Yahoo is refusing us."""
    for attempt in range(3):
        for host in ("query1", "query2"):
            try:
                r = sess.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{sym}",
                             params={"range": "2y", "interval": "1wk"}, timeout=25)
            except Exception as e:
                LAST_HTTP["status"] = str(e)[:60]
                continue
            LAST_HTTP["status"] = r.status_code
            if r.status_code == 404:
                return None
            if r.status_code != 200:
                continue
            try:
                res = r.json()["chart"]["result"][0]
            except Exception:
                return None
            closes = res["indicators"]["quote"][0].get("close") or []
            pts = [[dt.datetime.fromtimestamp(t, IST).strftime("%Y-%m-%d"), round(c, 2)]
                   for t, c in zip(res.get("timestamp") or [], closes) if c]
            return pts if len(pts) > 20 else None
        time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Yahoo Finance not answering (last: {LAST_HTTP['status']})")


def big_moves(pts, window=4, limit=6):
    """Largest 4-week rises and falls (non-overlapping)."""
    cands = []
    for i in range(window, len(pts)):
        a, b = pts[i - window][1], pts[i][1]
        cands.append((abs(b / a - 1), i - window, i, (b / a - 1) * 100))
    cands.sort(reverse=True)
    used, out = set(), []
    for mag, s, e, ch in cands:
        if mag < 0.12 or any(k in used for k in range(s, e + 1)):
            continue
        used.update(range(s, e + 1))
        out.append({"from": pts[s][0], "to": pts[e][0], "p0": pts[s][1], "p1": pts[e][1], "pct": round(ch, 1)})
        if len(out) >= limit:
            break
    return sorted(out, key=lambda m: m["from"])


def price_text(pts, moves):
    hi = max(pts, key=lambda p: p[1])
    lo = min(pts, key=lambda p: p[1])
    q = pts[::13] + [pts[-1]]  # roughly quarterly
    lines = ["Quarterly path: " + " → ".join(f"{d[:7]}: {p:g}" for d, p in q),
             f"2-year high {hi[1]:g} ({hi[0]}), low {lo[1]:g} ({lo[0]}), now {pts[-1][1]:g} ({pts[-1][0]})",
             "Biggest 4-week moves: " + "; ".join(f"{m['from']} to {m['to']}: {m['p0']:g} → {m['p1']:g} ({m['pct']:+.0f}%)" for m in moves)]
    return "\n".join(lines)


def headlines(name, months=24, per_window=40):
    import feedparser
    name = short_name(name)
    today = dt.date.today()
    out, seen = [], set()
    for k in range(0, months, 6):
        end = today - dt.timedelta(days=30 * k)
        start = today - dt.timedelta(days=30 * (k + 6))
        q = f'"{name}" after:{start.isoformat()} before:{end.isoformat()}'
        url = f"https://news.google.com/rss/search?q={quote_plus(q)}&hl=en-IN&gl=IN&ceid=IN:en"
        try:
            feed = feedparser.parse(url, agent="Mozilla/5.0 MarketDesk")
        except Exception:
            continue
        got = 0
        for e in feed.entries:
            t = re.sub(r"\s+-\s+[^-]{2,40}$", "", e.get("title", "")).strip()
            key = re.sub(r"\W+", "", t.lower())[:70]
            if not t or key in seen or name.split()[0].lower() not in t.lower():
                continue
            try:
                d = dt.date(*e.published_parsed[:3]).isoformat()
            except Exception:
                continue
            seen.add(key)
            out.append((d, t))
            got += 1
            if got >= per_window:
                break
        time.sleep(1)
    return sorted(out)


def concall_notes(lib, code):
    rows = []
    for c in sorted([c for c in lib["calls"].values() if c["code"] == code and c.get("summary")], key=lambda c: c["date"]):
        try:
            text = C.here(c["summary"]).read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r"(?im)^.*tone[^:\n]*:\s*(.+)$", text)
        one = (m.group(1) if m else re.sub(r"^#.*\n", "", text).strip()[:300]).strip().strip("*").strip()
        rows.append(f"{c['quarter']} ({c['date']}): {one[:300]}")
    return rows[-6:]


COMPOUND = "groq/compound"


def ask_compound(ai, prompt):
    """Groq's compound system: an LLM that runs its own web searches. Free tier ~250 requests/day."""
    import requests
    url = ai.url.rstrip("/") + "/chat/completions"
    for attempt in range(4):
        try:
            r = requests.post(url, headers={"Authorization": f"Bearer {ai.key}"}, timeout=180,
                              json={"model": COMPOUND, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3})
        except Exception as e:
            if attempt == 3:
                raise C.AIError(f"no answer from Groq ({str(e)[:60]})")
            time.sleep(10)
            continue
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"]
        body = r.text[:300]
        if r.status_code == 429:
            if "per day" in body or "RPD" in body or "TPD" in body:
                raise C.QuotaOver("Groq's daily allowance for web-search answers is used up - the rest continue tomorrow")
            wait = float(r.headers.get("retry-after", 20) or 20)
            time.sleep(min(wait, 90))
            continue
        if r.status_code in (500, 502, 503) and attempt < 3:
            time.sleep(15)
            continue
        raise C.AIError(f"Groq {r.status_code}: {body[:140]}")
    raise C.AIError("Groq kept asking us to wait")


# ---- requests from the website ("Write the story for this company" -> a GitHub issue titled "Story: <code> <name>")
def _gh(method, path, **kw):
    import os
    import requests
    tok, repo = os.environ.get("GH_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not tok or not repo:
        return None
    try:
        r = requests.request(method, f"https://api.github.com/repos/{repo}{path}", timeout=20,
                             headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json"}, **kw)
        return r.json() if r.status_code < 300 else None
    except Exception:
        return None


def requested():
    """{code: issue_number} for open "Story: <code> ..." issues."""
    out = {}
    for it in _gh("GET", "/issues", params={"state": "open", "per_page": 50}) or []:
        m = re.match(r"\s*story:\s*(\d{5,6})", it.get("title", ""), re.I)
        if m and "pull_request" not in it:
            out[m.group(1)] = it["number"]
    return out


def close_request(num, company, ok=True):
    msg = (f"Done - 'The story so far' for {company} is on the website after this update." if ok
           else f"Couldn't write it for {company} this time (no share-price data found).")
    _gh("POST", f"/issues/{num}/comments", json={"body": msg})
    _gh("PATCH", f"/issues/{num}", json={"state": "closed"})


def step(mode="full"):
    try:
        ai = C.AI("backup")
    except C.AIError:
        say("  story so far: no backup AI key (Groq) - skipped to keep Gemini free")
        return
    lib = C.load_lib()
    store = load()
    for k in [k for k, v in store.items() if v.get("status") == "no-price" and v.get("v", 0) < 3]:
        del store[k]
    n_max, minutes = ALLOWANCE.get(mode, (5, 8))
    latest = {}
    for c in lib["calls"].values():
        if c.get("summary") and c.get("code"):
            if c["code"] not in latest or c["date"] > latest[c["code"]]["date"]:
                latest[c["code"]] = c
    pres = json.loads(C.PRES_FILE.read_text(encoding="utf-8")) if C.PRES_FILE.exists() else []
    asked = requested()
    for code in asked:  # a requested company may have only a deck, no concall yet
        if code not in latest:
            d = next((d for d in pres if d["code"] == code), None)
            latest[code] = {"code": code, "company": d["company"] if d else code, "date": "", "quarter": ""}
    import daily
    watch = daily.watchlist()
    today = dt.date.today()

    def due(code, c):
        s1 = store.get(code)
        if code in asked:
            return True
        if not s1 or s1.get("v", 1) < 4:  # v4 = written with web search
            return True
        if s1.get("status") == "no-price":
            return (today - dt.date.fromisoformat(s1["at"])).days > 20
        return (today - dt.date.fromisoformat(s1["at"])).days > REFRESH_DAYS or c["date"] > s1.get("call_date", "")

    todo = [c for code, c in latest.items() if due(code, c)]
    todo.sort(key=lambda c: (c["code"] in asked, any(w in c["company"].lower() for w in watch),
                             c["code"] not in store, c["date"]), reverse=True)
    if mode == "request":
        todo = [c for c in todo if c["code"] in asked]
    write_meta(store, latest, todo, n_max)
    if not todo:
        say("  story so far: nothing waiting")
        return
    say(f"\nWriting 'the story so far' with Groq + web search: {len(todo)} waiting, up to {n_max} this update ...")
    from trackers import _session
    sess = _session()
    deadline = time.time() + minutes * 60
    made = 0
    start = (today - dt.timedelta(days=730)).strftime("%b %Y")
    for c in todo:
        if made >= n_max or time.time() > deadline:
            break
        code = c["code"]
        sym = (store.get(code) or {}).get("sym") or find_symbol(sess, c["company"], code)
        try:
            pts = prices(sess, sym)
            if not pts and sym != f"{code}.BO":
                pts = prices(sess, f"{code}.BO")
        except RuntimeError as e:
            say(f"  {e} - stopping here, the rest continue next update")
            break
        time.sleep(1.5)
        if not pts:
            store[code] = {"status": "no-price", "at": today.isoformat(), "company": c["company"], "v": 4, "sym": sym}
            if code in asked:
                close_request(asked[code], c["company"], ok=False)
            continue
        moves = big_moves(pts)
        notes = concall_notes(lib, code)
        body = PROMPT.format(company=c["company"], code=code, sym=f", {sym}" if not sym[0].isdigit() else "",
                             sector=lib["sectors"].get(code, "") or "-", start=start, price=price_text(pts, moves),
                             concalls="\n".join(notes[-4:]) or "(none)")
        try:
            text = ask_compound(ai, body)
        except C.QuotaOver as e:
            say(f"  {e}")
            break
        except C.AIError as e:
            say(f"  {c['company']}: {str(e)[:140]}")
            continue
        src = ""
        m = re.search(r"(?im)^\**sources?:?\**\s*(.+)$", text)
        if m:
            src = m.group(1).strip()
            text = text[:m.start()].rstrip()
        one = ""
        m = re.search(r"\*\*In one line:\*\*\s*(.+)", text)
        if m:
            one = m.group(1).strip()
            text = text.replace(m.group(0), "")
        store[code] = {"status": "ok", "at": today.isoformat(), "call_date": c["date"], "company": c["company"], "sym": sym,
                       "one": one, "html": C.md(text), "pts": pts, "moves": moves, "sources": src[:300], "v": 4,
                       "model": COMPOUND}
        made += 1
        STORE.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
        if code in asked:
            close_request(asked[code], c["company"])
        time.sleep(4)
    STORE.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    write_meta(store, latest, [c for c in todo if not (store.get(c["code"], {}).get("v", 0) >= 4 and store[c["code"]].get("at") == today.isoformat())], n_max)
    say(f"  story so far: {made} written, {sum(1 for v in store.values() if v.get('status') == 'ok' and v.get('v', 0) >= 4)} companies in total")


META = C.DATA / "backstory_meta.json"


def write_meta(store, latest, todo, n_max):
    ok = [k for k, v in store.items() if v.get("status") == "ok" and v.get("v", 0) >= 4]
    META.write_text(json.dumps({"done": len(ok), "total": len(latest), "per_update": n_max,
                                "next": [c["company"] for c in todo[:12]],
                                "at": dt.datetime.now(IST).isoformat(timespec="minutes")}, ensure_ascii=False), encoding="utf-8")
