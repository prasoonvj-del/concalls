#!/usr/bin/env python3
"""
Short AI summaries of investor presentations (decks) filed on BSE -> data/deck_summaries.json

AI limits are managed, not fixed:
  * every deck is summarised once and remembered; scanned (image-only) decks never reach the AI
  * a queue decides what's worth it first: watchlist > companies with a concall summary >
    companies in today's news > the rest, newest first
  * each update gets a small allowance (full updates more, news-only updates less), plus a ceiling per day
  * it stops at once if Gemini says the free quota is used up, or if Gemini is down and the
    backup AI has taken over (the backup is kept for concalls and news)
"""
import datetime as dt
import json
import re
import shutil
import tempfile
import time
from pathlib import Path

import concalls as C

say = C.say
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
DECK_SUMS = C.DATA / "deck_summaries.json"
ALLOWANCE = {"full": (25, 12), "news": (6, 5)}  # (decks, minutes) per update
DAILY_CEILING = 70
MAX_CHARS = 24000

DECK_PROMPT = """You are an equity analyst. Below is the text of an investor presentation (slides) by {company}.
{concall}Summarise it for an investor in Markdown, about 200 words, using ONLY facts in the slides:

**In one line:** <the single most important message of the deck>
### Key numbers
(3-6 bullets: revenue, growth, margins, profit, volumes, order book, net debt - with the period)
### Business & segments
(2-4 bullets: what drove the numbers, segment or geography mix)
### Targets & guidance
(bullets: medium-term targets, capex plans, capacity additions, timelines. Skip if none.)
{extra}
Use Rs crore where the deck does. If the slides are mostly pictures with little text, say so in one line.

SLIDES:
"""


def load():
    try:
        return json.loads(DECK_SUMS.read_text(encoding="utf-8")) if DECK_SUMS.exists() else {}
    except ValueError:
        return {}


def save(d):
    C.DATA.mkdir(parents=True, exist_ok=True)
    DECK_SUMS.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def deck_text(deck, tmp):
    """Downloads the deck, returns (text, problem). The PDF itself is not kept."""
    pdf = tmp / "deck.pdf"
    try:
        r = C.bse().get(deck["pdf"], timeout=90)
    except Exception as e:
        return None, f"download failed ({str(e)[:60]})"
    if r.status_code != 200 or r.content[:4] != b"%PDF":
        return None, f"download failed (HTTP {r.status_code})"
    if len(r.content) > 40_000_000:
        return None, "PDF too large"
    pdf.write_bytes(r.content)
    try:
        pages = C.PdfReader(str(pdf)).pages
        text = "\n".join((p.extract_text() or "") for p in pages[:60])
    except Exception as e:
        return None, f"couldn't read the PDF ({str(e)[:60]})"
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text).strip()
    if len(text) < 1500:
        return None, "no-text"
    return text[:MAX_CHARS], None


def queue(decks, done, lib, watch, news_names):
    """Highest value first."""
    call_codes = {c["code"] for c in lib["calls"].values() if c.get("summary")}
    today = dt.date.today()

    def score(d):
        s = 0
        name = d["company"].lower()
        if any(w in name for w in watch):
            s += 1000
        if d["code"] in call_codes:
            s += 300
        if any(C.norm(d["company"]).startswith(n) or n.startswith(C.norm(d["company"])) for n in news_names if len(n) > 3):
            s += 200
        age = (today - dt.date.fromisoformat(d["when"][:10])).days
        return s - age * 5

    todo = []
    for d in decks:
        st = done.get(d["id"])
        if st and (st.get("status") in ("ok", "no-text") or st.get("tries", 0) >= 2):
            continue
        todo.append(d)
    return sorted(todo, key=score, reverse=True)


def concall_hint(lib, code):
    calls = [c for c in lib["calls"].values() if c["code"] == code and c.get("summary")]
    if not calls:
        return None
    c = max(calls, key=lambda c: c["date"])
    try:
        text = C.here(c["summary"]).read_text(encoding="utf-8")
    except OSError:
        return None
    m = re.search(r"\*\*In one line:\*\*\s*(.+)", text)
    if not m:
        text = re.sub(r"^#.*\n(\*.*\*\n)?", "", text).strip()
    return c, (m.group(1).strip() if m else text[:400])


