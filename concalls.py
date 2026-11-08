#!/usr/bin/env python3
"""
Concall Summaries - simple and transparent.

  1. Test AI          - 10-second check that your AI key works
  2. Download list    - finds earnings-call transcripts filed on BSE
  3. Summarise        - by sector or by company; writes one Markdown file per concall
  4. Open summaries   - one HTML page to browse everything

Run with no arguments (or double-click "Concall Summaries.bat") for the menu.
"""
import configparser
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path

try:
    import requests
    from pypdf import PdfReader
    import markdown as mdlib
except ImportError:
    print("Missing libraries. Double-click setup.bat first.")
    input("Press Enter to close")
    sys.exit(1)
try:  # connects like Chrome; BSE blocks plain Python
    from curl_cffi import requests as cffi
except ImportError:
    cffi = None
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE = Path(__file__).resolve().parent
IS_TABLET = "com.termux" in os.environ.get("PREFIX", "")  # running in Termux on Android
DATA = BASE / "data"
PDF_DIR = DATA / "pdf"
TXT_DIR = DATA / "text"
OUT_DIR = BASE / "summaries"
LIB_FILE = DATA / "library.json"
CONFIG_FILE = BASE / "config.ini"
PAGE_FILE = BASE / "summaries.html"

BSE_API = "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w"
BSE_PDF = ["https://www.bseindia.com/xml-data/corpfiling/AttachLive/",
           "https://www.bseindia.com/xml-data/corpfiling/AttachHis/"]

SECTORS = [
    "Textiles & Apparel", "Pharma & Healthcare Products", "Hospitals & Diagnostics", "Banks",
    "NBFC & Financial Services", "Insurance", "IT & Software", "Telecom", "Automobiles",
    "Auto Components", "Chemicals", "Fertilisers & Agrochemicals", "Metals & Mining", "Oil & Gas",
    "Power & Utilities", "Capital Goods & Engineering", "Defence & Aerospace", "Electrical & Electronics",
    "Construction & Infrastructure", "Cement & Building Materials", "Real Estate", "FMCG & Food",
    "Consumer Durables", "Retail & E-commerce", "Media & Entertainment", "Hotels & Travel",
    "Logistics & Shipping", "Paper & Packaging", "Plastics & Pipes", "Agri & Sugar",
    "Services & Others",
]

SUMMARY_PROMPT = """You are an experienced Indian equity research analyst. Below is the transcript of the earnings conference call of {company} (filed on BSE on {date}).

Write a concise, factual summary in Markdown for a fundamental investor.
Rules:
- Use ONLY what is in the transcript. Never guess or add outside knowledge.
- Keep numbers exactly as stated, with units (Rs crore, %, bps, tonnes, YoY/QoQ).
- Skip any section the call did not discuss.
- Attribute forward-looking statements to management.
- Crisp bullets, no filler.

Use exactly this structure:

**Quarter:** <as stated in the call, e.g. Q2 FY27>
**Tone:** <Positive / Mixed / Cautious / Negative> - <one-line reason>

### Key numbers
### Highlights
### Guidance & outlook
### Demand & industry commentary
### Costs, margins & raw materials
### Capex, capacity & expansion
### Balance sheet, debt & working capital
### Risks & concerns flagged
### Notable analyst Q&A
(3-6 most revealing questions and how management answered; note if they dodged)
### One-line takeaway

Finally, add this block at the very end for a peer-comparison table. Numbers only (no units, no % sign,
no commas); write na when the call doesn't state it or it doesn't apply. Use figures for the quarter
discussed; growth is year-on-year. Net debt: negative means net cash.
```metrics
revenue_cr:\nrevenue_growth_yoy_pct:\nebitda_margin_pct:\nebitda_margin_change_bps_yoy:\npat_cr:\npat_growth_yoy_pct:\ncapacity_utilisation_pct:\nnet_debt_cr:\ncapex_guidance_cr:\nloan_book_or_aum_growth_yoy_pct:\nnim_pct:\ngross_npa_pct:\ncredit_cost_pct:
guidance: <raised / cut / maintained / initiated / none>
```
"""

OVERVIEW_PROMPT = """You are a senior Indian equity analyst covering {sector}. Below are summaries of the {quarter} earnings calls of {n} companies in this sector.

Write a sector overview in Markdown: what are managements across the sector saying? Use only the summaries; name companies when attributing views; show where they agree AND disagree; keep numbers as given; skip sections with nothing to say.

# {sector}: what managements are saying ({quarter})
## Big picture
## Demand outlook - consensus and divergence
## Costs, raw materials & margins
## Capex & capacity
## What changed since last quarter
(only if the summaries include last-quarter comparisons: guidance raised/cut, tone shifts, delivery on promises)
## Bullish vs cautious
(table: Company | Tone | Key reason)
## Company one-liners
## What to watch next quarter

SUMMARIES:
{body}
"""

CLASSIFY_PROMPT = """Put each Indian listed company below into exactly ONE of these sectors:
{sectors}

Use what you know about each company's main business. If you don't know it and the name doesn't make it obvious, answer Services & Others.
Reply with one line per company in exactly this form, nothing else:
<code>|<sector>

{rows}
"""


# ============================================================================ basics

def here(rel):
    """A saved path inside this folder (works for paths saved on Windows or Android)."""
    return BASE / str(rel).replace("\\", "/")


def md(text):
    """Markdown -> HTML, tolerant of AI formatting (headings/lists stuck to the end of a table)."""
    lines, out = (text or "").splitlines(), []
    for i, ln in enumerate(lines):
        prev = out[-1] if out else ""
        if prev.strip().startswith("|") and not ln.strip().startswith("|"):
            out.append("")  # end the table before the next block
        elif re.match(r"\s*#{1,6} ", ln) and prev.strip():
            out.append("")  # headings need a blank line before them
        elif re.match(r"\s*\|", ln) and prev.strip() and not prev.strip().startswith("|"):
            out.append("")  # tables too
        out.append(ln)
    return mdlib.markdown("\n".join(out), extensions=["tables", "sane_lists"])


def say(msg=""):
    print(msg, flush=True)


def load_lib():
    if LIB_FILE.exists():
        lib = json.loads(LIB_FILE.read_text(encoding="utf-8"))
    else:
        lib = {}
    lib.setdefault("calls", {})
    lib.setdefault("sectors", {})
    lib.setdefault("overviews", {})
    return lib


