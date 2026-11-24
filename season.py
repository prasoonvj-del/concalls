#!/usr/bin/env python3
"""
Results season or build season - decided from the data, not the calendar.

Results season (mid Jan-Feb, mid Apr-May, mid Jul-Aug, mid Oct-Nov): hundreds of concalls a week; the free AI
allowance goes to summarising them as they come, and quick Lite drafts are the standard.

Build season (the weeks in between): a handful of calls a week, so the same allowance - every free full-quality
model, every day - goes to making the site complete before the next season:
  1. history: the previous quarter's concall for companies that have only one, so every company gets
     "what changed vs last quarter" and "said vs did"
  2. full-quality rewrites of every Lite summary (with the comparison), most-read companies first
  3. every sector and industry overview rewritten with the full model, "where the industry is heading" included
  4. "the story so far" for every concall company, several times faster than in season
  5. management vs market expectations and read-across for the rewritten calls

The switch uses the concall filings of the last 7 days, with a gap between the two thresholds so it doesn't flicker:
build season starts when fewer than 60 were filed, results season when 100 or more.
"""
import datetime as dt
import json

import concalls as C

FILE = C.DATA / "season.json"
ENTER_BUILD, LEAVE_BUILD = 60, 100


def load():
    try:
        return json.loads(FILE.read_text(encoding="utf-8")) if FILE.exists() else {}
    except ValueError:
        return {}


def check(lib=None):
    lib = lib or C.load_lib()
    today = dt.date.today()
    cut = (today - dt.timedelta(days=7)).isoformat()
    n7 = sum(1 for c in lib["calls"].values() if (c.get("date") or "") >= cut)
    old = load()
    mode = old.get("mode", "results")
    if mode == "results" and n7 < ENTER_BUILD:
        mode = "build"
    elif mode == "build" and n7 >= LEAVE_BUILD:
        mode = "results"
    since = old.get("since") if old.get("mode") == mode else today.isoformat()
    s = {"mode": mode, "n7": n7, "since": since or today.isoformat(), "at": dt.datetime.now().isoformat(timespec="minutes")}
    FILE.write_text(json.dumps(s), encoding="utf-8")
    C.BUILD = mode == "build"
    C.say(f"\nSeason: {'BUILD - the free AI allowance goes to completing the site' if C.BUILD else 'results'} "
          f"({n7} concalls filed in the last 7 days; since {s['since']})")
    return mode


def build():
    return getattr(C, "BUILD", None) if getattr(C, "BUILD", None) is not None else load().get("mode") == "build"
