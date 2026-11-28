#!/usr/bin/env python3
"""
Runs everything unattended - on GitHub every morning (see .github/workflows/daily.yml),
or on a laptop/tablet with:  python daily.py

  1. Today's news brief from your feeds (feeds.opml)
  2. New concall transcripts from BSE -> summaries (with last-quarter comparison) -> sector overviews
  3. Rebuild the website (public/)

Each step is independent: if one fails (e.g. BSE is down), the others still run and the site is published.
Settings: the [cloud] section of config.ini. API keys: GEMINI_API_KEY / GROQ_API_KEY (GitHub secrets).
"""
import configparser
import datetime as dt
import os
import time as _t
RUN_START = _t.time()  # the workflow step is stopped at 75 minutes - everything here finishes well before
import re
import time
import traceback

import concalls as C
import news
import site_builder

say = C.say


def settings():
    cp = configparser.ConfigParser()
    cp.read(C.CONFIG_FILE, encoding="utf-8")
    c = cp["cloud"] if cp.has_section("cloud") else {}
    sectors = c.get("concall_sectors", "all").strip()
    return {
        "news": c.get("news", "yes").strip().lower() in ("yes", "true", "1", "on"),
        "concalls": c.get("concalls", "yes").strip().lower() in ("yes", "true", "1", "on"),
        "days": int(c.get("concall_days", "7") or 7),
        "first_days": int(c.get("first_run_days", "150") or 150),
        "sectors": None if sectors.lower() == "all" else [x.strip() for x in sectors.split(",") if x.strip()],
        # a Mistral key adds a whole second daily allowance, so more concalls fit in a run
        "limit": int(c.get("max_concalls_per_run", "60") or 60) + (30 if any(os.environ.get(k, "").strip() for k in ("MISTRAL_API_KEY", "SAMBANOVA_API_KEY")) else 0),
        # all = every company; watchlist = only those (others compare once last quarter is summarised anyway)
        "compare": {"yes": "all", "true": "all", "no": "none", "false": "none"}.get(
            c.get("compare_with_last_quarter", "watchlist").strip().lower(),
            c.get("compare_with_last_quarter", "watchlist").strip().lower()),
        "backfill": int(c.get("metrics_backfill_per_run", "60") or 60),
        # stop starting new concall work after this many minutes, so the site always publishes promptly
        "minutes": int(c.get("max_concall_minutes", "30") or 30),
    }


def step_news():
    say("\n================ NEWS BRIEF ================")
    news.build()
    try:
        say("\nInvestor presentations filed on BSE ...")
        C.fetch_presentations()
    except Exception as e:  # BSE is sometimes slow - the news brief is already saved
        say(f"  presentations skipped this time: {str(e)[:150]}")
    try:
        import directory
        directory.update()
        directory.refresh_sectors()
    except Exception as e:
        say(f"  company directory skipped: {str(e)[:120]}")
    say("\nPrices, results calendar, week in review ...")
    import trackers
    trackers.step()


def watchlist():
    cp = configparser.ConfigParser()
    cp.read(C.CONFIG_FILE, encoding="utf-8")
    raw = cp.get("cloud", "watchlist", fallback="") or cp.get("news", "watchlist", fallback="")
    return [w.strip().lower() for w in raw.split(",") if w.strip()]


def plan_concalls(lib, conf):
    """Which calls to summarise this run: each company's LATEST call, your watchlist first,
    then sectors take turns (round-robin) so no single sector uses up the run."""
    watch = watchlist()
    is_watch = lambda c: any(w in c["company"].lower() for w in watch)
    latest = [c for c in C.latest_call_each(list(lib["calls"].values()))
              if not c.get("summary") and not c.get("skip")]
    if conf["sectors"] is not None:
        latest = [c for c in latest if C.sector_of(lib, c) in conf["sectors"] or is_watch(c)]
    first = sorted([c for c in latest if is_watch(c)], key=lambda c: c["date"], reverse=True)
    queues = {}
    for c in sorted((c for c in latest if not is_watch(c)), key=lambda c: c["date"], reverse=True):
        queues.setdefault(C.sector_of(lib, c), []).append(c)  # newest calls first within a sector
    order = sorted(queues, key=lambda s: (s in ("Services & Others", "Unsorted"), -len(queues[s])))
    turns = []
    while any(queues[s] for s in order):
        for s in order:
            if queues[s]:
                turns.append(queues[s].pop(0))
    return first + turns, is_watch


