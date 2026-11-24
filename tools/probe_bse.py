"""One-off: look inside BSE's results endpoints (as text)."""
import json, re, sys
sys.path.insert(0, ".")
import concalls as C
API = "https://api.bseindia.com/BseIndiaAPI/api"
def text(h):
    h = re.sub(r"</t[dh]>", " | ", h); h = re.sub(r"</tr>", "\n", h); h = re.sub(r"<[^>]+>", "", h)
    return re.sub(r"[ \t]+", " ", h)
for code in ("500325", "522074"):
    for ep in ("FinancialResult/w", "GetReportNewFor_Result/w"):
        r = C.bse().get(f"{API}/{ep}", params={"scripcode": code}, timeout=25)
        try:
            j = r.json()
        except Exception:
            print(ep, "not json"); continue
        for k, v in (j.items() if isinstance(j, dict) else []):
            print(f"=== {code} {ep} [{k}]\n{text(str(v))[:2500]}\n")
    r = C.bse().get(f"{API}/TabResults/w", params={"scripcode": code, "tabtype": "RESULTS"}, timeout=25)
    print("=== TabResults", code, r.text[:2000])
