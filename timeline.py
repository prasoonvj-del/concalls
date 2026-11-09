#!/usr/bin/env python3
"""
A permanent record per company -> data/timeline.json (never pruned, capped per company).

Collects, on every update, what we already have - no AI:
  * concall: quarter + tone + one line          (library)
  * deck: one-line summary                      (deck summaries)
  * pivots, results, order wins, broker calls   (trackers - those only keep 4 months, this keeps them for good)
  * share-price story one-liner                 (the story so far)

The record is shown as a timeline on company pages, and fed back into the AI write-ups (concall summaries,
deck summaries, the story so far) so they can say "third capacity addition in 18 months".
"""
import json
import re

import concalls as C

say = C.say
FILE = C.DATA / "timeline.json"
PER_COMPANY = 250


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {"companies": {}, "names": {}}
    except ValueError:
        return {"companies": {}, "names": {}}


def save(tl):
    FILE.write_text(json.dumps(tl, ensure_ascii=False), encoding="utf-8")


def _first_line(md_text):
    t = re.sub(r"^#.*\n(\*.*\*\n)?", "", md_text or "").strip()
    m = re.search(r"(?m)^\s*[-*]\s+(.+)$", t)
    line = (m.group(1) if m else t.split("\n")[0]).strip()
    line = re.sub(r"\*\*|__", "", line)
    return line[:260]


def key_for(name, by_name):
    """Companies are filed by BSE code when we know it, else by normalised name."""
    n = C.norm(name)
    return by_name.get(n) or ("n:" + n)


