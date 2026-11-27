"""Breakout + catalyst: a fresh Ichimoku cloud breakout, read against what Market Desk knows about the company.

The idea (the user's): a breakout works better when the market is getting ahead of news that is still coming -
monthly volumes, a plant starting, an approval, results - and the business evidence has been building, than when the
stock is merely reacting to news already out. So for each Market Desk company that broke above the cloud in the last
few sessions this module scores four things, all from data, no AI:

  evidence  - what happened in the last ~90 days: turning points (capacity, approvals, M&A, strategy), orders,
              broker initiations, the latest concall (tone, management rating, guidance, said vs did), Top 10 / early lists
  ahead     - what is due in the next 30 days: results, what the company itself said is due, its sector's monthly
              data, government decisions awaited for its sector
  industry  - its industry's shifts that it acts on, and whether more of its peers talk about them each quarter
  timing    - anticipation (catalyst still ahead, no big news on the breakout day) vs reaction (breakout on the news)

plus the chart: the cloud-launch quality score, relative strength and the swing plan (entry, stop, target).
Grade A = strong on all of it (sent at once); B = worth a look (in the 3:15 pm and evening summaries); C = not sent.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

KIND_W = {"pivot": 2.0, "order": 2.0, "broker": 1.0, "result": 1.0, "deck": 0.5, "policy": 0.5}


def _d(s: str) -> date | None:
    try:
        return date.fromisoformat(s[:10])
    except (TypeError, ValueError):
        return None


def grade(md: dict, r: dict, today: date | None = None) -> dict:
    """md = Market Desk's row for the company (why.json); r = the scan result (hits, launch, pick, rs...)."""
    today = today or date.today()
    pts = {"evidence": 0.0, "ahead": 0.0, "industry": 0.0, "timing": 0.0, "chart": 0.0}
    build, coming, inds, flags = [], [], [], []

    # -- evidence: the last ~90 days
    cut = today - timedelta(days=90)
    kinds: dict[str, float] = {}
    for d, k, t in md.get("ev") or []:
        dd = _d(d)
        if not dd or dd < cut or k not in KIND_W:
            continue
        if kinds.get(k, 0) >= 2 * KIND_W[k]:
            continue  # two of a kind are enough to count
        kinds[k] = kinds.get(k, 0) + KIND_W[k]
        build.append((dd, t.split(" - ")[0][:120]))
    pts["evidence"] += sum(kinds.values())
    call = md.get("call") or {}
    bad_call = False
    if call:
        tone = call.get("tone", "")
        pts["evidence"] += {"Positive": 2, "Mixed": 0.5, "Cautious": -1.5, "Negative": -2.5}.get(tone, 0)
        pts["evidence"] += {"raised": 2, "initiated": 1, "cut": -2}.get(call.get("guid", ""), 0)
        pts["evidence"] += {"delivered": 1, "missed": -1}.get(call.get("did", ""), 0)
        if (call.get("rate") or 0) >= 5:
            pts["evidence"] += 1
        bits = [f"{call.get('q', '')} concall {tone.lower() or 'neutral'}"]
        if call.get("guid") in ("raised", "cut", "initiated"):
            bits.append(f"guidance {call['guid']}")
        if call.get("did") in ("delivered", "missed"):
            bits.append(f"{call['did']} on last quarter's promises")
        build.insert(0, (_d(call.get("d", "")) or today, ", ".join(bits)))
        bad_call = tone in ("Cautious", "Negative") or call.get("guid") == "cut"
        if bad_call:
            flags.append("the latest concall was cautious - the breakout runs against what management said")
    if md.get("top"):
        pts["evidence"] += 1.5
        build.append((today, f"on Market Desk's Top 10 today (#{md['top'].get('r')}: {md['top'].get('h', '')[:80]})"))
    if md.get("early"):
        pts["evidence"] += 1.5

    # -- ahead: the next 30 days
    horizon = today + timedelta(days=30)
    n_dec, kinds_ahead = 0, set()
    for d, k, t in md.get("ahead") or []:
        dd = _d(d) if d else None
        if dd and not (today <= dd <= horizon):
            continue
        seen_k = set(kinds_ahead)
        kinds_ahead.add(k)
        if k == "due":
            pts["ahead"] += 3
            coming.append((dd, "company said due: " + t))
        elif k == "data":  # sector-wide, so worth less than something the company itself said is coming
            pts["ahead"] += 1.5 if "data" not in seen_k else 0.25
            coming.append((dd, t.replace("around this date: ", "monthly data: ")))
        elif k == "results":
            pts["ahead"] += 1.5
            coming.append((dd, "results (board meeting)"))
            flags.append("results due inside the window - an event risk both ways")
        elif k == "decision" and n_dec < 2:
            n_dec += 1
            pts["ahead"] += 1
            coming.append((None, "awaited: " + t))
    pts["ahead"] = min(pts["ahead"], 8)

    # -- industry: shifts it acts on, and whether they are spreading among its peers
    for sh in md.get("shifts") or []:
        if not sh.get("me"):
            continue
        if not sh.get("own", True):  # another industry's shift its own words touch: shown, counts little
            pts["industry"] += 0.5
            inds.append(f"{sh['n']} (from another industry)")
            continue
        s = sh.get("s") or []
        trend = ""
        if len(s) >= 2 and s[-2][2] and s[-1][2] and s[-1][1] >= 2 and s[-1][1] / s[-1][2] > s[-2][1] / s[-2][2] + 0.05:
            pts["industry"] += 1.5  # more of its peers talk about it each quarter
            trend = f", spreading: {s[-2][1]} of {s[-2][2]} peers → {s[-1][1]} of {s[-1][2]}"
        elif s and s[-1][2]:
            trend = f", {s[-1][1]} of {s[-1][2]} peers"
        pts["industry"] += {"early": 1.5, "scaling": 1}.get(sh.get("st"), 0)
        inds.append(f"{sh['n']} ({sh.get('st') or 'stage n/a'}{trend})")
    pts["industry"] = min(pts["industry"], 4)

    # -- timing: getting ahead of news, or reacting to it?
    launch = r.get("launch") or {}
    ago = launch.get("ago", 0) or 0
    bday = today - timedelta(days=int(ago * 7 / 5 + 0.5))  # trading bars -> calendar days, roughly
    if any(dd and abs((dd - bday).days) <= 2 for dd, _ in build if dd != today):
        pts["timing"] -= 2
        flags.append(("the retest" if r.get("setup") == "retest" else "the breakout") + " came with the news - a reaction, not anticipation")
    elif coming:
        pts["timing"] += 2

    # -- chart
    ls = launch.get("score") or 0
    if ls >= 60:
        pts["chart"] += 2
    elif ls:
        pts["chart"] += 1
    if r.get("rs_state") and "Leader" in str(r.get("rs_state")):
        pts["chart"] += 1
    pick = ((r.get("pick") or {}).get("long")) or {}
    if (pick.get("score") or 0) >= 60:
        pts["chart"] += 1

    due_txt = {t for _, t in coming}
    build = [(d, t) for d, t in build if not any(t and t in c for c in due_txt)]  # don't say the same thing twice
    total = round(sum(pts.values()), 1)
    # a dated catalyst of its own: something the company said is due, or its sector's monthly numbers when it is
    # clearly riding a shift that is spreading through its industry
    dated = "due" in kinds_ahead or ("data" in kinds_ahead and pts["industry"] >= 2.5)
    if total >= 14 and dated and pts["evidence"] >= 5 and pts["timing"] > 0 and pts["chart"] >= 3 and not bad_call:
        g = "A"
    elif total >= 9 and (pts["ahead"] >= 2 or pts["evidence"] >= 4):
        g = "B"
    else:
        g = "C"
    rr = None
    if pick.get("entry") and pick.get("stop") and pick.get("target") and pick["entry"] > pick["stop"]:
        rr = round((pick["target"] - pick["entry"]) / (pick["entry"] - pick["stop"]), 1)
    return {"grade": g, "score": total, "pts": {k: round(v, 1) for k, v in pts.items()}, "setup": r.get("setup", "breakout"),
            "build": [t for _, t in sorted(build, key=lambda x: x[0], reverse=True)][:4],
            "coming": [((dd.strftime("%d %b") + ": ") if dd else "") + t for dd, t in sorted(coming, key=lambda x: x[0] or date.max)][:4],
            "industry": inds[:2], "flags": flags[:3], "launch": launch, "rr": rr,
            "plan": {k: pick.get(k) for k in ("entry", "stop", "target")} if pick else {}}


