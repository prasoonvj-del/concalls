"""Check transcript reading on calls that were skipped as 'scanned' (by hand: .github/workflows/diag.yml)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import concalls as C  # noqa: E402

lib = C.load_lib()
names = sys.argv[1:] or ["AXIS Bank", "Larsen & Toubro", "Maruti Suzuki", "JSW Steel", "NLC India", "Kotak Mahindra", "Indian Oil", "Coforge"]
for n in names:
    cs = [c for c in lib["calls"].values() if c["company"].lower().startswith(n.lower()) and str(c.get("skip", "")).startswith("PDF is a scanned")]
    for c in cs[-1:]:
        t, prob = C.get_text(c)
        if not t:
            o = C.ocr_text(C.PDF_DIR / f"{c['id']}.pdf")
            print("   OCR text:", o[:600].replace(chr(10), " | "))
        print(f"{c['company']} {c['date']}: {'OK ' + str(len(t)) + ' chars - ' + t[:160].replace(chr(10), ' ') if t else prob}", flush=True)
