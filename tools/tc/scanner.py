"""
Setup scanner: evaluates chart setups on daily (or weekly) candles.
Calculations match the chart's indicators: Wilder smoothing for RSI / DMI, Ichimoku spans shifted forward 26 bars.
Candles are rows [ts, open, high, low, close, volume], oldest first.
"""
from __future__ import annotations

RULES = [  # id, group, label, bullish?
    ("ichi_above", "Ichimoku", "Price above the cloud", True),
    ("ichi_break", "Ichimoku", "Price broke above the cloud", True),
    ("ichi_tk", "Ichimoku", "Tenkan crossed above Kijun", True),
    ("ichi_chikou", "Ichimoku", "Chikou above price (26 bars ago)", True),
    ("ichi_future", "Ichimoku", "Future cloud bullish (Span A > Span B)", True),
    ("ichi_attack", "Ichimoku", "Attacking the cloud: closed into or through the cloud from below", True),
    ("ichi_breakdown", "Ichimoku", "Price broke below the cloud", False),
    ("dmi_cross", "DMI", "+DI crossed above −DI", True),
    ("dmi_trend", "DMI", "+DI > −DI with ADX > 20 and rising", True),
    ("dmi_cross_dn", "DMI", "−DI crossed above +DI", False),
    ("rsi_50", "RSI", "RSI crossed above 50", True),
    ("rsi_strong", "RSI", "RSI 60 or higher", True),
    ("rsi_os", "RSI", "RSI 30 or lower (oversold)", False),
    ("macd_cross", "MACD", "MACD crossed above signal", True),
    ("macd_zero", "MACD", "MACD crossed above zero", True),
    ("macd_hist_up", "MACD", "Histogram rising for 2 bars", True),
    ("macd_hist_surge", "MACD", "Strong histogram: above zero, rising 3 bars, tallest in ~3 months and 2× its usual size", True),
    ("macd_cross_dn", "MACD", "MACD crossed below signal", False),
    ("hi52", "Price & volume", "Within 3% of the 52-week high", True),
    ("hi52_break", "Price & volume", "New 52-week high", True),
    ("ema_stack", "Price & volume", "Close > EMA 20 > EMA 50 > EMA 200", True),
    ("ema20_reclaim", "Price & volume", "Close crossed above EMA 20", True),
    ("vol_surge", "Price & volume", "Volume 2× the 20-bar average", True),
    ("cloud_launch", "Setups", "Cloud launch: breakout from a base on the cloud (see score)", True),
    ("flow_acc", "Smart money", "Accumulation score 65+ (delivery, money flow, F&O, deals)", True),
    ("flow_strong", "Smart money", "Strong accumulation: score 75+", True),
    ("flow_deliv", "Smart money", "Delivery 2× its normal on an up day (latest day)", True),
    ("flow_long", "Smart money", "F&O long build-up or short covering", True),
    ("flow_dist", "Smart money", "Distribution: score 35 or less", False),
    ("rs_lead", "Relative strength", "Leader: stronger than its sector index AND its broad index (RS 55 above 0)", True),
    ("rs_sector", "Relative strength", "Stronger than its sector index (RS 55 above 0)", True),
    ("rs_broad", "Relative strength", "Stronger than its broad index: Nifty 50 / Midcap / Smallcap… (RS 55 above 0)", True),
    ("rs_turn", "Relative strength", "Turning into a leader: RS vs its broad index crossed above 0 recently", True),
    ("rs_rising", "Relative strength", "RS rising: stronger than 10 bars ago against both indices", True),
    ("rs_lag", "Relative strength", "Laggard: weaker than its sector index AND its broad index", False),
    ("rs_long", "Relative strength", "Leader on the bigger picture too: ahead of both indices over ~6 months (125 days / 26 weeks)", True),
    ("ichi_near", "Ichimoku", "Pulled back to cloud support: dipped to within 3% of the cloud top and still closes above it", True),
    ("cloud_retest", "Setups", "Cloud retest: a fresh cloud breakout pulled back to the cloud top / Kijun, held, and is turning up (see score)", True),
    ("ms_up", "Market structure", "Uptrend structure: higher highs and higher lows (last swing break was upward)", True),
    ("ms_bos", "Market structure", "Break of structure ↑: closed above the last swing high", True),
    ("ms_choch_up", "Market structure", "Change of character ↑: a downtrend just broke upward (first higher high)", True),
    ("ms_choch_dn", "Market structure", "Change of character ↓: an uptrend just broke its last higher low (warning for longs)", False),
    ("vp_support", "Volume profile", "Sitting on the busiest price (point of control) of the last ~6 months: within 3% above it", True),
]
RS_LEN = 55
TAGS = {"ichi_above": "☁↑", "ichi_break": "☁ break", "ichi_tk": "TK×", "ichi_chikou": "Chikou↑", "ichi_future": "☁+",
        "ichi_breakdown": "☁↓", "dmi_cross": "DI×↑", "dmi_trend": "ADX↑", "dmi_cross_dn": "DI×↓", "rsi_50": "RSI>50",
        "rsi_strong": "RSI 60+", "rsi_os": "RSI≤30", "macd_cross": "MACD×↑", "macd_zero": "MACD>0", "macd_hist_up": "Hist↑", "flow_acc": "🏦 acc", "flow_strong": "🏦🏦", "flow_deliv": "Deliv×2", "flow_long": "OI long", "flow_dist": "🏦 dist", "macd_hist_surge": "Hist⚡", "ichi_attack": "☁ attack",
        "macd_cross_dn": "MACD×↓", "hi52": "near 52wH", "hi52_break": "52wH!", "ema_stack": "EMA stack", "ema20_reclaim": ">EMA20",
        "vol_surge": "Vol 2×", "cloud_launch": "🚀 Cloud launch", "rs_lead": "RS leader", "rs_sector": "RS>sector",
        "rs_broad": "RS>mkt", "rs_turn": "RS turn↑", "rs_rising": "RS↑", "rs_lag": "RS laggard", "rs_long": "RS 6M",
        "ichi_near": "☁ pullback", "cloud_retest": "↩ Cloud retest", "ms_up": "HH·HL", "ms_bos": "BOS↑", "ms_choch_up": "ChoCH↑", "ms_choch_dn": "ChoCH↓",
        "vp_support": "on POC"}
