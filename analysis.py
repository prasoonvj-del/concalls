#!/usr/bin/env python3
"""
Analysis & deep dives - a lane of its own, apart from the 24-hour news.

Reads the analysts, newsletters and deep-dive sections in analysis_feeds.txt (Substacks, Zerodha's newsletters,
BusinessLine's deep dives, research blogs, rating-agency and brokerage sector views), keeps 4 months of them, and
sorts each new piece once with the cheap model (batches of 10): how substantive it is, what kind (company, comparison,
sector, policy, macro...), the companies and sectors it is about, and a 1-2 line takeaway in its own words.
The article text itself is only read for that, never shown - the site shows the title, the link and the takeaway.

Used by: the Analysis page, "Worth reading" on company and sector pages, "Deep dives this week" on Today, and as a
secondary source for "Where the industry is heading".
"""
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import re
import time
from urllib.parse import quote_plus

import concalls as C
from concalls import say

FILE = C.DATA / "analysis.json"
FEEDS = C.here("analysis_feeds.txt")
KEEP_DAYS = 120
PER_RUN = 150  # new pieces sorted per run (15 cheap requests; the backlog clears in a few runs)
KINDS = ("company", "comparison", "sector", "policy", "macro", "global", "technical", "other")

PROMPT = """You sort analysis articles for an Indian equity investor's research desk.
For each article below (id, source, title, opening text) answer ONE line, fields separated by " | ", no other text:
<id> | <score 1-5> | <kind> | <companies> | <sectors> | <takeaway>
- score: 5 = deep, specific analysis of Indian listed companies, sectors or policy with numbers; 4 = useful analysis;
  3 = some insight; 2 = thin / generic; 1 = promotional, personal-finance tips, listicles, unrelated to markets
- kind: one of company, comparison (two or more companies against each other), sector, policy, macro, global,
  technical (charts), other
- companies: Indian listed companies the article is mainly about, full names separated by ";" (max 5), or - .
  Not the brokerage, rating agency or publisher that wrote or is quoted, unless the article is about that firm itself
- sectors: from this list only, separated by ";" (max 3), or -
{sectors}
- takeaway: 1-2 sentences in your own words - the specific argument or finding with its key numbers. Never copy
  sentences from the text. No "|" inside it.

ARTICLES:
{rows}"""


def load():
    if FILE.exists():
        try:
            return json.loads(FILE.read_text(encoding="utf-8"))
        except ValueError:
            pass
    return {"items": {}}


def feeds():
    out = []
    for ln in FEEDS.read_text(encoding="utf-8").splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#"):
            continue
        p = [x.strip() for x in ln.split("|")]
        if len(p) < 3:
            continue
        group, name, url = p[0], p[1], "|".join(p[2:])
        if url.lower().startswith("search:"):  # Google News search, last 7 days
            q = url[7:].strip()
            url = f"https://news.google.com/rss/search?q={quote_plus(q + ' when:7d')}&hl=en-IN&gl=IN&ceid=IN:en"
        out.append({"group": group, "name": name, "url": url, "folder": group})
    return out


def urls():
    """Feed addresses read here - the news brief leaves them out (see news.collect)."""
    try:
        return {f["url"] for f in feeds()}
    except OSError:
        return set()


def _text(e):
    import news
    body = ""
    for c in e.get("content") or []:
        body += " " + (c.get("value") or "")
    body = body or e.get("summary") or e.get("description") or ""
    return news.clean(body, 1500)


def _parse(content, feed):
    import feedparser
    import news
    d = feedparser.parse(content)
    out = []
    for e in d.entries[:40]:
        title = news.clean(e.get("title", ""))
        link = e.get("link", "")
        if not title or not link:
            continue
        source = feed["name"]
        if "news.google." in feed["url"]:
            m = re.match(r"^(.*\S)\s+[-–]\s+([^-–]{2,60})$", title)
            if m:
                title, source = m.group(1), m.group(2)
        ts = e.get("published_parsed") or e.get("updated_parsed")
        when = dt.datetime(*ts[:6]).date().isoformat() if ts else dt.date.today().isoformat()
        text = "" if "news.google." in feed["url"] else _text(e)
        out.append({"t": title, "l": link, "s": source, "g": feed["group"], "d": when, "body": text})
    return out


def collect(fs):
    import news
    got, failed = [], []

    def one(f):
        content, err = news.fetch(f["url"])
        if err and err.startswith(("HTTP 403", "HTTP 429", "HTTP 503")):
            content = news.via_relay(f["url"]) or news.via_jina(f["url"])
            err = None if content else err
        if err or not content:
            return f, [], err or "no content"
        try:
            items = _parse(content, f)
        except Exception as e:
            return f, [], f"unreadable ({type(e).__name__})"
        return f, items, None if items else "empty feed"
    with cf.ThreadPoolExecutor(max_workers=12) as pool:
        for f, items, err in pool.map(one, fs):
            if err:
                failed.append(f"{f['name']} ({err})")
            got += items
    return got, failed


