#!/usr/bin/env python3
"""
Industry level under each sector, so tone, overviews and peer comparisons compare like with like
(a gold-loan NBFC with gold-loan NBFCs, not with an AMC or a broker).

lib["industries"][code] = industry; the company's sector follows from the industry (that is also how misplaced
companies get corrected, e.g. paint makers out of Chemicals). Each company is classified once (AI, ~40 per
request, using its name + the first line of its latest concall summary), and again only if its sector is unknown.
"""
import re
import time

import concalls as C

say = C.say

TAXONOMY = {
    "Banks": ["Private banks", "PSU banks", "Small finance banks"],
    "NBFC & Financial Services": ["Housing finance", "Vehicle & equipment finance", "Microfinance", "Gold loans",
                                  "MSME & business lending", "Consumer & diversified NBFCs", "Infra & PSU finance",
                                  "Fintech & payments", "Holding & investment companies"],
    "Capital Markets & Wealth": ["Asset management (AMCs)", "Stockbroking & distribution", "Wealth management",
                                 "Exchanges & depositories", "Registrars & rating agencies"],
    "Insurance": ["Life insurance", "General & health insurance", "Insurance broking"],
    "IT & Software": ["IT services", "Engineering R&D services", "Software products & SaaS", "Digital & internet platforms"],
    "Telecom": ["Telecom services", "Telecom equipment & towers"],
    "Pharma & Healthcare Products": ["Domestic formulations", "Export generics", "API & CDMO", "Biologics & vaccines",
                                     "Medical devices & consumables", "Animal health & nutraceuticals"],
    "Hospitals & Diagnostics": ["Hospitals", "Diagnostics", "Pharmacy & health-tech"],
    "Automobiles": ["Passenger vehicles", "Two & three wheelers", "Commercial vehicles", "Tractors & farm equipment", "EV makers"],
    "Auto Components": ["Engine & drivetrain parts", "Auto electricals & electronics", "Tyres & rubber", "Batteries",
                        "Castings & forgings", "Bearings & precision parts", "Seating, lighting & interiors"],
    "Chemicals": ["Specialty chemicals", "Fluorochemicals", "Commodity & bulk chemicals", "Dyes & pigments",
                  "Petrochemicals & polymers", "Industrial gases & explosives", "Adhesives & sealants"],
    "Paints & Coatings": ["Decorative paints", "Industrial & auto coatings"],
    "Fertilisers & Agrochemicals": ["Fertilisers", "Agrochemicals & crop protection"],
    "Metals & Mining": ["Steel", "Aluminium", "Copper, zinc & other non-ferrous", "Mining (coal, iron ore)",
                        "Ferro alloys & graphite", "Steel pipes & tubes"],
    "Oil & Gas": ["Refining & marketing", "Upstream oil & gas", "City gas distribution", "Gas transmission & LNG", "Lubricants"],
    "Power & Utilities": ["Thermal & hydro generation", "Renewable power producers", "Power transmission & distribution",
                          "Power trading & exchanges", "Water & waste management"],
    "Capital Goods & Engineering": ["Heavy electrical equipment", "Industrial machinery", "Pumps, valves & compressors",
                                    "Railway equipment & wagons", "Process & engineering equipment"],
    "Defence & Aerospace": ["Defence platforms & shipyards", "Defence electronics", "Aerospace components", "Drones & anti-drone"],
    "Electrical & Electronics": ["Cables & wires", "Transformers & switchgear", "Electronics manufacturing (EMS)",
                                 "Consumer electricals", "Solar modules & cells", "Power electronics & meters"],
    "Construction & Infrastructure": ["Roads & highways EPC", "Water & irrigation EPC", "Railway & metro EPC",
                                      "Building & industrial construction", "Ports & airports operators"],
    "Cement & Building Materials": ["Cement", "Tiles & sanitaryware", "Wood panels & laminates", "Glass & building products"],
    "Real Estate": ["Residential developers", "Commercial & office", "Real estate services"],
    "FMCG & Food": ["Personal & home care", "Packaged foods", "Beverages (non-alcoholic)", "Alcoholic beverages",
                    "Dairy", "Tobacco", "Edible oils & staples"],
    "Consumer Durables": ["Home appliances", "Jewellery", "Footwear", "Furniture & furnishings", "Watches, eyewear & luggage"],
    "Retail & E-commerce": ["Apparel & lifestyle retail", "Grocery & value retail", "E-commerce & quick commerce",
                            "Specialty retail", "Restaurants & QSR"],
    "Media & Entertainment": ["Broadcasting", "Films & content production", "Digital media & gaming", "Print media"],
    "Hotels & Travel": ["Hotels", "Airlines", "Travel services & online travel"],
    "Logistics & Shipping": ["Ports", "Shipping", "Logistics & 3PL", "Express & courier", "Container rail & warehousing"],
    "Textiles & Apparel": ["Spinning & yarn", "Home textiles", "Garment exports", "Technical textiles", "Synthetic fibres"],
    "Paper & Packaging": ["Paper", "Packaging"],
    "Plastics & Pipes": ["Plastic pipes", "Plastic products & packaging"],
    "Agri & Sugar": ["Sugar & ethanol", "Seeds & agri inputs", "Agri processing (rice, tea, spices)", "Animal feed & aquaculture"],
    "Services & Others": ["Staffing & facility services", "Education", "Diversified conglomerates", "Other services"],
}
PARENT = {ind: sec for sec, inds in TAXONOMY.items() for ind in inds}