def save_lib(lib):
    DATA.mkdir(parents=True, exist_ok=True)
    tmp = LIB_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(lib, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(LIB_FILE)


def norm(name):
    s = name.lower().replace("&", " and ").replace("'", "").replace(".", "")
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = re.sub(r"\b(limited|ltd|the)\b", " ", s)
    return re.sub(r"\s+", "", s)


def safe_name(s):
    return re.sub(r'[<>:"/\\|?*]+', "", s).strip()[:90] or "x"


def quarter_from_date(d):
    m, y = d.month, d.year
    q, fy = ((1, y + 1) if m in (7, 8, 9) else (2, y + 1) if m in (10, 11, 12)
             else (3, y) if m in (1, 2, 3) else (4, y))
    return f"Q{q} FY{fy % 100:02d}"


def quarter_key(q):
    m = re.match(r"Q(\d) FY(\d\d)", q or "")
    return (int(m.group(2)), int(m.group(1))) if m else (0, 0)


def latest_per_company(calls):
    """One call per company per quarter (companies sometimes re-file)."""
    best = {}
    for c in calls:
        k = (norm(c["company"]), c["quarter"])
        if k not in best or c["date"] > best[k]["date"]:
            best[k] = c
    return sorted(best.values(), key=lambda c: c["company"])


def ask(prompt, default=""):
    v = input(f"{prompt}{f' [{default}]' if default else ''}: ").strip()
    return v or default


# ============================================================================ AI

class AIError(Exception):
    pass


class QuotaOver(AIError):
    pass


class AI:
    """Any OpenAI-compatible endpoint: Gemini (default), Groq, OpenRouter, Ollama..."""

    def __init__(self, section="ai"):
        cp = configparser.ConfigParser()
        cp.read(CONFIG_FILE, encoding="utf-8")
        c = cp[section] if cp.has_section(section) else {}
        self.section = section
        self.patient = True  # set False when a backup provider can take over
        # Most free tiers other than Gemini accept only a few thousand tokens per request;
        # longer transcripts are then summarised in parts (0 = no limit).
        self.max_input_tokens = int(c.get("max_input_tokens", "0" if section == "ai" else "5000") or 0)
        if os.environ.get("XAI_API_KEY") or os.environ.get("GROK_API_KEY", "").startswith("xai-") or \
                c.get("api_key", "").strip().startswith("xai-"):
            self.max_input_tokens = 0 if section != "ai" else self.max_input_tokens  # Grok takes whole transcripts
        # In the cloud (GitHub Actions) keys come from encrypted secrets, not config.ini
        names = ("GEMINI_API_KEY",) if section == "ai" else ("GROQ_API_KEY", "GROK_API_KEY", "XAI_API_KEY")
        env_key = next((os.environ[n].strip() for n in names if os.environ.get(n, "").strip()), "")
        self.key = env_key or c.get("api_key", "").strip()
        default_url = ("https://generativelanguage.googleapis.com/v1beta/openai" if section == "ai"
                       else "https://api.groq.com/openai/v1")
        self.url = c.get("base_url", default_url).strip().rstrip("/")
        self.model = c.get("model", "auto").strip()
        # the key tells us the provider, whatever config.ini says (Groq: gsk_..., xAI Grok: xai-...)
        if self.key.startswith("xai-"):
            self.url, self.provider = "https://api.x.ai/v1", "xAI Grok"
            if "x.ai" not in c.get("base_url", ""):
                self.model = "auto"
        elif self.key.startswith("gsk_"):
            self.url, self.provider = "https://api.groq.com/openai/v1", "Groq"
        else:
            self.provider = "Gemini" if "generativelanguage" in self.url else self.url.split("/")[2]
        self.max_wait = int(c.get("max_wait_seconds", "180") or 180)
        self.pause = float(c.get("seconds_between_calls", "5") or 5)
        self.max_chars = int(c.get("max_transcript_chars", "250000") or 250000)
        self.reasoning = "generativelanguage" in self.url or self.model.startswith("gemini")
        if section != "ai" and (not self.key or "PASTE" in self.key.upper()):
            raise AIError("no backup configured")
        if not self.key or "PASTE" in self.key.upper():
            raise AIError("No API key yet. Open config.ini in Notepad and paste your key after api_key = "
                          "(free Gemini key: https://aistudio.google.com/apikey)")

    def _headers(self):
        return {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}

    def _pick_model(self):
        if self.model.lower() != "auto":
            return
        say("  Finding the best free model for your key ...")
        try:
            r = requests.get(f"{self.url}/models", headers=self._headers(), timeout=30)
        except requests.RequestException as e:
            raise AIError(f"Can't reach the AI server: {e}")
        if r.status_code in (400, 401, 403):
            raise AIError(f"The AI server rejected your key ({r.status_code}): {self._msg(r)}")
        if r.status_code != 200:
            raise AIError(f"Couldn't list models ({r.status_code}): {self._msg(r)}")
        ids = [m.get("id", "").replace("models/", "") for m in r.json().get("data", [])]
        if not any("gemini" in i for i in ids):
            # Groq / xAI / others: take the best general chat model on offer
            prefs = ["openai/gpt-oss-120b", "llama-3.3-70b-versatile", "moonshotai/kimi-k2-instruct",
                     "qwen/qwen3-32b", "openai/gpt-oss-20b"]
            skip = ("whisper", "tts", "guard", "embed", "image", "vision", "audio", "playai", "compound", "imagine")
            chat = [i for i in ids if not any(x in i.lower() for x in skip)]
            pick = next((p for p in prefs if p in chat), None)
            if not pick and any("grok" in i for i in chat):
                grok = [i for i in chat if "grok" in i]
                pick = next((i for i in grok if "fast" in i), None) or next((i for i in grok if "mini" in i), None) or grok[0]
            if not pick and chat:
                pick = chat[0]
            if not pick:
                raise AIError(f"No usable model found for {self.url}")
            self.model, self.backups = pick, [i for i in prefs if i in chat and i != pick]
            say(f"  Using {pick}")
            return
        self.reasoning = True  # ask Gemini to think briefly - much faster
        bad = ("image", "tts", "audio", "live", "embed", "robotics", "computer", "preview", "exp", "native")
        flash = [i for i in ids if "flash" in i and not any(b in i for b in bad)]

        def rank(i):
            v = re.search(r"(\d+(?:\.\d+)?)", i)
            return ("lite" in i, -(float(v.group(1)) if v else 99), i)

        flash.sort(key=rank)
        if not flash:
            raise AIError(f"No suitable model found. Models available: {', '.join(ids[:15])}")
        last = DATA / "working_model.txt"  # start with whichever model worked last time
        if last.exists() and last.read_text(encoding="utf-8").strip() in flash:
            m = last.read_text(encoding="utf-8").strip()
            flash.remove(m)
            flash.insert(0, m)
        self.model = flash[0]
        self.backups = flash[1:]
        say(f"  Models to try, in order: {', '.join(flash[:5])}")

    @staticmethod
    def _msg(r):
        try:
            js = r.json()
            js = js[0] if isinstance(js, list) and js else js
            return (js.get("error") or {}).get("message") or str(js)[:300]
        except Exception:
            return r.text[:300]

    def ask(self, prompt, label="AI", max_wait=None):
        """Send one prompt. Shows a live counter. If a model is busy or silent, switches to
        another free model straight away instead of waiting on it."""
        max_wait = max_wait or self.max_wait
        if self.model.lower() == "auto":
            self._pick_model()
        busy_waits = 0
        for _ in range(12):
            body = {"model": self.model, "messages": [{"role": "user", "content": prompt}], "temperature": 0.2}
            if self.reasoning:
                body["reasoning_effort"] = "low"
            box = {}

            def work():
                try:
                    box["r"] = requests.post(f"{self.url}/chat/completions", headers=self._headers(),
                                             json=body, timeout=(15, max_wait))
                except Exception as e:
                    box["e"] = e

            t = threading.Thread(target=work, daemon=True)
            start = time.time()
            t.start()
            while t.is_alive() and time.time() - start < max_wait + 5:
                t.join(1)
                print(f"\r    {label}: waiting for {self.model} ... {int(time.time() - start)}s ",
                      end="", flush=True)
            waited = int(time.time() - start)
            ok = "r" in box and box["r"].status_code == 200
            print(f"\r    {label}: {self.model} replied in {waited}s{' ' * 20}" if ok else "\r" + " " * 70 + "\r",
                  end="\n" if ok else "", flush=True)

            r = box.get("r")
            silent = r is None
            busy = silent or r.status_code >= 500
            if busy:
                why = f"no reply in {waited}s" if silent else f"overloaded ({r.status_code})"
                switches = getattr(self, "_switches", 0)
                if switches < len(getattr(self, "backups", [])) and self._switch(f"{self.model} {why}"):
                    self._switches = switches + 1
                    continue
                self._switches = 0
                busy_waits += 1
                if busy_waits > (2 if self.patient else 0):
                    raise AIError(f"The AI service is overloaded right now ({why}). Try again in a while, "
                                  "or switch to Groq (see README).")
                say(f"    {self.model} {why} - retrying in 20s")
                time.sleep(20)
                continue

            if r.status_code == 200:
                self._switches = 0
                try:
                    text = r.json()["choices"][0]["message"]["content"] or ""
                except Exception:
                    raise AIError(f"Unexpected reply: {r.text[:300]}")
                if not text.strip():
                    raise AIError("The AI returned an empty answer (possibly a safety block).")
                try:
                    DATA.mkdir(parents=True, exist_ok=True)
                    (DATA / "working_model.txt").write_text(self.model, encoding="utf-8")
                except Exception:
                    pass
                return text.strip()
            msg = self._msg(r)
            if r.status_code == 400 and self.reasoning and "reason" in msg.lower():
                self.reasoning = False  # this model doesn't take that setting
                continue
            if r.status_code in (401, 403):
                raise AIError(f"Key rejected ({r.status_code}): {msg}")
            if r.status_code == 404 or "no longer available" in msg:
                rec = re.search(r"use (?:models/)?(gemini-[\w.-]+)", msg)
                sug = rec.group(1).rstrip(".") if rec else ""
                if sug and sug != self.model and sug not in getattr(self, "backups", []):
                    self.backups = [sug] + getattr(self, "backups", [])
                if self._switch(f"{self.model} no longer offered by Google", drop=True):
                    continue
                raise AIError(f"Model '{self.model}' isn't available: {msg[:200]}")
            if r.status_code == 429:
                if re.search(r"per ?day|daily|PerDay", msg, re.I):
                    if self._switch(f"daily free limit used on {self.model}", drop=True):
                        continue
                    raise QuotaOver("Today's free AI limit is used up. Everything done so far is saved - "
                                    "run again tomorrow and it continues where it stopped.")
                m = re.search(r"(?:retry|try again) in (?:(\d+)m)?([\d.]+)s|retryDelay\D+(\d+)", msg + r.text)
                if m:
                    wait = int(m.group(1) or 0) * 60 + int(float(m.group(2) or m.group(3))) + 3
                else:
                    wait = 60
                for left in range(wait, 0, -1):
                    print(f"\r    per-minute limit hit - resuming in {left}s ", end="", flush=True)
                    time.sleep(1)
                print("\r" + " " * 50 + "\r", end="")
                continue
            if r.status_code == 413:
                raise AIError(f"Request too large for {self.model} ({msg[:120]}). "
                              f"Lower max_input_tokens in the [{self.section}] part of config.ini.")
            raise AIError(f"AI error {r.status_code}: {msg}")
        raise AIError("The AI kept failing - try again later.")

    def _switch(self, reason, drop=False):
        """Move to the next model. A busy model goes to the back of the queue (it may recover);
        drop=True removes it for this run (retired by Google, or daily limit used)."""
        if not getattr(self, "backups", None):
            return False
        nxt = self.backups.pop(0)
        if not drop:
            self.backups.append(self.model)
        say(f"    {reason} - switching to {nxt}")
        self.model = nxt
        return True


class Pool:
    """Gemini first; if it's down, the backup provider takes over for 15 minutes."""

    def __init__(self):
        self.primary = AI("ai")
        try:
            self.backup = AI("backup")
        except AIError:
            self.backup = None
        self.primary.patient = self.backup is None
        self.down_until = 0
        self.pause = self.primary.pause

    def providers(self):
        """Who to try, in order, right now."""
        if self.backup and time.time() < self.down_until:
            return [self.backup]
        return [self.primary] + ([self.backup] if self.backup else [])

    def ask(self, prompt, label="AI", max_wait=None):
        """Returns (text, ai_used). Falls back to the backup if Gemini fails."""
        return self.run(lambda ai: ai.ask(prompt, label=label, max_wait=max_wait))

    def run(self, job):
        last = None
        for ai in self.providers():
            try:
                return job(ai), ai
            except AIError as e:
                last = e
                if ai is self.primary and self.backup:
                    say(f"    Gemini unavailable ({str(e)[:90]})\n"
                        f"    -> using backup {self.backup.model} for the next 15 minutes")
                    self.down_until = time.time() + 900
                    continue
                raise
        raise last


def test_ai():
    ok = False
    for section, name in (("ai", "Main AI (Gemini)"), ("backup", "Backup AI")):
        say(f"\nTesting {name} ...")
        try:
            ai = AI(section)
        except AIError as e:
            say("  not set up (optional - see README)" if section == "backup" else f"  PROBLEM: {e}")
            continue
        try:
            t = time.time()
            out = ai.ask("Reply with exactly: OK", label="test", max_wait=45)
            say(f"  SUCCESS - {ai.model} answered '{out[:40]}' in {time.time() - t:.0f}s.")
            ok = True
        except AIError as e:
            say(f"  PROBLEM: {e}")
    return ok


# ============================================================================ BSE

_sess = None
BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com",
    "Accept": "application/json, text/plain, */*", "Accept-Language": "en-IN,en;q=0.9",
}