def step(pool, mode="full"):
    pres = json.loads(C.PRES_FILE.read_text(encoding="utf-8")) if C.PRES_FILE.exists() else []
    if not pres:
        return
    done = load()
    usage = done.setdefault("_usage", {})
    today = dt.datetime.now(IST).strftime("%Y-%m-%d")
    for k in list(usage):
        if k < (dt.date.today() - dt.timedelta(days=7)).isoformat():
            del usage[k]
    used_today = usage.get(today, 0)
    n_max, minutes = ALLOWANCE[mode]
    n_max = min(n_max, DAILY_CEILING - used_today)
    if n_max <= 0:
        say(f"  deck summaries: today's allowance ({DAILY_CEILING}) already used")
        return
    lib = C.load_lib()
    import daily
    watch = daily.watchlist()
    news_names = set()
    briefs = sorted((C.DATA / "news").glob("*.json"))
    if briefs:
        b = json.loads(briefs[-1].read_text(encoding="utf-8"))
        for s in b.get("stories", []):
            news_names.update(C.norm(c) for c in s.get("companies", []))
    todo = queue(pres, done, lib, watch, news_names)
    if not todo:
        say("  deck summaries: all caught up")
        return
    say(f"\nSummarising investor decks: {len(todo)} waiting, up to {n_max} this update ...")
    deadline = time.time() + minutes * 60
    tmp = Path(tempfile.mkdtemp())
    made = skipped = 0
    try:
        for d in todo:
            if made >= n_max or time.time() > deadline:
                break
            if len(pool.chain) > 1 and pool.providers()[0] is pool.backup:
                say("  only the last-resort AI is left - keeping it for concalls and news; decks continue next update")
                break
            text, problem = deck_text(d, tmp)
            rec = done.get(d["id"], {"tries": 0})
            if problem == "no-text":
                done[d["id"]] = {"status": "no-text", "at": today}
                skipped += 1
                continue
            if problem:
                rec["tries"] = rec.get("tries", 0) + 1
                rec["status"] = "failed"
                rec["why"] = problem
                done[d["id"]] = rec
                continue
            hint = concall_hint(lib, d["code"])
            try:
                import timeline
                rec = timeline.context(code=d["code"], name=d["company"], before=d["when"][:10], limit=8)
            except Exception:
                rec = ""
            prompt = DECK_PROMPT.format(
                company=d["company"],
                concall=(f"Its last concall ({hint[0]['quarter']}) was summed up as: \"{hint[1][:400]}\"\n" if hint else ""),
                extra=("### Beyond the concall\n(1-3 bullets: what the deck shows that the concall line above doesn't. Skip if nothing.)\n"
                       if hint else ""))
            try:
                rec_txt = (f"\n\nOUR RECORD OF EARLIER EVENTS (if the deck continues or changes one of these, say so in one bullet):\n{rec}"
                           if rec else "")
                out, ai = pool.ask(prompt + text + rec_txt, label=f"deck {made + 1}: {d['company'][:30]}")
            except C.QuotaOver as e:
                say(f"  {e}")
                break
            except C.AIError as e:
                rec["tries"] = rec.get("tries", 0) + 1
                rec["status"] = "failed"
                rec["why"] = str(e)[:120]
                done[d["id"]] = rec
                continue
            if ai is pool.backup and len(pool.chain) > 1:  # answered by the last resort - fine, but stop after this one
                pool.down[id(ai)] = 0
                for a in pool.chain[:-1]:
                    pool.down[id(a)] = time.time() + 900
            one = ""
            m = re.search(r"\*\*In one line:\*\*\s*(.+)", out)
            if m:
                one = m.group(1).strip()
                out = out.replace(m.group(0), "")
            done[d["id"]] = {"status": "ok", "one": one, "html": C.md(out), "model": ai.model, "at": today}
            made += 1
            usage[today] = usage.get(today, 0) + 1
            save(done)
            time.sleep(pool.pause)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        save(done)
    say(f"  deck summaries: {made} written, {skipped} image-only skipped, "
        f"{len([1 for k, v in done.items() if not k.startswith('_') and v.get('status') == 'ok'])} in total")
