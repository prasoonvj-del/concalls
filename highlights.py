#!/usr/bin/env python3
"""
Top 10 developments: companies (or industries) where several independent threads line up - news flow, turning
points (capacity, approvals, strategy), orders, results, broker calls, government decisions, what management said
on the concall and whether earlier events followed through, read-across from bigger companies' calls.

How it stays cheap: the linking is done in code. Every company's last ~45 days are scored from data Market Desk
already keeps (data/timeline.json, the concall library, the follow-through file, read-across, the news briefs);
the strongest ~40 "confluences" (2+ different kinds of evidence) go to ONE full-model request a day, which picks
the ten that matter most, groups companies into an industry thread where they show the same thing, and writes the
thread with dated evidence. Only the evidence given can be used.

  data/highlights.json  {"days": {date: [items]}, "at": ...}  (30 days kept: each item knows how many days running
  it has been on the list - a thread that keeps building is itself a signal)
"""
import datetime as dt
import json
import re
import time

import concalls as C

say = C.say
FILE = C.DATA / "highlights.json"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
WINDOW = 45
KEEP_DAYS = 30


def load():
    try:
        d = json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    except ValueError:
        d = {}
    d.setdefault("days", {})
    return d


def today_ist():
    return dt.datetime.now(IST).date().isoformat()


# ============================================================================ evidence, in code

def _pct(t):
    m = re.search(r"\(([+-]?\d+(?:\.\d+)?)%\)", t)
    return float(m.group(1)) if m else None


