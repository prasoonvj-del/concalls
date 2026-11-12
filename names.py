#!/usr/bin/env python3
"""
One place that decides "are these the same company?" and "which sector is it in?".

Rules (also mirrored in web/app.js sameCo):
  * exact match after normalising (Ltd / Limited / punctuation removed)
  * one name may extend the other only by a generic tail - "Prestige Estates" = "Prestige Estates Projects",
    "Adani Ports" = "Adani Ports and Special Economic Zone" - never by a business word:
    "Mahindra & Mahindra" is NOT "Mahindra & Mahindra Financial Services"
  * common short forms: M&M, L&T, SBI, RIL, TCS, HUL ...
Sector: the concall library's classification for that BSE code when we have it; otherwise one cached AI answer.
"""
import json
import re

import concalls as C

GENERIC_TAIL = {
    "projects", "industries", "industry", "india", "corporation", "corp", "company", "co", "inc", "group",
    "andspecialeconomiczone", "specialeconomiczone", "sez", "technologies", "technology", "tech", "enterprise",
    "international", "global", "incorporated", "indiaprivate", "indialimited", "infra",
}
ALIASES = {
    # government companies: headlines nearly always use the short form
    "rcf": "Rashtriya Chemicals and Fertilizers",
    "nfl": "National Fertilizers",
    "fact": "Fertilisers and Chemicals Travancore",
    "gnfc": "Gujarat Narmada Valley Fertilizers and Chemicals",
    "gsfc": "Gujarat State Fertilizers and Chemicals",
    "bhel": "Bharat Heavy Electricals",
    "beml": "BEML",
    "sail": "Steel Authority of India",
    "nmdc": "NMDC",
    "nalco": "National Aluminium Company",
    "moil": "MOIL",
    "hzl": "Hindustan Zinc",
    "bpcl": "Bharat Petroleum Corporation",
    "hpcl": "Hindustan Petroleum Corporation",
    "ioc": "Indian Oil Corporation",
    "iocl": "Indian Oil Corporation",
    "gail": "GAIL (India)",
    "mrpl": "Mangalore Refinery and Petrochemicals",
    "nhpc": "NHPC",
    "sjvn": "SJVN",
    "pfc": "Power Finance Corporation",
    "rec": "REC",
    "ireda": "Indian Renewable Energy Development Agency",
    "irfc": "Indian Railway Finance Corporation",
    "hudco": "Housing and Urban Development Corporation",
    "rvnl": "Rail Vikas Nigam",
    "ircon": "IRCON International",
    "nbcc": "NBCC (India)",
    "rites": "RITES",
    "irctc": "Indian Railway Catering and Tourism Corporation",
    "concor": "Container Corporation of India",
    "bdl": "Bharat Dynamics",
    "mdl": "Mazagon Dock Shipbuilders",
    "grse": "Garden Reach Shipbuilders and Engineers",
    "mandm": "Mahindra & Mahindra", "mahindra": "Mahindra & Mahindra", "landt": "Larsen & Toubro", "lt": "Larsen & Toubro",
    "sbi": "State Bank of India", "ril": "Reliance Industries", "reliance": "Reliance Industries",
    "tcs": "Tata Consultancy Services", "hul": "Hindustan Unilever", "hdfcbank": "HDFC Bank", "icici": "ICICI Bank",
    "airtel": "Bharti Airtel", "infy": "Infosys", "hcl": "HCL Technologies", "hcltech": "HCL Technologies",
    "maruti": "Maruti Suzuki India", "bajajauto": "Bajaj Auto", "zomato": "Eternal", "indigo": "InterGlobe Aviation",
    "ongc": "Oil and Natural Gas Corporation", "ntpc": "NTPC", "bel": "Bharat Electronics", "hal": "Hindustan Aeronautics",
    "coalindia": "Coal India", "drreddys": "Dr Reddys Laboratories", "sunpharma": "Sun Pharmaceutical Industries",
    "tatasteel": "Tata Steel", "jswsteel": "JSW Steel", "adaniports": "Adani Ports and Special Economic Zone",
    "lic": "Life Insurance Corporation of India", "bob": "Bank of Baroda", "pnb": "Punjab National Bank",
    "kotak": "Kotak Mahindra Bank", "axis": "Axis Bank", "itc": "ITC", "ultratech": "UltraTech Cement",
}
# a few large companies that may have no concall in our library yet
KNOWN_SECTORS = {
    "Rashtriya Chemicals and Fertilizers": "Fertilisers & Agrochemicals",
    "National Fertilizers": "Fertilisers & Agrochemicals",
    "Fertilisers and Chemicals Travancore": "Fertilisers & Agrochemicals",
    "Gujarat Narmada Valley Fertilizers and Chemicals": "Fertilisers & Agrochemicals",
    "Gujarat State Fertilizers and Chemicals": "Fertilisers & Agrochemicals",
    "Bharat Heavy Electricals": "Capital Goods & Engineering",
    "BEML": "Capital Goods & Engineering",
    "Steel Authority of India": "Metals & Mining",
    "NMDC": "Metals & Mining",
    "National Aluminium Company": "Metals & Mining",
    "MOIL": "Metals & Mining",
    "Hindustan Zinc": "Metals & Mining",
    "Bharat Petroleum Corporation": "Oil & Gas",
    "Hindustan Petroleum Corporation": "Oil & Gas",
    "Indian Oil Corporation": "Oil & Gas",
    "Indian Oil Corporation": "Oil & Gas",
    "GAIL (India)": "Oil & Gas",
    "Mangalore Refinery and Petrochemicals": "Oil & Gas",
    "NHPC": "Power & Utilities",
    "SJVN": "Power & Utilities",
    "Power Finance Corporation": "NBFC & Financial Services",
    "REC": "NBFC & Financial Services",
    "Indian Renewable Energy Development Agency": "NBFC & Financial Services",
    "Indian Railway Finance Corporation": "NBFC & Financial Services",
    "Housing and Urban Development Corporation": "NBFC & Financial Services",
    "Rail Vikas Nigam": "Construction & Infrastructure",
    "IRCON International": "Construction & Infrastructure",
    "NBCC (India)": "Construction & Infrastructure",
    "RITES": "Construction & Infrastructure",
    "Indian Railway Catering and Tourism Corporation": "Hotels & Travel",
    "Container Corporation of India": "Logistics & Shipping",
    "Bharat Dynamics": "Defence & Aerospace",
    "Mazagon Dock Shipbuilders": "Defence & Aerospace",
    "Garden Reach Shipbuilders and Engineers": "Defence & Aerospace",
    "Hindustan Aeronautics": "Defence & Aerospace",
    "Bharat Electronics": "Defence & Aerospace",
    "Mahindra & Mahindra": "Automobiles", "Maruti Suzuki India": "Automobiles", "Bharti Airtel": "Telecom",
    "Reliance Industries": "Oil & Gas", "State Bank of India": "Banks", "Larsen & Toubro": "Capital Goods & Engineering",
    "Eternal": "Retail & E-commerce", "InterGlobe Aviation": "Hotels & Travel", "Infosys": "IT & Software",
    "Tata Consultancy Services": "IT & Software", "Hindustan Unilever": "FMCG & Food", "ITC": "FMCG & Food",
}


