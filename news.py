#!/usr/bin/env python3
"""
Morning news brief - reads your RSS feeds (feeds.opml), groups the same story across papers,
tags each story (sector, companies, importance, sentiment), explains the top stories, writes a digest
per sector and the big picture, and saves it for the website (site_builder.py).

Run:  python news.py           (builds the brief and opens it)
      python news.py --quiet   (for scheduled runs: no browser)
Uses the same AI settings as concalls.py (config.ini).
"""
import concurrent.futures as cf
import configparser
import datetime as dt
import html
import json
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

import concalls as C

try:
    import feedparser
except ImportError:
    print("Missing library 'feedparser'. Laptop: run setup.bat. Tablet: pip install feedparser")
    sys.exit(1)
import requests

say = C.say
NEWS_DIR = C.BASE / "news"
SEEN_FILE = C.DATA / "news_seen.json"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
UA = ("Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/130.0 Mobile Safari/537.36")

EXTRA = ["Economy & Policy", "Markets & Flows", "Global Markets & Macro", "Commodities",
         "IPOs, Deals & Funding", "Personal Finance", "Not market-relevant"]
CATEGORIES = [s for s in C.SECTORS if s != "Services & Others"] + ["Services & Others"] + EXTRA

SECTION_PROMPT = """You are a senior Indian equity research analyst writing one section of an investor's morning brief.
Topic: {cat}. Below are {n} news stories from the last {hours} hours. Each has an id in brackets, the headline,
a short description (often missing - feeds carry little text), and how many outlets covered it.

Write in Markdown, using ONLY these stories - don't invent details or numbers. After each point put the ids
it comes from, like [12] or [12, 40]. Merge stories about the same event. Skip trivia. Skip any section
with nothing worth saying.

**In one line:** <the single most important takeaway for an investor>
### What's happening
(3-6 bullets: main developments and themes, and why they matter)
### Company news
(one bullet per company with meaningful news: **Company** - what happened, why it matters [ids])
### Signals
- Positive: ...
- Negative / risks: ...

STORIES:
"""

BIG_PROMPT = """You are a senior Indian equity strategist. Below are today's section briefs ({date}), built from {n}
news stories across Indian and global financial media over the last {hours} hours.

Write the top of the morning brief in Markdown, using only these briefs. Keep the [ids] after each point.

## The big picture
(5-7 bullets: the themes that matter most today for an Indian equity investor)
## Market mood
(2-3 lines)
## Stocks in focus
(table: Company | What happened | Read - Positive / Negative / Mixed)
## Sectors to watch
(bullets: sector - why)
## What to watch next

SECTION BRIEFS:
"""


# ============================================================================ settings & feeds

def settings():
    cp = configparser.ConfigParser()
    cp.read(C.CONFIG_FILE, encoding="utf-8")
    n = cp["news"] if cp.has_section("news") else {}

    def lst(key, default):
        return [x.strip() for x in n.get(key, default).split(",") if x.strip()]

    # separate tabs: "Tab name = folder, folder; Tab name = folder"
    tabs = {}
    for part in n.get("tabs", "Tech = Tech; Auto = Auto; Sports = Sports").split(";"):
        name, _, folders = part.partition("=")
        if name.strip() and folders.strip():
            tabs[name.strip()] = [f.strip().lower() for f in folders.split(",") if f.strip()]
    return {"opml": n.get("opml", "feeds.opml").strip(),
            "skip": [x.lower() for x in lst("skip_folders", "Financial History")],
            "tabs": tabs,
            "google": n.get("google_news", "yes").strip().lower() in ("yes", "true", "1", "on"),
            "hours": int(n.get("hours", "24") or 24),
            "watch": lst("watchlist", ""),
            "min_stories": int(n.get("min_stories_for_digest", "3") or 3)}


def google_feeds(tab=None):
    """Google News searches from google_news.txt (+ watchlist companies) as extra feeds.
    Lines starting "Tab: <name> |" feed that tab instead of the main brief."""
    from urllib.parse import quote_plus
    out, path = [], C.BASE / "google_news.txt"
    rows = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "|" in line:
                folder, _, q = line.partition("|")
                folder = folder.strip()
                is_tab = folder.lower().startswith("tab:")
                if tab is None and not is_tab:
                    rows.append((folder, q.strip()))
                elif tab is not None and is_tab and folder[4:].strip().lower() == tab.lower():
                    rows.append((tab, q.strip()))
    if tab is None:
        import daily  # watchlist companies get their own search
        rows += [("Google: Watchlist", f'"{w}"') for w in daily.watchlist()]
    for folder, q in rows:
        url = f"https://news.google.com/rss/search?q={quote_plus(q + ' when:1d')}&hl=en-IN&gl=IN&ceid=IN:en"
        out.append({"url": url, "name": f"Google News: {q}", "folder": folder})
    return out


