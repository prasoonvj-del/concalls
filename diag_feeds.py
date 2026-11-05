"""One-off test: which routes can reach feeds that block cloud servers? Writes data/diag.log"""
import json, urllib.parse, requests
try:
    from curl_cffi import requests as cffi
except ImportError:
    cffi = None
FEEDS = ["https://filtercoffee.substack.com/feed", "https://nitishastra.substack.com/feed",
         "https://indianexpress.com/section/business/market/feed/"]
UA = {"User-Agent": "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 Chrome/130.0 Mobile Safari/537.36"}
q = urllib.parse.quote
routes = {
    "direct": lambda u: requests.get(u, headers=UA, timeout=25),
    "curl_cffi": lambda u: cffi.get(u, impersonate="chrome", timeout=25),
    "rss2json": lambda u: requests.get("https://api.rss2json.com/v1/api.json?rss_url=" + q(u, safe=""), timeout=25),
    "jina": lambda u: requests.get("https://r.jina.ai/" + u, headers={"X-Return-Format": "text"}, timeout=40),
    "allorigins": lambda u: requests.get("https://api.allorigins.win/raw?url=" + q(u, safe=""), timeout=40),
    "corsproxy": lambda u: requests.get("https://corsproxy.io/?url=" + q(u, safe=""), timeout=40),
    "codetabs": lambda u: requests.get("https://api.codetabs.com/v1/proxy/?quest=" + q(u, safe=""), timeout=40),
    "substack_api": lambda u: (cffi or requests).get(u.replace("/feed", "/api/v1/archive?sort=new&limit=5"), timeout=25,
                                                    **({"impersonate": "chrome"} if cffi else {})),
}
out = []
for u in FEEDS:
    for name, fn in routes.items():
        if name == "substack_api" and "substack" not in u:
            continue
        try:
            r = fn(u)
            body = r.text[:160].replace("\n", " ")
            ok = r.status_code == 200 and ("<item" in r.text or '"items"' in r.text or '"title"' in r.text or "Title:" in r.text)
            out.append(f"{'OK  ' if ok else 'FAIL'} {name:<13} {r.status_code} {len(r.content):>7}b  {u[:45]}  | {body}")
        except Exception as e:
            out.append(f"ERR  {name:<13} {type(e).__name__}: {str(e)[:80]}  {u[:45]}")
open("data/diag.log", "w").write("\n".join(out) + "\n")
print("\n".join(out))