RS_LONG = {"D": 125, "1W": 26}


def _align(rows: list, idx_rows: list) -> list:
    """Index close for each stock bar (same day, or the last one before it); rows are [ts, o, h, l, c, v]."""
    out, j, m = [], 0, len(idx_rows)
    for r in rows:
        t = r[0]
        while j + 1 < m and idx_rows[j + 1][0] <= t:
            j += 1
        out.append(idx_rows[j][4] if m and idx_rows[j][0] <= t else None)
    return out


def rs_series(rows: list, idx_rows: list | None, n: int = RS_LEN) -> list:
    """RS = (stock now / stock n bars ago) / (index now / index n bars ago) - 1, per bar (None where unknown)."""
    if not idx_rows:
        return [None] * len(rows)
    I = _align(rows, idx_rows)
    out = []
    for i, r in enumerate(rows):
        if i < n or not (I[i] and I[i - n] and r[4] and rows[i - n][4]):
            out.append(None)
        else:
            out.append((r[4] / rows[i - n][4]) / (I[i] / I[i - n]) - 1)
    return out


def rs_state(sv, bv, s_ago, b_ago) -> str:
    """Plain-English reading of the two RS lines now and 10 bars ago (the same words the chart's RS legend uses)."""
    if bv is None:
        return ""
    sec_ok = sv is None or sv > 0
    rising = bv > (b_ago if b_ago is not None else bv) and (sv is None or s_ago is None or sv >= s_ago)
    if bv > 0 and sec_ok:
        return "Leader, still pulling ahead" if rising else "Leader, but fading"
    if bv < 0 and (sv is None or sv < 0):
        return "Improving laggard" if rising else "Laggard"
    return ("Beats its sector, not the market" if sv is not None and sv > 0 else "Beats the market, not its sector") + (" (rising)" if rising else "")


def rs_eval(rows: list, sec_rows: list | None, brd_rows: list | None, within: int = 3, weekly: bool = False) -> tuple[set, dict]:
    """Relative-strength rules and the latest RS values (in %)."""
    s, b = rs_series(rows, sec_rows), rs_series(rows, brd_rows)
    nl = RS_LONG["1W" if weekly else "D"]
    sl, bl = rs_series(rows, sec_rows, nl), rs_series(rows, brd_rows, nl)
    last = len(rows) - 1
    hits = set()
    sv, bv = s[last] if s else None, b[last] if b else None
    if sv is not None and sv > 0:
        hits.add("rs_sector")
    if bv is not None and bv > 0:
        hits.add("rs_broad")
    if bv is not None and bv > 0 and (sv is None or sv > 0):
        hits.add("rs_lead")  # no sector index for the stock: the broad index decides
    if bv is not None and bv < 0 and (sv is None or sv < 0):
        hits.add("rs_lag")
    if any(b[i] is not None and b[i - 1] is not None and b[i] > 0 >= b[i - 1] for i in range(max(1, last - within + 1), last + 1)):
        hits.add("rs_turn")
    k = last - 10
    if k >= 0 and bv is not None and b[k] is not None and bv > b[k] and (sv is None or (s[k] is not None and sv > s[k])):
        hits.add("rs_rising")
    slv, blv = sl[last] if sl else None, bl[last] if bl else None
    if blv is not None and blv > 0 and (slv is None or slv > 0):
        hits.add("rs_long")
    pct = lambda v: round(v * 100, 1) if v is not None else None  # noqa: E731
    state = rs_state(sv, bv, s[k] if k >= 0 else None, b[k] if k >= 0 else None)
    return hits, {"rs_sec": pct(sv), "rs_brd": pct(bv), "rs_long": pct(blv), "rs_state": state}


def structure(rows_h: list, rows_l: list, rows_c: list, k: int = 5) -> dict:
    """Swing highs / lows (a bar higher / lower than the k bars each side) and the breaks between them.

    Walking forward, a close above the last unbroken swing high is a break of structure (BOS) up when the trend was
    already up, or a change of character (ChoCH) up when it was down; the same downward. Pivots only count once the
    k bars after them exist, so nothing here repaints. Same rules as the chart's "Market structure" indicator.
    """
    n = len(rows_c)
    piv = []  # (bar, 'H'|'L', price, label)
    events = []  # (bar, 'BOS'|'CHOCH', 'up'|'down', level, pivot bar)
    trend = None
    sh = sl = None  # last unbroken swing high / low: (bar, price)
    last_h = last_l = None
    for i in range(n):
        j = i - k  # the bar that becomes a confirmed pivot now
        if j >= k:
            hj, lj = rows_h[j], rows_l[j]
            if hj > max(rows_h[j - k:j]) and hj >= max(rows_h[j + 1:i + 1]):
                lab = "HH" if last_h is None or hj > last_h else "LH"
                piv.append((j, "H", hj, lab)); last_h = hj; sh = (j, hj)
            if lj < min(rows_l[j - k:j]) and lj <= min(rows_l[j + 1:i + 1]):
                lab = "LL" if last_l is None or lj < last_l else "HL"
                piv.append((j, "L", lj, lab)); last_l = lj; sl = (j, lj)
        c = rows_c[i]
        if sh and c > sh[1]:
            events.append((i, "CHOCH" if trend == "down" else "BOS", "up", sh[1], sh[0])); trend = "up"; sh = None
        elif sl and c < sl[1]:
            events.append((i, "CHOCH" if trend == "up" else "BOS", "down", sl[1], sl[0])); trend = "down"; sl = None
    return {"pivots": piv, "events": events, "trend": trend}