def read_opml(path, skip):
    feeds, seen = [], set()

    def walk(node, folder):
        for o in node.findall("outline"):
            url = (o.get("xmlUrl") or "").strip()
            name = (o.get("title") or o.get("text") or "").strip()
            if url:
                if folder.lower() in skip or url in seen:
                    continue
                seen.add(url)
                feeds.append({"url": url, "name": name or url, "folder": folder})
            else:
                walk(o, name)

    walk(ET.parse(path).getroot().find("body"), "")
    return feeds


def fetch(url):
    """Returns (bytes, error). Plain request first; if a site blocks it, retry like a browser."""
    headers = {"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"}
    err = ""
    try:
        r = requests.get(url, headers=headers, timeout=25)
        if r.status_code == 200 and r.content.strip():
            return r.content, None
        err = f"HTTP {r.status_code}"
    except Exception as e:
        err = type(e).__name__
    try:
        if C.cffi is not None:
            r = C.cffi.get(url, impersonate="chrome", timeout=25)
            if r.status_code == 200 and r.content.strip():
                return r.content, None
            err = f"HTTP {r.status_code}"
        elif shutil.which("curl"):
            out = subprocess.run(["curl", "-sSL", "--compressed", "-m", "25", "-A", UA, url],
                                 capture_output=True, timeout=40)
            if out.returncode == 0 and out.stdout.strip():
                return out.stdout, None
    except Exception as e:
        err = err or type(e).__name__
    return None, err or "no content"


def via_jina(url):
    """Second relay: the Jina reader returns the feed's original XML."""
    try:
        r = requests.get("https://r.jina.ai/" + url, headers={"X-Return-Format": "text"}, timeout=45)
        if r.status_code == 200 and "<item" in r.text:
            return r.content
    except Exception:
        pass
    return None


def via_relay(url):
    """Fetches a feed through the free rss2json service and turns it back into RSS."""
    try:
        r = requests.get("https://api.rss2json.com/v1/api.json", params={"rss_url": url}, timeout=30)
        js = r.json()
        if js.get("status") != "ok" or not js.get("items"):
            return None
    except Exception:
        return None
    from xml.sax.saxutils import escape
    from email.utils import format_datetime
    items = []
    for it in js["items"]:
        when = ""
        try:
            d = dt.datetime.strptime(it.get("pubDate", ""), "%Y-%m-%d %H:%M:%S").replace(tzinfo=dt.timezone.utc)
            when = f"<pubDate>{format_datetime(d)}</pubDate>"
        except ValueError:
            pass
        items.append(f"<item><title>{escape(it.get('title', ''))}</title><link>{escape(it.get('link', ''))}</link>"
                     f"<description>{escape(clean(it.get('description', ''), 400))}</description>{when}</item>")
    return ("<?xml version='1.0'?><rss version='2.0'><channel><title>relay</title>" + "".join(items) +
            "</channel></rss>").encode()


def clean(text, limit=None):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rsplit(" ", 1)[0] + "…" if limit and len(text) > limit else text


def parse(content, feed):
    d = feedparser.parse(content)
    out = []
    for e in d.entries:
        title = clean(e.get("title", ""))
        if not title:
            continue
        source = feed["name"]
        desc = clean(e.get("summary") or e.get("description") or "", 280)
        if "news.google." in feed["url"]:  # "Headline - Publisher"; the description is only links
            m = re.match(r"^(.*\S)\s+[-–]\s+([^-–]{2,60})$", title)
            if m:
                title, source = m.group(1), m.group(2)
            desc = ""
        if desc[:60].lower() == title[:60].lower():
            desc = ""
        ts = e.get("published_parsed") or e.get("updated_parsed")
        when = dt.datetime(*ts[:6], tzinfo=dt.timezone.utc) if ts else None
        out.append({"title": title, "desc": desc, "link": e.get("link", ""), "source": source,
                    "folder": feed["folder"], "when": when})
    return out


