#!/usr/bin/env python3
"""
One-off quality test: OpenRouter's (and NVIDIA's, when keyed) free models against Gemini's full model on the
same concalls, with the same prompt the site uses. Uses no Gemini allowance: the Gemini side is the summary its
full model already wrote. Writes compare/ (report.md + every summary) for review; changes nothing on the site.

Automatic checks per summary: figures not found word-for-word in the transcript, unit slips (million/lakh written as
crore), sections present, length, time taken. Reading them side by side decides the rest.
"""
import json
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import requests  # noqa: E402

import concalls as C  # noqa: E402
import checks  # noqa: E402

OUT = pathlib.Path("compare")
N_CALLS = int(os.environ.get("N_CALLS", "5"))
PREF = ["deepseek-r1", "deepseek-v3", "deepseek", "qwen3-235b", "qwen3", "kimi", "glm", "gpt-oss-120b",
        "llama-4-maverick", "nemotron-ultra", "nemotron", "llama-3.3-70b", "gemma-3-27b", "mistral"]


def free_models(section):
    ai = C.AI(section)
    r = requests.get(f"{ai.url}/models", headers=ai._headers(), timeout=30)
    r.raise_for_status()
    data = r.json().get("data", [])
    if section == "openrouter":
        data = [m for m in data if m.get("id", "").endswith(":free")]
    return [(m["id"], m.get("context_length") or 0) for m in data]


def pick(models, n=3):
    """Best candidates: preferred families first, large context, one per family."""
    out, fams = [], set()
    for p in PREF:
        for mid, ctx in sorted(models, key=lambda x: -x[1]):
            low = mid.lower()
            if p in low and (ctx == 0 or ctx >= 64000) and not any(f in low for f in fams) \
                    and not any(x in low for x in ("embed", "vision", "-vl", "guard", "reward", "coder")):
                out.append(mid)
                fams.add(p)
                break
        if len(out) >= n:
            break
    return out


def calls_to_test(lib):
    """Recent calls already summarised by Gemini's full model, with a previous quarter, from different sectors."""
    seen, out = set(), []
    for c in sorted(lib["calls"].values(), key=lambda c: c.get("date", ""), reverse=True):
        sec = C.sector_of(lib, c)
        if not c.get("summary") or "lite" in (c.get("model") or "lite") or sec in seen:
            continue
        if not c.get("compared"):
            continue
        seen.add(sec)
        out.append(c)
        if len(out) >= N_CALLS:
            break
    return out


def checks_for(md, text, source):
    md2, fixes = checks.unit_fix(md, text)
    bad = C.unverified_numbers(md2, source)
    return {"words": len(md.split()), "sections": len(re.findall(r"^#{2,3} ", md, re.M)),
            "unverified": len(bad), "unit_slips": len(fixes), "bad": bad[:12]}


def main():
    OUT.mkdir(exist_ok=True)
    lib = C.load_lib()
    cands = []
    for section in ("openrouter", "nvidia"):
        try:
            ms = free_models(section)
        except Exception as e:
            C.say(f"{section}: not available ({str(e)[:120]})")
            continue
        (OUT / f"{section}_models.json").write_text(json.dumps(ms, indent=1), encoding="utf-8")
        chosen = pick(ms)
        C.say(f"{section}: {len(ms)} free models; testing {chosen}")
        cands += [(section, m) for m in chosen]
    calls = calls_to_test(lib)
    C.say(f"Calls: {[c['company'] + ' ' + c['quarter'] for c in calls]}")
    rows = []
    for c in calls:
        text, problem = C.get_text(c)
        if problem:
            C.say(f"  {c['company']}: {problem}")
            continue
        text = C.strip_boilerplate(text)
        prev = C.find_prev(lib, c)
        prev_info = None
        source = text
        if prev and prev.get("summary") and C.here(prev["summary"]).exists():
            pt = re.sub(r"^# .*\n(\*Filed.*\*\n)?", "", C.here(prev["summary"]).read_text(encoding="utf-8")).split("\n---\n")[0]
            prev_info = {"quarter": prev["quarter"], "text": pt}
            ptxt, _ = C.get_text(prev)
            source += "\n" + (ptxt or "")
        slug = C.safe_name(c["company"])[:40]
        d = OUT / slug
        d.mkdir(exist_ok=True)
        gem = C.here(c["summary"]).read_text(encoding="utf-8")
        (d / "gemini_full.md").write_text(gem, encoding="utf-8")
        row = {"company": c["company"], "quarter": c["quarter"], "chars": len(text),
               "gemini": dict(checks_for(gem.split("\n---\n")[0], text, source), model=c.get("model"))}
        for section, mid in cands:
            ai = C.AI(section)
            ai.model, ai.backups, ai.patient, ai.max_wait = mid, [], False, 240
            t0 = time.time()
            try:
                out = C.build_summary(ai, c, text, prev_info, [])
                ok = True
            except Exception as e:
                out, ok = f"FAILED: {str(e)[:300]}", False
            secs = round(time.time() - t0)
            (d / (re.sub(r"[^\w.-]", "_", mid) + ".md")).write_text(out, encoding="utf-8")
            row[mid] = dict(checks_for(out, text, source), secs=secs, ok=ok) if ok else {"ok": False, "err": out[:200], "secs": secs}
            C.say(f"  {c['company']} / {mid}: {'ok' if ok else 'failed'} in {secs}s")
            time.sleep(4)
        rows.append(row)
        (OUT / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    lines = ["# Free models vs Gemini full - same concalls, same prompt\n"]
    for r in rows:
        lines.append(f"\n## {r['company']} {r['quarter']} ({r['chars']:,} chars of transcript)\n")
        lines.append("| model | ok | words | sections | figures not in transcript | unit slips | secs |\n|---|---|---|---|---|---|---|")
        for k, v in r.items():
            if isinstance(v, dict):
                lines.append(f"| {k} {v.get('model', '')} | {v.get('ok', True)} | {v.get('words', '')} | {v.get('sections', '')} | "
                             f"{v.get('unverified', '')} | {v.get('unit_slips', '')} | {v.get('secs', '')} |")
    (OUT / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    C.say("\n".join(lines))


if __name__ == "__main__":
    main()