def _key(it):
    return hashlib.sha1((it["l"].split("?")[0] if "news.google." not in it["l"] else it["t"]).encode()).hexdigest()[:14]


def _sort(pool, batch):
    rows = "\n".join(f"{k} | {it['s']} | {it['t']}" + (f" -- {it['body'][:900]}" if it.get("body") else "")
                     for k, it in batch)
    out = pool.ask(PROMPT.format(sectors="\n".join(C.SECTORS), rows=rows), label="analysis")[0]
    res = {}
    for ln in out.splitlines():
        p = [x.strip() for x in ln.strip().strip("-*").split("|")]
        if len(p) < 6 or p[0] not in dict(batch):
            continue
        try:
            score = int(re.sub(r"\D", "", p[1])[:1] or 0)
        except ValueError:
            score = 0
        kind = p[2].lower().split()[0] if p[2] else "other"
        cos = [x.strip() for x in p[3].split(";") if x.strip() and x.strip() != "-"][:5]
        secs = [x.strip() for x in p[4].split(";") if x.strip() in C.SECTORS][:3]
        res[p[0]] = {"r": score, "k": kind if kind in KINDS else "other", "c": cos, "sec": secs,
                     "x": " | ".join(p[5:]).strip()[:400]}
    return res


def step(deadline=None):
    d = load()
    items = d.setdefault("items", {})
    fs = feeds()
    got, failed = collect(fs)
    cut = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    titles = {re.sub(r"\W+", " ", v["t"].lower()).strip() for v in items.values()}
    new = 0
    for it in got:
        if it["d"] < cut:
            continue
        k = _key(it)
        tk = re.sub(r"\W+", " ", it["t"].lower()).strip()
        if k in items or tk in titles:
            continue
        titles.add(tk)
        items[k] = dict(it, at=dt.date.today().isoformat())
        new += 1
    # sort the unsorted ones, newest first
    todo = sorted([(k, v) for k, v in items.items() if "r" not in v], key=lambda kv: kv[1]["d"], reverse=True)[:PER_RUN]
    done = 0
    if todo:
        pool = C.Pool(bulk=True)
        import names
        res_ = names.Resolver()
        for i in range(0, len(todo), 10):
            if deadline and time.time() > deadline:
                break
            batch = todo[i:i + 10]
            try:
                res = _sort(pool, batch)
            except C.QuotaOver:
                break
            except Exception as e:
                say(f"  analysis: a batch failed ({str(e)[:80]})")
                continue
            for k, v in batch:
                r = res.get(k)
                if not r:  # the model skipped it: try once more next run, then let it go
                    v["miss"] = v.get("miss", 0) + 1
                    if v["miss"] >= 2:
                        v["r"] = 0
                        v.pop("body", None)
                    continue
                v.update(r)
                v["cc"] = [res_.resolve(c)[1] for c in r["c"]]
                v["c"] = [res_.resolve(c)[0] for c in r["c"]]
                v.pop("body", None)
                done += 1
            time.sleep(pool.pause)
    for k in [k for k, v in items.items() if v["d"] < cut]:
        del items[k]
    FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    say(f"  analysis & deep dives: {len(fs) - len(failed)}/{len(fs)} feeds read, {new} new pieces, {done} sorted, "
        f"{sum(1 for v in items.values() if v.get('r', 0) >= 3)} worth reading kept")
    if failed:
        say("    feeds not read: " + "; ".join(failed[:25]))
    return done


def for_industry(sector, industry=None, days=120, n=12):
    """Takeaways of substantive pieces on this sector (or its companies) - secondary sources for the direction."""
    try:
        items = load()["items"].values()
    except Exception:
        return ""
    cut = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    pick = [v for v in items if v.get("r", 0) >= 4 and v["d"] >= cut and sector in (v.get("sec") or [])
            and v.get("k") in ("company", "comparison", "sector", "policy")]
    pick.sort(key=lambda v: (v["r"], v["d"]), reverse=True)
    rows = [f"- {v['d']} {v['s']} ({v['k']}): {v['x']}" for v in pick[:n]]
    return ("\n\nANALYSIS PIECES ON THIS SECTOR (secondary: press and independent analysts - use only to support or "
            "question the companies' own evidence; cite as [<source> analysis, <Mon YYYY>]):\n" + "\n".join(rows)) if rows else ""


def site_data():
    d = load()
    cut = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    out = [{k2: v.get(k2) for k2 in ("t", "l", "s", "g", "d", "k", "c", "cc", "sec", "x", "r")}
           for v in d.get("items", {}).values() if v.get("r", 0) >= 3 and v["d"] >= cut]
    out.sort(key=lambda v: v["d"], reverse=True)
    return out


if __name__ == "__main__":
    step()
