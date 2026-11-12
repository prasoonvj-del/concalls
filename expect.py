"""Management vs market expectations, and said vs did - read from the concall summaries we already have.

What the market expects is taken from what analysts pressed on in the call's Q&A (repeated questions =
the market's real worry), plus the risks in broker research notes we hold for the company. We then judge
whether management addressed it concretely (numbers, timelines, actions) or talked about something else.
Said vs did compares last quarter's guidance with what this quarter's call reports.

Stored on each call in the library:
  call["expect"]   = {"v": "addressed" | "partly" | "gap", "focus": what the market wants, "line": one line}
  call["delivery"] = {"v": "delivered" | "partly" | "missed", "line": one line}   (only when last quarter is on file)

Batches of 8 summaries per AI request; new calls first, then the backlog, `limit` per run.
"""
import re
import time

import concalls as C
from concalls import say

PROMPT = """You are a sharp Indian equity analyst. For each company below you get its latest concall summary
(analyst Q&A, highlights, guidance, risks, key numbers), sometimes last quarter's guidance, and sometimes the
risks brokers flagged in research notes.

Be a SCEPTICAL buy-side analyst. Managements always sound confident; that is not the same as answering the
question. Judge each company on its own evidence. For each company answer two things, using ONLY the text given:
1. MARKET vs MANAGEMENT. What the market wanted to hear = the concerns analysts pressed on (questions asked by
   several analysts, or pushed repeatedly) and the risks brokers flag. Did management address those concerns
   CONCRETELY (numbers, timelines, specific actions)?
   First name the ONE concern analysts pressed hardest (asked by several analysts, or asked again after a
   weak answer). Then:
   addressed = that concern got a concrete answer: a number, a date, or a specific action already taken
               (e.g. "net debt to fall from Rs 900 cr to Rs 500 cr by March via the land sale").
   partly    = some specifics, but the hardest-pressed part stays open, or the answer is only directional
               ("we expect improvement", "we are confident", "will normalise").
   gap       = dodged, declined to guide, repeated old talking points, or steered to other topics
               (e.g. talked revenue growth when analysts asked about debt), or the summary notes they dodged.
   Explanations of WHY something went wrong are not a plan to fix it: that is partly at best.
2. SAID vs DID (only if LAST QUARTER'S GUIDANCE is given). Compare like with like: a guided figure for THIS
   quarter or year-to-date against what this quarter's call reports. delivered = met or beat; partly = close
   but short, or some promises met and others not; missed = clearly short, delayed, or guidance cut.
   If the guidance was for a later period, or there is no comparable figure, write na - do not guess.

Reply with exactly two lines per company, nothing else:
EXP | <id> | addressed/partly/gap | <market's main concern, max 10 words> | <how management responded, max 22 words>
DEL | <id> | delivered/partly/missed/na | <max 22 words: what was promised vs what happened>

COMPANIES:
{items}
"""

SECTIONS = ("Notable analyst Q&A", "Highlights", "Guidance & outlook", "Risks & concerns flagged", "Key numbers",
            "Balance sheet, debt & working capital")


def section(md, name, cap=1400):
    m = re.search(r"###\s*" + re.escape(name) + r"\s*\n(.*?)(?=\n###\s|\n---|\Z)", md, re.S | re.I)
    return m.group(1).strip()[:cap] if m else ""


def _read(call):
    f = C.here(call["summary"]) if call.get("summary") else None
    return f.read_text(encoding="utf-8") if f and f.exists() else ""


def _broker_risks(name):
    try:
        import ic
        from names import same
        out = []
        for r in ic.load().get("items", []):
            if r.get("company") and same(r["company"], name):
                out += [f"{r['broker']}: " + "; ".join((r.get("risks") or []) + (r.get("thesis") or [])[:1])]
        return "\n".join(out[:3])
    except Exception:
        return ""


def step(lib, pool, limit=40, deadline=None):
    """Grades up to `limit` summaries (latest call per company first). Returns how many were graded."""
    calls = [c for c in lib["calls"].values() if c.get("summary") and (c.get("expect") or {}).get("ver", 0) < 2
             and not (c.get("expect") == {"ver": 2})]
    latest = {c["code"]: c for c in sorted(C.latest_per_company(list(lib["calls"].values())), key=lambda c: c["date"])}
    calls = sorted(calls, key=lambda c: (latest.get(c["code"]) is not c, -int(c["date"].replace("-", ""))))[:limit]
    if not calls:
        return 0
    say(f"\nManagement vs market expectations: grading {len(calls)} calls ...")
    done, ai = 0, None
    for i in range(0, len(calls), 8):
        if deadline and time.time() > deadline:
            say("  out of time - the rest next run")
            break
        part = calls[i:i + 8]
        items = []
        for n, c in enumerate(part, 1):
            md = _read(c)
            body = "\n".join(f"[{s}]\n{section(md, s)}" for s in SECTIONS if section(md, s))
            prev = C.find_prev(lib, c)
            pg = section(_read(prev), "Guidance & outlook", 900) if prev else ""
            br = _broker_risks(c["company"])
            items.append(f"=== id {n}: {c['company']} - {c.get('quarter', '')}\n{body}"
                         + (f"\n[LAST QUARTER'S GUIDANCE ({prev.get('quarter', '')})]\n{pg}" if pg else "")
                         + (f"\n[BROKER RESEARCH]\n{br}" if br else ""))
        try:
            out, ai = pool.ask(PROMPT.format(items="\n\n".join(items)), label="expectations", max_wait=60)
        except C.AIError as e:
            say(f"  stopped: {str(e)[:100]} - the rest next run")
            break
        for line in out.splitlines():
            p = [x.strip(" *`") for x in line.split("|")]
            if len(p) < 4 or p[0].upper() not in ("EXP", "DEL"):
                continue
            try:
                c = part[int(re.sub(r"\D", "", p[1])) - 1]
            except (ValueError, IndexError):
                continue
            v = p[2].lower()
            if p[0].upper() == "EXP" and v in ("addressed", "partly", "gap") and len(p) >= 5:
                c["expect"] = {"v": v, "focus": p[3][:90], "line": p[4][:200], "ver": 2}
            elif p[0].upper() == "DEL":
                c["delivery"] = {"v": v, "line": p[3][:200]} if v in ("delivered", "partly", "missed") else {}
        for c in part:
            if (c.get("expect") or {}).get("ver") == 2 and c["expect"].get("v"):
                done += 1
            else:
                c["expect"] = {"ver": 2}  # nothing usable - don't keep asking about it
        C.save_lib(lib)
    say(f"  graded {done}" + (f" ({ai.model})" if ai else ""))
    return done