def message(sym: str, name: str, g: dict, r: dict, link: str, when: str) -> str:
    """One alert, Telegram-ready (plain text)."""
    L = g["launch"] or {}
    chart = []
    if g.get("setup") == "retest":
        chart.append(f"cloud retest {L.get('score', 0)}/100 ({(L.get('why') or [''])[0]}; broke out {L.get('break_ago', '?')} sessions ago)")
    elif L.get("score"):
        chart.append(f"cloud launch {L.get('score', 0)}/100" + (f", {L.get('gain')}% bar" if L.get("gain") else ""))
    else:
        chart.append("broke above the cloud")
    if r.get("rs_state"):
        chart.append(f"RS: {r['rs_state']}")
    vx = next((w for w in (L.get("why") or []) if w.startswith("volume")), "")
    if vx:
        chart.append(vx)
    p = g["plan"]
    E = g.get("edge") or {}
    if E.get("rs3m") is not None:
        chart.append(f"beating Nifty by {E['rs3m']:+g} pts in 3 months, {E.get('rs1m') or 0:+g} in 1 · ATR {E.get('atr_pct')}% · ADX {E.get('adx')}")
    kind = "cloud retest" if g.get("setup") == "retest" else "cloud breakout"
    if g.get("side") == "short":
        kind = "failed pullback to the cloud" if g.get("setup") == "retest" else "cloud breakdown"
        chart[:] = [kind + (f" ({(L.get('why') or [''])[0]})" if g.get("setup") == "retest" and L.get("why") else "")]
        if E.get("lag3m") is not None:
            chart.append(f"lagging Nifty by {E['lag3m']:g} pts in 3 months · ATR {E.get('atr_pct')}% · below 200-day average"
                         + (" · Nifty below its cloud" if E.get("nifty_weak") else ""))
    icon = ("🔴" if g.get("side") == "short" else "🟢") if g["grade"] == "A" else ("🟠" if g.get("side") == "short" else "🟡")
    lines = [f"{icon} {'SHORT ' if g.get('side') == 'short' else ''}{g['grade']} · {'INDEX ' if g.get('kind') == 'index' else ''}{name} ({sym}) · {kind} · {when}",
             "Chart: " + ", ".join(chart)]
    if g["build"]:
        lines.append("Building: " + " · ".join(g["build"][:3]))
    if g["coming"]:
        lines.append("Next 30 days: " + " · ".join(g["coming"][:3]))
    if g["industry"]:
        lines.append("Industry: " + " · ".join(g["industry"]))
    if g.get("breadth"):
        lines.append("Breadth: " + g["breadth"])
    if p.get("entry") and p.get("t2") and g.get("side") == "short":
        lines.append(f"Plan (short, futures): sell ~{p['entry']:g} · stop {p['stop']:g} · book half at {p['target']:g} (1R), then stop to entry · rest to {p['t2']:g} (2.5R)")
    elif p.get("entry") and p.get("t2"):
        lines.append(f"Plan: entry ~{p['entry']:g} · stop {p['stop']:g} · book half at {p['target']:g} (+1R), then stop to entry · rest to {p['t2']:g} (2.5R)")
    elif p.get("entry"):
        lines.append(f"Plan: entry ~{p['entry']:g} · stop {p['stop']:g} · target {p['target']:g}" + (f" · reward:risk {g['rr']}" if g["rr"] else ""))
    for f in g["flags"]:
        lines.append("⚠ " + f)
    lines.append(link)
    return "\n".join(lines)