def concall_requests():
    """'Summarise its latest concall' from the website = a GitHub issue titled "Concall: <BSE code> <name>"."""
    import re
    import backstory
    asked = {}
    for it in backstory._gh("GET", "/issues", params={"state": "open", "per_page": 50}) or []:
        if (it.get("user") or {}).get("login", "") != os.environ.get("GITHUB_REPOSITORY_OWNER", "prasoonvj-del"):
            continue  # only the owner's requests spend the AI allowance
        m = re.match(r"\s*concall:\s*(\d{5,6})", it.get("title", ""), re.I)
        if m and "pull_request" not in it:
            asked.setdefault(m.group(1), []).append(it["number"])
    if not asked:
        return
    say(f"\nConcall summaries requested from the website: {', '.join(asked)}")
    pool = C.Pool()
    try:
        import directory
        dr = directory.load()
    except Exception:
        dr = {}
    for code, nums in asked.items():
        C.transcripts_for(code)
        lib = C.load_lib()
        if not lib["sectors"].get(code) and (dr.get(code) or {}).get("s"):
            lib["sectors"][code] = dr[code]["s"]
            C.save_lib(lib)
        calls = sorted([c for c in lib["calls"].values() if c["code"] == code], key=lambda c: c["date"])
        if not calls:
            msg = "No earnings-call transcript from this company on BSE in the last ~7 months."
        else:
            c = calls[-1]
            if not c.get("summary"):
                prev = C.find_prev(lib, c)
                try:
                    C.summarise_one(c, lib, pool, prev if prev and prev.get("summary") else None)
                    msg = f"Done - the {c['quarter']} concall of {c['company']} is summarised on the website after this update."
                except C.AIError as e:
                    msg = f"Couldn't summarise it this time ({str(e)[:120]}) - it stays in the queue."
            else:
                msg = f"The {c['quarter']} concall of {c['company']} was already summarised - it's on the website."
        for n in nums:
            backstory._gh("POST", f"/issues/{n}/comments", json={"body": msg})
            backstory._gh("PATCH", f"/issues/{n}", json={"state": "closed"})


def is_draft(call):
    """Written by a Lite model (or unknown) - to be redone by a full model."""
    m = (call.get("model") or "").lower()
    return bool(call.get("summary")) and (not m or "lite" in m)


def importance():
    """code -> sort key: watchlist first, then the bigger companies (market cap), so the most-read pages improve first."""
    try:
        import fundamentals
        F = fundamentals.load()
    except Exception:
        F = {}
    return lambda c: -((F.get(str(c.get("code"))) or {}).get("mcap") or 0)


def backfill_history(lib, deadline, limit=15):
    """Build season: companies with only one concall on file get the previous quarter's (found on BSE, summarised
    on the cheap model - it is the reference point), so their latest call can be rewritten with "what changed"
    and "said vs did". Returns the library (reloaded: the BSE lookup saves its own copy)."""
    watch = watchlist()
    calls = [c for c in lib["calls"].values() if c.get("summary")]
    have = {}
    for c in calls:
        have.setdefault(c["code"], set()).add(C.filing_quarter(c))
    tried = lib.setdefault("hist_tried", {})
    latest = C.latest_per_company(calls)
    key = importance()
    todo = [c for c in latest if len(have.get(c["code"], ())) == 1 and c["code"] not in tried and str(c["code"]).isdigit()]
    todo.sort(key=lambda c: (not any(w in c["company"].lower() for w in watch), key(c)))
    if not todo:
        return lib
    say(f"\nHistory: previous-quarter concalls for companies with only one on file ({len(todo)} waiting) ...")
    pool, done = C.Pool(bulk=True), 0
    for c in todo[:limit]:
        if time.time() > deadline:
            break
        lib["hist_tried"][c["code"]] = dt.date.today().isoformat()
        C.save_lib(lib)
        try:
            C.transcripts_for(c["code"], days=230)
        except Exception as e:
            say(f"  {c['company']}: BSE lookup failed ({str(e)[:60]})")
        lib = C.load_lib()
        pq = C.prev_quarter(C.filing_quarter(c))
        prev = [x for x in lib["calls"].values() if x["code"] == c["code"] and C.filing_quarter(x) == pq and not x.get("summary")]
        if not prev:
            continue
        p = max(prev, key=lambda x: x["date"])
        say(f"  [{done + 1}] {c['company']}: {pq} concall")
        try:
            C.summarise_one(p, lib, pool, None)
            done += 1
            cur = lib["calls"].get(c["id"])
            if cur:
                cur["compared"] = False  # now it has something to compare with: rewritten next
        except C.AIError as e:
            say(f"    skipped ({str(e)[:80]})")
        C.save_lib(lib)
        time.sleep(pool.pause)
    say(f"  history: {done} earlier-quarter summaries added")
    return lib