class CurlResponse:
    def __init__(self, status, content):
        self.status_code, self.content = status, content
        self.text = content.decode("utf-8", "replace")

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class CurlSession:
    """Uses the curl program (HTTP/2, browser-like) - for Android/Termux, where curl_cffi won't install."""
    headers = {}

    def get(self, url, params=None, timeout=40):
        if params:
            url += ("&" if "?" in url else "?") + requests.compat.urlencode(params)
        fd, tmp = tempfile.mkstemp()
        os.close(fd)
        cmd = ["curl", "-sS", "-L", "--compressed", "--http2", "-m", str(int(timeout)), "-o", tmp, "-w", "%{http_code}"]
        for k, v in BROWSER_HEADERS.items():
            cmd += ["-H", f"{k}: {v}"]
        try:
            out = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=timeout + 10)
            if out.returncode != 0:
                raise ConnectionError(out.stderr.strip()[:150] or f"curl exit {out.returncode}")
            return CurlResponse(int(out.stdout.strip() or 0), Path(tmp).read_bytes())
        finally:
            os.remove(tmp)


def bse():
    global _sess
    if _sess is None:
        if cffi is not None:  # laptop: connect exactly like Chrome
            _sess = cffi.Session(impersonate="chrome")
            _sess.headers.update({k: v for k, v in BROWSER_HEADERS.items() if k != "User-Agent"})
        elif shutil.which("curl"):  # tablet (Termux)
            _sess = CurlSession()
        else:
            _sess = requests.Session()
            _sess.headers.update(BROWSER_HEADERS)
    return _sess


