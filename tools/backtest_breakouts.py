"""Back-test of TradeCharts' breakout + news alerts over the last few weeks (since Market Desk's news starts).

For every trading day from START, every Market Desk company is checked the way TradeCharts' scanner would have seen it
on that day (prices only up to that day): a cloud breakout, a cloud launch, or a cloud retest. Each signal is graded
with TradeCharts' catalyst grade using only what Market Desk knew by then (events up to that day, the concall only if
it had happened, monthly data dates rolled to that day), then followed to today: return, best and worst point, and
whether the 2R target or the stop came first. The news that came after the signal is listed next to it.

Prices: Yahoo daily candles (NSE where the company is listed there). Output: backtest/report.md + results.json.
Run by .github/workflows/backtest.yml (by hand)."""
from __future__ import annotations

import csv
import io
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "tc"))
import catalyst  # noqa: E402  (TradeCharts' copy)
import scanner  # noqa: E402

START = date.fromisoformat(os.getenv("START", "2026-11-03"))
OUT = HERE.parent / "backtest"
IST = timezone(timedelta(hours=5, minutes=30))
MIN_TURNOVER = 5e7


def why():
    import backstory as BS
    import site_builder as S
    import timeline as TL
    return S.why_file(TL.load(), BS.load())["cos"]


def tickers(codes):
    """BSE code -> Yahoo symbol (NSE via ISIN where listed there, else BSE)."""
    def master(seg):
        t = requests.get(f"https://public.fyers.in/sym_details/{seg}.csv", timeout=60).text
        return list(csv.reader(io.StringIO(t)))
    nse = {}
    for c in master("NSE_CM"):
        if len(c) > 9 and c[9].endswith(("-EQ", "-BE")) and c[5].strip():
            nse[c[5].strip()] = c[9].split(":")[1].rsplit("-", 1)[0]
    out = {}
    for c in master("BSE_CM"):
        if len(c) > 12 and c[12].strip() in codes:
            isin = c[5].strip()
            out[c[12].strip()] = (nse[isin] + ".NS") if isin in nse else (c[12].strip() + ".BO")
    for code in codes:
        out.setdefault(code, code + ".BO")
    return out


def prices(symbols):
    import yfinance as yf
    rows = {}
    syms = list(dict.fromkeys(symbols))
    for k in range(0, len(syms), 150):
        part = syms[k:k + 150]
        df = yf.download(part, period="2y", interval="1d", auto_adjust=False, group_by="ticker", progress=False, threads=True)
        for s in part:
            try:
                d = df[s] if len(part) > 1 else df
                d = d.dropna(subset=["Close"])
                rows[s] = [[int(datetime(t.year, t.month, t.day, 9, 15, tzinfo=IST).timestamp()), float(r["Open"]), float(r["High"]),
                            float(r["Low"]), float(r["Close"]), float(r["Volume"] or 0)] for t, r in d.iterrows()]
            except Exception:  # noqa: BLE001
                pass
        print(f"prices {min(k + 150, len(syms))}/{len(syms)}", flush=True)
    return rows


def as_of(md, d):
    """Market Desk's row as it would have looked on day d."""
    m = dict(md)
    m["ev"] = [e for e in md.get("ev") or [] if e[0] <= d.isoformat()]
    call = md.get("call") or {}
    if call.get("d", "9999") > d.isoformat():
        m.pop("call", None)
    ahead = []
    for a in md.get("ahead") or []:
        if a[1] == "data" and a[0]:  # monthly: the next date with that day of month after d
            day = int(a[0][8:10])
            nd = d.replace(day=min(day, 28))
            while nd <= d:
                nd = (nd.replace(day=1) + timedelta(days=32)).replace(day=min(day, 28))
            ahead.append([nd.isoformat(), "data", a[2]])
        elif a[1] in ("due", "results") and a[0] and a[0] > d.isoformat():
            ahead.append(a)
        elif a[1] == "decision":
            ahead.append(a)
    m["ahead"] = ahead
    m.pop("top", None)
    m.pop("early", None)
    return m