def build_step(stop):
    """Build season, news-only runs: history, full-quality rewrites and overviews - the day's allowance is used,
    not left idle between the two full runs."""
    lib = backfill_history(C.load_lib(), min(stop, RUN_START + 18 * 60), limit=10)
    qpool = C.Pool(quality=True)
    touched = upgrade_summaries(lib, qpool, min(stop - 12 * 60, _t.time() + 20 * 60), build=True)
    lib = C.load_lib()
    import direction
    due = sorted(touched) + sorted({o["sector"] for o in lib.get("overviews", {}).values() if not o.get("industry")
                                    and ("lite" in (o.get("model") or "lite") or o.get("dir_v", 0) < direction.DIR_V)})
    for sector in list(dict.fromkeys(due))[:6]:
        if _t.time() > stop - 8 * 60:
            break
        try:
            C.overview(sector, lib, qpool)
        except C.QuotaOver:
            return
        except C.AIError as e:
            say(f"    overview {sector}: {str(e)[:80]}")
    try:
        import industries
        if _t.time() < stop - 5 * 60:
            industries.overviews(lib, qpool, set(), limit=10)
    except C.QuotaOver:
        pass
    except Exception as e:
        say(f"  industry overviews skipped: {str(e)[:100]}")


def upgrade_summaries(lib, qpool, deadline, build=False):
    """Quality over speed: rewrite quick drafts with a full Gemini model, most useful first - watchlist,
    then large companies, then the newest calls. Stops when today's full-quality allowance is used;
    tomorrow carries on. Returns the sectors whose overviews should be refreshed."""
    import readacross
    watch = watchlist()
    latest = {c["code"]: c for c in C.latest_call_each(list(lib["calls"].values()))}
    todo = [c for c in latest.values() if is_draft(c) and not c.get("skip")]
    try:  # Market Desk's own early-signal shortlist: the summaries most likely to be opened next
        import highlights
        H = highlights.load()
        hot = {x["key"] for v in (H.get("short") or {}).values() for x in v}
    except Exception:
        hot = set()
    # Lite summaries are the standard; the full model only rewrites what is read most: the watchlist and Market
    # Desk's early-signal shortlist (the Top 10 is picked from it)
    mine = lambda c: any(w in c["company"].lower() for w in watch)
    if build:  # build season: every draft, and every call that now has a previous quarter to compare with
        def stale(c):
            prev = C.find_prev(lib, c)
            return bool(prev and prev.get("summary") and not c.get("compared"))
        todo = [c for c in latest.values() if not c.get("skip") and (is_draft(c) or stale(c))]
        key = importance()
        prio = lambda c: (not mine(c), c.get("code") not in hot, key(c))
    else:
        todo = [c for c in todo if mine(c) or c.get("code") in hot]
        prio = lambda c: (not mine(c), c.get("code") not in hot, -int(c["date"].replace("-", "")))
    todo.sort(key=prio)
    if not todo:
        return set()
    say(f"\nFull-quality rewrite of quick drafts: {len(todo)} waiting "
        f"({'build season: all of them, biggest companies first' if build else 'watchlist, then the Top 10 shortlist'}) ...")
    touched, done, busy = set(), 0, 0
    for c in todo:
        if time.time() > deadline:
            break
        old = (c.get("summary"), c.get("model"))
        prev = C.find_prev(lib, c)
        say(f"  [{done + 1}] {c['company']} ({c.get('quarter', '')}, draft by {old[1] or '?'})")
        try:
            C.summarise_one(c, lib, qpool, prev if prev and prev.get("summary") else None)
        except C.QuotaOver as e:
            say(f"  stopping: no full-quality model left today ({str(e)[:80]}) - the rest continue tomorrow")
            break
        except C.AIError as e:
            # Google's servers busy (503s) is not the end of the day's allowance: wait and try again
            busy += 1
            if busy > 1 or time.time() + 120 > deadline:  # one wait; a second "overloaded" means try next run
                say(f"  stopping for this run: models busy ({str(e)[:80]}) - the rest continue next run")
                break
            say(f"  models busy ({str(e)[:60]}) - waiting 90s and trying again")
            time.sleep(90)
            continue
        if old[0] and old[0] != c.get("summary"):
            try:
                (C.BASE / old[0]).unlink()
            except Exception:
                pass
        c.pop("expect", None)
        c.pop("delivery", None)
        try:  # its read-across signals are redone from the better summary
            d = readacross.load()
            if d["done"].pop(c["id"], None):
                d["items"] = [x for x in d["items"] if x.get("src_code") != c["code"] or x["date"] != c["date"]]
                readacross.save(d)
        except Exception:
            pass
        touched.add(C.sector_of(lib, c))
        done += 1
        C.save_lib(lib)
        time.sleep(qpool.pause)
    say(f"  rewrote {done} with a full model; {len(todo) - done} still to go")
    return touched