def bse_query(frm, to, subcategory, cat=None):
    rows, page = [], 1
    while page <= 300:
        params = {"pageno": page, "strCat": cat or ("Company Update" if subcategory != "-1" else "-1"),
                  "strPrevDate": frm.strftime("%Y%m%d"), "strToDate": to.strftime("%Y%m%d"),
                  "strScrip": "", "strSearch": "P", "strType": "C", "subcategory": subcategory}
        for attempt in range(4):
            try:
                r = bse().get(BSE_API, params=params, timeout=40)
                if r.status_code == 403:
                    raise RuntimeError("BSE refused the connection (403). Run setup.bat to install curl_cffi.")
                r.raise_for_status()
                try:
                    js = r.json()
                except ValueError:
                    raise ValueError(f"not JSON (HTTP {r.status_code}): {r.text[:80]!r}")
                break
            except RuntimeError:
                raise
            except Exception as e:
                if attempt == 3:
                    raise RuntimeError(f"BSE not responding: {str(e)[:150]}")
                time.sleep(3 * (attempt + 1))
        table = js.get("Table") or []
        if not table:
            break
        rows += table
        total = (js.get("Table1") or [{}])[0].get("ROWCNT")
        if total and len(rows) >= int(total):
            break
        page += 1
        time.sleep(0.4)
    return rows


def is_transcript(row):
    text = " ".join(str(row.get(k) or "") for k in ("NEWSSUB", "HEADLINE", "SUBCATNAME")).lower()
    return "transcript" in text and str(row.get("ATTACHMENTNAME") or "").lower().endswith(".pdf")


def download_list(days):
    lib = load_lib()
    to = dt.date.today()
    frm = to - dt.timedelta(days=days)
    say(f"\nLooking for concall transcripts filed on BSE, {frm:%d %b} - {to:%d %b %Y}")
    new, day = 0, frm
    while day <= to:
        end = min(day + dt.timedelta(days=6), to)
        print(f"  {day:%d %b} - {end:%d %b} ... ", end="", flush=True)
        rows = [r for r in bse_query(day, end, "Earnings Call Transcript") if is_transcript(r)]
        if not rows:
            rows = [r for r in bse_query(day, end, "-1") if is_transcript(r)]
        say(f"{len(rows)} transcripts")
        for row in rows:
            try:
                d = dt.datetime.fromisoformat(str(row.get("NEWS_DT") or row.get("DT_TM"))[:19])
            except ValueError:
                continue
            att = row["ATTACHMENTNAME"]
            cid = f"{row.get('SCRIP_CD')}_{Path(att).stem}"[:120]
            if cid not in lib["calls"]:
                lib["calls"][cid] = {
                    "id": cid, "code": str(row.get("SCRIP_CD")),
                    "company": (row.get("SLONGNAME") or "").strip() or str(row.get("SCRIP_CD")),
                    "date": d.strftime("%Y-%m-%d"), "quarter": quarter_from_date(d), "pdf": att}
                new += 1
        day = end + dt.timedelta(days=1)
    save_lib(lib)
    companies = {c["code"] for c in lib["calls"].values()}
    say(f"\nDone: {new} new transcripts. Library: {len(lib['calls'])} transcripts from {len(companies)} companies.")


PRES_FILE = DATA / "presentations.json"


def is_presentation(row):
    text = " ".join(str(row.get(k) or "") for k in ("NEWSSUB", "HEADLINE", "SUBCATNAME")).lower()
    return "presentation" in text and str(row.get("ATTACHMENTNAME") or "").lower().endswith(".pdf")


def fetch_presentations(days=2, keep_days=45):
    """Investor presentations filed on BSE (what blogs like Alpha Ideas repost), kept for ~6 weeks."""
    old = json.loads(PRES_FILE.read_text(encoding="utf-8")) if PRES_FILE.exists() else []
    have = {p["id"] for p in old}
    to = dt.date.today()
    frm = to - dt.timedelta(days=days)
    try:
        rows = [r for r in bse_query(frm, to, "Investor Presentation") if is_presentation(r)]
    except RuntimeError as e:  # fall back to all of today's announcements, filtered
        say(f"  presentation filter not answering ({str(e)[:80]}) - scanning today's announcements instead")
        rows = [r for r in bse_query(to - dt.timedelta(days=1), to, "-1") if is_presentation(r)]
    lib = load_lib()
    new = 0
    for row in rows:
        att = row["ATTACHMENTNAME"]
        pid = f"{row.get('SCRIP_CD')}_{Path(att).stem}"[:120]
        if pid in have:
            continue
        try:
            d = dt.datetime.fromisoformat(str(row.get("NEWS_DT") or row.get("DT_TM"))[:19])
        except ValueError:
            continue
        code = str(row.get("SCRIP_CD"))
        old.append({"id": pid, "code": code, "company": (row.get("SLONGNAME") or "").strip() or code,
                    "when": d.strftime("%Y-%m-%dT%H:%M"), "title": clean_head(row),
                    "sector": lib["sectors"].get(code, ""), "pdf": BSE_PDF[0] + att})
        have.add(pid)
        new += 1
    cutoff = (to - dt.timedelta(days=keep_days)).isoformat()
    old = sorted([p for p in old if p["when"] >= cutoff], key=lambda p: p["when"], reverse=True)
    for p in old:  # fill in sectors learnt since
        if not p.get("sector"):
            p["sector"] = lib["sectors"].get(p["code"], "")
    DATA.mkdir(parents=True, exist_ok=True)
    PRES_FILE.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    say(f"  investor presentations: {new} new, {len(old)} kept")
    return old


def clean_head(row):
    t = str(row.get("HEADLINE") or row.get("NEWSSUB") or "").strip()
    t = re.sub(r"\s+", " ", t)
    return t[:220]


def get_text(call):
    """Downloads the PDF and extracts the text. Returns (text, problem)."""
    txt = TXT_DIR / f"{call['id']}.txt"
    if txt.exists():
        return txt.read_text(encoding="utf-8"), None
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    TXT_DIR.mkdir(parents=True, exist_ok=True)
    pdf = PDF_DIR / f"{call['id']}.pdf"
    if not pdf.exists():
        for base in BSE_PDF:
            try:
                r = bse().get(base + call["pdf"], timeout=90)
            except Exception:
                continue
            if r.status_code == 200 and r.content[:4] == b"%PDF":
                pdf.write_bytes(r.content)
                call["pdf_url"] = base + call["pdf"]
                break
        else:
            return None, "couldn't download the PDF from BSE"
    try:
        text = "\n".join((p.extract_text() or "") for p in PdfReader(str(pdf)).pages)
    except Exception as e:
        return None, f"couldn't read the PDF ({str(e)[:80]})"
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) < 3000:
        return None, "PDF is a scanned image (no text) - open it on BSE"
    txt.write_text(text, encoding="utf-8")
    return text, None


# ============================================================================ sectors