def collect(feeds, hours):
    """Fetch all feeds in parallel; keep articles from the last `hours`."""
    now = dt.datetime.now(dt.timezone.utc)
    since = now - dt.timedelta(hours=hours)
    seen = json.loads(SEEN_FILE.read_text(encoding="utf-8")) if SEEN_FILE.exists() else {}
    articles, failed, done = [], [], 0
    with cf.ThreadPoolExecutor(max_workers=16) as pool:
        jobs = {pool.submit(fetch, f["url"]): f for f in feeds}
        for fut in cf.as_completed(jobs):
            f = jobs[fut]
            done += 1
            print(f"\r  feeds read: {done}/{len(feeds)} ", end="", flush=True)
            content, err = fut.result()
            if err:
                failed.append({"name": f["name"], "folder": f["folder"], "error": err})
                continue
            try:
                items = parse(content, f)
            except Exception as e:
                failed.append({"name": f["name"], "folder": f["folder"], "error": f"unreadable ({type(e).__name__})"})
                continue
            if not items:
                failed.append({"name": f["name"], "folder": f["folder"], "error": "empty feed"})
            for a in items:
                key = a["link"] or a["title"]
                if a["when"] is None:  # undated: treat as published when first seen
                    first = seen.get(key)
                    a["when"] = dt.datetime.fromisoformat(first) if first else now
                seen.setdefault(key, a["when"].isoformat())
                if since <= a["when"] <= now + dt.timedelta(hours=2):
                    articles.append(a)
    say("")
    blocked = [f for f in failed if f["error"].startswith(("HTTP 403", "HTTP 429", "HTTP 503"))]
    if blocked:
        say(f"  {len(blocked)} feeds block cloud servers - retrying them one at a time through relays ...")
        by_name = {(f["name"], f["folder"]): f for f in feeds}
        rescued = 0
        for fb in blocked:
            feed = by_name.get((fb["name"], fb["folder"]))
            if not feed:
                continue
            content = via_relay(feed["url"]) or via_jina(feed["url"])
            time.sleep(1.5)  # free relays refuse bursts
            if not content:
                continue
            try:
                items = parse(content, feed)
            except Exception:
                continue
            if not items:
                continue
            failed.remove(fb)
            rescued += 1
            for a in items:
                key = a["link"] or a["title"]
                if a["when"] is None:
                    first = seen.get(key)
                    a["when"] = dt.datetime.fromisoformat(first) if first else now
                seen.setdefault(key, a["when"].isoformat())
                if since <= a["when"] <= now + dt.timedelta(hours=2):
                    articles.append(a)
        say(f"  rescued {rescued} of {len(blocked)}")
    cutoff = (now - dt.timedelta(days=10)).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    C.DATA.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen), encoding="utf-8")
    return articles, failed


# ============================================================================ grouping

STOP = set("""a an the and or of to in on for with at by from as is are was were be been its it this that
after over under into amid about up down new says said say will may can could would than more most less
news today live update updates latest india indian stock stocks share shares market markets ltd limited
check here why how what who when top key amp via report reports sees seen""".split())


def tokens(title):
    return {w for w in re.findall(r"[a-z0-9]+(?:\.\d+)?", title.lower())
            if w not in STOP and (len(w) > 2 or w.isdigit())}


def group(articles):
    """The same event in several papers becomes one story."""
    # exact duplicates first (same link or same headline)
    uniq, keys = [], set()
    for a in sorted(articles, key=lambda a: a["when"], reverse=True):
        k1, k2 = a["link"], re.sub(r"\W+", "", a["title"].lower())
        if (k1 and k1 in keys) or k2 in keys:
            continue
        keys.update({k1, k2})
        uniq.append(a)
    stories, index = [], {}
    for a in uniq:
        t = tokens(a["title"])
        best, best_score = None, 0
        counts = {}
        for w in t:
            for sid in index.get(w, ()):
                counts[sid] = counts.get(sid, 0) + 1
        for sid, inter in counts.items():
            score = inter / max(1, min(len(t), len(stories[sid]["tokens"])))
            same = (inter >= 3 and score >= 0.6) or (inter >= 4 and score >= 0.5)
            if same and score > best_score:
                best, best_score = sid, score
        if best is None:
            sid = len(stories)
            stories.append({"tokens": t, "items": [a]})
            for w in t:
                index.setdefault(w, []).append(sid)
        else:
            stories[best]["items"].append(a)
    out = []
    for i, s in enumerate(stories, 1):
        items = s["items"]
        lead = items[0]
        out.append({"id": i, "key": re.sub(r"\W+", "", items[-1]["title"].lower())[:120], "title": lead["title"],
                    "desc": max((x["desc"] for x in items), key=len),
                    "when": max(x["when"] for x in items),
                    "folder": lead["folder"],
                    "sources": [{"name": x["source"], "link": x["link"]} for x in items],
                    "outlets": len({x["source"] for x in items})})
    return out


# ============================================================================ AI steps

