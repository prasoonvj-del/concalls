#!/usr/bin/env python3
"""
"The story so far" for each company: the last ~2 years of re-rating / de-rating factors, pivots and how
the share price reacted -> data/backstories.json (one entry per BSE code).

Grounded, not guessed: the AI gets
  * the weekly share price for 2 years (Yahoo Finance, BSE code) with the big up/down moves and their dates
  * ~80 dated headlines about the company spread over those 2 years (Google News search, 4 half-year windows)
  * our own concall summaries (tone + one line per quarter), latest deck summary, tracker facts
and is told to link a price move to news only when the dates line up.

AI: Gemini with Google Search grounding, capped at ~15 companies a day (+ requests from the website) so the
concall and news summaries keep most of Gemini's free allowance. If Gemini is out for the day, a requested
company is written with Groq's GPT-OSS + browser search instead.
Each company is written once and refreshed only after ~45 days or when a new concall arrives.
"""
import datetime as dt
import json
import os
import re
import time
from urllib.parse import quote_plus

import concalls as C

say = C.say
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
STORE = C.DATA / "backstories.json"
FAILS = C.DATA / "backstory_fails.json"  # companies whose answer came back incomplete today
REFRESH_DAYS = 45
ALLOWANCE = {"full": (6, 20), "news": (2, 10), "request": (5, 15),  # (companies, minutes) per update
             "build-full": (12, 30), "build-news": (5, 15)}  # (two stages: research, then the best writer - slower)  # build season (season.py): the rest, several times faster

# Two stages since 27 Nov 2026 (v6): a web-searching model only GATHERS sourced facts (it is good at finding, weak at
# judgement), then the best writer we have (Pool(quality=True): Nemotron 3 Ultra, Gemini full) writes from that evidence
# plus our own records. If no full-quality writer is free, the company waits for the next update - never a weaker story.
RESEARCH = """Research the Indian listed company {company} (BSE {code}{sym}, sector: {sector}) on the web: annual reports,
investor presentations, results, management commentary, credible news (business papers, exchange filings, rating
agencies) and analyst views, from {start} to today. Do NOT write a story - gather facts only.

Return a FACT SHEET in Markdown bullets, every bullet with its month/year and source site in brackets, e.g.
"- Mar 2025: commissioned 5,000 tpa plant at Dahej, taking capacity to 12,000 tpa [company deck]".
Sections:
### Business
segments and their share of revenue, products, key customers / end markets, export share, latest annual revenue and
profit, capacity and plants / network, order book if any
### Industry and position
how the industry works, market share or rank, the main listed competitors, what is hard to copy (cost, approvals,
technology, brand, contracts, distribution)
### What happened, {start} to today (time order)
capacity coming on stream, approvals, big orders won or lost, new products, competition (imports, dumping, new
entrants), raw-material or price cycles, demand shifts, regulation and government schemes, management or governance
changes, capex / M&A / fund-raising, guidance changes, results that surprised
### Risks and views
specific risks; what analysts / rating agencies said
Only facts you found, with numbers where available. Leave out anything you are not sure of. 30-60 bullets."""

