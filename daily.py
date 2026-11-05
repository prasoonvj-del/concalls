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
        "limit": int(c.get("max_concalls_per_run", "30") or 30),
        "compare": c.get("compare_with_last_quarter", "yes").strip().lower() in ("yes", "true", "1", "on"),
    }


def step_news():
    say("\n================ NEWS BRIEF ================")
    news.build()


def step_concalls(conf):
    say("\n================ CONCALLS ================")
    lib = C.load_lib()
    days = conf["first_days"] if not lib["calls"] else conf["days"]
    C.download_list(days)
    lib = C.load_lib()
    try:
        pool = C.Pool()
        pool.ask("Reply with exactly: OK", label="check", max_wait=45)
    except C.AIError as e:
        say(f"AI not available: {e}")
        return
    repair_once(lib)
    C.classify(lib, pool)
    recheck_figures(lib)
    groups = {}
    for c in C.latest_call_each(list(lib["calls"].values())):
        groups.setdefault(C.sector_of(lib, c), []).append(c)
    wanted = [s for s in groups if conf["sectors"] is None or s in conf["sectors"]]

    def pending(sector):
        calls = C.latest_per_company([c for c in lib["calls"].values() if C.sector_of(lib, c) == sector])
        if not calls:
            return 0
        target = max((C.filing_quarter(c) for c in calls), key=C.quarter_key)
        return sum(1 for c in calls if C.filing_quarter(c) == target and not c.get("summary") and not c.get("skip"))

    # real sectors first; the catch-all bucket last
    order = sorted(wanted, key=lambda s: (s == "Services & Others", -pending(s)))
    budget = conf["limit"]
    say(f"Up to {budget} new summaries this run. Pending by sector: "
        + ", ".join(f"{s} {pending(s)}" for s in order if pending(s)) or "none")
    for sector in order:
        if budget <= 0:
            say("\nReached this run's limit - the rest will be done on the next run.")
            break
        if not pending(sector):
            continue
        say(f"\n--- {sector} ---")
        stats = {}
        calls = [c for c in lib["calls"].values() if C.sector_of(lib, c) == sector]
        ok = C.summarise(calls, lib, pool, conf["compare"], limit=budget, stats=stats)
        budget -= max(1, stats.get("done", 0))
        C.overview(sector, lib, pool)
        if not ok:
            say("Stopping concalls for today (AI limit or repeated failures).")
            break
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


def main():
    conf = settings()
    started = time.time()
    for name, enabled, fn in (("news", conf["news"], step_news),
                              ("concalls", conf["concalls"], lambda: step_concalls(conf))):
        if not enabled:
            continue
        try:
            fn()
        except Exception:  # keep going - the site still gets built
            say(f"\n!! The {name} step failed:\n{traceback.format_exc()}")
    say("\n================ WEBSITE ================")
    site_builder.build()
    say(f"\nAll done in {(time.time() - started) / 60:.0f} minutes.")


if __name__ == "__main__":
    main()