def n(s):
    return C.norm(s or "")


def same(a, b):
    x, y = n(a), n(b)
    if not x or not y:
        return False
    x, y = n(ALIASES.get(x, a)), n(ALIASES.get(y, b))
    if x == y:
        return True
    short, long_ = (x, y) if len(x) < len(y) else (y, x)
    return len(short) > 3 and long_.startswith(short) and long_[len(short):] in GENERIC_TAIL


class Resolver:
    """Maps any company name seen in the news to one canonical name, BSE code and sector."""

    def __init__(self, cache=None):
        lib = C.load_lib()
        self.canon = {}  # norm -> (name, code)
        for c in lib["calls"].values():
            if c.get("code"):
                self.canon.setdefault(n(c["company"]), (re.sub(r"\s+(Ltd\.?|Limited)$", "", c["company"]).strip(), c["code"]))
        if C.PRES_FILE.exists():
            for d in json.loads(C.PRES_FILE.read_text(encoding="utf-8")):
                self.canon.setdefault(n(d["company"]), (re.sub(r"\s+(Ltd\.?|Limited)$", "", d["company"]).strip(), d["code"]))
        self.sectors = dict(lib["sectors"])
        try:
            import directory
            for code, v in directory.load().items():
                if code != "_meta":
                    self.canon.setdefault(n(v["n"]), (re.sub(r"\s+(Ltd\.?|Limited)$", "", v["n"]).strip(), code))
                    if v.get("s") and not self.sectors.get(code):
                        self.sectors[code] = v["s"]
        except Exception:
            pass
        self.cache = cache if cache is not None else {}
        self._memo = {}

    def resolve(self, name):
        """-> (canonical name, code or '')"""
        if name in self._memo:
            return self._memo[name]
        x = n(name)
        x = n(ALIASES.get(x, name))
        out = None
        if x in self.canon:
            out = self.canon[x]
        else:
            hits = [v for k, v in self.canon.items() if same(k, x) or same(x, k)]
            codes = {h[1] for h in hits}
            if len(codes) == 1:
                out = hits[0]
        if not out:
            alias = ALIASES.get(n(name))
            out = (alias or re.sub(r"\s+(Ltd\.?|Limited)$", "", name).strip(), "")
        self._memo[name] = out
        return out

    def sector(self, name, fallback=""):
        cname, code = self.resolve(name)
        if code and self.sectors.get(code):
            return self.sectors[code]
        kn = {n(k): v for k, v in KNOWN_SECTORS.items()}
        for k in (n(cname), n(ALIASES.get(n(name), ""))):
            if k and k in kn:
                return kn[k]
        got = self.cache.get("cosector", {}).get(n(cname))
        return got or fallback

    def classify_unknown(self, names):
        """One cached request to the backup AI (Groq) for companies with no sector yet."""
        cs = self.cache.setdefault("cosector", {})
        todo = sorted({self.resolve(x)[0] for x in names} - {k for k in KNOWN_SECTORS})
        todo = [t for t in todo if not self.resolve(t)[1] or not self.sectors.get(self.resolve(t)[1])]
        todo = [t for t in todo if n(t) not in cs][:120]
        if not todo:
            return
        try:
            ai = C.AI("backup")
        except C.AIError:
            return
        prompt = ("Put each Indian listed company in exactly one of these sectors:\n" + "\n".join(C.SECTORS) +
                  "\n\nAnswer one line per company, exactly: <company> | <sector>\n\n" + "\n".join(todo))
        try:
            text = ai.ask(prompt, label="sectors for new companies")
        except C.AIError:
            return
        for line in text.splitlines():
            if "|" in line:
                a, _, b = line.rpartition("|")
                b = b.strip(" *")
                if b in C.SECTORS:
                    cs[n(a.strip(" -*"))] = b