def outcome(rows: list, entry: float, stop: float, target: float, since_ts: int) -> dict:
    """What happened after an alert: target or stop first (daily bars after the alert), and the return so far.
    A short has its stop above the entry; its return is the fall."""
    after = [r for r in rows if r[0] > since_ts]
    res = {"bars": len(after), "status": "open", "ret": None}
    short = stop > entry
    for i, r in enumerate(after):
        lo, hi = r[3], r[2]
        if (hi >= stop) if short else (lo <= stop):
            res.update(status="stopped", day=i + 1)
            break
        if (lo <= target) if short else (hi >= target):
            res.update(status="target", day=i + 1)
            break
    if after:
        res["ret"] = round((after[-1][4] / entry - 1) * (-100 if short else 100), 1)
    if res["status"] == "open" and len(after) >= 40:
        res["status"] = "expired"
    return res


def stats(log_rows: list, days: int = 60) -> dict:
    cut = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    out = {}
    for g in ("A", "B", "SA", "SB"):
        rows = [x for x in log_rows if x.get("date", "") >= cut and
                (x.get("grade") == g[-1]) and ((x.get("side") == "short") == g.startswith("S"))]
        won = sum(1 for x in rows if (x.get("out") or {}).get("status") == "target")
        lost = sum(1 for x in rows if (x.get("out") or {}).get("status") == "stopped")
        out[g] = {"n": len(rows), "won": won, "lost": lost, "open": len(rows) - won - lost}
    return out