def step_concalls(conf):
    say("\n================ CONCALLS ================")
    lib = C.load_lib()
    days = conf["first_days"] if not lib["calls"] else conf["days"]
    if lib["calls"] and not lib.get("rescan_meet"):  # once: transcripts filed as "Analyst / Investor Meet"
        days = conf["first_days"]
    ok = True
    try:
        C.download_list(days)
    except Exception as e:  # BSE hiccup: still summarise/sort what we already have
        ok = False
        say(f"  BSE list download failed this time ({str(e)[:120]}) - carrying on with the library")
    lib = C.load_lib()
    if ok and not lib.get("rescan_meet"):
        lib["rescan_meet"] = True
        C.save_lib(lib)
    try:
        pool = C.Pool(bulk=True)  # quick drafts on Flash-Lite; full-quality versions follow in upgrade_summaries()
        pool.ask("Reply with exactly: OK", label="check", max_wait=45)
        qpool = C.Pool(quality=True)
    except C.AIError as e:
        say(f"AI not available: {e}")
        return
    repair_once(lib)
    C.classify(lib, pool)
    try:
        import industries
        industries.classify(lib, C.Pool(bulk=True))
        lib = C.load_lib()
        # (sector overviews are refreshed after the summaries, with a full-quality model only)
    except Exception as e:
        say(f"  industry sorting skipped: {str(e)[:120]}")
    recheck_figures(lib)
    queue, is_watch = plan_concalls(lib, conf)
    budget = conf["limit"]
    deadline = min(time.time() + conf["minutes"] * 60, RUN_START + 52 * 60)
    say(f"\n{len(queue)} companies have a call without a summary. Doing up to {budget} AI summaries this run "
        f"(watchlist first, then sectors in turn).")
    touched, fails, done = set(), 0, 0
    # your watchlist and the ~150 largest companies: the full-quality version straight away (up to 12 a run);
    # everyone else gets the quick draft now and the fuller version later
    try:
        import fundamentals
        F = fundamentals.load()
        caps = sorted(((v.get("mcap") or 0), k) for k, v in F.items() if isinstance(v, dict))
        bigco = {k for _, k in caps[-150:]}
    except Exception:
        bigco = set()
    first_full = 0
    for c in queue:
        if budget <= 0:
            say("\nReached this run's limit - the rest continue on the next run.")
            break
        if time.time() > deadline:
            say(f"\nTime limit ({conf['minutes']} min) reached - the rest continue on the next run.")
            break
        compare = conf["compare"] == "all" or (conf["compare"] == "watchlist" and is_watch(c))
        prev = C.find_prev(lib, c)
        say(f"\n[{done + 1}] {c['company']}  ({C.sector_of(lib, c)}, filed {c['date']})")
        try:
            if compare and prev and not prev.get("summary") and not prev.get("skip"):
                say(f"    first, last quarter's call (filed {prev['date']}) ...")
                C.summarise_one(prev, lib, pool)
                budget -= 1
                time.sleep(pool.pause)
            # compare whenever last quarter's summary already exists (costs nothing extra)
            use = pool
            if first_full < 12 and (is_watch(c) or str(c.get("code")) in bigco):
                use = qpool
            try:
                C.summarise_one(c, lib, use, prev if prev and prev.get("summary") else None)
                first_full += use is qpool
            except C.AIError:
                if use is pool:
                    raise
                say("    full-quality writers busy - quick draft now, the fuller version follows later")
                C.summarise_one(c, lib, pool, prev if prev and prev.get("summary") else None)
            budget -= 1
            done += 1
            fails = 0
            touched.add(C.sector_of(lib, c))
        except C.QuotaOver as e:
            say(f"\n{e}")
            break
        except C.AIError as e:
            say(f"    failed: {e}")
            fails += 1
            budget -= 1
            if fails >= 3:
                say("Stopping concalls for this run (AI failing repeatedly).")
                break
        time.sleep(pool.pause)
    touched_ind = set()
    import season
    build = season.build()
    if build:  # build season: earlier quarters first, so the rewrites below can compare
        lib = backfill_history(lib, min(deadline, RUN_START + 20 * 60), limit=20)
    touched |= upgrade_summaries(lib, qpool, deadline, build=build)
    # overviews written by a Lite model earlier: a few each run get a full-quality rewrite
    lite_ov = sorted({o["sector"] for o in lib.get("overviews", {}).values()
                      if not o.get("industry") and "lite" in (o.get("model") or "lite")} - touched)[:8 if build else 3]
    # and a couple without "where the industry is heading" yet (oldest written first)
    import direction
    latest_ov = {}
    for o in lib.get("overviews", {}).values():
        if not o.get("industry") and C.quarter_key(o["quarter"]) >= C.quarter_key(latest_ov.get(o["sector"], {}).get("quarter", "Q1 FY00")):
            latest_ov[o["sector"]] = o
    lite_ov += [s for s, o in sorted(latest_ov.items(), key=lambda x: x[1].get("at", ""))
                if o.get("dir_v", 0) < direction.DIR_V and s not in touched and s not in lite_ov][:8 if build else 2]
    # sectors whose overview is due: carried over between runs, so a sector skipped for time isn't forgotten
    due = sorted(set(lib.get("ov_pending", [])) | touched) + lite_ov
    hard = RUN_START + 56 * 60  # the website and the timeline still need their minutes
    left = list(due)
    for sector in due:
        if time.time() + 5 * 60 > hard:  # one overview can take several minutes with the full-quality writer
            say(f"    overviews: out of time - {len(left)} wait for the next run")
            break
        try:
            if C.overview(sector, lib, qpool) is not None:  # None = due, but redone in a few days
                left.remove(sector)
        except C.QuotaOver as e:
            say(f"    overviews wait for a full-quality model (none left today): {str(e)[:80]}")
            break
        except C.AIError as e:
            say(f"    overview waits for a full-quality model: {str(e)[:80]}")
            left.remove(sector)
            left.append(sector)
    lib["ov_pending"] = [x for x in dict.fromkeys(left) if x not in lite_ov]
    C.save_lib(lib)
    try:
        import industries
        touched_ind = {industries.industry_of(lib, c) for c in lib["calls"].values() if C.sector_of(lib, c) in touched}
        if time.time() < min(deadline, hard - 4 * 60):
            industries.overviews(lib, qpool, touched_ind, limit=20 if build else 8)
        if time.time() < min(deadline, hard - 6 * 60):  # coverage: drafts where there is nothing yet
            industries.draft_overviews(lib, C.Pool(bulk=True), limit=6, deadline=min(deadline, hard - 3 * 60))
    except Exception as e:
        say(f"  industry overviews skipped: {str(e)[:120]}")
    late = time.time() > RUN_START + 58 * 60  # leave the last minutes for the timeline and the website
    try:  # management vs market expectations, said vs did
        import expect
        if time.time() < deadline and not late:
            expect.step(lib, qpool, limit=80, deadline=deadline)
    except Exception as e:
        say(f"  expectations skipped: {str(e)[:120]}")
    try:  # read-across: what big companies' calls signal for smaller listed players
        import readacross
        if time.time() < deadline and not late:
            readacross.step(lib, qpool, limit=24, deadline=deadline)
        if not late:
            readacross.outcomes()
    except Exception as e:
        say(f"  read-across skipped: {str(e)[:120]}")
    if time.time() < deadline:
        backfill_metrics(lib, pool, conf["backfill"], deadline)


