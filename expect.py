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

import concalls as C
from concalls import say

PROMPT = """You are a sharp Indian equity analyst. For each company below you get its latest concall summary
(analyst Q&A, highlights, guidance, risks, key numbers), sometimes last quarter's guidance, and sometimes the
risks brokers flagged in research notes.

For each company answer two things, using ONLY the text given:
1. MARKET vs MANAGEMENT. What the market wanted to hear = the concerns analysts pressed on (questions asked by
   several analysts, or pushed repeatedly) and the risks brokers flag. Did management address those concerns
   CONCRETELY (numbers, timelines, specific actions)?
   addressed = the main concern answered with specifics; partly = some specifics but the main concern stays
   vague; gap = management dodged it, stayed vague, or focused on other things (e.g. talked revenue growth
   when analysts asked about debt).
2. SAID vs DID (only if LAST QUARTER'S GUIDANCE is given). Did this quarter deliver on it?
   delivered / partly / missed. If no comparable figure or statement, write na.

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


def step(lib, pool, limit=40):
    """Grades up to `limit` summaries (latest call per company first). Returns how many were graded."""
    calls = [c for c in lib["calls"].values() if c.get("summary") and "expect" not in c]
    latest = {c["code"]: c for c in sorted(C.latest_per_company(list(lib["calls"].values())), key=lambda c: c["date"])}
    calls = sorted(calls, key=lambda c: (latest.get(c["code"]) is not c, -int(c["date"].replace("-", ""))))[:limit]
    if not calls:
        return 0
    say(f"\nManagement vs market expectations: grading {len(calls)} calls ...")
    done, ai = 0, None
    for i in range(0, len(calls), 8):
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
            out, ai = pool.ask(PROMPT.format(items="\n\n".join(items)), label="expectations")
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
                c["expect"] = {"v": v, "focus": p[3][:90], "line": p[4][:200]}
            elif p[0].upper() == "DEL" and v in ("delivered", "partly", "missed"):
                c["delivery"] = {"v": v, "line": p[3][:200]}
        for c in part:
            if "expect" in c:
                done += 1
            else:
                c["expect"] = {}  # nothing usable - don't keep asking about it
        C.save_lib(lib)
    say(f"  graded {done}" + (f" ({ai.model})" if ai else ""))
    return done