def structure_hits(I: dict, within: int, weekly: bool) -> set:
    st = structure(I["h"], I["l"], I["c"], 3 if weekly else 5)
    last = len(I["c"]) - 1
    hits = set()
    if st["trend"] == "up":
        hits.add("ms_up")
    for i, kind, d, _lv, _pb in st["events"]:
        if i > last - within:
            if d == "up":
                hits.add("ms_bos")
                if kind == "CHOCH":
                    hits.add("ms_choch_up")
            elif kind == "CHOCH":
                hits.add("ms_choch_dn")
    return hits


def volume_profile(h: list, l: list, v: list, bins: int = 40) -> dict | None:
    """Volume at price over the given bars: each bar's volume spread evenly over its high-low range.
    Returns the bin edges, volume per bin, the point of control (busiest price) and the 70% value area."""
    if not h:
        return None
    lo, hi = min(l), max(h)
    if not hi > lo:
        return None
    step = (hi - lo) / bins
    vol = [0.0] * bins
    for a, b, x in zip(h, l, v):
        if not x:
            continue
        i0, i1 = int((b - lo) / step), int((a - lo) / step)
        i0, i1 = max(0, min(bins - 1, i0)), max(0, min(bins - 1, i1))
        share = x / (i1 - i0 + 1)
        for i in range(i0, i1 + 1):
            vol[i] += share
    poc = max(range(bins), key=lambda i: vol[i])
    tot, acc, a, b = sum(vol), vol[poc], poc, poc
    while tot and acc < 0.7 * tot and (a > 0 or b < bins - 1):
        up = vol[b + 1] if b < bins - 1 else -1
        dn = vol[a - 1] if a > 0 else -1
        if up >= dn:
            b += 1; acc += up
        else:
            a -= 1; acc += dn
    mid = lambda i: lo + (i + 0.5) * step  # noqa: E731
    return {"lo": lo, "step": step, "vol": vol, "poc": mid(poc), "val": lo + a * step, "vah": lo + (b + 1) * step}


def _ema(v: list, n: int) -> list:
    out, k, e, s, c = [], 2 / (n + 1), None, 0.0, 0
    for x in v:
        if x is None:
            out.append(None); continue
        if e is None:
            s += x; c += 1
            if c == n:
                e = s / n
            out.append(e); continue
        e = x * k + e * (1 - k); out.append(e)
    return out


def _rma(v: list, n: int) -> list:  # Wilder's smoothing
    out, r, s, c = [], None, 0.0, 0
    for x in v:
        if x is None:
            out.append(None); continue
        if r is None:
            s += x; c += 1
            if c == n:
                r = s / n
            out.append(r); continue
        r = (r * (n - 1) + x) / n; out.append(r)
    return out


def _sma(v: list, n: int) -> list:
    out = []
    for i in range(len(v)):
        w = v[max(0, i - n + 1): i + 1]
        out.append(sum(w) / n if len(w) == n and None not in w else None)
    return out


def _hl(h: list, l: list, i: int, n: int):
    if i - n + 1 < 0:
        return None
    return (max(h[i - n + 1: i + 1]) + min(l[i - n + 1: i + 1])) / 2


def indicators(rows: list) -> dict:
    o = [r[1] for r in rows]; h = [r[2] for r in rows]; l = [r[3] for r in rows]; c = [r[4] for r in rows]
    v = [(r[5] if len(r) > 5 and r[5] is not None else 0) for r in rows]
    n = len(c)
    # RSI 14
    g = [None] + [max(c[i] - c[i - 1], 0) for i in range(1, n)]
    ls = [None] + [max(c[i - 1] - c[i], 0) for i in range(1, n)]
    ag, al = _rma(g, 14), _rma(ls, 14)
    rsi = [None if ag[i] is None else (100.0 if al[i] == 0 else 100 - 100 / (1 + ag[i] / al[i])) for i in range(n)]
    # MACD 12 26 9
    e12, e26 = _ema(c, 12), _ema(c, 26)
    macd = [None if e12[i] is None or e26[i] is None else e12[i] - e26[i] for i in range(n)]
    sig = _ema(macd, 9)
    hist = [None if macd[i] is None or sig[i] is None else macd[i] - sig[i] for i in range(n)]
    # DMI 14 14
    tr, pdm, mdm = [None], [None], [None]
    for i in range(1, n):
        up, dn = h[i] - h[i - 1], l[i - 1] - l[i]
        tr.append(max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])))
        pdm.append(up if up > dn and up > 0 else 0); mdm.append(dn if dn > up and dn > 0 else 0)
    atr, sp, sm = _rma(tr, 14), _rma(pdm, 14), _rma(mdm, 14)
    pdi = [None if not atr[i] else 100 * sp[i] / atr[i] for i in range(n)]
    mdi = [None if not atr[i] else 100 * sm[i] / atr[i] for i in range(n)]
    dx = [None if pdi[i] is None or mdi[i] is None else (100 * abs(pdi[i] - mdi[i]) / (pdi[i] + mdi[i]) if pdi[i] + mdi[i] else 0) for i in range(n)]
    adx = _rma(dx, 14)
    # Ichimoku 9 26 52 26: the cloud at bar i was computed 26 bars earlier
    ten = [_hl(h, l, i, 9) for i in range(n)]; kij = [_hl(h, l, i, 26) for i in range(n)]; sb = [_hl(h, l, i, 52) for i in range(n)]
    span_a = [None] * n; span_b = [None] * n
    for i in range(26, n):
        j = i - 26
        if ten[j] is not None and kij[j] is not None:
            span_a[i] = (ten[j] + kij[j]) / 2
        span_b[i] = sb[j]
    ema20, ema50, ema200 = _ema(c, 20), _ema(c, 50), _ema(c, 200)
    vavg = _sma(v, 20)
    return dict(o=o, h=h, l=l, c=c, v=v, rsi=rsi, macd=macd, sig=sig, hist=hist, pdi=pdi, mdi=mdi, adx=adx, ten=ten, kij=kij,
                sb=sb, span_a=span_a, span_b=span_b, ema20=ema20, ema50=ema50, ema200=ema200, vavg=vavg)