PROMPT = """Write about the Indian listed company {company} (BSE {code}{sym}, sector: {sector}) for an investor, from {start}
to today, using ONLY the material below - research notes gathered from the web (with their sources), the real share
price, our concall notes and our own dated record. Do not add facts that are not in this material. Write two parts.

Research notes from the web:
{facts}

The REAL weekly share price (use these numbers for price moves, not numbers from the web):
{price}

Our notes from its recent earnings calls:
{concalls}

Our own dated record of the company (orders, pivots, results, broker calls) - use it, and check the web for more:
{record}

Markdown, plain and specific (dates, Rs, %, tonnes, market share). Bullet points only - never tables. No citation
markers, no filler, no hedging lines. Only facts you found; leave a point out rather than guess.

PART 1 - the business, like an investment-committee note (180-240 words):
### The business
- **What it does:** products or services, main segments with their share of revenue, key customers / end markets, export share
- **Scale:** latest annual revenue, capacity, plants or network (whatever describes its size)
- **Industry and position:** how the industry works, its rank or market share, the main listed competitors
- **Competitive edge:** what is hard to copy - cost position, integration, approvals, technology, brands, contracts, distribution
- **Key risks:** 2-3, specific to this company (e.g. a raw material, one customer, Chinese competition, regulation)
- **What to track:** 2-3 business numbers that drive its value

PART 2 - the story so far (250-350 words). Tell how the BUSINESS changed over the last two years and why the market
re-valued it. Lead with causes, not prices: new capacity coming on stream, approvals, contract wins or losses,
competition (cheap imports, dumping, new entrants), commodity / raw-material cycles, demand shifts, regulation,
management and governance, capital allocation. For each, explain the mechanism - what it did to volumes, prices,
margins or the long-term outlook. The share price is only the evidence: give the stock's move as a short closing
clause in brackets, and its direction must match the real price data. A phase that is only a price move is not a
phase - if a move has no business cause you can find, leave it out.
The style wanted (a made-up company): "**Mar 2024 - Dec 2024: new plant makes it a global supplier** - the 5,000
tpa plant started, making it one of three non-Chinese makers; exports doubled and margins rose to 22% (stock
+60%)." then "**Jan 2025 - Jun 2025: China dumps the same product** - Chinese exporters cut prices ~30%; it had to
match them and margins fell to 9% (stock gave up the gains)."

**In one line:** <the business story in one sentence: what changed in the business, and how the market re-valued it>
### How the story unfolded
(3-5 phases in time order, in the style above: **<Mon YYYY - Mon YYYY>: <what changed in the business>** - cause,
mechanism, effect on the numbers (stock move))
### What re-rated it
(2-4 bullets: the business developments the market rewarded, and why they mattered)
### What de-rated it
(1-3 bullets: what the market punished, and why. Skip the section if nothing.)
### News that moves this stock
(2-3 bullets: the kind of announcement to watch for next, e.g. "large defence orders", "USFDA clearances")

End with one line: Sources: <3-5 site names from the research notes that you relied on>
"""


CHECK = """Below is MATERIAL (research notes from the web, our concall notes, our record, share prices) and a TEXT written
only from it. List every factual claim in the TEXT - a number, date, name, plant, order, market share, event - that the
MATERIAL does not support. Ignore opinions, wording and price moves that match the price data.
Answer one claim per line starting with "- ", quoting the claim briefly, or exactly NONE if everything is supported.

MATERIAL:
{material}

TEXT:
{text}"""


def check_claims(material, text):
    """A second model reads the story against the evidence it was written from: unsupported claims, flagged (not edited)."""
    try:
        out, _ = C.Pool(bulk=True).ask(CHECK.format(material=material[:30000], text=text[:9000]), label="claim check")
    except C.AIError:
        return None  # couldn't check this time
    if re.search(r"^\s*NONE\s*$", out.strip(), re.I):
        return []
    return [re.sub(r"^\s*[-*]\s*", "", ln).strip()[:220] for ln in out.splitlines() if re.match(r"^\s*[-*]\s+\S", ln)][:8]


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


# Groq models that can search the web themselves, best first. The last one is GPT-OSS with Groq's
# built-in browser-search tool. The first that works for this key is remembered for the run.
SEARCHERS = [("groq/compound", None), ("groq/compound-mini", None),
             ("openai/gpt-oss-120b", [{"type": "browser_search"}])]  # (the 20b model cut answers short: not used)
COMPOUND = SEARCHERS[0][0]
_working = {}


