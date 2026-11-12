#!/usr/bin/env python3
"""
Follow-through: did what we recorded earlier show up later?

Earlier events for a company - turning points from the news, concalls and decks (capacity, orders, approvals,
M&A, funding...), big order wins, government decisions that name the company, read-across signals from large
companies' calls - are checked against that company's NEXT concall. The check rides inside the concall summary
request itself (no extra AI requests): the summary gets a numbered list of open items and answers each one with
showed / partly / notyet / reversed / silent plus the line from the call as evidence.

  * the verdicts are kept in data/followthrough.json (one record per item, one check per call)
  * a "Follow-through on earlier events" section is added to the summary
  * the company timeline shows each event's latest verdict next to it
  * an item stays open until a call shows it (or the opposite), or until it is ~15 months old

Sectors: government decisions for the sector and the previous overview's "What to watch next quarter" are given
to the next sector overview, which writes a "What we were watching" section.
"""
import datetime as dt
import json
import re

import concalls as C

say = C.say
FILE = C.DATA / "followthrough.json"
MAX_AGE_DAYS = 450
MAX_ITEMS = 10
VERDICTS = ("showed", "partly", "notyet", "reversed", "silent")
LABEL = {"showed": "Showed up", "partly": "Partly", "notyet": "Not yet", "reversed": "Went the other way"}
ICON = {"showed": "✅", "partly": "◐", "notyet": "⏳", "reversed": "✖"}


def load():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    except ValueError:
        d = {}
    d.setdefault("items", {})
    d.setdefault("policy", {})
    return d


def save(d):
    FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _when(d):
    try:
        return dt.date.fromisoformat(d[:10]).strftime("%b %Y")
    except ValueError:
        return d


# ============================================================================ company items