def _atr(I: dict, n: int = 14) -> list:
    h, l, c = I["h"], I["l"], I["c"]
    tr = [None] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    return _rma(tr, n)


def cloud_launch(I: dict, within: int = 3, weekly: bool = False, volume: bool = True, at: int | None = None) -> dict | None:
    """The 'cloud launch' setup: after a quiet base that sat on / inside the Ichimoku cloud, one wide-range bar on
    heavy volume closes above the cloud and above the whole base, and price is still above the cloud now.

    Must have (at the breakout bar, within the last `within` bars):
      - close above the cloud (and still above it on the latest bar)
      - a base: in the 20 bars before (12 on weekly), at least 3 closes in or just above the cloud (within 2%)
      - close above the highest high of that base
      - a thrust: the bar's gain is at least 1.5 x ATR(14), or its range at least 2 x ATR
      - volume at least 1.5 x the 20-bar average (skipped with volume=False: indices have no volume)
    Score (0-100) for quality: quiet before (low ADX, tight base, flat Kijun), Chikou in open space, cloud below
    bullish and rising, future cloud bullish, +DI jumping with ADX turning up, RSI / MACD confirming, big volume."""
    c, h, l, v = I["c"], I["h"], I["l"], I["v"]
    n = len(c) if at is None else at + 1  # at: evaluate as of an earlier bar (history check)
    L = 12 if weekly else 20
    atr = I.get("atr") or _atr(I)

    def top(i):
        a, b = I["span_a"][i], I["span_b"][i]
        return None if a is None or b is None else max(a, b)

    last = n - 1
    if top(last) is None or c[last] <= top(last):
        return None
    for b in range(last, max(L + 30, n - within) - 1, -1):
        t = top(b)
        if t is None or c[b] <= t or atr[b - 1] is None:
            continue
        base = range(b - L, b)
        near = sum(1 for i in base if top(i) is not None and c[i] <= top(i) * 1.02)
        if near < 3:
            continue
        base_hi = max(h[i] for i in base)
        if c[b] < base_hi:
            continue
        a = atr[b - 1]
        thrust = (c[b] - c[b - 1]) >= 1.5 * a or (h[b] - l[b]) >= 2 * a
        if not thrust or c[b] <= c[b - 1]:
            continue
        vavg = sum(v[b - 20:b]) / 20 if b >= 20 else 0
        vx = v[b] / vavg if vavg else 0
        if volume and vx < 1.5:
            continue
        # ---- quality score
        score, why = 0, []
        adx_b = I["adx"][b - 1]
        if adx_b is not None and adx_b <= 22:
            score += 15; why.append(f"quiet before (ADX {adx_b:.0f})")
        base_lo = min(l[i] for i in base)
        if base_lo and (base_hi / base_lo - 1) <= (0.25 if weekly else 0.15):
            score += 10; why.append(f"tight base ({(base_hi / base_lo - 1) * 100:.0f}%)")
        k = I["kij"]
        if None not in (k[b - 1], k[b - 6]) and abs(k[b - 1] - k[b - 6]) <= 0.005 * c[b]:
            score += 10; why.append("flat Kijun")
        lo_i, hi_i = max(0, b - 26 - 6), min(n, b - 26 + 7)
        if lo_i < hi_i and c[b] > max(h[lo_i:hi_i]):
            score += 15; why.append("Chikou in open space")
        sa, sb = I["span_a"][b], I["span_b"][b]
        if sa is not None and sb is not None and sa >= sb:
            score += 10; why.append("cloud below is bullish")
        if top(b - 10) is not None and t >= top(b - 10):
            score += 5; why.append("cloud rising")
        ten, kij, sbf = I["ten"][b], I["kij"][b], I["sb"][b]
        if None not in (ten, kij, sbf) and (ten + kij) / 2 >= sbf:
            score += 10; why.append("future cloud bullish")
        pdi, mdi, adx = I["pdi"], I["mdi"], I["adx"]
        if None not in (pdi[b], pdi[b - 3], mdi[b]) and pdi[b] > mdi[b] and pdi[b] - pdi[b - 3] >= 8:
            score += 10; why.append(f"+DI jumped to {pdi[b]:.0f}")
        if None not in (adx[b], adx[b - 1]) and adx[b] > adx[b - 1]:
            score += 5; why.append("ADX turning up")
        r = I["rsi"]
        if r[b] is not None and r[b] >= 65 and any(x is not None and x < 65 for x in r[max(0, b - 5):b]):
            score += 5; why.append(f"RSI broke out ({r[b]:.0f})")
        hs = I["hist"]
        if hist_surge(hs, b, 52 if weekly else 60):
            score += 10; why.append("MACD histogram surging")
        elif None not in (hs[b], hs[b - 1]) and hs[b] > 0 and hs[b] > hs[b - 1]:
            score += 5; why.append("MACD histogram rising")
        if volume:
            if vx >= 2.5:
                score += 5
            why.append(f"volume {vx:.1f}×")
        return {"bar": b, "ago": last - b, "score": min(100, score), "why": why,
                "gain": round((c[b] / c[b - 1] - 1) * 100, 1), "above_cloud": round((c[last] / top(last) - 1) * 100, 1)}
    return None