TAG_PROMPT = """Tag each news story for an Indian stock-market investor.
For every story reply with ONE line, exactly:  <id>|<category>|<companies>|<importance>|<sentiment>
- category: exactly one of:
{cats}
- companies: listed companies the story is mainly about, by common name (e.g. Tata Motors, HUL, Infosys),
  comma-separated; "-" if none.
- importance 1-5 for an Indian equity investor: 5 = market-moving (policy rates, big results surprises,
  major regulation, large M&A); 3 = useful sector/company news; 1 = minor or routine.
- sentiment for the companies/sector involved: + (positive), - (negative) or = (neutral/mixed).
Use "Not market-relevant" for gadget reviews, sports, lifestyle and anything an equity investor wouldn't care about.
A story about one company (results, dividend, buyback, split, order, plant, management change) goes in THAT
company's own industry - e.g. a chemicals maker's dividend is Chemicals. "Capital Markets & Wealth" is only for
brokers, AMCs, wealth managers, exchanges, depositories, registrars, rating agencies and SEBI market rules.
No other text.

STORIES (id | headline | feed folder):
{rows}
"""

EXPLAIN_PROMPT = """You are a senior Indian equity research analyst. For each of today's most important stories below,
explain it for a smart investor who hasn't followed the topic. Use the headline and description, plus
well-established background knowledge (how the business, sector or policy works) - but do NOT invent new
facts, figures or events about today's story.

For EACH story write exactly this block:
### [<id>]
Context: <one sentence, max 30 words, of background needed to understand it - skip textbook definitions>
Why it matters: <one or two sentences, max 40 words: the concrete impact - which companies or sector, which way, how much>
What to watch: <one sentence, max 20 words: the next signal or date to track>

Be precise and specific; name companies and numbers where the story gives them. No filler.

STORIES:
"""


def tag(stories, pool):
    lookup = {c.lower(): c for c in CATEGORIES}
    for i in range(0, len(stories), 100):
        batch = stories[i:i + 100]
        rows = "\n".join(f"{s['id']} | {s['title']} | {s['folder']}" for s in batch)
        text, _ = pool.ask(TAG_PROMPT.format(cats="\n".join(CATEGORIES), rows=rows),
                           label=f"sorting stories {i + 1}-{i + len(batch)} of {len(stories)}")
        got = {}
        for line in text.splitlines():
            parts = [p.strip() for p in line.strip().lstrip("-* ").split("|")]  # a trailing "-" is a sentiment
            if len(parts) >= 2 and parts[0].isdigit():
                got[int(parts[0])] = parts + [""] * 5
        for s in batch:
            p = got.get(s["id"])
            cat = lookup.get(p[1].lower()) if p else None
            if p and not cat:
                cat = next((c for c in CATEGORIES if p[1].lower() in c.lower() or c.lower() in p[1].lower()),
                           "Services & Others")
            s["category"] = cat or "Services & Others"
            comps = p[2] if p else "-"
            s["companies"] = [c.strip() for c in comps.split(",") if c.strip() and c.strip() != "-"]
            imp = re.search(r"[1-5]", p[3]) if p else None
            s["importance"] = int(imp.group(0)) if imp else 2
            sent = (p[4] if p else "").strip()[:1]
            s["sentiment"] = sent if sent in "+-=" and sent else "="
    own_sector(stories)


def own_sector(stories):
    """A story about one company belongs in that company's own sector (the AI sometimes files a chemicals
    maker's dividend under Capital Markets). Uses the sectors we already hold for listed companies."""
    try:
        from names import Resolver
        R = Resolver()
    except Exception as e:
        say(f"  (sector check skipped: {e})")
        return
    moved = 0
    for s in stories:
        if not s.get("companies") or s["category"] not in C.SECTORS + ["Markets & Flows", "IPOs, Deals & Funding"]:
            continue
        secs = {R.sector(c) for c in s["companies"]} - {""}
        if len(secs) != 1:
            continue
        sec = secs.pop()
        if sec in CATEGORIES and sec != s["category"] and \
                (s["category"] in C.SECTORS or len(s["companies"]) == 1):
            s["category"] = sec
            moved += 1
    if moved:
        say(f"  {moved} stories moved to their company's own sector")


def explain_top(stories, pool, n=12, cache=None):
    """Context / why it matters / what to watch for the day's most important stories.
    Explanations are remembered, so a later run only explains newly important stories."""
    top = sorted(stories, key=lambda s: (-s["importance"], -s["outlets"], -s["when"].timestamp()))[:n]
    if cache is not None:
        known = cache.setdefault("explain", {})
        fresh = [s for s in top if s["key"] not in known]
        if fresh:
            for e in explain_top(fresh, pool, n=len(fresh)):
                s = next(x for x in fresh if x["id"] == e["id"])
                known[s["key"]] = {k: e[k] for k in ("context", "why", "watch")}
        return [dict(known[s["key"]], id=s["id"]) for s in top if s["key"] in known]
    if not top:
        return []
    lines = [story_line(s) for s in top]
    text = ask_fitted(pool, EXPLAIN_PROMPT, lines, label="explaining top stories")
    out = []
    for block in re.split(r"^###\s*", text, flags=re.M):
        m = re.match(r"\[?(\d+)\]?", block.strip())
        if not m:
            continue

        def field(name):
            f = re.search(rf"{name}:\s*(.+?)(?=\n\s*(?:Context|Why it matters|What to watch):|\Z)", block, re.S | re.I)
            return re.sub(r"\s+", " ", f.group(1)).strip() if f else ""

        out.append({"id": int(m.group(1)), "context": field("Context"), "why": field("Why it matters"),
                    "watch": field("What to watch")})
    known = {s["id"] for s in top}
    return [o for o in out if o["id"] in known]