def company_items(call, lib=None):
    """Open items to check against this call, newest first: [{"u", "d", "k", "t"}]."""
    try:
        import timeline
        tl = timeline.load().get("companies", {})
    except Exception:
        tl = {}
    D = call["date"]
    cut = (dt.date.fromisoformat(D) - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
    try:
        own = C.pdf_url(call)
    except Exception:
        own = ""
    keys = [k for k in (call.get("code"), "n:" + C.norm(call["company"])) if k]
    got, seen = [], set()
    for k in keys:
        for e in tl.get(k, []):
            if e["k"] not in ("pivot", "order", "policy") or not (cut <= e["d"] < D) or e["u"] in seen:
                continue
            if own and e.get("l") == own:
                continue  # a turning point taken from this very call
            seen.add(e["u"])
            got.append({"u": e["u"], "d": e["d"], "k": e["k"], "t": e["t"]})
    # read-across: a large company's call pointed at this one
    try:
        import readacross
        for r in readacross.load().get("items", []):
            if not (cut <= r["date"] < D) or r.get("src_code") == call.get("code"):
                continue
            if any(m.get("code") == call.get("code") for m in r.get("matches", [])):
                u = "RA|" + r["uid"]
                if u not in seen:
                    seen.add(u)
                    got.append({"u": u, "d": r["date"], "k": "readacross",
                                "t": f"Read-across from {r['src']} ({r.get('quarter', '')}), a {r['dir']}: {r['trend']}"})
    except Exception:
        pass
    # already settled by an earlier call
    done = load()["items"]
    open_ = []
    for it in got:
        checks = [c for c in done.get(it["u"], {}).get("checks", []) if c["cd"] < D and c["call"] != call["id"]]
        if any(c["v"] in ("showed", "reversed") for c in checks):
            continue
        open_.append(it)
    # results are reported anyway; keep the list to the events that change the story
    open_.sort(key=lambda x: x["d"], reverse=True)
    return open_[:MAX_ITEMS]


FT_INSTRUCTIONS = """
Below the transcript is a numbered list of EARLIER EVENTS for this company that we recorded before this call
(announcements, orders, approvals, government decisions, signals from other companies). For each one, judge from
THIS call only whether it shows up. End your answer with this block (one line per event, nothing else inside):
```followthrough
<number> | showed / partly / notyet / reversed / silent | evidence from this call (max 25 words; - if silent)
```
showed = the call confirms it happened or is feeding the numbers; partly = some progress or a smaller effect;
notyet = management says it is still to come or delayed; reversed = it went the other way (cancelled, lost, hurt);
silent = the call doesn't address it. Evidence must come from the transcript, with its numbers. Do not mention
these events anywhere else in the summary.
"""


def prompt_parts(items):
    if not items:
        return "", ""
    lines = "\n".join(f"{n}. {_when(it['d'])} - {it['t']}" for n, it in enumerate(items, 1))
    return FT_INSTRUCTIONS, f"\n\nEARLIER EVENTS (check each against this call):\n{lines}"


def parse(text, items):
    """Takes the ```followthrough block out of the summary. Returns (verdicts {n: (v, line)}, text)."""
    m = re.search(r"```\s*followthrough\s*\n(.*?)```", text, re.S | re.I)
    if not m:
        return {}, text
    out = {}
    for line in m.group(1).splitlines():
        p = [x.strip(" *`") for x in line.split("|")]
        if len(p) < 2:
            continue
        try:
            n = int(re.sub(r"\D", "", p[0]))
        except ValueError:
            continue
        v = re.sub(r"[^a-z]", "", p[1].lower())
        v = {"notyetdelayed": "notyet", "showedup": "showed", "wenttheotherway": "reversed"}.get(v, v)
        if 1 <= n <= len(items) and v in VERDICTS:
            ev = p[2] if len(p) > 2 else ""
            out[n] = (v, "" if ev in ("-", "") else ev[:240])
    text = (text[:m.start()] + text[m.end():]).rstrip() + "\n"
    return out, text


def section(items, verdicts):
    """Markdown section for the summary."""
    if not verdicts:
        return ""
    rows, quiet = [], []
    for n, it in enumerate(items, 1):
        v, ev = verdicts.get(n, ("silent", ""))
        what = re.sub(r"\s*\[[^\]]*\]$", "", it["t"])
        if v == "silent":
            quiet.append(f"{what[:90]} ({_when(it['d'])})")
        else:
            rows.append(f"- {ICON[v]} **{LABEL[v]}** · {_when(it['d'])}: {what}" + (f"  \n  → {ev}" if ev else ""))
    if not rows and not quiet:
        return ""
    out = "\n### Follow-through on earlier events\n" + "\n".join(rows)
    if quiet:
        out += ("\n" if rows else "") + "\n*Not addressed on the call:* " + "; ".join(quiet)
    return out + "\n"


def record(call, items, verdicts):
    """Keeps this call's verdicts (a rewrite of the same call replaces them)."""
    if not items:
        return
    d = load()
    for n, it in enumerate(items, 1):
        v, ev = verdicts.get(n, ("silent", ""))
        rec = d["items"].setdefault(it["u"], {"d": it["d"], "k": it["k"], "t": it["t"], "code": call.get("code", ""),
                                               "company": call["company"], "checks": []})
        rec["checks"] = [c for c in rec["checks"] if c["call"] != call["id"]]
        if not verdicts:
            continue  # the model skipped the block: nothing judged
        rec["checks"].append({"call": call["id"], "cd": call["date"], "q": call.get("quarter", ""), "v": v, "x": ev})
        rec["checks"].sort(key=lambda c: c["cd"])
    save(d)


def latest(rec):
    """The verdict to show: the newest one that says something (silent only if that's all there is)."""
    ch = rec.get("checks") or []
    said = [c for c in ch if c["v"] != "silent"]
    return (said or ch or [None])[-1]


# ============================================================================ sectors

_STOP = {"and", "the", "other", "others", "services", "products", "goods", "india", "indian", "sector", "industry",
         "companies", "company", "general", "&"}


def _words(s):
    out = set()
    for w in re.findall(r"[a-z]{4,}", (s or "").lower()):
        if w in _STOP:
            continue
        w = w.replace("z", "s").replace("isres", "isers")
        w = re.sub(r"(ing|s)$", "", w)
        out.add(w)
    return out


def keep_policy():
    """Government decisions only stay ~10 days in the trackers; keep them here for the sector checks."""
    try:
        import trackers
        T = trackers.load(trackers.TRACK_FILE, {})
    except Exception:
        return
    d = load()
    n = 0
    for r in T.get("policy", []):
        if r.get("status") == "decided" and r.get("uid") and r["uid"] not in d["policy"]:
            d["policy"][r["uid"]] = {"d": r["date"], "body": r.get("body", ""), "what": r.get("what", ""),
                                     "sectors": r.get("sectors", ""), "cos": r.get("cos", [])}
            n += 1
    cut = (dt.date.today() - dt.timedelta(days=MAX_AGE_DAYS)).isoformat()
    d["policy"] = {k: v for k, v in d["policy"].items() if v["d"] >= cut}
    save(d)
    if n:
        say(f"  follow-through: {n} government decision(s) kept for the sector checks")


def sector_items(sector, quarter, lib, industry=None):
    """For a sector overview: decisions since the previous quarter's calls + the previous overview's watch list."""
    try:
        import industries as I
        inds = [k for k, v in I.PARENT.items() if v == sector] if isinstance(I.PARENT, dict) else []
    except Exception:
        inds = []
    want = _words(sector) | (_words(industry) if industry else set().union(set(), *[_words(i) for i in inds]))
    lo = (dt.date.today() - dt.timedelta(days=200)).isoformat()
    pol = []
    for r in load()["policy"].values():
        if r["d"] < lo:
            continue
        if _words(r["sectors"]) & want:
            body = r["body"] if r["body"] and "ministry name" not in r["body"].lower() else "Govt"
            pol.append(f"{_when(r['d'])} - {body}: {r['what']} (seen as: {r['sectors']})")
    kept, sets = [], []
    for p in sorted(pol, reverse=True):  # the same decision reported by several outlets: keep one
        w = _words(p.split(": ", 1)[-1])
        if any(len(w & o) / max(1, len(w | o)) > 0.4 for o in sets):
            continue
        kept.append(p)
        sets.append(w)
    pol = kept[:10]
    prev_watch = ""
    pq = C.prev_quarter(quarter)
    key = f"{sector}|{industry}|{pq}" if industry else f"{sector}|{pq}"
    old = (lib.get("overviews") or {}).get(key)
    if old and old.get("file"):
        try:
            t = C.here(old["file"]).read_text(encoding="utf-8")
            m = re.search(r"(?ims)^#+\s*What to watch next quarter\s*$(.*?)(?=^#|\Z)", t)
            if m:
                prev_watch = "\n".join(ln for ln in m.group(1).strip().splitlines()
                                       if ln.strip() and not ln.strip().lower().startswith("*based on"))[:1500]
        except OSError:
            pass
    return pol, prev_watch, pq


OVERVIEW_ADD = """
## What we were watching
Check the items below against these summaries: for each, does it show up in this quarter's calls? Use one bullet
per item: ✅ showed up / ◐ partly / ⏳ not yet / ✖ went the other way / — not discussed, then the companies and the
evidence from their summaries. Skip this section if there are no items. Put it right after "What changed since
last quarter".
{items}
"""


def overview_parts(sector, quarter, lib, industry=None):
    pol, prev_watch, pq = sector_items(sector, quarter, lib, industry)
    parts = []
    if prev_watch:
        parts.append(f"LAST QUARTER'S OVERVIEW ({pq}) SAID TO WATCH:\n{prev_watch}")
    if pol:
        parts.append("GOVERNMENT DECISIONS FOR THIS SECTOR SINCE THEN:\n" + "\n".join(f"- {p}" for p in pol))
    return OVERVIEW_ADD.format(items="\n\n".join(parts)) if parts else ""