def grade_index(label: str, members: list, r: dict, today: date | None = None) -> dict:
    """The same reading for a (sectoral) index: its breakout, backed by what Market Desk knows about the companies in it,
    weighted by their index weight. members = [(md row or None, weight %, state)], state = {"above": bool, "brk": bool,
    "sym": "SBIN"} from the stock scan (None if not scanned)."""
    today = today or date.today()
    tot_w = sum(w for _, w, _ in members) or 1
    cov = [(md, w, st) for md, w, st in members if md]
    W = sum(w for _, w, _ in cov) or 1
    pts = {"evidence": 0.0, "ahead": 0.0, "industry": 0.0, "breadth": 0.0, "timing": 0.0, "chart": 0.0}
    build, coming, inds, flags = [], [], [], []
    subs = [(md, w, st, grade(md, {}, today)) for md, w, st in cov]

    # evidence: the weighted business picture of its companies
    pts["evidence"] = round(sum(w * min(max(g["pts"]["evidence"], -3), 8) for _, w, _, g in subs) / W, 1)
    tone = {}
    for md, w, _, _ in subs:
        t = (md.get("call") or {}).get("tone")
        if t:
            tone[t] = tone.get(t, 0) + w
    tw = sum(tone.values())
    if tw:
        pos, neg = tone.get("Positive", 0) / tw, (tone.get("Cautious", 0) + tone.get("Negative", 0)) / tw
        up = sum(1 for md, *_ in subs if (md.get("call") or {}).get("guid") == "raised")
        cut = sum(1 for md, *_ in subs if (md.get("call") or {}).get("guid") == "cut")
        build.append((today, f"latest concalls: {pos * 100:.0f}% positive, {neg * 100:.0f}% cautious by weight"
                             + (f"; guidance raised by {up}, cut by {cut}" if up or cut else "")))
        if neg > 0.4:
            flags.append("most of its heavyweights sounded cautious on their latest concalls")
    heavy = sorted(subs, key=lambda x: -x[1])[:6]
    cut90 = today - timedelta(days=45)
    for md, w, _, _ in heavy:  # what its heavyweights did lately
        for d, k, t in md.get("ev") or []:
            dd = _d(d)
            if dd and dd >= cut90 and k in ("pivot", "order"):
                build.append((dd, f"{md.get('n', '')[:28]}: {t.split(' - ')[0][:90]}"))
                break

    # ahead: what most of its companies wait for (sector data, decisions), and what its heavyweights said is due
    horizon = today + timedelta(days=30)
    common: dict = {}
    for md, w, _, _ in subs:
        for d, k, t in md.get("ahead") or []:
            dd = _d(d) if d else None
            if dd and not (today <= dd <= horizon):
                continue
            if k in ("data", "decision"):
                common.setdefault((d, k, t), 0)
                common[(d, k, t)] += w
            elif k == "due" and w >= 2:
                pts["ahead"] += min(2.0, w / 4)
                coming.append((dd, f"{md.get('n', '')[:28]} said due: {t[:90]}"))
    for (d, k, t), w in sorted(common.items(), key=lambda x: -x[1]):
        if w / W < 0.2:
            continue
        if k == "data" and not any(c[1].startswith("monthly data") for c in coming):
            pts["ahead"] += 2
            coming.append((_d(d), t.replace("around this date: ", "monthly data: ")))
        elif k == "decision" and sum(1 for c in coming if c[1].startswith("awaited")) < 2:
            pts["ahead"] += 1
            coming.append((None, "awaited: " + t))
    res = sorted((_d(d), md.get("n", "")) for md, w, _, _ in heavy for d, k, _ in (md.get("ahead") or []) if k == "results" and _d(d) and today <= _d(d) <= horizon)
    if res:
        coming.append((res[0][0], "results from " + ", ".join(n[:20] for _, n in res[:3])))
    pts["ahead"] = min(pts["ahead"], 8)

    # industry: shifts its companies are part of, by weight
    agg: dict = {}
    for md, w, _, _ in subs:
        for sh in md.get("shifts") or []:
            if sh.get("me") and sh.get("own", True):
                a = agg.setdefault(sh["n"], {"w": 0, "sh": sh})
                a["w"] += w
    for name, a in sorted(agg.items(), key=lambda x: -x[1]["w"])[:2]:
        if a["w"] / W < 0.15:
            continue
        sh, s = a["sh"], a["sh"].get("s") or []
        spread = len(s) >= 2 and s[-2][2] and s[-1][2] and s[-1][1] / s[-1][2] > s[-2][1] / s[-2][2] + 0.05
        pts["industry"] += (1.5 if spread else 0.5) + {"early": 1, "scaling": 0.5}.get(sh.get("st"), 0)
        inds.append(f"{name} ({a['w'] / W * 100:.0f}% of the index by weight{', spreading' if spread else ''})")
    pts["industry"] = min(pts["industry"], 4)

    # breadth: are its stocks breaking out too, or is one heavyweight carrying it?
    sc = [(w, st) for _, w, st in members if st]
    sw = sum(w for w, _ in sc)
    above = sum(w for w, st in sc if st["above"]) / sw if sw else 0
    fresh = [st["sym"] for w, st in sorted(sc, key=lambda x: -x[0]) if st["brk"]]
    if sw:
        pts["breadth"] = (2 if above >= 0.6 else 1 if above >= 0.45 else -1) + (1 if len(fresh) >= 3 else 0)
        if above < 0.45:
            flags.append(f"only {above * 100:.0f}% of the index (by weight) is above its cloud - narrow")

    # timing: on its heavyweights' news, or ahead of what's coming?
    launch = r.get("launch") or {}
    bday = today - timedelta(days=int((launch.get("ago") or 0) * 7 / 5 + 0.5))
    if any(dd and dd != today and abs((dd - bday).days) <= 1 for dd, _ in build[1:]):
        pts["timing"] -= 1
        flags.append("a heavyweight's news came with the breakout")
    elif coming:
        pts["timing"] += 2

    ls = launch.get("score") or 0
    rs = str(r.get("rs_state") or "")
    pts["chart"] = (2 if ls >= 60 else 1) + (1 if "Leader" in rs or "Beats" in rs else 0)
    total = round(sum(pts.values()), 1)
    covered = W / tot_w
    if total >= 13 and pts["evidence"] >= 3 and pts["breadth"] >= 2 and pts["timing"] > 0 and pts["chart"] >= 2 and covered >= 0.4:
        g = "A"
    elif total >= 8 and covered >= 0.3:
        g = "B"
    else:
        g = "C"
    pick = ((r.get("pick") or {}).get("long")) or {}
    rr = None
    if pick.get("entry") and pick.get("stop") and pick.get("target") and pick["entry"] > pick["stop"]:
        rr = round((pick["target"] - pick["entry"]) / (pick["entry"] - pick["stop"]), 1)
    return {"grade": g, "score": total, "pts": {k: round(v, 1) for k, v in pts.items()}, "kind": "index",
            "build": [t for _, t in sorted(build, key=lambda x: x[0], reverse=True)][:4],
            "coming": [((dd.strftime("%d %b") + ": ") if dd else "") + t for dd, t in sorted(coming, key=lambda x: x[0] or date.max)][:4],
            "industry": inds, "flags": flags[:3], "launch": launch, "rr": rr,
            "breadth": f"{above * 100:.0f}% of it (by weight) above the cloud" + (f"; fresh breakouts: {', '.join(fresh[:5])}" if fresh else "") if sw else "",
            "covered": round(covered * 100), "plan": {k: pick.get(k) for k in ("entry", "stop", "target")} if pick else {}}