def story_line(s):
    d = f" - {s['desc']}" if s["desc"] else ""
    return f"[{s['id']}] {s['title']}{d} ({s['outlets']} outlet{'s' if s['outlets'] > 1 else ''})"


def ask_fitted(pool, head, lines, label):
    """One request if the provider can take it all; otherwise in parts, then merged."""
    def job(ai):
        body = "\n".join(lines)
        budget = ai.max_input_tokens
        if not budget or C.est_tokens(head + body) <= budget:
            return ai.ask(head + body, label=label)
        room = max(2000, (budget - 1500) * 4 - len(head))
        parts, cur = [], ""
        for ln in lines:
            if cur and len(cur) + len(ln) > room:
                parts.append(cur)
                cur = ""
            cur += ln + "\n"
        parts.append(cur)
        notes = [ai.ask(head + f"(Part {i} of {len(parts)} - cover just these.)\n" + p,
                        label=f"{label} {i}/{len(parts)}") for i, p in enumerate(parts, 1)]
        merged = "\n\n".join(notes)[:max(2000, (budget - 800) * 4)]
        if len(parts) > 1 and head is EXPLAIN_PROMPT:
            return merged  # explainer blocks are independent - no merge needed
        return ai.ask("Merge these partial briefs into ONE brief with the same headings. Remove repetition, "
                      "keep the [ids], don't add anything new:\n\n" + merged, label=f"{label} (merging)")
    return pool.run(job)[0]


# ============================================================================ output

BRIEF_DIR = C.DATA / "news"


def md_html(text):
    """Markdown -> HTML; [12, 40] become story chips the website makes clickable."""
    h = C.md(text)
    return re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]",
                  lambda m: "".join(f'<a class="r" data-id="{n}">{int(n) % 100000}</a>' for n in re.findall(r"\d+", m.group(1))), h)


def newer_export(opml):
    """On the tablet: if you exported a fresher OPML from FeedFlow into Download, use it."""
    from pathlib import Path
    dl = Path.home() / "storage" / "shared" / "Download"
    if not C.IS_TABLET or not dl.exists():
        return
    exports = sorted(dl.glob("feedflow-export*.opml"), key=lambda p: p.stat().st_mtime)
    if exports and (not opml.exists() or exports[-1].stat().st_mtime > opml.stat().st_mtime):
        shutil.copy(exports[-1], opml)
        say(f"Using your latest FeedFlow export: {exports[-1].name}")


CACHE_FILE = C.DATA / "news_cache.json"


def load_cache():
    c = json.loads(CACHE_FILE.read_text(encoding="utf-8")) if CACHE_FILE.exists() else {}
    if c.get("version") != 2:  # v1 recorded negative stories as neutral - start fresh
        c = {"next_id": c.get("next_id", 1), "ids": c.get("ids", {}), "version": 2}
    for k in ("ids", "tags", "explain", "sections", "seen", "extract", "listed"):
        c.setdefault(k, {})
    c.setdefault("next_id", 1)
    return c


def save_cache(c, now):
    cutoff = (now - dt.timedelta(days=3)).isoformat()
    old = {k for k, v in c["seen"].items() if v < cutoff}
    for part in ("ids", "tags", "explain", "seen", "extract"):
        c[part] = {k: v for k, v in c[part].items() if k not in old}
    CACHE_FILE.write_text(json.dumps(c, ensure_ascii=False), encoding="utf-8")