def classify(lib, pool):
    """Asks the AI once for every company that has no sector yet (saved, so it's one-off)."""
    comp = {c["code"]: c["company"] for c in lib["calls"].values()}
    todo = [(code, name) for code, name in comp.items() if code not in lib["sectors"]]
    if not todo:
        return
    say(f"\nSorting {len(todo)} companies into sectors (one-off, takes a minute) ...")
    for i in range(0, len(todo), 100):
        batch = todo[i:i + 100]
        got = {}
        for attempt in range(2):
            text, _ = pool.ask(CLASSIFY_PROMPT.format(sectors="\n".join(SECTORS),
                                                      rows="\n".join(f"{c}|{n}" for c, n in batch)),
                               label=f"sectors {i + 1}-{i + len(batch)}")
            got = parse_sectors(text, {c for c, _ in batch})
            if len(got) >= 0.6 * len(batch):
                break
            say(f"    couldn't read the AI's answer for this batch ({len(got)}/{len(batch)}) - asking again")
        if len(got) < 0.6 * len(batch):
            say("    still unreadable - these companies will be sorted on the next run")
            continue  # left unsorted, so they're retried - never filed under a default sector
        for code, _ in batch:
            lib["sectors"][code] = got.get(code, "Services & Others")
        save_lib(lib)


def parse_sectors(text, codes):
    """Reads '<code>|<sector>' lines, tolerating markdown, tables, colons and near-miss sector names."""
    lookup = {s.lower(): s for s in SECTORS}
    got = {}
    for line in text.splitlines():
        line = line.replace("`", "").replace("*", "").strip(" -|")
        m = re.match(r"^(\d{5,6})\s*(?:\|[^|]*?\|)?\s*[|:–-]\s*(.+?)\s*\|?\s*$", line)
        if not m or m.group(1) not in codes:
            continue
        name = m.group(2).strip(" .|").lower()
        sec = lookup.get(name) or next((v for k, v in lookup.items() if k in name or name in k), None)
        if sec:
            got[m.group(1)] = sec
    return got


def sector_of(lib, call):
    return lib["sectors"].get(call["code"], "Unsorted")


# ============================================================================ number check

NUM_RE = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{2,3})+|\d+)(?:\.(\d+))?(?![\w])")


def _num_key(intpart, dec):
    k = intpart.replace(",", "").lstrip("0") or "0"
    d = (dec or "").rstrip("0")
    return f"{k}.{d}" if d else k


def transcript_numbers(text):
    """Every number in a transcript, however it's written: 'Rs.9,197', 'INR9,197', '9, 197' (PDF spacing)."""
    text = re.sub(r"(?<=\d),\s+(?=\d{2,3}\b)", ",", text)
    text = re.sub(r"(?<=\d)\.\s+(?=\d)", ".", text)
    out = set()
    for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", text):
        whole, _, dec = m.group(0).rstrip(",").partition(".")
        out.add(_num_key(whole, dec))
    return out


def unverified_numbers(summary, transcript):
    """Numbers in the summary that don't appear anywhere in the transcript.
    These are either calculated by the AI (e.g. a growth % it worked out) or misread - worth a check."""
    have = transcript_numbers(transcript)
    body = re.sub(r"\*\*Quarter:\*\*.*", "", summary)  # quarter labels aren't figures
    out = []
    for m in NUM_RE.finditer(body):
        raw = m.group(0)
        key = _num_key(m.group(1), m.group(2))
        whole = int(m.group(1).replace(",", ""))
        if not m.group(2) and (whole < 10 or 1990 <= whole <= 2040):
            continue  # small counts and years: too ambiguous to check
        if key not in have and raw not in out:
            out.append(raw)
    return out


# ============================================================================ summarising

COMPARE_INSTRUCTIONS = """
The summary of this company's PREVIOUS quarter call ({pq}) is given below the transcript.
Add this section right after the Tone line:
### What changed vs last quarter
- Guidance: raised / cut / maintained (with the old and new numbers)
- Tone and demand view: how it shifted
- New topics or risks that weren't there last quarter, and old ones that disappeared
- Last quarter's promises (targets, launches, capex, timelines) and whether they were delivered
"""

NOTES_PROMPT = """This is part {i} of {n} of the earnings call transcript of {company}.
Write dense factual notes from THIS PART ONLY, as bullets: every number with its units and what it refers to,
guidance and outlook statements, demand and industry comments, costs and margins, capex, debt and working
capital, risks, and the most revealing analyst questions with management's answers. No outside knowledge.

TEXT:
"""


def strip_boilerplate(text):
    """Removes disclaimers, operator lines and page furniture: fewer tokens, less noise."""
    drop = re.compile(r"^(page \d+( of \d+)?|\d+ ?/ ?\d+|\d+)$|press \* (and|then) 1|press star|"
                      r"please press|this conference call may contain forward[- ]looking|"
                      r"all participant lines are in the listen[- ]only|"
                      r"^(moderator|operator): (thank you|ladies and gentlemen)", re.I)
    rows = [ln.strip() for ln in text.splitlines()]
    count = {}
    for t in rows:
        count[t] = count.get(t, 0) + 1
    # short lines repeated on many pages are headers/footers
    return "\n".join(t for t in rows if t and not drop.search(t) and not (len(t) < 80 and count[t] > 3))


def est_tokens(s):
    return len(s) // 4


def build_summary(ai, call, text, prev):
    """One call if the provider can take the whole transcript; otherwise notes per part, then a summary."""
    head = SUMMARY_PROMPT.format(company=call["company"], date=call["date"])
    tail = ""
    if prev:
        head += COMPARE_INSTRUCTIONS.format(pq=prev["quarter"])
        tail = f"\n\nPREVIOUS QUARTER SUMMARY ({prev['quarter']}):\n{prev['text']}"
    try:  # our permanent record of the company: lets the summary spot patterns across quarters
        import timeline
        rec = timeline.context(code=call.get("code"), name=call["company"], before=call["date"], limit=12)
    except Exception:
        rec = ""
    if rec:
        head += ("\nBelow the transcript is OUR RECORD of earlier events for this company (orders, pivots, results, "
                 "past calls). Where the call continues or breaks a pattern in that record (e.g. a third capacity "
                 "addition, a legal case still pending, guidance missed again), say so in one line under Highlights "
                 "or Risks. Do not repeat the record otherwise.\n")
        tail += f"\n\nOUR RECORD (oldest first):\n{rec}"
    text = text[:ai.max_chars]
    budget = ai.max_input_tokens
    if not budget or est_tokens(head + text + tail) <= budget:
        return ai.ask(head + "TRANSCRIPT:\n" + text + tail, label="summary")
    size = max(6000, (budget - 1500) * 4)
    parts = [text[i:i + size] for i in range(0, len(text), size)]
    say(f"    {ai.model} takes ~{budget} tokens at a time - reading the transcript in {len(parts)} parts")
    notes = []
    for i, part in enumerate(parts, 1):
        notes.append(ai.ask(NOTES_PROMPT.format(i=i, n=len(parts), company=call["company"]) + part,
                            label=f"part {i}/{len(parts)}"))
    joined = "\n\n".join(notes)
    if est_tokens(head + joined + tail) > budget:
        tail = tail[:max(0, (budget - est_tokens(head + joined)) * 4 - 200)]
    return ai.ask(head + "TRANSCRIPT NOTES (taken from the full transcript, in order):\n" + joined + tail,
                  label="summary")