METRICS_PROMPT = """For each company summary below, copy the key figures into a metrics block. Use ONLY numbers
stated in that summary (no units, no % sign, no commas); write na when not stated or not applicable.
Growth is year-on-year; net debt negative means net cash. Reply with one block per company, exactly:

### <id>
```metrics
""" + "\n".join(f"{k}:" for k in C.METRIC_KEYS) + """
guidance: <raised / cut / maintained / initiated / none>
```

SUMMARIES:
"""


def backfill_metrics(lib, pool, limit, deadline=None):
    """Adds peer-comparison figures to summaries written before metrics existed (3 per request)."""
    todo = [c for c in lib["calls"].values() if c.get("summary") and "metrics" not in c][:limit]
    if not todo:
        return
    say(f"\nAdding peer-comparison figures to {len(todo)} earlier summaries ...")
    for i in range(0, len(todo), 3):
        if deadline and time.time() > deadline:
            say("    time limit reached - continuing next run")
            break
        batch = todo[i:i + 3]
        body = ""
        for c in batch:
            f = C.here(c["summary"])
            if f.exists():
                body += f"\n=== id {c['id']} - {c['company']} ===\n" + f.read_text(encoding="utf-8").split("\n---\n")[0]
        try:
            text, _ = pool.ask(METRICS_PROMPT + body, label=f"figures {i + 1}-{i + len(batch)}")
        except C.AIError as e:
            say(f"    stopped: {e}")
            break
        for block in re.split(r"^###\s*", text, flags=re.M):
            cid = block.split("\n", 1)[0].strip().removeprefix("id").strip(" -")
            hit = next((c for c in batch if c["id"] == cid or cid.startswith(c["id"])), None)
            m, _ = C.parse_metrics(block)
            if hit and m:
                hit["metrics"] = m
        C.save_lib(lib)
        time.sleep(pool.pause)