def ask_compound(ai, prompt):
    """Ask a Groq model that runs its own web searches (free tier: a few hundred requests a day)."""
    import requests
    global COMPOUND
    url = ai.url.rstrip("/") + "/chat/completions"
    order = [m for m in SEARCHERS if m[0] not in _working.setdefault("groq_off", set())]
    last, quota = "", 0
    for model, tools in order:
        payload = {"model": model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3}
        if tools:
            payload["tools"] = tools
        for attempt in range(4):
            try:
                r = requests.post(url, headers={"Authorization": f"Bearer {ai.key}"}, timeout=240, json=payload)
            except Exception as e:
                last = str(e)[:80]
                time.sleep(10)
                continue
            if r.status_code == 200:
                COMPOUND = model + (" + browser search" if tools else "")
                return r.json()["choices"][0]["message"]["content"]
            body = r.text[:300]
            last = f"{model}: {r.status_code} {body[:120]}"
            if r.status_code == 429:
                if "per day" in body or "RPD" in body or "TPD" in body:
                    _working["groq_off"].add(model)
                    quota += 1
                    break  # this model is done for today - try the next
                time.sleep(min(float(r.headers.get("retry-after", 20) or 20), 90))
                continue
            if r.status_code in (500, 502, 503) and attempt < 3:
                time.sleep(15)
                continue
            _working["groq_off"].add(model)  # 400/404: not available for this key
            break
    if quota:
        raise C.QuotaOver("Groq's daily allowance for web-search answers is used up - the rest continue tomorrow")
    raise C.AIError(f"no web-search model answered ({last})")


GEMINI_MODELS = ["gemini-2.5-flash", "gemini-flash-latest", "gemini-2.5-flash-lite", "gemini-2.0-flash"]


def ask_gemini_search(prompt):
    """Gemini with Google Search grounding (the same way the reports you pasted were made). Returns (text, sources)."""
    import requests
    key = C.AI("ai").key
    last, out_of_quota = "", 0
    if "models" not in _working:  # the Gemini line-up changes; use what this key can see, the model in daily use first
        names = []
        try:
            wm = (C.DATA / "working_model.txt").read_text(encoding="utf-8").strip().replace("models/", "")
            names.append(wm)
        except OSError:
            pass
        try:
            js = requests.get("https://generativelanguage.googleapis.com/v1beta/models", params={"key": key, "pageSize": 200}, timeout=30).json()
            avail = [m["name"].replace("models/", "") for m in js.get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in m["name"]
                     and not re.search(r"image|tts|audio|live|thinking|exp", m["name"])]
            avail.sort(key=lambda n: ("lite" in n, "preview" in n, [-int(x) for x in re.findall(r"\d+", n)[:2]]))
            names += avail
        except Exception:
            pass
        names += GEMINI_MODELS
        _working["models"] = list(dict.fromkeys(n for n in names if n))
    order = _working["models"]
    for model in order:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        for attempt in range(3):
            try:
                r = requests.post(url, params={"key": key}, timeout=240, json={
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "tools": [{"google_search": {}}], "generationConfig": {"temperature": 0.3}})
            except Exception as e:
                last = str(e)[:80]
                time.sleep(10)
                continue
            if r.status_code == 200:
                js = r.json()
                cand = (js.get("candidates") or [{}])[0]
                text = "".join(p.get("text", "") for p in (cand.get("content") or {}).get("parts", []))
                if not text.strip():
                    last = f"{model}: empty answer"
                    break
                chunks = (cand.get("groundingMetadata") or {}).get("groundingChunks") or []
                srcs = []
                for ch in chunks:
                    t = ((ch.get("web") or {}).get("title") or "").strip()
                    if t and t not in srcs:
                        srcs.append(t)
                _working["models"] = [model] + [m for m in _working["models"] if m != model]
                return text, ", ".join(srcs[:6]), model
            body = r.text[:600]
            last = f"{model}: {r.status_code} {re.sub(chr(10) + '|  +', ' ', body)[:160]}"
            if r.status_code == 429:
                if "plan and billing" in body or "PerDay" in body or "per day" in body.lower():
                    out_of_quota += 1
                    break  # this model is done for today (or search isn't on the free plan) - try the next
                time.sleep(30)
                continue
            if r.status_code in (500, 502, 503):
                time.sleep(20)
                continue
            break  # 400/404: try the next model
    _working["gemini_off"] = True  # don't keep knocking for the rest of this run
    if out_of_quota:
        raise C.QuotaOver("Gemini's Google-Search answers aren't available on the free allowance right now")
    raise C.AIError(f"Gemini search didn't answer ({last})")


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
        if (it.get("user") or {}).get("login", "") != os.environ.get("GITHUB_REPOSITORY_OWNER", "prasoonvj-del"):
            continue  # only the owner's requests spend the AI allowance
        m = re.match(r"\s*story:\s*(\d{5,6})", it.get("title", ""), re.I)
        if m and "pull_request" not in it:
            out.setdefault(m.group(1), []).append(it["number"])
    return out