def prev_quarter(q):
    y, n = quarter_key(q)
    return f"Q4 FY{y - 1:02d}" if n == 1 else f"Q{n - 1} FY{y:02d}"


def filing_quarter(call):
    return quarter_from_date(dt.date.fromisoformat(call["date"]))


def find_prev(lib, call):
    """The same company's call from the previous quarter, if it's in the library."""
    pq = prev_quarter(filing_quarter(call))
    cands = [c for c in lib["calls"].values()
             if c["code"] == call["code"] and filing_quarter(c) == pq]
    return max(cands, key=lambda c: c["date"]) if cands else None


METRIC_KEYS = ["revenue_cr", "revenue_growth_yoy_pct", "ebitda_margin_pct", "ebitda_margin_change_bps_yoy",
               "pat_cr", "pat_growth_yoy_pct", "capacity_utilisation_pct", "net_debt_cr", "capex_guidance_cr",
               "loan_book_or_aum_growth_yoy_pct", "nim_pct", "gross_npa_pct", "credit_cost_pct"]
GUIDANCE = ("raised", "cut", "maintained", "initiated", "none")


def parse_metrics(text):
    """Reads the ```metrics block. Returns (metrics dict, text without the block)."""
    m = re.search(r"```\s*metrics\s*\n(.*?)```", text, re.S | re.I)
    if not m:
        return None, text
    out = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        k, v = k.strip().lower(), v.strip().lower()
        if k == "guidance":
            out[k] = next((g for g in GUIDANCE if g in v), "none")
        elif k in METRIC_KEYS:
            num = re.search(r"-?\d[\d,]*(?:\.\d+)?", v.replace("(", "-"))
            out[k] = float(num.group(0).replace(",", "")) if num and "na" != v else None
    clean = (text[:m.start()] + text[m.end():]).rstrip()
    clean = re.sub(r"\n+(Finally|Metrics)[^\n]*$", "", clean).rstrip()
    return out, clean


def metrics_unchecked(metrics, source):
    """Metric values that don't appear in the transcript (usually calculated by the AI)."""
    have = transcript_numbers(source)
    bad = []
    for k, v in (metrics or {}).items():
        if isinstance(v, float):
            whole, _, dec = ("%f" % abs(v)).rstrip("0").rstrip(".").partition(".")
            if _num_key(whole, dec) not in have:
                bad.append(k)
    return bad


def summarise_one(call, lib, pool, prev=None):
    """Summarise one call and save it. Returns True if saved."""
    text, problem = get_text(call)
    if problem:
        say(f"    skipped: {problem}")
        call["skip"] = problem
        save_lib(lib)
        return False
    text = strip_boilerplate(text)
    prev_info = None
    if prev and prev.get("summary") and (here(prev["summary"])).exists():
        prev_text = re.sub(r"^# .*\n(\*Filed.*\*\n)?", "", (here(prev["summary"])).read_text(encoding="utf-8"))
        prev_text = prev_text.split("\n---\n")[0]  # without the number-check note
        prev_info = {"quarter": prev["quarter"], "text": prev_text}
    out, ai = pool.run(lambda a: build_summary(a, call, text, prev_info))
    metrics, out = parse_metrics(out)
    q = re.search(r"\*\*Quarter:\*\*\s*Q\s*([1-4])\s*[-' ]*FY\s*'?(\d{2,4})", out, re.I)
    call["quarter"] = f"Q{q.group(1)} FY{int(q.group(2)) % 100:02d}" if q else filing_quarter(call)
    tone = re.search(r"\*\*Tone:\*\*\s*\**\s*([A-Za-z]+)", out)
    call["tone"] = tone.group(1).capitalize() if tone else ""
    source = text
    if prev_info:  # the comparison section quotes last quarter's figures
        old = TXT_DIR / f"{prev['id']}.txt"
        if old.exists():  # check against the real transcript only - never against AI-written text
            source += "\n" + old.read_text(encoding="utf-8")
    bad = unverified_numbers(out, source)
    call["unverified"] = bad
    if metrics:
        call["metrics"] = metrics
        call["metrics_unchecked"] = metrics_unchecked(metrics, source)
    call["compared"] = bool(prev_info)
    note = ""
    if bad:
        note = ("\n---\n**Check these figures** - not found word-for-word in the transcript "
                f"(may be calculated by the AI, or misread): {', '.join(bad)}\n")
    folder = OUT_DIR / safe_name(sector_of(lib, call))
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{safe_name(call['company'])} - {call['quarter']}.md"
    path.write_text(f"# {call['company']} - {call['quarter']} concall\n"
                    f"*Filed on BSE {call['date']} · {sector_of(lib, call)}*\n\n{out}\n{note}", encoding="utf-8")
    call["summary"] = path.relative_to(BASE).as_posix()
    call["model"] = ai.model
    save_lib(lib)
    checks = f"  ({len(bad)} figure(s) to check)" if bad else "  (all figures found in transcript)"
    say(f"    saved: {path.relative_to(BASE)}{checks}")
    return True


def summarise(calls, lib, pool, compare=True, limit=None, stats=None):
    """Summarise the latest call of each company; with compare=True, also last quarter's call
    (if needed) so each summary says what changed."""
    calls = latest_per_company(calls)
    target = max((filing_quarter(c) for c in calls), key=quarter_key)
    calls = [c for c in calls if filing_quarter(c) == target]
    plan = []
    for c in calls:
        prev = find_prev(lib, c) if compare else None
        if c.get("summary") and (c.get("compared") or not prev or not compare):
            continue
        plan.append((c, prev))
    if limit is not None:
        plan = plan[:max(0, limit)]
    need_prev = [p for _, p in plan if p and not p.get("summary") and not p.get("skip")]
    redo = [c for c, _ in plan if c.get("summary")]
    say(f"\n{len(calls)} concalls for {target}: {len(plan)} to do now"
        + (f" (incl. {len(redo)} re-done to add the last-quarter comparison)" if redo else "") + ".")
    if need_prev:
        say(f"Plus {len(need_prev)} previous-quarter calls to summarise first, for the comparison.")
    if not plan:
        return True
    say("Each takes about 20-90 seconds. Stop any time with Ctrl+C - finished ones are kept.\n")
    fails = 0
    for i, (call, prev) in enumerate(plan, 1):
        say(f"[{i}/{len(plan)}] {call['company']}  (filed {call['date']})")
        try:
            if prev and not prev.get("summary") and not prev.get("skip"):
                say(f"    first, last quarter's call (filed {prev['date']}) ...")
                summarise_one(prev, lib, pool)
                time.sleep(pool.pause)
            summarise_one(call, lib, pool, prev)
            fails = 0
            if stats is not None:
                stats["done"] = stats.get("done", 0) + 1
        except QuotaOver as e:
            say(f"\n{e}")
            return False
        except AIError as e:
            say(f"    failed: {e}")
            fails += 1
            if fails >= 3:
                say("\nStopping: the AI failed 3 times in a row. Everything finished so far is saved -\n"
                    "run Summarise again later and it continues with the companies not done yet.")
                return False
        if i < len(plan):
            time.sleep(pool.pause)
    return True