# --------------------------------------------------------------------------- the tested edge (chart side)
# From a study of ~6,500 cloud breakouts / launches / retests among Market Desk's companies, Sep 2025 - Nov 2026
# (concalls repo, tools/research_setups.py), checked on a later period than the one it was found on:
#   - a cloud breakout on its own has no edge (about 31% reach 2R before a 1.5-ATR stop; 46-50% reach 1R)
#   - what helps: beating the Nifty over 3 months (by 8+ points) and over 1 month (6+), a stock that moves (daily
#     range, ATR, 3.7%+ of price) and a trend that is young, not stretched (ADX under 21)
#   - all four: ~70% reach +1R before the stop (both periods), ~44-56% reach 1.5-2R; about 20 signals a month, in bursts
#   - the first three without the 1-month RS: ~61% reach +1R, ~44% reach 2R
# So the plan is: stop 1.5 ATR under the entry, book half at +1R and move the stop to the entry, let the rest run to 2.5R.
EDGE = {"rs3m": 8.0, "rs1m": 6.0, "atr_pct": 3.7, "adx": 21}


def edge(rows: list, nifty: list, I: dict | None = None) -> dict:
    """Where a stock stands on the tested conditions. tier 'A' = all four, 'B' = all but the 1-month RS."""
    import scanner
    I = I or scanner.indicators(rows)
    atr = (I.get("atr") or scanner._atr(I))[-1]
    c = rows[-1][4]
    nmap = {r[0] // 86400: r[4] for r in nifty or []}

    def nret(k):
        a, b = nmap.get(rows[-1][0] // 86400), nmap.get(rows[-1 - k][0] // 86400)
        if a is None:  # Nifty's last bar may be a day apart from the stock's
            a = nifty[-1][4] if nifty else None
        return (a / b - 1) * 100 if a and b else None
    out = {"atr_pct": round(atr / c * 100, 2) if atr and c else None, "adx": round(I["adx"][-1] or 0)}
    if len(rows) > 61:
        n3, n1 = nret(60), nret(20)
        out["rs3m"] = round((c / rows[-61][4] - 1) * 100 - n3, 1) if n3 is not None else None
        out["rs1m"] = round((c / rows[-21][4] - 1) * 100 - n1, 1) if n1 is not None else None
    ok3 = out.get("rs3m") is not None and out["rs3m"] > EDGE["rs3m"]
    vol = (out["atr_pct"] or 0) > EDGE["atr_pct"]
    young = out["adx"] < EDGE["adx"]
    ok1 = out.get("rs1m") is not None and out["rs1m"] > EDGE["rs1m"]
    out["tier"] = "A" if ok3 and vol and young and ok1 else "B" if ok3 and vol and young else None
    out["miss"] = [t for t, ok in (("beating the Nifty over 3 months", ok3), ("over 1 month", ok1),
                                   ("moves enough (ATR 3.7%+)", vol), ("young trend (ADX < 21)", young)) if not ok]
    if atr and c:
        R = 1.5 * atr
        out["plan"] = {"entry": round(c, 2), "stop": round(c - R, 2), "target": round(c + R, 2), "t2": round(c + 2.5 * R, 2)}
    return out


def final_grade(e: dict, g: dict) -> str | None:
    """The alert grade: the tested chart edge, kept only when Market Desk's reading isn't against it.
    A breakout that came on the day of the news (reaction) is dropped: in November those won half as often."""
    if not e.get("tier") or g["grade"] == "C":
        return None
    if any("reaction" in f for f in g.get("flags") or []):
        return None
    return e["tier"]


# --------------------------------------------------------------------------- the short side (F&O stocks)
# Same study, prices turned upside down (10,000 / price, so a fall reads like a rise) on F&O stocks, Sep 2022 -
# Nov 2026, split at Jan 2025. Mirroring the long edge did NOT work (too few, no better). What held in both halves:
#   a breakdown below the cloud (or a pullback up to it that fails) by a stock that has lagged the Nifty by 8+ points
#   over 3 months, moves enough (ATR 2.1%+ of price) and is below its 200-day average:
#   ~59-63% reached -1R before a 1.5-ATR stop (40 sessions), ~55-65% within 5 sessions; ~1 in 3 reached -2R.
#   When the Nifty itself was below its cloud too: ~63-67%, but rarer.
SHORT_EDGE = {"lag3m": 8.0, "atr_pct": 2.1}


def mirror(rows: list) -> list:
    """Prices upside down (10,000 / price): the long-side rules then read breakdowns and failed pullbacks."""
    return [[r[0], 1e4 / r[1], 1e4 / r[3], 1e4 / r[2], 1e4 / r[4], r[5]] for r in rows if min(r[1:5]) > 0]


def short_edge(rows: list, nifty: list, nifty_below_cloud: bool | None) -> dict:
    import scanner
    I = scanner.indicators(rows)
    atr = scanner._atr(I)[-1]
    c = rows[-1][4]
    out = {"atr_pct": round(atr / c * 100, 2) if atr and c else None, "below200": bool(I["ema200"][-1] and c < I["ema200"][-1])}
    nmap = {r[0] // 86400: r[4] for r in nifty or []}
    if len(rows) > 61:
        a = nmap.get(rows[-1][0] // 86400) or (nifty[-1][4] if nifty else None)
        b = nmap.get(rows[-61][0] // 86400)
        if a and b:
            out["lag3m"] = round((a / b - 1) * 100 - (c / rows[-61][4] - 1) * 100, 1)
    ok = (out.get("lag3m") or -99) > SHORT_EDGE["lag3m"] and (out["atr_pct"] or 0) > SHORT_EDGE["atr_pct"] and out["below200"]
    out["nifty_weak"] = bool(nifty_below_cloud)
    out["tier"] = ("A" if nifty_below_cloud else "B") if ok else None
    if atr and c:
        R = 1.5 * atr
        out["plan"] = {"entry": round(c, 2), "stop": round(c + R, 2), "target": round(c - R, 2), "t2": round(c - 2.5 * R, 2)}
    return out


def short_view(md: dict | None, today: date) -> dict:
    """Market Desk's reading for a short: a strong positive reading is a reason not to short (veto); events ahead are
    risks either way. Not tested as an edge (the news history is too short) - only used to stay out."""
    if not md:
        return {"veto": False, "notes": [], "coming": []}
    g = grade(md, {}, today)
    call = md.get("call") or {}
    notes = []
    if call.get("tone") in ("Cautious", "Negative"):
        notes.append(f"{call.get('q', '')} concall {call['tone'].lower()}")
    if call.get("guid") == "cut":
        notes.append("guidance cut")
    if call.get("did") == "missed":
        notes.append("missed last quarter's promises")
    strong = g["pts"]["evidence"] >= 5 and call.get("tone") == "Positive"
    return {"veto": strong, "notes": notes, "coming": g["coming"][:3], "build": g["build"][:2] if strong else [],
            "backing": g["grade"]}