def cloud_retest(I: dict, within: int = 3, weekly: bool = False, at: int | None = None) -> dict | None:
    """The 'cloud retest': a second, lower-risk entry after a cloud breakout.

    Must have:
      - a close up through the cloud top 3-25 bars ago (2-12 on weekly), and no close below the cloud since
      - a real move after it: the high since the break at least ~2 ATR (and 4%) above the breakout close
      - within the last `within` bars, a dip back to support: low within 2% of the cloud top, or within 1% of the Kijun
      - now holding and turning up: close above the cloud and above the Kijun, a higher close than the bar before
        (or a green bar closing in its upper half), and not already 6%+ above the support it tested
    Score (0-100): Kijun flat / rising, cloud below bullish, future cloud bullish, volume dried up on the pullback,
    a shallow pullback (kept 40%+ of the move), volume back on the turn, RSI held 45+, MACD histogram turning up,
    Chikou above price. Comes with a plan: stop a little under the low of the dip, target 2R or the move's high."""
    c, h, l, o, v = I["c"], I["h"], I["l"], I["o"], I["v"]
    n = len(c) if at is None else at + 1  # at: evaluate as of an earlier bar (history check)
    last = n - 1
    atr = I.get("atr") or _atr(I)

    def top(i):
        a, b = I["span_a"][i], I["span_b"][i]
        return None if a is None or b is None else max(a, b)

    def bot(i):
        a, b = I["span_a"][i], I["span_b"][i]
        return None if a is None or b is None else min(a, b)

    kij = I["kij"]
    if n < 80 or top(last) is None or kij[last] is None or atr[last] is None:
        return None
    if c[last] <= top(last) or c[last] <= kij[last]:
        return None
    lo_b, hi_b = (2, 12) if weekly else (3, 25)
    b = next((i for i in range(last - lo_b, max(1, last - hi_b) - 1, -1)
              if top(i) and top(i - 1) and c[i] > top(i) and c[i - 1] <= top(i - 1)), None)
    if b is None:
        return None
    if any(bot(i) is not None and c[i] < bot(i) for i in range(b, last + 1)):
        return None
    peak_i = max(range(b, last + 1), key=lambda i: h[i])
    peak = h[peak_i]
    if peak - c[b] < max(2 * atr[b], 0.04 * c[b]) or peak_i >= last - 1:
        return None
    touch = None
    for i in range(last, max(peak_i, last - within + 1) - 1, -1):
        if top(i) and l[i] <= top(i) * 1.02:
            touch = (i, "cloud top", top(i))
            break
        if kij[i] and l[i] <= kij[i] * 1.01:
            touch = (i, "Kijun", kij[i])
            break
    if not touch:
        return None
    ti, where, level = touch
    turning = c[last] > c[last - 1] or (c[last] > o[last] and c[last] >= (h[last] + l[last]) / 2)
    if not turning or c[last] > level * 1.06:
        return None
    score, why = 0, [f"tested the {where} {last - ti} bar{'s' if last - ti != 1 else ''} ago" if last > ti else f"tested the {where} today"]
    if kij[last - 5] is not None and kij[last] >= kij[last - 5]:
        score += 15; why.append("Kijun flat / rising")
    sa, sb = I["span_a"][last], I["span_b"][last]
    if sa is not None and sb is not None and sa >= sb:
        score += 10; why.append("cloud below is bullish")
    ten, sbf = I["ten"][last], I["sb"][last]
    if None not in (ten, kij[last], sbf) and (ten + kij[last]) / 2 >= sbf:
        score += 10; why.append("future cloud bullish")
    leg = range(b, peak_i + 1)
    pull = range(peak_i + 1, last)
    if pull and sum(v[i] for i in pull) / len(pull) < 0.8 * sum(v[i] for i in leg) / len(leg):
        score += 15; why.append("volume dried up on the pullback")
    low = min(l[i] for i in range(peak_i, last + 1))
    if peak > c[b] and (peak - low) / (peak - c[b]) <= 0.6:
        score += 10; why.append("shallow pullback")
    if pull and v[last] > sum(v[i] for i in pull) / len(pull) * 1.2:
        score += 10; why.append("volume back on the turn")
    r = I["rsi"]
    if all(x is not None and x >= 45 for x in r[peak_i:last + 1]):
        score += 10; why.append("RSI held above 45")
    hs = I["hist"]
    if None not in (hs[last], hs[last - 1]) and hs[last] > hs[last - 1]:
        score += 10; why.append("MACD histogram turning up")
    if last >= 26 and c[last] > h[last - 26]:
        score += 10; why.append("Chikou above price")
    stop = round(min(low, level) - 0.25 * atr[last], 2)
    entry = c[last]
    risk = entry - stop
    if risk <= 0:
        return None
    target = round(max(peak, entry + 2 * risk), 2)
    return {"bar": ti, "ago": last - ti, "break_ago": last - b, "where": where, "score": min(100, score), "why": why,
            "peak": round(peak, 2), "plan": {"entry": round(entry, 2), "stop": stop, "target": target},
            "rr": round((target - entry) / risk, 1)}


def hist_surge(hs: list, i: int, look: int = 60) -> bool:
    """Strong MACD histogram at bar i: above zero, rising 3 bars in a row, the tallest bar of the last
    `look` bars, and at least 2x the average bar size (up or down) over that window."""
    if i < look or None in (hs[i], hs[i - 1], hs[i - 2], hs[i - 3]):
        return False
    if not (hs[i] > 0 and hs[i] > hs[i - 1] > hs[i - 2] > hs[i - 3]):
        return False
    win = [x for x in hs[i - look:i] if x is not None]
    if len(win) < look // 2:
        return False
    avg = sum(abs(x) for x in win) / len(win)
    return hs[i] >= max(win) and avg > 0 and hs[i] >= 2 * avg


def flow_hits(m: dict | None) -> set:
    """Smart-money rules from a stock's flow metrics (see flow.py); empty when there's no data for it."""
    if not m:
        return set()
    h = set()
    if m["score"] >= 65:
        h.add("flow_acc")
    if m["score"] >= 75:
        h.add("flow_strong")
    if m["score"] <= 35:
        h.add("flow_dist")
    if (m.get("dq_x") or 0) >= 2 and (m.get("chg") or 0) > 0:
        h.add("flow_deliv")
    if m.get("build") in ("long build-up", "short covering"):
        h.add("flow_long")
    return h


