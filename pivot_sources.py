#!/usr/bin/env python3
"""
Pivots from concall and deck summaries (not only from the news): new businesses, capex, capacity, strategy shifts.
Each summary is read once - a few per AI request - and remembered in data/pivot_sources.json.
The pivots go to the trackers (4-month view) and from there into each company's permanent timeline.

AI cost: ~1 request per 3 summaries. New concalls/decks are read every update; the backlog of older summaries
is cleared gradually (capped per update).
"""
import datetime as dt
import json
import re
import time

import concalls as C

say = C.say
DONE = C.DATA / "pivot_sources.json"
THEMES = [
    "EV & two-wheelers", "Battery materials & cells (LFP, cathode, anode, electrolyte)", "Solar manufacturing",
    "Wind & renewables IPP", "Green hydrogen & ammonia", "Power T&D, transformers & cables", "Nuclear",
    "Data centres & AI infrastructure", "Semiconductors & electronics manufacturing", "Defence", "Railways",
    "Aerospace", "Specialty chemicals & fluorochemicals", "Pharma CDMO, peptides & biologics", "GLP-1 & obesity drugs",
    "Hospitals & healthcare expansion", "Real estate & land", "Quick commerce & consumer internet",
    "Premiumisation & new consumer brands", "Exports & China+1", "Import substitution & PLI", "Capacity expansion (other)",
    "M&A & consolidation", "Debt reduction & fund-raising", "Legal & regulatory",
]
PROMPT = """Below are summaries of earnings calls / investor presentations of Indian listed companies, each marked [n].
Pick out PIVOTS only: a new business or product line, a big capex or capacity addition, entry into a new market,
a shift in business model or product mix, an acquisition or demerger, a large fund-raise, a legal or regulatory
turning point. Not routine growth, margins or guidance.

One line per pivot, exactly:
PIVOT | n | type (capacity / strategy / M&A / funding / legal / approval / order / management) | what changed (max 18 words, include Rs crore / capacity / timeline if given) | why it could re-rate or de-rate the stock (max 12 words) | theme

theme = one of:
{themes}
or "Other: <2-4 words>". At most 3 pivots per summary; none is fine. Output only the lines.

SUMMARIES:
"""


def load_done():
    try:
        return json.loads(DONE.read_text(encoding="utf-8")) if DONE.exists() else {}
    except ValueError:
        return {}


def _core(text, limit=2600):
    """The parts of a summary where pivots live."""
    keep = []
    for sec in re.split(r"(?m)^### ", text):
        head = sec.split("\n", 1)[0].lower()
        if any(k in head for k in ("highlight", "guidance", "capex", "capacity", "outlook", "beyond", "business", "targets", "key numbers")):
            keep.append("### " + sec.strip())
    out = "\n".join(keep) or text
    return re.sub(r"\n{2,}", "\n", out)[:limit]


def step(pool, mode="full"):
    done = load_done()
    lib = C.load_lib()
    items = []
    for c in lib["calls"].values():
        if c.get("summary") and c.get("code") and f"cc|{c['id']}" not in done:
            try:
                text = C.here(c["summary"]).read_text(encoding="utf-8")
            except OSError:
                continue
            items.append({"key": f"cc|{c['id']}", "company": c["company"], "code": c["code"], "date": c["date"],
                          "src": f"Concall {c['quarter']}", "link": c.get("pdf") or "", "text": _core(text)})
    try:
        import decks
        sums = decks.load()
        pres = json.loads(C.PRES_FILE.read_text(encoding="utf-8")) if C.PRES_FILE.exists() else []
        for d in pres:
            s = sums.get(d["id"]) or {}
            if s.get("status") == "ok" and f"dk|{d['id']}" not in done:
                text = (s.get("one", "") + "\n" + re.sub(r"<[^>]+>", " ", s.get("html", "")))
                items.append({"key": f"dk|{d['id']}", "company": d["company"], "code": d["code"], "date": d["when"][:10],
                              "src": "Investor deck", "link": d["pdf"], "text": re.sub(r"\s+", " ", text)[:2200]})
    except Exception:
        pass
    if not items:
        return
    items.sort(key=lambda x: x["date"], reverse=True)  # newest first; the backlog follows
    cap = {"full": 45, "news": 15}.get(mode, 15)
    todo = items[:cap]
    say(f"\nLooking for pivots in {len(todo)} concall/deck summaries ({len(items)} not read yet) ...")
    import trackers
    data = trackers.load(trackers.TRACK_FILE, {})
    data.setdefault("pivots", [])
    have = {p["uid"] for p in data["pivots"]}
    found = 0
    for i in range(0, len(todo), 3):
        batch = todo[i:i + 3]
        body = "\n\n".join(f"[{k + 1}] {x['company']} - {x['src']} ({x['date']}):\n{x['text']}" for k, x in enumerate(batch))
        try:
            text, _ = pool.ask(PROMPT.format(themes="\n".join("- " + t for t in THEMES)) + body,
                               label=f"pivots in summaries {i + 1}-{i + len(batch)}")
        except C.QuotaOver as e:
            say(f"  {e}")
            break
        except C.AIError as e:
            say(f"  pivot reading skipped: {str(e)[:100]}")
            continue
        for line in text.splitlines():
            p = [x.strip() for x in line.strip().lstrip("-* ").split("|")]
            if len(p) < 5 or p[0].upper() != "PIVOT":
                continue
            try:
                x = batch[int(re.sub(r"\D", "", p[1])) - 1]
            except (ValueError, IndexError):
                continue
            what = p[3] if p[3] != "-" else ""
            if not what:
                continue
            uid = f"P|{x['code']}|{re.sub(r'[^a-z0-9]', '', what.lower())[:30]}"
            if uid in have:
                continue
            have.add(uid)
            data["pivots"].append({"uid": uid, "company": x["company"], "code": x["code"], "type": p[2].lower(),
                                   "what": what, "why": p[4] if len(p) > 4 and p[4] != "-" else "",
                                   "theme": p[5] if len(p) > 5 and p[5] != "-" else "", "imp": 3, "sent": "=",
                                   "date": x["date"], "link": x["link"], "title": x["src"], "src": x["src"]})
            found += 1
        for x in batch:
            done[x["key"]] = dt.date.today().isoformat()
        time.sleep(pool.pause)
    trackers.TRACK_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    DONE.write_text(json.dumps(done), encoding="utf-8")
    say(f"  pivots from summaries: {found} found · {max(0, len(items) - len(todo))} summaries still to read")
