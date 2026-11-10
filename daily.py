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
import os
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
        pool = C.Pool()
        pool.ask("Reply with exactly: OK", label="check", max_wait=45)
    except C.AIError as e:
        say(f"AI not available: {e}")
        return
    repair_once(lib)
    C.classify(lib, pool)
    try:
        import industries
        industries.classify(lib, C.Pool(bulk=True))
        lib = C.load_lib()
        # sectors whose line-up changed (companies moved by the industry sorting) get a fresh overview
        redo = 0
        for sector in C.SECTORS:
            if redo >= 5:
                break
            if C.overview(sector, lib, pool):
                redo += 1
    except Exception as e:
        say(f"  industry sorting skipped: {str(e)[:120]}")
    recheck_figures(lib)
    queue, is_watch = plan_concalls(lib, conf)
    budget = conf["limit"]
    deadline = time.time() + conf["minutes"] * 60
    say(f"\n{len(queue)} companies have a call without a summary. Doing up to {budget} AI summaries this run "
        f"(watchlist first, then sectors in turn).")
    touched, fails, done = set(), 0, 0
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
    for sector in sorted(touched):
        try:
            C.overview(sector, lib, pool)
        except C.AIError as e:
            say(f"    overview failed: {e}")
    try:
        import industries
        touched_ind = {industries.industry_of(lib, c) for c in lib["calls"].values() if C.sector_of(lib, c) in touched}
        if time.time() < deadline:
            industries.overviews(lib, pool, touched_ind, limit=8)
    except Exception as e:
        say(f"  industry overviews skipped: {str(e)[:120]}")
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
    started = time.time()
    for name, enabled, fn in (("news", conf["news"], step_news),
                              ("concalls", conf["concalls"], lambda: step_concalls(conf))):
        if not enabled:
            continue
        try:
            fn()
        except Exception:  # keep going - the site still gets built
            say(f"\n!! The {name} step failed:\n{traceback.format_exc()}")
    if conf["news"] or conf["concalls"]:
        try:  # requests from the website that a busy queue may have pushed out of their own run
            concall_requests()
        except Exception:
            say(f"\n!! Concall request failed:\n{traceback.format_exc()}")
        try:
            import decks
            decks.step(C.Pool(bulk=True), "full" if conf["concalls"] else "news")
        except Exception:
            say(f"\n!! Deck summaries failed:\n{traceback.format_exc()}")
        try:
            import backstory
            backstory.step("full" if conf["concalls"] else "news")
        except Exception:
            say(f"\n!! 'Story so far' failed:\n{traceback.format_exc()}")
        if not conf["concalls"]:
            try:
                import industries
                industries.classify(C.load_lib(), C.Pool(bulk=True), limit=200, minutes=4)
            except Exception as e:
                say(f"  industry sorting skipped: {str(e)[:120]}")
        try:
            import pivot_sources
            pivot_sources.step(C.Pool(bulk=True), "full" if conf["concalls"] else "news")
        except Exception:
            say(f"\n!! Pivots from summaries failed:\n{traceback.format_exc()}")
    try:
        import directory
        directory.refresh_sectors()
    except Exception:
        pass
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