PROMPT = """Classify each Indian listed company into exactly ONE industry from this list (copy the name exactly).
Use the hint (its latest earnings-call summary line) to decide what it mainly does.

INDUSTRIES:
{inds}

Answer one line per company, exactly: <code> | <industry>

COMPANIES:
"""


def _hint(lib, code):
    calls = sorted([c for c in lib["calls"].values() if c["code"] == code and c.get("summary")], key=lambda c: c["date"])
    if not calls:
        return ""
    try:
        t = C.here(calls[-1]["summary"]).read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"(?im)^\**tone:?\**.*$", t)
    keys = re.findall(r"(?m)^- (.{20,160})$", t)[:2]
    return re.sub(r"\*\*", "", ((m.group(0) if m else "") + " " + " ".join(keys)))[:300]


def classify(lib, pool, limit=400, minutes=8):
    inds = lib.setdefault("industries", {})
    names = {}
    for c in lib["calls"].values():
        names.setdefault(c["code"], c["company"])
    todo = [code for code in names if code not in inds][:limit]
    if not todo:
        return 0
    say(f"\nSorting {len(todo)} companies into industries ...")
    listing = "\n".join(f"{sec}: " + "; ".join(v) for sec, v in TAXONOMY.items())
    deadline = time.time() + minutes * 60
    done = 0
    for i in range(0, len(todo), 40):
        if time.time() > deadline:
            break
        part = todo[i:i + 40]
        body = "\n".join(f"{code} | {names[code]} | hint: {_hint(lib, code)}" for code in part)
        try:
            text, _ = pool.ask(PROMPT.format(inds=listing) + body, label=f"industries {i + 1}-{i + len(part)} of {len(todo)}")
        except C.QuotaOver as e:
            say(f"  {e}")
            break
        except C.AIError as e:
            say(f"  industry sorting skipped: {str(e)[:100]}")
            continue
        for line in text.splitlines():
            if "|" not in line:
                continue
            code, _, ind = line.partition("|")
            code, ind = re.sub(r"\D", "", code), ind.strip(" *-")
            ind = next((k for k in PARENT if k.lower() == ind.lower()), None) or \
                next((k for k in PARENT if ind.lower().startswith(k.lower()[:12])), None)
            if code in names and ind:
                inds[code] = ind
                lib["sectors"][code] = PARENT[ind]  # sector follows the industry
                done += 1
        C.save_lib(lib)
        time.sleep(pool.pause)
    say(f"  industries: {done} companies sorted, {len([c for c in names if c not in inds])} to go")
    return done


def industry_of(lib, call):
    return (lib.get("industries") or {}).get(call["code"], "")


def overviews(lib, pool, touched=None, limit=8):
    """Industry overviews for the latest quarter (3+ companies). `touched` = industries with a new summary."""
    from collections import defaultdict
    by = defaultdict(list)
    for c in lib["calls"].values():
        ind = industry_of(lib, c)
        if ind and c.get("summary"):
            by[ind].append(c)
    order = sorted(by, key=lambda k: (k not in (touched or set()), -len(by[k])))
    made = 0
    for ind in order:
        if made >= limit:
            break
        if C.overview(PARENT[ind], lib, pool, industry=ind):
            made += 1
            time.sleep(pool.pause)
    return made