def evaluate(rows: list, within: int = 3, weekly: bool = False) -> dict | None:
    """All rules for one stock. within = how many recent bars a 'crossed' event may be in."""
    n = len(rows)
    if n < 60:
        return None
    I = indicators(rows)
    c, h = I["c"], I["h"]
    last = n - 1
    rng = range(max(1, n - within), n)

    def crossed(a, b, i):  # a crossed above b at bar i
        return None not in (a[i], b[i], a[i - 1], b[i - 1]) and a[i] > b[i] and a[i - 1] <= b[i - 1]

    def top(i):
        return None if I["span_a"][i] is None or I["span_b"][i] is None else max(I["span_a"][i], I["span_b"][i])

    def bot(i):
        return None if I["span_a"][i] is None or I["span_b"][i] is None else min(I["span_a"][i], I["span_b"][i])

    zero = [0.0] * n
    fifty = [50.0] * n
    hits = set()
    t = top(last)
    if t is not None and c[last] > t:
        hits.add("ichi_above")
    if any(top(i) is not None and top(i - 1) is not None and c[i] > top(i) and c[i - 1] <= top(i - 1) for i in rng):
        hits.add("ichi_break")
    if any(bot(i) is not None and bot(i - 1) is not None and c[i] < bot(i) and c[i - 1] >= bot(i - 1) for i in rng):
        hits.add("ichi_breakdown")
    if any(crossed(I["ten"], I["kij"], i) for i in rng):
        hits.add("ichi_tk")
    if last >= 26 and c[last] > c[last - 26]:
        hits.add("ichi_chikou")
    if None not in (I["ten"][last], I["kij"][last], I["sb"][last]) and (I["ten"][last] + I["kij"][last]) / 2 > I["sb"][last]:
        hits.add("ichi_future")
    if any(crossed(I["pdi"], I["mdi"], i) for i in rng):
        hits.add("dmi_cross")
    if any(crossed(I["mdi"], I["pdi"], i) for i in rng):
        hits.add("dmi_cross_dn")
    if None not in (I["pdi"][last], I["mdi"][last], I["adx"][last], I["adx"][last - 3]) and I["pdi"][last] > I["mdi"][last] and I["adx"][last] > 20 and I["adx"][last] > I["adx"][last - 3]:
        hits.add("dmi_trend")
    if any(crossed(I["rsi"], fifty, i) for i in rng):
        hits.add("rsi_50")
    r = I["rsi"][last]
    if r is not None and r >= 60:
        hits.add("rsi_strong")
    if r is not None and r <= 30:
        hits.add("rsi_os")
    if any(crossed(I["macd"], I["sig"], i) for i in rng):
        hits.add("macd_cross")
    if any(crossed(I["sig"], I["macd"], i) for i in rng):
        hits.add("macd_cross_dn")
    if any(crossed(I["macd"], zero, i) for i in rng):
        hits.add("macd_zero")
    hs = I["hist"]
    if None not in (hs[last], hs[last - 1], hs[last - 2]) and hs[last] > hs[last - 1] > hs[last - 2]:
        hits.add("macd_hist_up")
    if any(hist_surge(hs, i, 52 if weekly else 60) for i in rng):
        hits.add("macd_hist_surge")
    if any(bot(i) is not None and bot(i - 1) is not None and c[i] > bot(i) and c[i - 1] <= bot(i - 1) for i in rng) and bot(last) is not None and c[last] > bot(last):
        hits.add("ichi_attack")
    look = min(n, 250)
    hi = max(h[n - look:]); prev_hi = max(h[n - look: last]) if look > 1 else hi
    if c[last] >= hi * 0.97:
        hits.add("hi52")
    if h[last] >= prev_hi and h[last] > 0 and last > 0 and h[last] > prev_hi * 0.9999:
        hits.add("hi52_break")
    e20, e50, e200 = I["ema20"][last], I["ema50"][last], I["ema200"][last]
    if None not in (e20, e50, e200) and c[last] > e20 > e50 > e200:
        hits.add("ema_stack")
    if any(crossed(c, I["ema20"], i) for i in rng):
        hits.add("ema20_reclaim")
    va = I["vavg"][last - 1] if last >= 1 else None
    if va and I["v"][last] >= 2 * va:
        hits.add("vol_surge")
    launch = cloud_launch(I, within, weekly)
    if launch:
        hits.add("cloud_launch")
    if t is not None and c[last] > t and any(top(i) is not None and I["l"][i] <= top(i) * 1.03 for i in rng):
        hits.add("ichi_near")
    retest = cloud_retest(I, within, weekly)
    if retest:
        hits.add("cloud_retest")
    hits |= structure_hits(I, within, weekly)
    span = 26 if weekly else 125
    vp = volume_profile(h[-span:], I["l"][-span:], I["v"][-span:])
    if vp and vp["poc"] <= c[last] <= vp["poc"] * 1.03:
        hits.add("vp_support")
    cloud = "above" if t is not None and c[last] > t else ("below" if bot(last) is not None and c[last] < bot(last) else "inside")
    prev = c[last - 1] if last else c[last]
    return {
        "hits": sorted(hits), "close": c[last], "chp": round((c[last] - prev) / prev * 100, 2) if prev else 0,
        "rsi": round(r, 1) if r is not None else None, "adx": round(I["adx"][last], 1) if I["adx"][last] is not None else None,
        "pdi": round(I["pdi"][last], 1) if I["pdi"][last] is not None else None, "mdi": round(I["mdi"][last], 1) if I["mdi"][last] is not None else None,
        "cloud": cloud, "from_hi": round((c[last] / hi - 1) * 100, 1) if hi else None,
        "vol_x": round(I["v"][last] / va, 1) if va else None, "bars": n,
        "launch": launch, "retest": retest, "poc": round(vp["poc"], 2) if vp else None,
    }


