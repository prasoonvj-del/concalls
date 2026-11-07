#!/usr/bin/env python3
"""
"The story so far" for each company: the last ~2 years of re-rating / de-rating factors, pivots and how
the share price reacted -> data/backstories.json (one entry per BSE code).

Grounded, not guessed: the AI gets
  * the weekly share price for 2 years (Yahoo Finance, BSE code) with the big up/down moves and their dates
  * ~80 dated headlines about the company spread over those 2 years (Google News search, 4 half-year windows)
  * our own concall summaries (tone + one line per quarter), latest deck summary, tracker facts
and is told to link a price move to news only when the dates line up.

AI limits: runs on the BACKUP provider (Groq) so Gemini stays free for concalls and news.
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
ALLOWANCE = {"full": (12, 10), "news": (6, 5)}  # (companies, minutes) per update

PROMPT = """You are a sell-side analyst explaining a stock's last two years to an investor who wants to learn
WHAT KIND OF NEWS MOVES THIS STOCK. Company: {company} ({sector}).

Use ONLY the material below. Link a price move to a piece of news only when their dates line up
(say "around the same time" if loose); if no news explains a move, say the cause isn't clear from the
headlines. Never invent numbers, dates or events. Prices are in Rs.

Write Markdown, about 250 words:
**In one line:** <the stock's story in one sentence, e.g. "Re-rated from Rs X to Rs Y as ... then ...">
### Re-rating factors
(bullets: what lifted the stock - date, the news, the price reaction)
### De-rating factors
(bullets: what hurt it - date, the news, the price reaction. Skip if none.)
### Pivots & turning points
(bullets: strategy shifts, capacity, big orders, legal wins, approvals, management changes)
### What moves this stock
(2-3 bullets: the kinds of news the market has rewarded or punished here)

SHARE PRICE (weekly, Rs):
{price}

OUR CONCALL NOTES:
{concalls}

HEADLINES (date - headline):
{news}
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


def prices(sess, code):
    for host in ("query1", "query2"):
        try:
            r = sess.get(f"https://{host}.finance.yahoo.com/v8/finance/chart/{code}.BO",
                         params={"range": "2y", "interval": "1wk"}, timeout=25)
            if r.status_code != 200:
                continue
            res = r.json()["chart"]["result"][0]
            closes = res["indicators"]["quote"][0].get("close") or []
            pts = [[dt.datetime.fromtimestamp(t, IST).strftime("%Y-%m-%d"), round(c, 2)]
                   for t, c in zip(res.get("timestamp") or [], closes) if c]
            if len(pts) > 20:
                return pts
        except Exception:
            continue
    return None


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


def step(mode="full"):
    try:
        ai = C.AI("backup")
    except C.AIError:
        say("  story so far: no backup AI key (Groq) - skipped to keep Gemini free")
        return
    lib = C.load_lib()
    store = load()
    n_max, minutes = ALLOWANCE[mode]
    latest = {}
    for c in lib["calls"].values():
        if c.get("summary") and c.get("code"):
            if c["code"] not in latest or c["date"] > latest[c["code"]]["date"]:
                latest[c["code"]] = c
    import daily
    watch = daily.watchlist()
    today = dt.date.today()

    def due(code, c):
        s = store.get(code)
        if not s:
            return True
        if s.get("status") == "no-price" and (today - dt.date.fromisoformat(s["at"])).days < 20:
            return False
        return (today - dt.date.fromisoformat(s["at"])).days > REFRESH_DAYS or c["date"] > s.get("call_date", "")

    todo = [c for code, c in latest.items() if due(code, c)]
    todo.sort(key=lambda c: (any(w in c["company"].lower() for w in watch), c["date"]), reverse=True)
    if not todo:
        say("  story so far: all companies up to date")
        return
    say(f"\nWriting 'the story so far' with {ai.provider}: {len(todo)} waiting, up to {n_max} this update ...")
    from trackers import _session
    sess = _session()
    deadline = time.time() + minutes * 60
    made = 0
    for c in todo:
        if made >= n_max or time.time() > deadline:
            break
        code = c["code"]
        pts = prices(sess, code)
        if not pts:
            store[code] = {"status": "no-price", "at": today.isoformat(), "company": c["company"]}
            continue
        moves = big_moves(pts)
        news = headlines(c["company"])
        notes = concall_notes(lib, code)
        body = PROMPT.format(company=c["company"], sector=lib["sectors"].get(code, ""), price=price_text(pts, moves),
                             concalls="\n".join(notes) or "(none)",
                             news="\n".join(f"{d} - {t}" for d, t in news[-90:]) or "(no headlines found)")
        if ai.max_input_tokens and C.est_tokens(body) > ai.max_input_tokens:
            keep = news[-60:]
            body = PROMPT.format(company=c["company"], sector=lib["sectors"].get(code, ""), price=price_text(pts, moves),
                                 concalls="\n".join(notes[-3:]) or "(none)", news="\n".join(f"{d} - {t}" for d, t in keep))
        try:
            text = ai.ask(body, label=f"story so far: {c['company'][:30]}")
        except C.AIError as e:
            say(f"  {c['company']}: {str(e)[:120]}")
            if isinstance(e, C.QuotaOver):
                break
            continue
        one = ""
        m = re.search(r"\*\*In one line:\*\*\s*(.+)", text)
        if m:
            one = m.group(1).strip()
            text = text.replace(m.group(0), "")
        store[code] = {"status": "ok", "at": today.isoformat(), "call_date": c["date"], "company": c["company"],
                       "one": one, "html": C.md(text), "pts": pts, "moves": moves, "n_news": len(news),
                       "model": getattr(ai, "model", "")}
        made += 1
        STORE.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
        time.sleep(3)
    STORE.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    say(f"  story so far: {made} written, {sum(1 for v in store.values() if v.get('status') == 'ok')} companies in total")
