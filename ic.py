"""Initiating coverage, from the news.

Brokerages' initiation reports are mostly behind logins, but NDTV Profit, ET Now, CNBC-TV18, Moneycontrol etc.
write them up: broker, rating, target and the thesis. This picks those stories out of each news run, reads the
article itself (not just the headline), and keeps one tidy note per initiation for good:

  data/ic.json  {"seen": {story key: date}, "items": [ {uid, date, scope, company, sector, broker, rating,
                 target, upside, thesis[], numbers[], risks[], picks[], title, link} ]}

Facts only: every figure in a note must appear in the article, or that line is dropped.
One AI request per run (all new articles together), at most `limit` articles.
"""
import datetime as dt
import html as htmllib
import json
import re

import requests

import concalls as C
from concalls import say

FILE = C.DATA / "ic.json"
PAT = re.compile(
    r"initiat\w*\s+(?:a\s+)?(?:research\s+)?coverage|coverage\s+initiat|initiat\w*\s+(?:on|with)\b.{0,60}\b(?:buy|sell|add|hold|"
    r"accumulate|outperform|overweight|underweight|neutral|reduce)\b|\binitiates?\b.{0,40}\btarget\b", re.I)

PROMPT = """Below are news articles about Indian brokerages INITIATING research coverage on a listed company,
a sector or a theme. For each article return one JSON object:
{{"id": <article id>, "scope": "company" | "sector" | "theme",
 "company": "<listed company, or empty for sector/theme reports>",
 "sector": "<the sector or theme the report is about, for sector/theme reports; else empty>",
 "broker": "<brokerage>", "rating": "<Buy/Add/Hold/Reduce/Sell/...>", "target": <target price in Rs or null>,
 "upside": <upside % or null>,
 "thesis": ["<up to 4 points: why the broker likes/dislikes it, max 22 words each>"],
 "numbers": ["<up to 3 key estimates the article states, e.g. 'Revenue CAGR 18% over FY26-28E'>"],
 "risks": ["<up to 2 risks the article states>"],
 "picks": ["<sector/theme reports only: up to 6 'Company - rating' the article names>"]}}
If an article has SEVERAL initiations (e.g. a sector report on five companies), give one object per company
(same id) only if the article gives a rating for each; otherwise one sector object with picks.
If the article is not actually about a NEW coverage initiation, return {{"id": <id>, "skip": true}}.
STRICT: use only what the article says. Never add numbers, targets or reasons that are not in the text.
Use null / [] for anything not stated. Reply with a JSON array only, nothing else.

ARTICLES:
{articles}
"""


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"seen": {}, "items": []}


def save(d):
    FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _html_text(raw):
    raw = re.sub(r"(?is)<(script|style|noscript|svg|header|footer|nav|aside)\b.*?</\1>", " ", raw)
    paras = re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", raw)
    text = "\n".join(htmllib.unescape(re.sub(r"<[^>]+>", " ", p)) for p in paras)
    return re.sub(r"[ \t]+", " ", text).strip()


def article_text(sources):
    """The article itself: the publisher page first, the Jina reader as a fallback (it also follows
    Google News links). Returns '' if nothing readable."""
    import news
    links = [x["link"] for x in sources if x.get("link")]
    links.sort(key=lambda u: "news.google." in u)  # publisher links before Google News redirects
    for url in links[:3]:
        if "news.google." not in url:
            raw, err = news.fetch(url)
            if raw:
                t = _html_text(raw.decode("utf-8", "ignore"))
                if len(t) > 600:
                    return t[:7000]
        try:
            r = requests.get("https://r.jina.ai/" + url, headers={"X-Return-Format": "text"}, timeout=45)
            if r.status_code == 200 and len(r.text) > 600:
                return r.text[:7000]
        except Exception:
            pass
    return ""


def _nums(s):
    return re.findall(r"\d+(?:\.\d+)?", s.replace(",", ""))


def _grounded(line, text):
    """Every number in the line must appear in the article (commas ignored)."""
    flat = text.replace(",", "")
    return all(n in flat for n in _nums(line) if len(n) > 1 or n not in "0123456789")


def _num(v):
    try:
        return float(str(v).replace(",", "").replace("Rs", "").strip())
    except (TypeError, ValueError):
        return None


def candidates(stories):
    return [s for s in stories if PAT.search(s["title"] + " " + (s.get("desc") or ""))]