# ------------------------------------------------------------------ top picks: one score per side, with a trade plan
PICK_MODES = {
    # hold ~1 month: weight the trend, relative strength and smart money; stop 1-3 ATR away
    "swing": {"risk": (1.0, 3.0), "fallback": 2.0, "trigger": 5, "rs": 1.0, "oi": 0},
    # hold 2-3 days (F&O): weight a fresh trigger and the F&O open-interest build-up; stop 0.8-1.5 ATR away
    "fno": {"risk": (0.8, 1.5), "fallback": 1.2, "trigger": 12, "rs": 0.6, "oi": 8},
}
LONG_TRIGGERS = {"ichi_break", "ms_bos", "macd_cross", "cloud_launch", "macd_hist_surge", "hi52_break", "ema20_reclaim", "dmi_cross"}
SHORT_TRIGGERS = {"ichi_breakdown", "macd_cross_dn", "dmi_cross_dn", "ms_choch_dn"}


def regime(rows: list) -> dict:
    """The market's own trend (run on Nifty 50): above / below its cloud and its swing structure."""
    if not rows or len(rows) < 80:
        return {"trend": "unknown", "text": "Market trend unknown"}
    I = indicators(rows)
    last = len(rows) - 1
    a, b = I["span_a"][last], I["span_b"][last]
    c = I["c"][last]
    st = structure(I["h"], I["l"], I["c"], 5)["trend"]
    above = a is not None and b is not None and c > max(a, b)
    below = a is not None and b is not None and c < min(a, b)
    if above and st == "up":
        return {"trend": "up", "text": "Nifty 50 is above its cloud with higher highs and lows: a market for longs"}
    if below and st == "down":
        return {"trend": "down", "text": "Nifty 50 is below its cloud with lower highs and lows: favour shorts, keep longs small"}
    return {"trend": "mixed", "text": "Nifty 50 is mixed (inside its cloud or its structure disagrees): be choosy, take only the top scores"}