def update():
    tl = load()
    cos, names = tl.setdefault("companies", {}), tl.setdefault("names", {})
    lib = C.load_lib()
    by_name = {}
    for c in lib["calls"].values():
        if c.get("code"):
            by_name[C.norm(c["company"])] = c["code"]
            names.setdefault(c["code"], c["company"])
    pres = json.loads(C.PRES_FILE.read_text(encoding="utf-8")) if C.PRES_FILE.exists() else []
    for d in pres:
        by_name.setdefault(C.norm(d["company"]), d["code"])
        names.setdefault(d["code"], d["company"])

    def add(key, uid, date, kind, text, link="", extra=None):
        if not text or not date:
            return 0
        lst = cos.setdefault(key, [])
        if any(e["u"] == uid for e in lst):
            return 0
        e = {"u": uid, "d": date[:10], "k": kind, "t": text[:300]}
        if link:
            e["l"] = link
        if extra:
            e.update(extra)
        lst.append(e)
        return 1

    n = 0
    # concalls
    for c in lib["calls"].values():
        if not c.get("summary") or not c.get("code"):
            continue
        try:
            text = C.here(c["summary"]).read_text(encoding="utf-8")
        except OSError:
            continue
        m = re.search(r"(?im)^\**tone:?\**\s*:?\s*\**\s*(positive|mixed|cautious|negative)\**\s*[-–—:]?\s*(.*)$", text)
        tone, line = (m.group(1).title(), m.group(2).strip()) if m else ("", _first_line(text))
        n += add(c["code"], f"cc|{c['id']}", c["date"], "concall",
                 f"Concall {c['quarter']}" + (f" ({tone})" if tone else "") + f": {line or _first_line(text)}",
                 extra={"q": c["quarter"], "tone": tone} if tone else {"q": c["quarter"]})
    # decks
    try:
        import decks
        sums = decks.load()
    except Exception:
        sums = {}
    for d in pres:
        s = sums.get(d["id"]) or {}
        if s.get("status") == "ok" and s.get("one"):
            n += add(d["code"], f"dk|{d['id']}", d["when"], "deck", f"Investor deck: {s['one']}", d["pdf"])
    # trackers (only 4 months there - kept for good here)
    try:
        import trackers
        T = trackers.load(trackers.TRACK_FILE, {})
    except Exception:
        T = {}
    for r in T.get("pivots", []):
        n += add(key_for(r["company"], by_name), r["uid"], r["date"], "pivot",
                 f"{(r.get('type') or 'pivot').title()}: {r['what']}" + (f" - {r['why']}" if r.get("why") else "")
                 + (f" [{r['src']}]" if r.get("src") else ""), r.get("link", ""),
                 {"s": r.get("sent", ""), "th": r.get("theme", "")})
    for r in T.get("results", []):
        bits = []
        if r.get("revenue") is not None:
            bits.append(f"revenue Rs {r['revenue']:,.0f} cr" + (f" ({r['rev_yoy']:+.0f}%)" if r.get("rev_yoy") is not None else ""))
        if r.get("profit") is not None:
            bits.append(f"net profit Rs {r['profit']:,.0f} cr" + (f" ({r['pat_yoy']:+.0f}%)" if r.get("pat_yoy") is not None else ""))
        n += add(key_for(r["company"], by_name), r["uid"], r["date"], "result",
                 f"Results {r.get('quarter', '')}: " + ", ".join(bits) + (f" - {r['read']}" if r.get("read") else ""), r.get("link", ""))
    for r in T.get("orders", []):
        n += add(key_for(r["company"], by_name), r["uid"], r["date"], "order",
                 "Order" + (f" Rs {r['value']:,.0f} cr" if r.get("value") else "") + (f" from {r['client']}" if r.get("client") else "")
                 + (f" - {r['what']}" if r.get("what") else ""), r.get("link", ""))
    for r in T.get("calls", []):
        n += add(key_for(r["company"], by_name), r["uid"], r["date"], "broker",
                 f"{r['broker']}: {r.get('rating', '')}" + (f", target Rs {r['target']:,.0f}" if r.get("target") else "")
                 + (f" ({r['action']})" if r.get("action") else ""), r.get("link", ""))
    # the story so far: keep each version's one-liner
    try:
        import backstory
        for code, b in backstory.load().items():
            if b.get("status") == "ok" and b.get("one") and b.get("v", 0) >= 4:
                n += add(code, f"bs|{code}|{b['at']}", b["at"], "story", f"Share-price story: {b['one']}")
    except Exception:
        pass
    themes = {r["uid"]: r.get("theme") for r in T.get("pivots", []) if r.get("theme")}
    for lst in cos.values():
        for e in lst:
            if e["k"] == "pivot" and not e.get("th") and e["u"] in themes:
                e["th"] = themes[e["u"]]
    # facts the trackers merged away as repeats (still inside their 4-month window) go from the timeline too
    live = {r["uid"] for k in ("pivots", "results", "orders", "calls") for r in T.get(k, [])}
    oldest = min([r["date"] for k in ("pivots", "results", "orders", "calls") for r in T.get(k, [])] or ["9999"])
    for k2 in list(cos):
        cos[k2] = [e for e in cos[k2] if e["k"] not in ("pivot", "result", "order", "broker") or e["u"] in live or e["d"] < oldest]
        if not cos[k2]:
            del cos[k2]
    for lst in cos.values():  # bare BSE file names -> full address
        for e in lst:
            if e.get("l") and not e["l"].startswith("http"):
                e["l"] = C.BSE_PDF[0] + e["l"]
    # tidy: newest first, capped
    for k, lst in cos.items():
        lst.sort(key=lambda e: e["d"], reverse=True)
        del lst[PER_COMPANY:]
    # names for name-keyed entries
    for r in T.get("pivots", []) + T.get("results", []) + T.get("orders", []) + T.get("calls", []):
        k = key_for(r["company"], by_name)
        if k.startswith("n:"):
            names.setdefault(k, r["company"])
    save(tl)
    say(f"  company timelines: {n} new entries · {sum(len(v) for v in cos.values())} entries for {len(cos)} companies")


def context(code=None, name=None, before=None, limit=14):
    """Short text of a company's record, for AI prompts. `before` = only entries before this date."""
    tl = load()
    cos = tl.get("companies", {})
    lst = []
    if code and code in cos:
        lst += cos[code]
    if name and ("n:" + C.norm(name)) in cos:
        lst += cos["n:" + C.norm(name)]
    lst = [e for e in lst if not before or e["d"] < before]
    lst = sorted(lst, key=lambda e: e["d"], reverse=True)[:limit]
    return "\n".join(f"{e['d']} - {e['t']}" for e in reversed(lst))