def repair_once(lib):
    """Fixes from the first cloud run: re-sort companies that a failed AI batch dumped into
    'Services & Others', and re-check figures with the improved checker."""
    if lib.get("repair_v2"):
        return
    n = sum(1 for v in lib["sectors"].values() if v == "Services & Others")
    lib["sectors"] = {k: v for k, v in lib["sectors"].items() if v != "Services & Others"}
    lib["overviews"] = {k: v for k, v in lib["overviews"].items() if not k.startswith("Services & Others|")}
    for c in lib["calls"].values():
        c.pop("unverified", None)
    lib["repair_v2"] = True
    C.save_lib(lib)
    say(f"One-time repair: re-sorting {n} companies, re-checking figures in existing summaries.")


def recheck_figures(lib):
    """Re-runs the figure check on summaries that don't have one (re-downloads transcripts as needed)."""
    todo = [c for c in lib["calls"].values() if c.get("summary") and c.get("unverified") is None]
    if not todo:
        return
    say(f"Re-checking figures in {len(todo)} summaries ...")
    for c in todo:
        f = C.here(c["summary"])
        text, problem = C.get_text(c)
        if problem or not f.exists():
            continue
        source = text
        if c.get("compared"):
            prev = C.find_prev(lib, c)
            if prev:
                ptext, _ = C.get_text(prev)
                source += "\n" + (ptext or "")
        summary = f.read_text(encoding="utf-8").split("\n---\n")[0]
        c["unverified"] = C.unverified_numbers(summary, source)
    C.save_lib(lib)
    say("  done.")


def report_ai():
    """Which AI providers this run can use (names only - never the keys)."""
    for section, label in (("ai", "Main AI"), ("backup", "Backup AI")):
        try:
            ai = C.AI(section)
            say(f"{label}: {ai.provider} ({ai.url.split('/')[2]})")
        except C.AIError as e:
            say(f"{label}: not set up ({e})")