def candidates(lib, limit=40):
    import timeline
    tl = timeline.load()
    cos, names = tl.get("companies", {}), tl.get("names", {})
    today = dt.date.today()
    cut = (today - dt.timedelta(days=WINDOW)).isoformat()
    cc_cut = (today - dt.timedelta(days=120)).isoformat()
    inds = lib.get("industries") or {}
    latest = {c["code"]: c for c in C.latest_call_each(list(lib["calls"].values())) if c.get("code")}

    # read-across: positive signals pointing at a company
    ra = {}
    try:
        import readacross
        for r in readacross.load().get("items", []):
            if r.get("date", "") >= cut:
                for m in r.get("matches", []):
                    ra.setdefault(m.get("code"), []).append(
                        (r["date"], f"Read-across from {r['src']} ({r['dir']}): {r['trend']} - its own call: {m.get('why', '')[:120]}"))
    except Exception:
        pass
    # news: the last 7 days' briefs, important stories naming the company
    news = {}
    try:
        from names import Resolver
        R = Resolver()
        files = sorted((C.DATA / "news").glob("*.json"))[-7:]
        seen = set()
        for f in files:
            for s in json.loads(f.read_text(encoding="utf-8")).get("stories", []):
                if s.get("imp", 0) < 3 or s.get("sent") not in ("+", "-") or len(s.get("companies") or []) > 2:
                    continue
                for nm in s.get("companies") or []:
                    code = R.resolve(nm)[1]
                    k = (code, s["title"][:60])
                    if code and k not in seen:
                        seen.add(k)
                        news.setdefault(code, []).append((s["when"][:10], f"News ({'+' if s['sent'] == '+' else '-'}): {s['title'][:150]}"))
    except Exception:
        pass
    try:
        import watch
        ft = watch.load()["items"]
    except Exception:
        ft = {}

    out = []
    for key in set(cos) | set(news) | set(ra):
        ev, kinds, score = [], set(), 0.0
        cnt = {}
        for e in cos.get(key, []):
            if e["d"] < cut or e["k"] in ("concall",):
                continue
            k = e["k"]
            cnt[k] = cnt.get(k, 0) + 1
            w = {"pivot": 3, "order": 2.5, "policy": 2, "broker": 0.5, "deck": 0, "story": 0, "result": 0}.get(k, 0)
            if k == "result":
                p = _pct(e["t"])
                w = 2.5 if (p is not None and p >= 25) or "strong" in e["t"] else (1 if "weak" in e["t"] else 0.5)
            if cnt[k] <= {"pivot": 3, "order": 2, "deck": 1, "story": 1, "broker": 1}.get(k, 2):
                score += w
                kinds.add(k)
                ev.append((e["d"], f"{k.capitalize()}: {e['t'][:170]}"))
            rec = ft.get(e["u"])
            if rec:
                c = watch.latest(rec)
                if c and c["v"] in ("showed", "partly", "reversed"):
                    score += 1.5 if c["v"] == "showed" else 0.5
                    kinds.add("follow-through")
                    ev.append((c["cd"], f"Follow-through on the {c['q']} call ({c['v']}): {c.get('x', '')[:140]}"))
        c = latest.get(key)
        if c and c["date"] >= cc_cut:
            bits = [f"Concall {c.get('quarter', '')} ({c.get('tone') or '?'})"]
            if c.get("tone") == "Positive":
                score += 1
            g = (c.get("metrics") or {}).get("guidance")
            if g in ("raised", "initiated"):
                score += 2
                bits.append(f"guidance {g}")
            ex, dl = (c.get("expect") or {}), (c.get("delivery") or {})
            if ex.get("v"):
                bits.append(f"vs market: {ex['v']} - {ex.get('line', '')[:100]}")
                score += 1 if ex["v"] == "addressed" else 0
            if dl.get("v"):
                bits.append(f"said vs did: {dl['v']}")
                score += 1 if dl["v"] == "delivered" else 0
            one = ""
            for e in cos.get(key, []):
                if e["k"] == "concall" and e["d"] == c["date"]:
                    one = e["t"].split(":", 1)[-1].strip()[:200]
            ev.append((c["date"], " · ".join(bits) + (f": {one}" if one else "")))
            kinds.add("concall")
        for d, t in ra.get(key, [])[:2]:
            score += 2
            kinds.add("read-across")
            ev.append((d, t))
        for i, (d, t) in enumerate(sorted(news.get(key, []), reverse=True)[:3]):
            score += 1 if i == 0 else 0  # being in the news a lot is coverage, not a development
            kinds.add("news")
            ev.append((d, t))
        hard = kinds - {"deck", "story", "news", "broker", "concall"}  # turning points, orders, results, follow-through...
        if len(kinds - {"deck", "story"}) < 2 or not hard:
            continue  # one kind of evidence is a headline, not a thread
        score += 2 * (len(hard) - 1) + 0.5 * len(kinds - hard - {"deck", "story"})
        name = names.get(key) or (c["company"] if c else key.replace("n:", ""))
        sector = C.sector_of(lib, c) if c else (lib.get("sectors") or {}).get(key, "")
        ev.sort(reverse=True)
        out.append({"key": key, "name": name, "sector": sector or "", "ind": inds.get(key, ""),
                    "score": round(score, 1), "kinds": sorted(kinds), "ev": ev[:9]})
    out.sort(key=lambda x: -x["score"])
    return out[:limit]


# ============================================================================ one request a day

PROMPT = """You are the research head of an Indian equity desk. Below are {n} listed companies where several
independent pieces of evidence from the last six weeks line up (news, turning points, orders, results, broker calls,
government decisions, what management said on the concall, read-across from bigger companies). Pick the TEN
developments that most deserve an investor's attention right now: something building - a re-rating, a turnaround,
a new growth leg, an industry upcycle - or a real risk building. Prefer threads where different kinds of evidence
confirm each other over a single big headline. When several companies show the same thing, make it ONE industry
item and name the companies.
{yesterday}
Use ONLY the evidence given; every thread line must carry its date. No price targets, no buy/sell advice.
Reply with exactly ten blocks, most important first:

### <company name exactly as given, or an industry name> | <up / down / watch>
Headline: <the development in one line, specific>
Thread:
- <date>: <evidence>
- <date>: <evidence>
(3-5 lines, oldest first, from different kinds of evidence)
Cooking: <what may be building and why it matters for earnings or the valuation - 2 sentences>
Confirm: <the next thing that would confirm it>
Risk: <what would break it>
Companies: <for an industry item: the companies, comma-separated; otherwise ->

EVIDENCE:
{body}
"""


def _body(cands):
    rows = []
    for x in cands:
        head = f"## {x['name']} ({x['sector']}{' / ' + x['ind'] if x['ind'] else ''}) - evidence: {', '.join(x['kinds'])}"
        rows.append(head + "\n" + "\n".join(f"- {d}: {t}" for d, t in x["ev"]))
    return "\n\n".join(rows)