def overview(sector, lib, pool):
    calls = [c for c in lib["calls"].values() if sector_of(lib, c) == sector and c.get("summary")]
    if len(calls) < 2:
        return
    q = max((c["quarter"] for c in calls), key=quarter_key)
    calls = latest_per_company([c for c in calls if c["quarter"] == q])
    if len(calls) < 2:
        return
    key = f"{sector}|{q}"
    names = sorted(c["company"] for c in calls)
    stamp = [c.get("compared", False) for c in sorted(calls, key=lambda c: c["company"])]
    old = lib["overviews"].get(key, {})
    if old.get("companies") == names and old.get("compared") == stamp:
        return  # already up to date
    say(f"\nWriting the {sector} overview for {q} from {len(calls)} companies ...")
    texts = [(c["company"], (here(c["summary"])).read_text(encoding="utf-8").split("\n---\n")[0]) for c in calls]

    def job(ai):
        per = None
        if ai.max_input_tokens:  # small-limit provider: give each company an equal share
            per = max(800, (ai.max_input_tokens - 1500) * 4 // len(texts))
        body = "\n\n".join(f"=== {n} ===\n" + (t[:per] if per else t) for n, t in texts)
        return ai.ask(OVERVIEW_PROMPT.format(sector=sector, quarter=q, n=len(calls), body=body), label="overview")

    try:
        out, _ = pool.run(job)
    except AIError as e:
        say(f"    overview failed: {e}")
        return
    folder = OUT_DIR / safe_name(sector)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"_SECTOR OVERVIEW - {q}.md"
    path.write_text(out + f"\n\n*Based on: {', '.join(names)}*\n", encoding="utf-8")
    lib["overviews"][key] = {"sector": sector, "quarter": q, "companies": names, "compared": stamp,
                             "file": path.relative_to(BASE).as_posix()}
    save_lib(lib)
    say(f"    saved: {path.relative_to(BASE)}")


# ============================================================================ page

PAGE = r"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Concall Summaries</title>
<style>
body{margin:0;background:#f6f5f1;color:#1d1f24;font:15px/1.55 -apple-system,"Segoe UI",Roboto,sans-serif}
header{background:#13201f;color:#fff;padding:16px 24px}header h1{margin:0;font-size:19px}
.bar{position:sticky;top:0;background:#f6f5f1;border-bottom:1px solid #e4e2dc;padding:10px 24px;display:flex;gap:8px;flex-wrap:wrap}
select,input{font:inherit;padding:7px 10px;border:1px solid #d9d6cf;border-radius:8px;background:#fff}input{flex:1;min-width:200px}
main{max-width:960px;margin:0 auto;padding:16px 24px 60px}
details{background:#fff;border:1px solid #e4e2dc;border-radius:10px;margin:0 0 10px}
summary{padding:12px 16px;cursor:pointer;display:flex;gap:10px;align-items:center;list-style:none}
summary::-webkit-details-marker{display:none}.n{font-weight:600}.m{color:#6b6f78;font-size:13px}
.t{font-size:12px;font-weight:600;padding:2px 9px;border-radius:99px;background:#eee}
.Positive{background:#e3f3e9;color:#1e7b46}.Mixed{background:#fbf3d6;color:#8a6a00}
.Cautious{background:#fdebd8;color:#b35a00}.Negative{background:#fbe1de;color:#b42318}
.ov{border-color:#0f5e57}.ov summary .n{color:#0f5e57}
.b{padding:0 20px 16px;border-top:1px solid #eee}.b h1{font-size:19px}.b h2,.b h3{color:#0f5e57;font-size:15px;margin:16px 0 6px}
table{border-collapse:collapse;width:100%}td,th{border:1px solid #e4e2dc;padding:5px 8px;text-align:left;vertical-align:top}
a{color:#0f5e57}.empty{text-align:center;color:#6b6f78;padding:40px}
mark{background:#ffe8a3;border-bottom:2px solid #d99a00;cursor:help}.warn{background:#fff6dc;border-left:3px solid #d99a00;padding:8px 12px;font-size:13px}
.c{font-size:12px;padding:2px 8px;border-radius:99px;background:#fff6dc;color:#8a5a00}.q{font-size:12px;padding:2px 8px;border-radius:99px;background:#e6efee;color:#0f5e57}
</style></head><body><header><h1>Concall Summaries</h1></header>
<div class="bar"><select id="s"><option value="">All sectors</option></select>
<select id="q"><option value="">All quarters</option></select>
<input id="f" placeholder="Search company or any word (e.g. cotton, capex, tariff)"></div>
<main id="list"></main>
<script>
const D=__DATA__,$=id=>document.getElementById(id);
[...new Set(D.map(x=>x.sector))].sort().forEach(s=>$("s").add(new Option(s,s)));
[...new Set(D.map(x=>x.quarter))].sort().reverse().forEach(q=>$("q").add(new Option(q,q)));
function draw(){const s=$("s").value,q=$("q").value,f=$("f").value.toLowerCase();
 const rows=D.filter(x=>(!s||x.sector===s)&&(!q||x.quarter===q)&&(!f||x.text.includes(f)));
 $("list").innerHTML=rows.map(x=>`<details class="${x.ov?"ov":""}"${x.ov&&s?" open":""}><summary>
  <div><div class="n">${x.title}</div><div class="m">${x.meta}</div></div><span style="margin-left:auto;display:flex;gap:6px;align-items:center">${x.cmp?'<span class="q" title="Includes what changed vs last quarter">vs last qtr</span>':""}${x.chk?`<span class="c" title="Figures not found word-for-word in the transcript">⚠ ${x.chk} to check</span>`:""}${x.tone?`<span class="t ${x.tone}">${x.tone}</span>`:""}</span></summary>
  <div class="b">${x.html}</div></details>`).join("")||'<div class="empty">Nothing matches.</div>'}
["s","q"].forEach(i=>$(i).onchange=draw);$("f").oninput=draw;draw();
</script></body></html>"""


def build_page(open_it=True):
    lib = load_lib()
    items = []
    for o in lib["overviews"].values():
        f = here(o["file"])
        if f.exists():
            t = f.read_text(encoding="utf-8")
            items.append({"ov": 1, "sector": o["sector"], "quarter": o["quarter"], "tone": "",
                          "title": f"{o['sector']} - sector overview", "date": "9999",
                          "meta": f"{o['quarter']} · {len(o['companies'])} companies",
                          "html": mdlib.markdown(t, extensions=["tables"]), "text": t.lower()})
    for c in latest_per_company([c for c in lib["calls"].values() if c.get("summary")]):
        f = here(c["summary"])
        if not f.exists():
            continue
        t = f.read_text(encoding="utf-8")
        t = re.sub(r"^# .*\n(\*Filed.*\*\n)?", "", t)
        t = re.sub(r"\*\*Quarter:\*\*.*\n", "", t)
        t = t.split("\n---\n")[0]  # the figure-check note is shown as a badge instead
        link = c.get("pdf_url", BSE_PDF[0] + c["pdf"])
        bad = c.get("unverified")
        if bad is None:  # summaries made before the check existed
            src = TXT_DIR / f"{c['id']}.txt"
            bad = unverified_numbers(t, src.read_text(encoding="utf-8")) if src.exists() else []
        html = mdlib.markdown(t, extensions=["tables"])
        if bad:
            pat = re.compile(r"(?<![\w.,])(" + "|".join(re.escape(b) for b in bad) + r")(?![\w])")
            html = re.sub(r">([^<]+)<", lambda m: ">" + pat.sub(
                r'<mark title="Not found word-for-word in the transcript - check it">\1</mark>', m.group(1)) + "<",
                html)
            html = (f'<p class="warn">⚠ {len(bad)} figure(s) highlighted below were not found word-for-word in '
                    f'the transcript. They may be calculated by the AI, or misread - check them in the PDF.</p>' + html)
        html += f'<p><a href="{link}" target="_blank">Original transcript (PDF)</a></p>'
        items.append({"ov": 0, "sector": sector_of(lib, c), "quarter": c["quarter"], "tone": c.get("tone", ""),
                      "chk": len(bad), "cmp": bool(c.get("compared")),
                      "title": c["company"], "date": c["date"],
                      "meta": f"{c['quarter']} · {sector_of(lib, c)} · filed {c['date']}",
                      "html": html, "text": (c["company"] + " " + t).lower()})
    items.sort(key=lambda x: (-x["ov"], x["date"]), reverse=False)
    items.sort(key=lambda x: x["ov"], reverse=True)
    data = json.dumps(items, ensure_ascii=False).replace("</", "<\\/")
    PAGE_FILE.write_text(PAGE.replace("__DATA__", data), encoding="utf-8")
    say(f"\nSummaries page: {PAGE_FILE}  ({sum(1 for i in items if not i['ov'])} concalls)")
    if open_it:
        if IS_TABLET:
            open_on_tablet()
        else:
            webbrowser.open(PAGE_FILE.as_uri())


_server = None


def open_on_tablet(page="summaries.html"):
    """Android can't open the page straight from Termux's folder, so serve it locally to Chrome."""
    global _server
    import functools
    import http.server
    port = 8765
    if _server is None:
        class Quiet(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *a):
                pass

        handler = functools.partial(Quiet, directory=str(BASE))
        try:
            _server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
            threading.Thread(target=_server.serve_forever, daemon=True).start()
        except OSError:
            pass  # already running from an earlier session
    url = f"http://127.0.0.1:{port}/{page}"
    say(f"Opening {url} in your browser (works while this menu is open).")
    try:
        subprocess.run(["termux-open-url", url], timeout=10)
    except Exception:
        say(f"Open this address in Chrome: {url}")


# ============================================================================ menu

def latest_call_each(calls):
    best = {}
    for c in calls:
        k = norm(c["company"])
        if k not in best or c["date"] > best[k]["date"]:
            best[k] = c
    return sorted(best.values(), key=lambda c: c["company"])


def choose_and_summarise():
    lib = load_lib()
    if not lib["calls"]:
        say("\nNo transcripts yet - choose 2 first.")
        return
    try:
        pool = Pool()
    except AIError as e:
        say(f"\n{e}")
        return
    say("\nChecking the AI connection first ...")
    try:
        _, ai = pool.ask("Reply with exactly: OK", label="check", max_wait=45)
    except AIError as e:
        say(f"  PROBLEM: {e}\n  Fix this first (option 1 tests it).")
        return
    say(f"  AI connection OK ({ai.model})." + ("" if pool.backup else "  Tip: add a backup AI (README) so runs don't stop when Gemini is busy."))
    say("\nSummarise:\n  1. A whole sector\n  2. Specific companies (search by name)")
    how = ask("Choose", "1")
    compare = ask("Compare each call with the company's previous quarter? "
                  "(first time costs ~1 extra AI call per company) y/n", "y").lower().startswith("y")
    if how == "2":
        q = norm(ask("Part of the company name (e.g. trident)"))
        calls = [c for c in lib["calls"].values() if q and q in norm(c["company"])]
        names = sorted({c["company"] for c in calls})
        if not names:
            say("No company with that name has a transcript in the library.")
            return
        say("Found: " + ", ".join(names))
        if ask("Summarise these? (y/n)", "y").lower() != "y":
            return
        for name in names:
            if not summarise([c for c in calls if c["company"] == name], lib, pool, compare):
                break
    else:
        try:
            classify(lib, pool)
        except AIError as e:
            say(f"  Couldn't sort companies into sectors: {e}")
            return
        groups = {}
        for c in latest_call_each(list(lib["calls"].values())):
            groups.setdefault(sector_of(lib, c), []).append(c)
        names = sorted(groups)
        say("")
        for i, s in enumerate(names, 1):
            done = sum(1 for c in groups[s] if c.get("summary"))
            say(f"  {i:>2}. {s}  ({len(groups[s])} companies, {done} summarised)")
        v = ask("Sector number")
        if not v.isdigit() or not 0 < int(v) <= len(names):
            return
        sector = names[int(v) - 1]
        say("Companies: " + ", ".join(c["company"] for c in groups[sector]))
        calls = [c for c in lib["calls"].values() if sector_of(lib, c) == sector]
        if summarise(calls, lib, pool, compare):
            overview(sector, lib, pool)
    import site_builder
    site_builder.build()
    site_builder.open_site("#concalls")


def menu():
    while True:
        lib = load_lib()
        n = len(lib["calls"])
        s = sum(1 for c in lib["calls"].values() if c.get("summary"))
        say(f"\n=== Concall Summaries ===   library: {n} transcripts, {s} summarised\n"
            " 1. Test the AI connection (10 seconds)\n"
            " 2. Download the latest transcript list from BSE\n"
            " 3. Summarise (a sector or companies)\n"
            " 4. Open the website (news brief + concalls)\n"
            " 5. Build today's news brief (takes 10-20 min)\n"
            " 0. Exit")
        c = ask("Choose", "1" if n == 0 else "3")
        try:
            if c == "1":
                test_ai()
            elif c == "2":
                v = ask("Look back how many days (150 includes last quarter, for comparisons)", "150")
                download_list(int(v) if v.isdigit() else 150)
            elif c == "3":
                choose_and_summarise()
            elif c == "4":
                import site_builder
                site_builder.build()
                site_builder.open_site()
            elif c == "5":
                import news
                news.run()
            elif c == "0":
                return
        except KeyboardInterrupt:
            say("\nStopped. Everything finished so far is saved.")
        except Exception as e:
            say(f"\nError: {e}")


def disable_quickedit():  # a click in the window would otherwise pause the program
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h = k.GetStdHandle(-10)
        mode = ctypes.c_uint32()
        if k.GetConsoleMode(h, ctypes.byref(mode)):
            k.SetConsoleMode(h, (mode.value & ~0x40) | 0x80)
    except Exception:
        pass


def wake_lock(on):  # stops Android pausing Termux during a long run with the screen off
    if IS_TABLET:
        try:
            subprocess.run(["termux-wake-lock" if on else "termux-wake-unlock"], timeout=10)
        except Exception:
            pass


if __name__ == "__main__":
    disable_quickedit()
    wake_lock(True)
    import atexit
    atexit.register(wake_lock, False)
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        test_ai()
    else:
        menu()