def trade_pick(rows: list, ev: dict, rs: dict | None, flow: dict | None, mode: str = "swing", market: str = "unknown") -> dict | None:
    """Score a stock 0-100 for a long and for a short using the setup you trade (Ichimoku + structure + relative
    strength + momentum + smart money + where the stop can go), and work out an entry, stop and 2R target per side."""
    P = PICK_MODES.get(mode, PICK_MODES["swing"])
    n = len(rows)
    if n < 80:
        return None
    I = indicators(rows)
    last = n - 1
    c, h, l = I["c"], I["h"], I["l"]
    atr = _atr(I)[last]
    if not atr:
        return None
    hits = set(ev.get("hits") or [])
    rs = rs or {}
    a, b = I["span_a"][last], I["span_b"][last]
    top = max(a, b) if a is not None and b is not None else None
    bot = min(a, b) if a is not None and b is not None else None
    kij, ten = I["kij"][last], I["ten"][last]
    st = structure(h, l, c, 5)
    L, S, wl, ws = 0.0, 0.0, [], []

    def lg(p, why):
        nonlocal L
        L += p
        if why:
            wl.append((p, why))

    def sh(p, why):
        nonlocal S
        S += p
        if why:
            ws.append((p, why))

    # trend: Ichimoku (25)
    if top is not None and c[last] > top:
        lg(10, "above the cloud")
    elif bot is not None and c[last] < bot:
        sh(10, "below the cloud")
    if "ichi_future" in hits:
        lg(5, "")
    else:
        sh(5, "")
    if ten is not None and kij is not None:
        if ten > kij:
            lg(5, "Tenkan above Kijun")
        else:
            sh(5, "Tenkan below Kijun")
    if last >= 26:
        if c[last] > c[last - 26]:
            lg(5, "")
        else:
            sh(5, "")
    e50, e200 = I["ema50"][last], I["ema200"][last]
    if e50 is not None and e200 is not None:
        if e50 > e200 and c[last] > e200:
            lg(5, "long-term uptrend (EMA 50 > 200)")
        elif e50 < e200 and c[last] < e200:
            sh(5, "long-term downtrend (EMA 50 < 200)")
    # structure (15)
    if st["trend"] == "up":
        lg(10, "higher highs & higher lows")
    elif st["trend"] == "down":
        sh(10, "lower highs & lower lows")
    ev_last = st["events"][-1] if st["events"] else None
    if ev_last and ev_last[0] >= last - 10:
        if ev_last[2] == "up":
            lg(5, f"{'ChoCH' if ev_last[1] == 'CHOCH' else 'BOS'} ↑ {last - ev_last[0]} bars ago")
        else:
            sh(5, f"{'ChoCH' if ev_last[1] == 'CHOCH' else 'BOS'} ↓ {last - ev_last[0]} bars ago")
    # relative strength (25, less for F&O)
    k = P["rs"]
    bv, sv, lv, state = rs.get("rs_brd"), rs.get("rs_sec"), rs.get("rs_long"), rs.get("rs_state") or ""
    if bv is not None:
        if bv > 0:
            lg(8 * k, f"beating {rs.get('rs_brd_of') or 'the market'} ({bv:+.1f}%)")
        elif bv < 0:
            sh(8 * k, f"trailing {rs.get('rs_brd_of') or 'the market'} ({bv:+.1f}%)")
        if sv is not None:
            if sv > 0:
                lg(7 * k, f"beating {rs.get('rs_sec_of') or 'its sector'} ({sv:+.1f}%)")
            elif sv < 0:
                sh(7 * k, f"trailing {rs.get('rs_sec_of') or 'its sector'} ({sv:+.1f}%)")
        elif bv > 0:
            lg(4 * k, "")
        if lv is not None:
            if lv > 0:
                lg(5 * k, "leader over ~6 months")
            elif lv < 0:
                sh(5 * k, "laggard over ~6 months")
        if "pulling ahead" in state:
            lg(5 * k, "RS still rising")
        elif state == "Laggard":
            sh(5 * k, "RS still falling")
    # momentum (10)
    m, sg, hs = I["macd"][last], I["sig"][last], I["hist"]
    if m is not None and sg is not None:
        if m > sg:
            lg(4, "")
        else:
            sh(4, "")
    if None not in (hs[last], hs[last - 1]):
        if hs[last] > hs[last - 1]:
            lg(3, "")
        else:
            sh(3, "")
    r = I["rsi"][last]
    if r is not None:
        if 55 <= r <= 72:
            lg(3, "")
        elif 28 <= r <= 45:
            sh(3, "")
        if r > 78:
            lg(-6, f"overbought (RSI {r:.0f})")
        if r < 22:
            sh(-6, f"oversold (RSI {r:.0f})")
    # smart money (10) and F&O open interest
    if flow:
        fs = flow.get("score")
        if fs is not None:
            if fs >= 65:
                lg(10, f"smart-money accumulation ({fs})")
            elif fs >= 55:
                lg(5, "")
            elif fs <= 35:
                sh(10, f"smart-money distribution ({fs})")
            elif fs <= 45:
                sh(5, "")
        bld = flow.get("build")
        if P["oi"] and bld:
            if bld == "long build-up":
                lg(P["oi"], "F&O long build-up")
            elif bld == "short build-up":
                sh(P["oi"], "F&O short build-up")
            elif bld == "short covering":
                lg(P["oi"] / 3, "short covering")
            elif bld == "long unwinding":
                sh(P["oi"] / 3, "long unwinding")
    # a fresh trigger (the entry happens now, not 3 weeks ago)
    tl, ts = sorted(hits & LONG_TRIGGERS), sorted(hits & SHORT_TRIGGERS)
    if tl:
        lg(P["trigger"], "fresh trigger: " + ", ".join(TAGS.get(x, x) for x in tl[:2]))
    if ts:
        sh(P["trigger"], "fresh trigger: " + ", ".join(TAGS.get(x, x) for x in ts[:2]))
    va = I["vavg"][last - 1] if last else None
    if va and I["v"][last] >= 1.3 * va:
        if c[last] >= c[last - 1]:
            lg(5, f"up on {I['v'][last] / va:.1f}× volume")
        else:
            sh(5, f"down on {I['v'][last] / va:.1f}× volume")

    # where the stop goes, and is there room for 2R?
    piv_l = [p[2] for p in st["pivots"] if p[1] == "L" and p[2] < c[last]]
    piv_h = [p[2] for p in st["pivots"] if p[1] == "H" and p[2] > c[last]]
    lo, hi = P["risk"]

    def plan(side):
        if side == "long":
            sup = [x for x in (kij, top, piv_l[-1] if piv_l else None) if x is not None and x < c[last]]
            lvl = max(sup) if sup else None
            stop = (lvl - 0.3 * atr) if lvl is not None else c[last] - P["fallback"] * atr
            risk = min(max(c[last] - stop, lo * atr), hi * atr)
            stop = c[last] - risk
            target = c[last] + 2 * risk
            cands = piv_h + ([max(h[-250:])] if max(h[-250:]) > c[last] else [])
            res = min(cands) if cands else None
            dist = (c[last] - lvl) / atr if lvl is not None else None
        else:
            sup = [x for x in (kij, bot, piv_h[-1] if piv_h else None) if x is not None and x > c[last]]
            lvl = min(sup) if sup else None
            stop = (lvl + 0.3 * atr) if lvl is not None else c[last] + P["fallback"] * atr
            risk = min(max(stop - c[last], lo * atr), hi * atr)
            stop = c[last] + risk
            target = c[last] - 2 * risk
            res = max(piv_l) if piv_l else None
            dist = (lvl - c[last]) / atr if lvl is not None else None
        return {"entry": round(c[last], 2), "stop": round(stop, 2), "target": round(target, 2),
                "risk_pct": round(risk / c[last] * 100, 1), "level": round(lvl, 2) if lvl is not None else None,
                "dist_atr": round(dist, 1) if dist is not None else None, "block": round(res, 2) if res is not None else None}

    pl, ps = plan("long"), plan("short")
    for side, p in (("long", pl), ("short", ps)):
        add = lg if side == "long" else sh
        d = p["dist_atr"]
        if d is not None:
            if d <= 1.5:
                add(10, "close to support – tight stop" if side == "long" else "close to resistance – tight stop")
            elif d <= 3:
                add(4, "")
            elif d > 4:
                add(-10, f"stretched {d:.0f} ATR from {'support' if side == 'long' else 'resistance'}")
        blk, risk = p["block"], abs(p["entry"] - p["stop"])
        if blk is not None and risk and abs(blk - p["entry"]) < 1.5 * risk:
            add(-8 if abs(blk - p["entry"]) >= 0.75 * risk else -14, f"{'resistance' if side == 'long' else 'support'} at {blk:g} before the 2R target")
        p["rr_room"] = round(abs(blk - p["entry"]) / risk, 1) if blk is not None and risk else None
    # the market's own trend
    if market == "up":
        lg(5, ""); sh(-5, "market in an uptrend")
    elif market == "down":
        sh(5, ""); lg(-10, "market in a downtrend")

    MAX = 95 + 25 * k + P["oi"] + P["trigger"]  # a near-perfect setup lands around 85-95

    def pack(score, why, p):
        why = [w for w in sorted(why, key=lambda x: -abs(x[0])) if w[1]]
        p.update(score=max(0, min(100, round(100 * score / MAX))), why=[w for _, w in why[:6]])
        return p
    return {"long": pack(L, wl, pl), "short": pack(S, ws, ps)}