def parse(text, cands):
    by = {C.norm(x["name"]): x for x in cands}
    items = []
    for block in re.split(r"(?m)^###\s*", text)[1:]:
        head, _, rest = block.partition("\n")
        p = [x.strip(" *") for x in head.split("|")]
        name = re.sub(r"^\d+[.)]\s*", "", p[0]).strip()
        d = (p[1].lower() if len(p) > 1 else "watch")
        d = "up" if d.startswith("up") else "down" if d.startswith("down") else "watch"

        def field(f):
            m = re.search(rf"(?im)^\s*\**{f}\**\s*:\s*\**\s*(.+)$", rest)
            return m.group(1).strip() if m else ""

        th = re.search(r"(?ims)^\s*\**Thread\**\s*:\s*\**\s*\n(.*?)(?=^\s*\**(?:Cooking|Confirm|Risk|Companies)\**\s*:)", rest)
        thread = [re.sub(r"^\s*[-*•]\s*", "", ln).strip() for ln in (th.group(1).splitlines() if th else []) if ln.strip()]
        comps = [c.strip() for c in field("Companies").split(",") if c.strip() and c.strip() not in ("-", "none")]
        x = by.get(C.norm(name))
        if not x:  # an industry item, or a slightly different spelling
            x = next((v for k, v in by.items() if k and (k in C.norm(name) or C.norm(name) in k)), None)
        if not x and not comps:
            continue  # not from the evidence
        if not x:
            known = [by.get(C.norm(c)) or next((v for k, v in by.items() if k and (k in C.norm(c) or C.norm(c) in k)), None) for c in comps]
            if not any(known):
                continue
        items.append({"name": x["name"] if x and not comps else name, "key": x["key"] if x and not comps else "IND|" + C.norm(name),
                      "sector": x["sector"] if x else "", "dir": d, "head": field("Headline"), "thread": thread[:6],
                      "cooking": field("Cooking"), "confirm": field("Confirm"), "risk": field("Risk"), "cos": comps[:8]})
    return items[:10]


def step(lib=None, force=False):
    d = load()
    day = today_ist()
    if d["days"].get(day) and not force:
        return
    lib = lib or C.load_lib()
    cands = candidates(lib)
    if len(cands) < 10:
        say("  top developments: not enough connected evidence yet")
        return
    prev_day = max((k for k in d["days"] if k < day), default=None)
    yest = ""
    if prev_day:
        yest = ("\nYESTERDAY'S TEN (keep a thread if it is still building; drop it if nothing new supports it): "
                + "; ".join(i["name"] for i in d["days"][prev_day]) + "\n")
    say(f"\nTop developments: linking {len(cands)} companies with 2+ kinds of evidence ...")
    try:
        text, ai = C.Pool(quality=True).ask(PROMPT.format(n=len(cands), yesterday=yest, body=_body(cands)),
                                            label="top developments", max_wait=120)
    except C.AIError as e:
        say(f"  top developments wait for a full-quality model: {str(e)[:100]}")
        return
    items = parse(text, cands)
    if len(items) < 5:
        say(f"  top developments: reply didn't parse ({len(items)} items) - trying again next run")
        return
    # how many days running each thread has been on the list
    for it in items:
        n, k = 1, it["key"]
        for prev in sorted((x for x in d["days"] if x < day), reverse=True):
            if any(p["key"] == k or C.norm(p["name"]) == C.norm(it["name"]) for p in d["days"][prev]):
                n += 1
            else:
                break
        it["days"] = n
    d["days"][day] = items
    d["at"] = dt.datetime.now(IST).isoformat(timespec="minutes")
    d["model"] = ai.model
    d["days"] = {k: v for k, v in d["days"].items() if k >= (dt.date.fromisoformat(day) - dt.timedelta(days=KEEP_DAYS)).isoformat()}
    FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    say(f"  top developments: {len(items)} written ({ai.model})")


if __name__ == "__main__":
    import sys
    if "--dry" in sys.argv:
        for x in candidates(C.load_lib())[:40]:
            print(x["score"], x["name"], x["kinds"])
    else:
        step(force=True)