def step(stories, pool, limit=12):
    """Picks new initiation stories out of this run, reads them, files the notes. Returns today's new notes."""
    d = load()
    todo = [s for s in candidates(stories) if s["key"] not in d["seen"]][:limit]
    if not todo:
        return []
    say(f"\nReading {len(todo)} initiating-coverage articles ...")
    texts = {}
    for i, s in enumerate(todo, 1):
        t = article_text(s["sources"])
        texts[i] = t or (s["title"] + ". " + (s.get("desc") or ""))
        say(f"  {i}. {s['title'][:80]} ({'article' if t else 'headline only'})")
    arts = "\n\n".join(f"[{i}] {s['title']}\n{texts[i]}" for i, s in enumerate(todo, 1))
    try:
        out, ai = pool.ask(PROMPT.format(articles=arts), label="initiating coverage")
    except C.AIError as e:
        say(f"  initiating coverage: AI unavailable ({str(e)[:80]}) - next run")
        return []
    m = re.search(r"\[.*\]", out, re.S)
    try:
        got = json.loads(m.group(0)) if m else []
    except Exception:
        got = []
    try:
        from names import Resolver
        R = Resolver()
    except Exception:
        R = None
    new, have = [], {x["uid"] for x in d["items"]}
    for o in got:
        try:
            i = int(o.get("id"))
        except (TypeError, ValueError):
            continue
        if not (1 <= i <= len(todo)) or o.get("skip"):
            continue
        s, text = todo[i - 1], texts[i]
        broker = (o.get("broker") or "").strip()
        company = (o.get("company") or "").strip()
        if R and company:
            company = R.resolve(company)[0] or company
        subject = company or (o.get("sector") or "").strip()
        if not broker or not subject:
            continue
        keep = lambda xs, n: [x.strip() for x in (xs or []) if isinstance(x, str) and x.strip() and _grounded(x, text)][:n]
        target, upside = _num(o.get("target")), _num(o.get("upside"))
        if target is not None and not _grounded(f"{target:g}", text):
            target = None
        if upside is not None and not _grounded(f"{upside:g}", text):
            upside = None
        date = s["when"].strftime("%Y-%m-%d")
        rec = {"uid": f"{C.norm(subject)}|{C.norm(broker)}|{date[:7]}", "date": date,
               "scope": o.get("scope") or ("company" if company else "sector"),
               "company": company, "sector": (R.sector(company) if R and company else "") or (o.get("sector") or "").strip()
               or s.get("category", ""), "broker": broker, "rating": (o.get("rating") or "").strip().title(),
               "target": target, "upside": upside, "thesis": keep(o.get("thesis"), 4), "numbers": keep(o.get("numbers"), 3),
               "risks": keep(o.get("risks"), 2), "picks": keep(o.get("picks"), 6),
               "title": s["title"][:200], "link": next((x["link"] for x in s["sources"] if "news.google." not in x["link"]),
                                                     s["sources"][0]["link"] if s["sources"] else ""),
               "src": "article" if texts[i] != s["title"] + ". " + (s.get("desc") or "") else "headline"}
        if rec["uid"] in have:
            continue
        have.add(rec["uid"])
        d["items"].append(rec)
        new.append(rec)
    for s in todo:
        d["seen"][s["key"]] = s["when"].strftime("%Y-%m-%d")
    cut = (dt.date.today() - dt.timedelta(days=60)).isoformat()
    d["seen"] = {k: v for k, v in d["seen"].items() if v >= cut}
    d["items"].sort(key=lambda x: x["date"], reverse=True)
    save(d)
    say(f"  initiating coverage: {len(new)} new notes ({ai.model})")
    return new


def big_lines(new):
    """Today's initiations as extra input for the big picture."""
    if not new:
        return []
    rows = []
    for r in new[:8]:
        head = f"{r['broker']} initiates on {r['company'] or r['sector']}: {r['rating']}" + (
            f", target Rs {r['target']:,.0f}" if r.get("target") else "") + (f" ({r['upside']:g}% upside)" if r.get("upside") else "")
        rows.append(head + (" - " + "; ".join(r["thesis"][:2]) if r["thesis"] else ""))
    return ["### New broker coverage (initiations today)\n" + "\n".join("- " + x for x in rows) + "\n"]
