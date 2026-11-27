"""Research for TradeCharts' setups: which conditions raise the win rate of a cloud breakout / retest?

Two years of daily prices (Yahoo) for Market Desk's companies. Every cloud breakout, cloud launch and cloud retest is
recorded with the conditions on that day (chart, relative strength, sector and market breadth, weekly trend ...) and the
price path for the next 40 sessions in ATR units from the entry (the signal day's close), so any stop / target can be
tried afterwards without fetching again. Output: research/signals.json (+ the Nifty), on the 'research' branch.
Run by .github/workflows/research.yml (by hand)."""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE / "tc"))
sys.path.insert(0, str(HERE))
import backtest_breakouts as BT  # noqa: E402
import scanner  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
OUT = HERE.parent / "research"
FWD = 40


def weekly(rows):
    w, key = [], None
    for r in rows:
        d = datetime.fromtimestamp(r[0], IST).date()
        k = d.isocalendar()[:2]
        if k != key:
            w.append(list(r))
            key = k
        else:
            x = w[-1]
            x[2], x[3], x[4], x[5] = max(x[2], r[2]), min(x[3], r[3]), r[4], x[5] + r[5]
    return w


def main():
    cos = BT.why()
    ymap = BT.tickers(set(cos))
    px = BT.prices(list(ymap.values()) + ["^NSEI"])
    nifty = px.get("^NSEI") or []
    nI = scanner.indicators(nifty)
    n_date = {datetime.fromtimestamp(r[0], IST).date(): k for k, r in enumerate(nifty)}

    def ntop(k):
        a, b = nI["span_a"][k], nI["span_b"][k]
        return None if a is None or b is None else max(a, b)
    # pass 1: every stock's indicators, and who is above its cloud each day (breadth)
    data, above = {}, {}
    for code, md in cos.items():
        rows = px.get(ymap.get(code))
        if not rows or len(rows) < 260:
            continue
        I = scanner.indicators(rows)
        I["atr"] = scanner._atr(I)
        dates = [datetime.fromtimestamp(r[0], IST).date() for r in rows]
        data[code] = (rows, I, dates)
        for i, d in enumerate(dates):
            a, b = I["span_a"][i], I["span_b"][i]
            if a is not None and b is not None:
                above.setdefault(d, {}).setdefault(md.get("s", ""), [0, 0])
                s = above[d][md.get("s", "")]
                s[0] += I["c"][i] > max(a, b)
                s[1] += 1
    print("stocks with prices:", len(data), flush=True)
    sigs = []
    for code, (rows, I, dates) in data.items():
        md = cos[code]
        sec = md.get("s", "")
        c, h, l, v = I["c"], I["h"], I["l"], I["v"]
        W = weekly(rows)
        WI = scanner.indicators(W) if len(W) > 60 else None
        wdates = [datetime.fromtimestamp(r[0], IST).date() for r in W]

        def top(i):
            a, b = I["span_a"][i], I["span_b"][i]
            return None if a is None or b is None else max(a, b)
        last_rt, wk = -1, 0
        for i in range(200, len(rows) - 1):
            d = dates[i]
            while wk + 1 < len(wdates) and wdates[wk + 1] <= d:
                wk += 1
            turnover = sum(rows[k][4] * rows[k][5] for k in range(i - 20, i)) / 20
            if turnover < 5e7:
                continue
            t0, t1 = top(i), top(i - 1)
            setup, L, R = None, None, None
            if t0 and t1 and c[i] > t0 and c[i - 1] <= t1:
                setup = "breakout"
                L = scanner.cloud_launch(I, 1, at=i)
                if L:
                    setup = "launch"
            else:
                R = scanner.cloud_retest(I, 1, at=i)
                if R and i - R["break_ago"] != last_rt:
                    last_rt = i - R["break_ago"]
                    setup = "retest"
            if not setup:
                continue
            atr = I["atr"][i]
            if not atr:
                continue
            e = c[i]
            kij = I["kij"][i] or t0
            if setup == "retest":
                stop = R["plan"]["stop"]
            else:
                stop = min(kij, t0) - 0.25 * atr
            k = n_date.get(d)
            nt = ntop(k) if k is not None else None
            mk = above.get(d, {})
            all_a = sum(x[0] for x in mk.values()), sum(x[1] for x in mk.values())
            sa = mk.get(sec, [0, 0])
            vavg = sum(v[i - 20:i]) / 20 or 1
            hi52 = max(h[max(0, i - 250):i + 1])
            wtop = None
            if WI and wk >= 1:
                a, b = WI["span_a"][wk - 1], WI["span_b"][wk - 1]
                wtop = max(a, b) if a is not None and b is not None else None
            f = {
                "code": code, "name": md.get("n", ""), "sector": sec, "date": d.isoformat(), "setup": setup,
                "score": (L or R or {}).get("score", 0),
                "stop_atr": round((e - stop) / atr, 2),
                "ret20": round((e / c[i - 20] - 1) * 100, 1), "ret60": round((e / c[i - 60] - 1) * 100, 1),
                "n_ret20": round((nifty[k][4] / nifty[k - 20][4] - 1) * 100, 1) if k and k >= 60 else None,
                "n_ret60": round((nifty[k][4] / nifty[k - 60][4] - 1) * 100, 1) if k and k >= 60 else None,
                "n_above": (nifty[k][4] > nt) if nt else None,
                "n_ema50": (nifty[k][4] > (nI["ema50"][k] or 0)) if k else None,
                "mkt_above": round(all_a[0] / all_a[1], 2) if all_a[1] else None,
                "sec_above": round(sa[0] / sa[1], 2) if sa[1] >= 5 else None,
                "vol_x": round(v[i] / vavg, 2), "day_chg": round((e / c[i - 1] - 1) * 100, 2),
                "close_pos": round((e - l[i]) / (h[i] - l[i]), 2) if h[i] > l[i] else 0.5,
                "ext_atr": round((e - t0) / atr, 2) if t0 else None, "kij_atr": round((e - kij) / atr, 2) if kij else None,
                "from_hi52": round((e / hi52 - 1) * 100, 1),
                "rsi": round(I["rsi"][i] or 0), "adx": round(I["adx"][i] or 0),
                "macd_pos": (I["macd"][i] or 0) > 0, "hist_up": (I["hist"][i] or 0) > (I["hist"][i - 1] or 0),
                "ema50_up": (I["ema50"][i] or 0) > (I["ema50"][i - 10] or 0), "above200": e > (I["ema200"][i] or 1e18),
                "fut_bull": None not in (I["ten"][i], I["kij"][i], I["sb"][i]) and (I["ten"][i] + I["kij"][i]) / 2 > I["sb"][i],
                "chikou": e > h[i - 26], "w_above": (W[wk - 1][4] > wtop) if wtop else None,
                "cloud_thick": round(abs((I["span_a"][i] or 0) - (I["span_b"][i] or 0)) / atr, 2),
                "atr_pct": round(atr / e * 100, 2), "turnover_cr": round(turnover / 1e7, 1),
                "path": [[round((h[j] - e) / atr, 2), round((l[j] - e) / atr, 2), round((c[j] - e) / atr, 2)]
                         for j in range(i + 1, min(len(rows), i + 1 + FWD))],
            }
            sigs.append(f)
    OUT.mkdir(exist_ok=True)
    (OUT / "signals.json").write_text(json.dumps({"at": datetime.now(IST).isoformat(), "signals": sigs}))
    print("signals:", len(sigs))


if __name__ == "__main__":
    main()
