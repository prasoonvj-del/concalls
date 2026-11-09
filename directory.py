#!/usr/bin/env python3
"""
Every company listed on BSE -> data/directory.json, refreshed weekly (no AI).
{code: {"n": name, "id": BSE symbol, "ind": BSE industry, "s": our sector}}

Used for: the Companies list (every listed company appears, even before we have anything on it), matching news
names to the right company, and sectors for companies without a concall yet.
"""
import datetime as dt
import json
import re

import concalls as C

say = C.say
FILE = C.DATA / "directory.json"
URL = "https://api.bseindia.com/BseIndiaAPI/api/ListofScripData/w"

# BSE industry words -> our sectors (first match wins; the concall classification always takes precedence)
IND_MAP = [
    (r"bank", "Banks"), (r"insurance", "Insurance"),
    (r"nbfc|finance|financial|broking|asset management|capital market|housing finance|holding compan", "NBFC & Financial Services"),
    (r"software|it enabled|computers|it services|internet", "IT & Software"),
    (r"pharma|drug|biotech", "Pharma & Healthcare Products"), (r"hospital|healthcare service|diagnostic", "Hospitals & Diagnostics"),
    (r"passenger car|two wheeler|commercial vehicle|tractor|automobile", "Automobiles"), (r"auto comp|auto part|tyre|tire", "Auto Components"),
    (r"defen[cs]e|aerospace", "Defence & Aerospace"), (r"cement", "Cement & Building Materials"),
    (r"steel|iron|metal|mining|alumin|copper|zinc", "Metals & Mining"),
    (r"refiner|oil|gas|petroleum|lpg", "Oil & Gas"), (r"power|electric util|renewable", "Power & Utilities"),
    (r"fertili[sz]er|pesticide|agro ?chem", "Fertilisers & Agrochemicals"),
    (r"chemical|dyes|pigment|paint", "Chemicals"), (r"textile|apparel|garment|cotton|yarn", "Textiles & Apparel"),
    (r"food|beverage|fmcg|personal care|tobacco|packaged|dairy|tea|coffee", "FMCG & Food"),
    (r"sugar|agri|edible oil|seeds", "Agri & Sugar"), (r"realty|real estate|residential|commercial project", "Real Estate"),
    (r"construction|infrastructure|engineering - construction|road", "Construction & Infrastructure"),
    (r"electrical|electronic|cable|wire|transformer", "Electrical & Electronics"),
    (r"capital goods|industrial machinery|heavy engineering|compressor|pump|bearing", "Capital Goods & Engineering"),
    (r"consumer durable|household appliance|furniture|jewel", "Consumer Durables"),
    (r"retail|e-?commerce", "Retail & E-commerce"), (r"hotel|resort|travel|tourism|airline|aviation", "Hotels & Travel"),
    (r"logistic|shipping|port|courier|transport", "Logistics & Shipping"), (r"telecom", "Telecom"),
    (r"media|entertainment|film|broadcast|publishing", "Media & Entertainment"),
    (r"plastic|pipe", "Plastics & Pipes"), (r"paper|packaging", "Paper & Packaging"),
]


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    except ValueError:
        return {}


def sector_from_industry(ind):
    for pat, sec in IND_MAP:
        if re.search(pat, ind or "", re.I):
            return sec
    return ""


def _pick(row, *keys):
    low = {k.lower(): v for k, v in row.items()}
    for k in keys:
        v = low.get(k.lower())
        if v not in (None, ""):
            return str(v).strip()
    return ""


def update(force=False):
    d = load()
    meta = d.get("_meta", {})
    if not force and meta.get("at") and (dt.date.today() - dt.date.fromisoformat(meta["at"])).days < 7:
        return d
    try:
        r = C.bse().get(URL, params={"Group": "", "Scripcode": "", "industry": "", "segment": "Equity", "status": "Active"},
                        timeout=90)
        rows = r.json() if r.status_code == 200 else []
        if isinstance(rows, dict):
            rows = rows.get("Table") or rows.get("data") or []
    except Exception as e:
        say(f"  company directory: BSE list not available ({str(e)[:80]}) - keeping the last one")
        return d
    if len(rows) < 1000:
        say(f"  company directory: BSE returned only {len(rows)} companies - keeping the last one")
        return d
    lib = C.load_lib()
    out = {"_meta": {"at": dt.date.today().isoformat(), "n": 0}}
    for row in rows:
        code = _pick(row, "SCRIP_CD", "scripcode", "Scrip_Code")
        name = _pick(row, "Issuer_Name", "Scrip_Name", "SCRIP_NAME", "LONG_NAME")
        if not code or not name or not code.isdigit():
            continue
        ind = _pick(row, "INDUSTRY", "Industry", "Sector", "SECTOR")
        out[code] = {"n": re.sub(r"\s+-\$$", "", name), "id": _pick(row, "scrip_id", "Scrip_Id", "SCRIP_ID"), "ind": ind,
                     "s": lib["sectors"].get(code) or sector_from_industry(ind)}
    out["_meta"]["n"] = len(out) - 1
    FILE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    say(f"  company directory: {out['_meta']['n']} listed companies")
    return out


def refresh_sectors():
    """Concall classification wins whenever we have it."""
    d = load()
    if not d:
        return
    lib = C.load_lib()
    filled = 0
    for code, v in d.items():
        if code == "_meta":
            continue
        if lib["sectors"].get(code):
            v["s"] = lib["sectors"][code]
        elif v.get("s") and any(c["code"] == code for c in lib["calls"].values()):
            lib["sectors"][code] = v["s"]  # e.g. a concall summarised on request before the AI sorted it
            filled += 1
    FILE.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    if filled:
        C.save_lib(lib)