def close_request(nums, company, ok=True):
    for num in nums:
        _close_one(num, company, ok)


def _close_one(num, company, ok=True):
    msg = (f"Done - 'The story so far' for {company} is on the website after this update." if ok
           else f"Couldn't write it for {company} this time (no share-price data found).")
    _gh("POST", f"/issues/{num}/comments", json={"body": msg})
    _gh("PATCH", f"/issues/{num}", json={"state": "closed"})


def open_research(company, code, sector, start):
    """A fact sheet without an AI web search (Gemini's search isn't free; Groq's runs out early each day):
    Wikipedia's article on the company, dated headlines from Google News going back to {start}, and the company's
    own exchange filings / turning points we have collected. Sources stay with each line."""
    import xml.etree.ElementTree as ET
    import requests
    name = short_name(company)
    H = {"User-Agent": "MarketDesk/1.0 (research; github.com/prasoonvj-del/concalls)"}
    out, srcs = [], []
    try:  # Wikipedia: the business, history, plants, segments
        r = requests.get("https://en.wikipedia.org/w/api.php", headers=H, timeout=20, params={
            "action": "query", "list": "search", "srsearch": f'"{name}" India company', "format": "json", "srlimit": 3})
        for hit in (r.json().get("query", {}).get("search") or []):
            title = hit["title"]
            if name.split()[0].lower() not in title.lower():
                continue
            r2 = requests.get("https://en.wikipedia.org/w/api.php", headers=H, timeout=20, params={
                "action": "query", "prop": "extracts", "explaintext": 1, "titles": title, "format": "json"})
            page = next(iter(r2.json().get("query", {}).get("pages", {}).values()), {})
            txt = re.sub(r"\n{2,}", "\n", page.get("extract") or "")
            txt = re.split(r"\n== (?:See also|References|External links|Notes) ==", txt)[0]
            if len(txt) > 400:
                out.append(f"### From Wikipedia ({title})\n" + txt[:7000])
                srcs.append(f"https://en.wikipedia.org/wiki/{quote_plus(title.replace(' ', '_'))}")
            break
    except Exception:
        pass
    heads = []
    for q in (f'"{name}"', f'"{name}" (capacity OR order OR acquisition OR plant OR guidance OR results)'):
        try:  # Google News: dated headlines, newest and older
            r = requests.get("https://news.google.com/rss/search", headers=H, timeout=20,
                             params={"q": f"{q} after:{start[:4]}-01-01", "hl": "en-IN", "gl": "IN", "ceid": "IN:en"})
            for it in ET.fromstring(r.content).iter("item"):
                t, d = it.findtext("title") or "", it.findtext("pubDate") or ""
                if re.search(r"share price|stock price|price today|quote and history|live nse|stock (?:rises|falls|jumps|gains)", t, re.I):
                    continue  # price-ticker pages and daily move headlines: not the business story
                src = it.findtext("source") or ""
                try:
                    dd = dt.datetime.strptime(d[5:16], "%d %b %Y").strftime("%b %Y")
                except ValueError:
                    dd = d[5:16]
                heads.append((d and dt.datetime.strptime(d[5:16], "%d %b %Y") if d else dt.datetime.min, f"- {dd}: {t} [{src}]"))
        except Exception:
            continue
    seen, lines = set(), []
    for _, ln in sorted(heads, key=lambda x: x[0]):
        k = re.sub(r"\W+", "", ln.lower())[:70]
        if k not in seen:
            seen.add(k)
            lines.append(ln)
    if lines:
        out.append("### Headlines (Google News, oldest first)\n" + "\n".join(lines[-120:]))
        srcs.append("news.google.com")
    try:
        T = json.loads((C.DATA / "trackers.json").read_text(encoding="utf-8"))  # turning points, orders, results we collected
        T = T.get("trackers", T)
        rows = [r for k in ("pivots", "orders", "results", "events", "calls") for r in (T.get(k) or [])
                if (code and str(r.get("code")) == str(code)) or short_name(r.get("company", "")).lower() == name.lower()]
        if rows:
            out.append("### Our record of filings and news\n" + "\n".join(
                f"- {r.get('date', '')}: {r.get('type', '')} {r.get('what') or r.get('title') or r.get('head') or ''} "
                f"{r.get('why', '')}".strip() for r in sorted(rows, key=lambda r: r.get("date", ""))[-60:]))
    except Exception:
        pass
    return "\n\n".join(out), ", ".join(srcs)


