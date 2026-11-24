"""One-off: which BSE JSON endpoints give annual results (revenue, profit, EPS by year)? Prints status + a sample."""
import json, sys
sys.path.insert(0, ".")
import concalls as C
API = "https://api.bseindia.com/BseIndiaAPI/api"
code = "500325"
tries = [
    ("TabResults_PAR/w", {"scripcode": code, "tabtype": "RESULTS"}),
    ("TabResults/w", {"scripcode": code, "tabtype": "RESULTS"}),
    ("TabResults_PAR/w", {"scripcode": code, "tabtype": "ANNUAL"}),
    ("GetReportNewFor_Result/w", {"scripcode": code}),
    ("Corpforthresults/w", {"scripcode": code}),
    ("ResultsTrend/w", {"scripcode": code}),
    ("FinancialResult/w", {"scripcode": code}),
    ("StockReachGraph/w", {"scripcode": code, "flag": "1Y", "fromdate": "", "todate": "", "seriesid": ""}),
    ("PeerSmartSearch/w", {"scripcode": code, "scripcomare": ""}),
    ("EQPeerGp/w", {"scripcode": code, "scripcomare": ""}),
]
for ep, p in tries:
    try:
        r = C.bse().get(f"{API}/{ep}", params=p, timeout=25)
        print(f"=== {ep} {p} -> {r.status_code} {len(r.text)}\n{r.text[:1500]}\n")
    except Exception as e:
        print(f"=== {ep} -> {e}")