def main():
    cos = why()
    ymap = tickers(set(cos))
    px = prices(list(ymap.values()) + ["^NSEI"])
    nifty = px.get("^NSEI") or []
    today = date.today()
    sigs = []
    for code, md in cos.items():
        rows = px.get(ymap.get(code))
        if not rows or len(rows) < 200:
            continue
        I = scanner.indicators(rows)
        I["atr"] = scanner._atr(I)
        c = I["c"]

        def top(i):
            a, b = I["span_a"][i], I["span_b"][i]
            return None if a is None or b is None else max(a, b)
        dates = [datetime.fromtimestamp(r[0], IST).date() for r in rows]
        last_rt = -1
        for i in range(len(rows)):
            d = dates[i]
            if d < START or i < 150:
                continue
            if sum(rows[k][4] * rows[k][5] for k in range(i - 20, i)) / 20 < MIN_TURNOVER:
                continue
            t0, t1 = top(i), top(i - 1)
            setup = None
            launch = None
            if t0 and t1 and c[i] > t0 and c[i - 1] <= t1:
                setup = "breakout"
                launch = scanner.cloud_launch(I, 1, at=i)
            else:
                R = scanner.cloud_retest(I, 1, at=i)
                if R and i - R["break_ago"] != last_rt:
                    last_rt = i - R["break_ago"]
                    setup = "retest"
            if not setup:
                continue
            tr = rows[:i + 1]
            ev = scanner.evaluate(tr, 3)
            if not ev:
                continue
            ntr = [r for r in nifty if r[0] <= rows[i][0]]
            try:
                _, vals = scanner.rs_eval(tr, ntr, ntr, 3)
                ev.update(vals)
            except Exception:  # noqa: BLE001
                pass
            if setup == "retest":
                L = {"ago": 0, "score": R["score"], "why": R["why"], "break_ago": R["break_ago"]}
                pick = {"long": dict(R["plan"], score=R["score"])}
            else:
                L = launch or {"ago": 0, "score": 0}
                ev["launch"] = launch
                pick = scanner.trade_pick(tr, ev, ev, None, "swing", "unknown")
            r = {"launch": L, "rs_state": ev.get("rs_state"), "pick": pick, "setup": setup}
            g = catalyst.grade(as_of(md, d), r, d)
            p = g.get("plan") or {}
            e = c[i]
            stop = p.get("stop") or (min(I["kij"][i] or t0 or e, t0 or e) - 0.25 * I["atr"][i])
            tgt = p.get("target") or e + 2 * (e - stop)
            res, day = "open", None
            for j in range(i + 1, len(rows)):
                if rows[j][3] <= stop:
                    res, day = "stopped", j - i
                    break
                if rows[j][2] >= tgt:
                    res, day = "target", j - i
                    break
            after = rows[i + 1:]
            news = [x for x in md.get("ev") or [] if x[0] > d.isoformat()]
            sigs.append({
                "code": code, "sym": ymap[code], "name": md.get("n", ""), "sector": md.get("s", ""), "date": d.isoformat(),
                "setup": "launch" if launch else setup, "grade": g["grade"], "score": g["score"], "pts": g["pts"],
                "close": round(e, 2), "now": round(c[-1], 2), "ret": round((c[-1] / e - 1) * 100, 1),
                "best": round((max(x[2] for x in after) / e - 1) * 100, 1) if after else 0,
                "worst": round((min(x[3] for x in after) / e - 1) * 100, 1) if after else 0,
                "entry": round(e, 2), "stop": round(stop, 2), "target": round(tgt, 2), "res": res, "day": day,
                "launch_score": L.get("score"), "rs": ev.get("rs_state"),
                "coming": g["coming"], "build": g["build"], "industry": g["industry"], "flags": g["flags"],
                "news_after": [f"{x[0]} {x[1]}: {x[2][:110]}" for x in news][:4],
            })
    OUT.mkdir(exist_ok=True)
    (OUT / "results.json").write_text(json.dumps({"at": datetime.now(IST).isoformat(), "start": START.isoformat(),
                                                  "today": today.isoformat(), "signals": sigs}, indent=1))
    lines = [f"# Breakout + news back-test, {START:%d %b} to {today:%d %b %Y}", "",
             f"{len(cos)} Market Desk companies, {len(sigs)} signals (cloud breakouts, launches, retests; ₹5 cr+ a day).", ""]
    lines.append("| Grade | Signals | Avg return to date | Hit target first | Stopped | Still open |")
    lines.append("|---|---|---|---|---|---|")
    for gr in ("A", "B", "C"):
        xs = [s for s in sigs if s["grade"] == gr]
        if xs:
            lines.append(f"| {gr} | {len(xs)} | {sum(s['ret'] for s in xs) / len(xs):+.1f}% | {sum(s['res'] == 'target' for s in xs)} | "
                         f"{sum(s['res'] == 'stopped' for s in xs)} | {sum(s['res'] == 'open' for s in xs)} |")
    for st in ("launch", "breakout", "retest"):
        xs = [s for s in sigs if s["setup"] == st]
        if xs:
            lines.append(f"| {st} (all grades) | {len(xs)} | {sum(s['ret'] for s in xs) / len(xs):+.1f}% | {sum(s['res'] == 'target' for s in xs)} | "
                         f"{sum(s['res'] == 'stopped' for s in xs)} | {sum(s['res'] == 'open' for s in xs)} |")
    for gr in ("A", "B"):
        lines += ["", f"## Grade {gr}", ""]
        for s in sorted((s for s in sigs if s["grade"] == gr), key=lambda s: s["date"]):
            lines.append(f"- **{s['name']}** ({s['sym']}) {s['date']} {s['setup']}: {s['close']} → {s['now']} ({s['ret']:+.1f}%, best {s['best']:+.1f}%, "
                         f"worst {s['worst']:+.1f}%) – {s['res']}{' day ' + str(s['day']) if s['day'] else ''}")
            for k in ("coming", "build", "industry", "flags", "news_after"):
                if s[k]:
                    lines.append(f"  - {k}: " + " · ".join(s[k][:3]))
    (OUT / "report.md").write_text("\n".join(lines))
    print("\n".join(lines[:20]))


if __name__ == "__main__":
    main()