def _record(code, name):
    try:
        import timeline
        return timeline.context(code=code, name=name, limit=20) or "(nothing yet)"
    except Exception:
        return "(nothing yet)"


def step(mode="full", hard_stop=None):
    """hard_stop: a time (epoch) this must end by - the daily run's own limit."""
    try:
        ai = C.AI("backup")
    except C.AIError:
        ai = None
    lib = C.load_lib()
    store = load()
    for k in [k for k, v in store.items() if v.get("status") == "no-price" and v.get("v", 0) < 3]:
        del store[k]
    for v in store.values():  # a new-style entry saved before answers were checked, and incomplete: redo it
        if v.get("v") == 5 and (not v.get("biz") or "unfolded" not in v.get("html", "").lower()):
            v["v"] = 4
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
        if s1.get("v", 4) < 6 and s1.get("status") == "ok":  # v6 = researched facts, written by the best writer
            return True
        if s1.get("status") == "no-price":
            return (today - dt.date.fromisoformat(s1["at"])).days > 20
        return (today - dt.date.fromisoformat(s1["at"])).days > REFRESH_DAYS or c["date"] > s1.get("call_date", "")

    try:
        fails = json.loads(FAILS.read_text(encoding="utf-8")) if FAILS.exists() else {}
    except ValueError:
        fails = {}
    todo = [c for code, c in latest.items() if due(code, c) and fails.get(code) != today.isoformat()]
    todo.sort(key=lambda c: (c["code"] in asked, any(w in c["company"].lower() for w in watch),
                             c["code"] not in store, c["date"]), reverse=True)
    if mode == "request":
        todo = [c for c in todo if c["code"] in asked]
    write_meta(store, latest, todo, n_max)
    if not todo:
        say("  story so far: nothing waiting")
        return
    say(f"\nWriting 'the story so far' (web research, then the best writer): {len(todo)} waiting, up to {n_max} this update ...")
    from trackers import _session
    sess = _session()
    deadline = time.time() + minutes * 60
    if hard_stop:
        deadline = min(deadline, hard_stop)
    made, search_fails, search_down = 0, 0, False
    start = (today - dt.timedelta(days=730)).strftime("%b %Y")
    for c in todo:
        if made >= n_max or time.time() > deadline or (hard_stop and time.time() + 7 * 60 > hard_stop):
            break  # (one company: web research + the full-quality writer can take several minutes)
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
        latest_md = ""
        if c.get("summary"):
            try:
                latest_md = C.here(c["summary"]).read_text(encoding="utf-8").split("\n---\n")[0][:7000]
            except OSError:
                pass
        args = dict(company=c["company"], code=code, sym=f", {sym}" if not sym[0].isdigit() else "",
                    sector=lib["sectors"].get(code, "") or "-", start=start)
        # stage 1: sourced facts from the web
        research = RESEARCH.format(**args)
        src, facts = "", None
        if not _working.get("gemini_off"):
            try:
                facts, src, used = ask_gemini_search(research)
            except C.AIError as e:
                say(f"  Gemini search: {str(e)[:160]} - using Groq's web search")
        if facts is None and ai is not None and not search_down:
            try:
                facts, used = ask_compound(ai, research), COMPOUND
            except C.AIError as e2:  # (used up for the day, or failing: the open sources below take over)
                say(f"  {c['company']}: web search - {str(e2)[:120]}")
                search_fails += 1
                if isinstance(e2, C.QuotaOver) or search_fails >= 2 or \
                        not [m for m in SEARCHERS if m[0] not in _working.get("groq_off", set())]:
                    search_down = True
                    say("  AI web search isn't available - researching from Wikipedia, Google News and our filings")
        if facts is None:
            facts, src = open_research(c["company"], code, args["sector"], start)
            used = "open sources"
        search_fails = 0
        facts = re.sub(r"【[^】]*】", "", facts)
        if len(facts) < 600:
            say(f"  {c['company']}: too little found on the web - trying again tomorrow")
            fails[code] = today.isoformat()
            FAILS.write_text(json.dumps(fails), encoding="utf-8")
            continue
        # stage 2: the best writer, from the evidence only
        concalls = ("Latest concall summary (" + (c.get("quarter") or "") + "):\n" + latest_md + "\n\nEarlier quarters:\n"
                    if latest_md else "") + ("\n".join(notes[-4:]) or "(none)")
        body = PROMPT.format(**args, facts=facts[:14000], price=price_text(pts, moves), concalls=concalls,
                             record=_record(code, c["company"]))
        try:
            text, wai = C.Pool(quality=True).ask(body, label="story so far")
            used = f"{used} (research) + {wai.model}"
        except C.AIError as e2:
            say(f"  {c['company']}: no full-quality writer free ({str(e2)[:100]}) - the rest wait for the next update")
            break
        text = re.sub(r"【[^】]*】", "", text)  # inline citation markers from the search tool
        text = re.sub(r"\[\d+(?:†[^\]]*)?\]", "", text)
        m = re.search(r"(?im)^\**sources?:?\**\s*(.+)$", text)
        if m:
            src = src or m.group(1).strip()
            text = text[:m.start()].rstrip()
        biz = ""  # part 1: the business profile, shown at the top of the company page
        m = re.search(r"(?ims)^#+\s*(?:PART\s*1\W*)?The business\s*$(.*?)(?=^#+\s|^\s*\**\s*in one line|\Z)", text)
        if m:
            biz = m.group(1).strip()
            text = (text[:m.start()] + text[m.end():]).strip()
        else:  # no heading: whatever comes before the story is the profile
            m = re.search(r"(?im)^\s*\**\s*in one line|^#+\s*How the story unfolded", text)
            if m and m.start() > 200:
                biz, text = text[:m.start()].strip(), text[m.start():].strip()
        if not re.search(r"(?i)how the story unfolded", text) or len(text) < 700 or len(biz) < 150:
            say(f"  {c['company']}: the answer came back incomplete - trying again tomorrow")
            fails[code] = today.isoformat()
            FAILS.write_text(json.dumps(fails), encoding="utf-8")
            continue
        text = re.sub(r"(?im)^\s*\**\s*PART\s*[12][^\n]*$", "", text).strip()
        one = ""
        m = re.search(r"(?im)^\s*\**\s*(?:in one line|one[\s\-‑]line story)\s*:?\s*\**\s*:?\s*(.+)$", text)
        if m:
            one = re.sub(r"\*\*", "", m.group(1)).strip()
            text = text.replace(m.group(0), "")
        store[code] = {"status": "ok", "at": today.isoformat(), "call_date": c["date"], "company": c["company"], "sym": sym,
                       "one": one, "html": C.md(text), "biz": C.md(biz) if biz else "", "pts": pts, "moves": moves,
                       "sources": src[:300], "v": 6,
                       "model": used}
        flags = check_claims(body.split("Markdown, plain and specific")[0], (biz or "") + "\n" + text)
        if flags is not None:
            store[code]["check"] = flags
            if flags:
                say(f"    claim check: {len(flags)} statement(s) not found in the material - shown on the page")
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
    week = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    per_day = round(sum(1 for k in ok if (store[k].get("at") or "")[:10] > week) / 7)
    META.write_text(json.dumps({"done": len(ok), "total": len(latest), "per_update": n_max, "per_day": per_day,
                                "next": [c["company"] for c in todo[:12]],
                                "at": dt.datetime.now(IST).isoformat(timespec="minutes")}, ensure_ascii=False), encoding="utf-8")
