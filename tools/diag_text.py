"""Check transcript reading on calls that were skipped as 'scanned' (by hand: .github/workflows/diag.yml)."""
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import concalls as C  # noqa: E402

lib = C.load_lib()
if sys.argv[1:] and sys.argv[1].startswith("story:"):  # check the open-source research for 'story so far'
    import backstory as B
    for n in [sys.argv[1][6:]] + sys.argv[2:]:
        f, src = B.open_research(n, "", "", "2021")
        print(f"== {n}: {len(f):,} characters from {src}\n{f[:1200]}\n...\n{f[-800:]}\n", flush=True)
    sys.exit(0)
names = sys.argv[1:] or ["AXIS Bank", "Larsen & Toubro", "Maruti Suzuki", "JSW Steel", "NLC India", "Kotak Mahindra", "Indian Oil", "Coforge"]
for n in names:
    cs = [c for c in lib["calls"].values() if c["company"].lower().startswith(n.lower()) and str(c.get("skip", "")).startswith("PDF is a scanned")]
    for c in cs[-1:]:
        t, prob = C.get_text(c)
        if not t:
            o = C.ocr_text(C.PDF_DIR / f"{c['id']}.pdf")
            print("   URLs seen:", re.findall(r"(?:https?://|www\\.)\\S+", o))
        print(f"{c['company']} {c['date']}: {'OK ' + str(len(t)) + ' chars - ' + t[:160].replace(chr(10), ' ') if t else prob}", flush=True)