def build(conf=None, log_failed=True):
    """Builds today's brief. Returns the saved brief dict, or None."""
    conf = conf or settings()
    opml = C.here(conf["opml"])
    newer_export(opml)
    if not opml.exists():
        say(f"\nFeed list not found: {opml}\nExport your feeds from FeedFlow (Settings > Export OPML), "
            f"save the file in this folder as feeds.opml, and try again.")
        return None
    tab_folders = {f for fs in conf["tabs"].values() for f in fs}
    feeds = read_opml(opml, conf["skip"] + list(tab_folders))
    if conf["google"]:
        feeds += google_feeds()
    say(f"\nMorning brief: reading {len(feeds)} feeds (skipping folders: {', '.join(conf['skip']) or 'none'})")
    articles, failed = collect(feeds, conf["hours"])
    stories = group(articles)
    say(f"  {len(articles)} articles in the last {conf['hours']}h -> {len(stories)} distinct stories "
        f"after merging duplicates. {len(failed)} feed(s) not readable.")
    if not stories:
        say("Nothing new to summarise.")
        return None
    try:
        pool = C.Pool()
        bulk = C.Pool(bulk=True)  # tagging and tab write-ups: Mistral first, keeping Gemini for the brief itself
        say("Checking the AI connection ...")
        pool.ask("Reply with exactly: OK", label="check", max_wait=45)
    except C.AIError as e:
        say(f"  PROBLEM: {e}")
        return None

    cache = load_cache()
    now_utc = dt.datetime.now(dt.timezone.utc)
    used = set()
    for s in stories:  # stable ids, so links and remembered write-ups stay valid between runs
        sid = cache["ids"].get(s["key"])
        if sid is None or sid in used:
            sid = cache["next_id"]
            cache["next_id"] += 1
            cache["ids"][s["key"]] = sid
        s["id"] = sid
        used.add(sid)
        cache["seen"][s["key"]] = now_utc.isoformat()
    fresh = [s for s in stories if s["key"] not in cache["tags"]]
    for s in stories:
        if s["key"] in cache["tags"]:
            s.update(cache["tags"][s["key"]])
    say(f"\nSorting stories by sector, company, importance and sentiment ({len(fresh)} new, "
        f"{len(stories) - len(fresh)} remembered from earlier runs) ...")
    if fresh:
        tag(fresh, bulk)
        for s in fresh:
            cache["tags"][s["key"]] = {k: s[k] for k in ("category", "companies", "importance", "sentiment")}
    fk = {s["key"] for s in fresh}
    own_sector([s for s in stories if s["key"] not in fk])  # earlier-tagged stories too (cheap, no AI)
    save_cache(cache, now_utc)
    relevant = [s for s in stories if s["category"] != "Not market-relevant"]
    by_cat = {}
    for s in relevant:
        by_cat.setdefault(s["category"], []).append(s)
    for v in by_cat.values():
        v.sort(key=lambda s: (-s["importance"], -s["outlets"], -s["when"].timestamp()))
    cats = sorted(by_cat, key=lambda c: -len(by_cat[c]))
    say(f"  {len(relevant)} market-relevant stories in {len(cats)} sectors/topics "
        f"({len(stories) - len(relevant)} set aside as not market-relevant).")

    say("\nExplaining the most important stories ...")
    try:
        top = explain_top(relevant, pool, cache=cache)
    except C.AIError as e:
        say(f"    failed: {e}")
        top = []
    time.sleep(pool.pause)

    try:  # results, order wins, broker calls and dated events -> data/trackers.json
        import trackers
        trackers.update(relevant, pool, cache, now_utc)
        save_cache(cache, now_utc)
    except Exception as e:
        say(f"  trackers skipped: {str(e)[:150]}")

    sections = {}
    todo = [c for c in cats if len(by_cat[c]) >= conf["min_stories"]]
    say(f"\nWriting {len(todo)} sector briefs ...")
    for i, c in enumerate(todo, 1):
        keys = [s["key"] for s in by_cat[c]]
        prev = cache["sections"].get(c)
        new = len(set(keys) - set(prev["keys"])) if prev else len(keys)
        if prev and new < max(2, 0.2 * len(keys)):
            sections[c] = prev["text"]  # little has changed - keep the earlier write-up
            say(f"[{i}/{len(todo)}] {c}: {new} new stor{'y' if new == 1 else 'ies'} - keeping the earlier write-up")
            continue
        say(f"[{i}/{len(todo)}] {c} ({len(by_cat[c])} stories, {new} new)")
        head = SECTION_PROMPT.format(cat=c, n=len(by_cat[c][:250]), hours=conf["hours"])
        try:
            sections[c] = ask_fitted(pool, head, [story_line(s) for s in by_cat[c][:250]], label=c)
            cache["sections"][c] = {"keys": keys, "text": sections[c]}
            save_cache(cache, now_utc)
        except C.QuotaOver as e:
            say(f"\n{e}")
            break
        except C.AIError as e:
            say(f"    failed: {e}")
        time.sleep(pool.pause)

    big = ""
    now = dt.datetime.now(IST)
    label = now.strftime("%a %d %b %Y")
    if sections:
        say("\nWriting the big picture ...")
        lines = [f"### {c}\n{sections[c]}\n" for c in cats if c in sections]
        try:
            big = ask_fitted(pool, BIG_PROMPT.format(date=label, n=len(relevant), hours=conf["hours"]), lines,
                             label="big picture")
            big = re.sub(r"^\s*#+\s*(Morning brief.*|The big picture)\s*$", "", big, count=2,
                         flags=re.M | re.I).strip()
        except C.AIError as e:
            say(f"    failed: {e}")
    big_html, big_from = md_html(big) if big else "", ""
    if not big_html:  # AI out of quota: keep the latest big picture on show, saying which day it is from
        for f in sorted(BRIEF_DIR.glob("*.json"), reverse=True):
            try:
                ob = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue
            if ob.get("big"):
                big_html = ob["big"]
                if ob.get("date") != now.strftime("%Y-%m-%d"):  # its [ids] point at that day's stories - drop them
                    big_html = re.sub(r'<a class="r" data-id="\d+">\d+</a>', "", big_html)
                big_from = ob.get("bigFrom") or ("" if ob.get("date") == now.strftime("%Y-%m-%d") else ob.get("label", ob.get("date", "")))
                say(f"  showing the big picture from {big_from or 'earlier today'} until the AI is free again")
                break

    out_sections = []
    for c in cats:
        items = by_cat[c]
        text = sections.get(c, "")
        one = ""
        m = re.search(r"\*\*In one line:\*\*\s*(.+)", text)
        if m:
            one = md_html(m.group(1)).replace("<p>", "").replace("</p>", "")
            text = text.replace(m.group(0), "")
        out_sections.append({"cat": c, "one": one, "html": md_html(text) if text else "",
                             "ids": [s["id"] for s in items],
                             "pos": sum(s["sentiment"] == "+" for s in items),
                             "neg": sum(s["sentiment"] == "-" for s in items),
                             "neu": sum(s["sentiment"] == "=" for s in items)})
    brief = {
        "date": now.strftime("%Y-%m-%d"), "label": label, "built": now.isoformat(timespec="minutes"),
        "hours": conf["hours"],
        "stats": {"feeds": len(feeds), "articles": len(articles), "stories": len(stories),
                  "relevant": len(relevant), "failed": len(failed),
                  "sources": len({x["name"] for s in relevant for x in s["sources"]})},
        "big": big_html, "bigFrom": big_from, "top": top, "sections": out_sections,
        "stories": [{"id": s["id"], "title": s["title"], "desc": s["desc"],
                     "when": s["when"].astimezone(IST).isoformat(timespec="minutes"),
                     "cat": s["category"], "companies": s["companies"], "imp": s["importance"],
                     "sent": s["sentiment"], "outlets": s["outlets"], "sources": s["sources"]}
                    for s in relevant],
        "failed": failed if log_failed else [],
        "tabs": [],
    }
    for t_i, (tab, folders) in enumerate(conf["tabs"].items(), 1):
        try:
            brief["tabs"].append(build_tab(tab, folders, opml, conf, bulk, cache, t_i * 100000))
        except Exception as e:
            say(f"  {tab} tab failed: {e}")
    save_cache(cache, now_utc)
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    path = BRIEF_DIR / f"{brief['date']}.json"
    path.write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
    for old in sorted(BRIEF_DIR.glob("*.json"))[:-90]:  # full briefs: ~3 months; their big picture is kept for good
        try:
            ob = json.loads(old.read_text(encoding="utf-8"))
            arch_path = C.DATA / "news_archive.json"
            arch = json.loads(arch_path.read_text(encoding="utf-8")) if arch_path.exists() else []
            if not any(a["date"] == ob["date"] for a in arch):
                arch.append({"date": ob["date"], "label": ob.get("label", ob["date"]), "big": ob.get("big", ""),
                             "stories": ob.get("stats", {}).get("relevant", 0),
                             "top": [s["title"] for s in sorted(ob.get("stories", []), key=lambda x: -(x.get("imp") or 0))[:8]]})
                arch_path.write_text(json.dumps(sorted(arch, key=lambda a: a["date"]), ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        old.unlink()
    say(f"\nSaved the brief: data/news/{path.name}")
    return brief


TAB_PROMPT = """You are writing the "{tab}" page of an Indian investor's daily briefing, from {n} stories in
enthusiast and industry media over the last {hours} hours. Each story has an id in brackets, the headline,
a short description (often missing) and how many outlets covered it.

Write in Markdown, using ONLY these stories. Put the ids after each point, like [12] or [12, 40].
Merge duplicates, skip trivia and pure reviews unless they matter.

**In one line:** <the most important thing today>
### The big stories
(4-6 bullets)
### Launches & products
(bullets: what launched, by whom, price/positioning if given)
### The market angle
(bullets: what this means for LISTED companies - name them - e.g. a launch, price cut, sales data,
supply-chain or policy news. Skip if nothing relevant.)
### Worth reading
(2-4 stories with substance, one line on why)

STORIES:
"""


SPORTS_PROMPT = """You are writing the "{tab}" page of a cricket fan's daily briefing, from {n} stories in
sports media over the last {hours} hours. Each story has an id in brackets, the headline, a short
description (often missing) and how many outlets covered it. The reader follows CRICKET ONLY:
ignore every story about other sports.

Write in Markdown, using ONLY these stories. Put the ids after each point, like [12] or [12, 40].
Merge duplicates (live-score updates of the same match are one item). India first.

**In one line:** <the biggest cricket story today>
### Results & scores
(bullets: match, result, standout performance - only what the stories state)
### The big stories
(3-6 bullets: selection, injuries, records, controversies, IPL/WPL auctions and transfers)
### Coming up
(bullets: matches or series in the next few days mentioned in the stories. Skip if none.)

STORIES:
"""


def build_tab(tab, folders, opml, conf, pool, cache, offset):
    """A separate tab (e.g. Tech, Auto): no per-story AI tagging - stories are merged and ranked by
    coverage, then ONE AI digest. Reused while little has changed, so it costs ~1 request a run."""
    feeds = [f for f in read_opml(opml, []) if f["folder"].lower() in folders]
    if conf["google"]:
        feeds += google_feeds(tab)
    if not feeds:
        return {"name": tab, "html": "", "one": "", "stories": [], "stats": {"feeds": 0}}
    say(f"\n{tab} tab: reading {len(feeds)} feeds ...")
    articles, failed = collect(feeds, conf["hours"])
    stories = group(articles)
    for i, s in enumerate(stories, 1):
        s["id"] = offset + i
    stories.sort(key=lambda s: (-s["outlets"], -s["when"].timestamp()))
    top = stories[:150]
    keys = [s["key"] for s in top]
    prev = cache["sections"].get("tab:" + tab)
    text = ""

    def earlier():
        # the earlier write-up, with its [ids] pointed at today's numbering (stories gone since lose their link)
        remap = {old: next((s["id"] for s in top if s["key"] == k), None) for old, k in prev.get("idmap", {}).items()}
        return re.sub(r"\[(\d+(?:\s*,\s*\d+)*)\]", lambda m: "[" + ", ".join(
            str(remap[n]) for n in re.findall(r"\d+", m.group(1)) if remap.get(n)) + "]", prev["text"]).replace("[]", "")

    if prev and len(set(keys) - set(prev["keys"])) < max(8, 0.25 * len(keys)):
        text = earlier()
        say(f"  little new - keeping the earlier {tab} digest")
    elif top:
        try:
            prompt = SPORTS_PROMPT if "sport" in tab.lower() else TAB_PROMPT
            text = ask_fitted(pool, prompt.format(tab=tab, n=len(top), hours=conf["hours"]),
                              [story_line(s) for s in top], label=f"{tab} digest")
            cache["sections"]["tab:" + tab] = {"keys": keys, "text": text,
                                               "idmap": {str(s["id"]): s["key"] for s in top}}
        except C.AIError as e:
            say(f"  {tab} digest failed: {e}")
            if prev and prev.get("text"):   # AI out of quota: show the last write-up rather than a bare list
                text = earlier()
                say(f"  showing the earlier {tab} digest until the AI is free again")
    one = ""
    m = re.search(r"\*\*In one line:\*\*\s*(.+)", text)
    if m:
        one = md_html(m.group(1)).replace("<p>", "").replace("</p>", "")
        text = text.replace(m.group(0), "")
    return {"name": tab, "one": one, "html": md_html(text) if text else "",
            "stats": {"feeds": len(feeds), "articles": len(articles), "stories": len(stories), "failed": len(failed)},
            "failed": failed,
            "stories": [{"id": s["id"], "title": s["title"], "desc": s["desc"],
                         "when": s["when"].astimezone(IST).isoformat(timespec="minutes"),
                         "outlets": s["outlets"], "sources": s["sources"], "cat": tab, "companies": [],
                         "imp": 0, "sent": "="} for s in top]}


def run(open_page=True):
    """Menu / command line: build today's brief and refresh the website."""
    brief = build()
    if brief is None:
        return
    import site_builder
    site_builder.build()
    if open_page:
        site_builder.open_site("#today")
    notify(f"Morning brief ready: {brief['stats']['relevant']} stories")


def notify(text):
    if C.IS_TABLET and shutil.which("termux-notification"):
        try:
            subprocess.run(["termux-notification", "--title", "Morning brief", "--content", text], timeout=10)
        except Exception:
            pass


if __name__ == "__main__":
    C.disable_quickedit()
    C.wake_lock(True)
    try:
        run(open_page="--quiet" not in sys.argv)
    finally:
        C.wake_lock(False)