def main():
    import sys
    conf = settings()
    report_ai()
    if "--news-only" in sys.argv:
        conf["concalls"] = False
    if "--concalls-only" in sys.argv:
        conf["news"] = False
    if "--site-only" in sys.argv:  # started again soon after an update: just rebuild the pages
        conf["news"] = conf["concalls"] = False
    story_only = "--story-only" in sys.argv  # a company was requested on the website
    if story_only:
        conf["news"] = conf["concalls"] = False
        try:
            concall_requests()
        except Exception:
            say(f"\n!! Concall request failed:\n{traceback.format_exc()}")
        try:
            import backstory
            backstory.step("request")
        except Exception:
            say(f"\n!! 'Story so far' failed:\n{traceback.format_exc()}")
    try:
        import season
        season.check()
    except Exception as e:
        say(f"  season check skipped: {str(e)[:100]}")
    started = time.time()
    for name, enabled, fn in (("news", conf["news"], step_news),
                              ("concalls", conf["concalls"], lambda: step_concalls(conf))):
        if not enabled:
            continue
        try:
            fn()
        except Exception:  # keep going - the site still gets built
            say(f"\n!! The {name} step failed:\n{traceback.format_exc()}")
        if name == "news":
            try:  # analysis & deep dives: newsletters, analysts, sector outlooks - sorted by the cheap model
                import analysis
                analysis.step(deadline=min(_t.time() + 300, RUN_START + 45 * 60))
            except Exception:
                say(f"\n!! Analysis & deep dives failed:\n{traceback.format_exc()}")
            try:  # top 10 developments: once a day, one full-model request, before the rewrites use the allowance
                import highlights
                if _t.time() < RUN_START + 40 * 60:
                    highlights.step()
            except Exception:
                say(f"\n!! Top developments failed:\n{traceback.format_exc()}")
    if conf["news"] or conf["concalls"]:
        try:  # requests from the website that a busy queue may have pushed out of their own run
            concall_requests()
        except Exception:
            say(f"\n!! Concall request failed:\n{traceback.format_exc()}")
        try:
            import decks
            if _t.time() > RUN_START + 60 * 60:
                raise RuntimeError("out of time this run - decks continue next run")
            decks.step(C.Pool(bulk=True), "full" if conf["concalls"] else "news")
        except Exception:
            say(f"\n!! Deck summaries failed:\n{traceback.format_exc()}")
        try:
            import backstory
            if _t.time() > RUN_START + 60 * 60:
                raise RuntimeError("out of time this run")
            import season
            backstory.step(("build-full" if conf["concalls"] else "build-news") if season.build()
                           else ("full" if conf["concalls"] else "news"), hard_stop=RUN_START + 66 * 60)  # the step itself stops at 75
        except Exception:
            say(f"\n!! 'Story so far' failed:\n{traceback.format_exc()}")
        if not conf["concalls"]:
            stop = RUN_START + 52 * 60  # news runs: AI extras only while time is left
            try:
                import industries
                if _t.time() > stop - 6 * 60:
                    raise RuntimeError("out of time this run")
                industries.classify(C.load_lib(), C.Pool(bulk=True), limit=200, minutes=4)
            except Exception as e:
                say(f"  industry sorting skipped: {str(e)[:120]}")
            try:  # leftover full-quality requests go to rewriting drafts first
                import season
                if season.build() and _t.time() < RUN_START + 30 * 60:
                    build_step(stop)  # build season: history, rewrites and overviews in every run
                elif _t.time() < RUN_START + 40 * 60:
                    upgrade_summaries(C.load_lib(), C.Pool(quality=True), _t.time() + 8 * 60)
            except Exception as e:
                say(f"  full-quality rewrite skipped: {str(e)[:120]}")
            try:
                import expect
                if _t.time() > stop:
                    raise RuntimeError("out of time this run")
                expect.step(C.load_lib(), C.Pool(quality=True), limit=24, deadline=stop)
            except Exception as e:
                say(f"  expectations skipped: {str(e)[:120]}")
            try:
                import readacross
                if _t.time() > stop:
                    raise RuntimeError("out of time this run")
                readacross.step(C.load_lib(), C.Pool(quality=True), limit=8, deadline=stop)
            except Exception as e:
                say(f"  read-across skipped: {str(e)[:120]}")
        try:
            import pivot_sources
            if _t.time() > RUN_START + 62 * 60:
                raise RuntimeError("out of time this run")
            pivot_sources.step(C.Pool(bulk=True), "full" if conf["concalls"] else "news")
        except Exception:
            say(f"\n!! Pivots from summaries failed:\n{traceback.format_exc()}")
    try:
        import directory
        directory.refresh_sectors()
    except Exception:
        pass
    try:
        import watch
        watch.keep_policy()
    except Exception as e:
        say(f"  follow-through: {str(e)[:120]}")
    try:  # summaries' figures vs units in the transcript and the company's BSE-filed quarter (no AI)
        import checks
        checks.step(C.load_lib(), budget_dl=25, deadline=time.time() + 240)
    except Exception:
        say(f"\n!! Figure checks failed:\n{traceback.format_exc()}")
    try:
        import timeline
        timeline.update()
    except Exception:
        say(f"\n!! Company timelines failed:\n{traceback.format_exc()}")
    say("\n================ WEBSITE ================")
    site_builder.build()
    say(f"\nAll done in {(time.time() - started) / 60:.0f} minutes.")


if __name__ == "__main__":
    main()
