#!/usr/bin/env python3
"""Freshness check: is every input current enough to project this week?

    python check_freshness.py --year 2026 --week 7            # before a run / lock
    python check_freshness.py --year 2026 --week 7 --lock     # stricter: lock-time

Built 2026-10-24 after the roster-status file sat at week 2 for five weeks
without anyone noticing (Jordan Mason still "on reserve" after being
designated to return). Every input the model reads is checked against the
week being projected; anything STALE stops the run (exit code 1) and says
which file and why, so a stale file is never silently projected. WARN is
printed but does not stop the run.

Checks:
  player stats / snaps / play-by-play   every game of last week that has a
                                        final score is in the file
  weekly rosters                        covers last week or later
  injury report                         this week's rows exist once the
                                        week's first game is 5 days away or less
  depth charts                          newest snapshot under 8 days old
  games + lines                         every game this week has a spread and total
  Sleeper snapshot                      today's (or yesterday's, outside --lock)
  news feed                             newest item under 2 days old
  site projections (consensus archive)  this week's folder exists; at lock
                                        time it must be from today
  ETR                                   WARN only -- Joe's download
"""

import argparse
import collections
import csv
import datetime
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
ROOT = os.path.dirname(HERE)
UTIL = os.path.join(ROOT, "ff_utilization", "cached", "nflverse")
SLEEPER = os.path.join(ROOT, "ff_projections", "cached", "sleeper")
WEEKLY = os.path.join(ROOT, "ff_weekly_proj", "weekly")


def _rows(path):
    with open(path, newline="", encoding="utf-8") as fh:
        yield from csv.DictReader(fh)


def check(year, week, lock=False, today=None):
    """-> list of (level, input, message); level is OK / WARN / STALE."""
    today = today or datetime.date.today()
    out = []
    ok = lambda name, msg: out.append(("OK", name, msg))
    warn = lambda name, msg: out.append(("WARN", name, msg))
    stale = lambda name, msg: out.append(("STALE", name, msg))

    # the schedule: last week's finished games, this week's lines
    games = [r for r in _rows(os.path.join(DATA, "games.csv"))
             if r["season"] == str(year) and r["game_type"] == "REG"]
    done_prev = {t for r in games if r["week"] == str(week - 1) and r["home_score"]
                 for t in (r["home_team"], r["away_team"])}
    this_wk = [r for r in games if r["week"] == str(week)]
    first_day = min((datetime.date.fromisoformat(r["gameday"]) for r in this_wk), default=today)
    no_line = [f"{r['away_team']}@{r['home_team']}" for r in this_wk
               if not r["spread_line"] or not r["total_line"]]
    if not this_wk:
        stale("games + lines", f"no week {week} games in games.csv")
    elif no_line:
        (stale if lock else warn)("games + lines", f"no betting line yet: {', '.join(no_line)}")
    else:
        ok("games + lines", f"{len(this_wk)} games, all with lines")

    # last week's box-score sources: every team with a final score must be in
    for name, path, team_col in (
            ("player stats", os.path.join(DATA, f"stats_player_week_{year}.csv"), "team"),
            ("snap counts", os.path.join(UTIL, f"snaps_{year}.csv"), "team"),
            ("play-by-play", os.path.join(UTIL, f"pbp_{year}.csv"), "posteam")):
        if week <= 1:
            continue
        if not os.path.exists(path):
            stale(name, f"missing: {path}")
            continue
        have = {r.get(team_col) for r in _rows(path) if r.get("week") == str(week - 1)}
        missing = sorted(done_prev - have)
        if missing:
            stale(name, f"week {week - 1} has final scores but no rows for {', '.join(missing)}")
        else:
            ok(name, f"week {week - 1} complete ({len(done_prev)} teams)")

    # roster status -- the file that was stuck at week 2
    path = os.path.join(DATA, f"roster_{year}.csv")
    if not os.path.exists(path):
        stale("weekly rosters", "missing")
    else:
        top = max((int(r["week"]) for r in _rows(path) if r.get("week")), default=0)
        if top < week - 1:
            stale("weekly rosters", f"only through week {top} (need {week - 1}+): roster statuses are old")
        else:
            ok("weekly rosters", f"through week {top}")

    # injury report for THIS week, once it can exist
    path = os.path.join(DATA, f"injuries_{year}.csv")
    n = sum(1 for r in _rows(path) if r["week"] == str(week)) if os.path.exists(path) else 0
    days_out = (first_day - today).days
    if n:
        ok("injury report", f"{n} week {week} rows")
    elif days_out <= 5:
        stale("injury report", f"no week {week} rows and the first game is in {days_out} days")
    else:
        warn("injury report", f"no week {week} rows yet (first game in {days_out} days)")

    # depth charts: newest snapshot
    path = os.path.join(DATA, f"depth_charts_{year}.csv")
    if os.path.exists(path):
        newest = max((r["dt"][:10] for r in _rows(path) if r.get("dt")), default="")
        age = (today - datetime.date.fromisoformat(newest)).days if newest else 99
        (ok if age < 8 else stale)("depth charts", f"newest snapshot {newest} ({age} days old)")
    else:
        stale("depth charts", "missing")

    # Sleeper: a dated snapshot per day
    snaps = sorted(f for f in os.listdir(SLEEPER) if f.startswith("players_nfl_")) if os.path.isdir(SLEEPER) else []
    newest = snaps[-1][len("players_nfl_"):-len(".json")] if snaps else ""
    age = (today - datetime.date.fromisoformat(newest)).days if newest else 99
    if age == 0 or (age == 1 and not lock):
        ok("Sleeper snapshot", newest)
    else:
        stale("Sleeper snapshot", f"newest is {newest or 'none'} ({age} days old)")

    # news feed
    path = os.path.join(DATA, f"news_{year}.csv")
    newest = max((r["published"] for r in _rows(path)), default="") if os.path.exists(path) else ""
    age = (today - datetime.date.fromisoformat(newest[:10])).days if newest else 99
    (ok if age < 2 else warn)("news feed", f"newest item {newest or 'none'}")

    # site projections (the consensus) archived for this week
    d = os.path.join(WEEKLY, f"{year}-wk{week:02d}")
    files = [f for f in os.listdir(d) if f.startswith("consensus_")] if os.path.isdir(d) else []
    if not files:
        (stale if lock else warn)("site projections", f"no consensus archive in {d}")
    else:
        mt = datetime.date.fromtimestamp(max(os.path.getmtime(os.path.join(d, f)) for f in files))
        if lock and mt != today:
            stale("site projections", f"archived {mt} -- re-archive the latest CI run before a lock")
        else:
            ok("site projections", f"archived {mt}")
    etr = os.path.join(d, "etr.csv")
    if os.path.exists(etr):
        ok("ETR", f"saved {datetime.date.fromtimestamp(os.path.getmtime(etr))}")
    else:
        warn("ETR", "no etr.csv this week (benchmark only)")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--lock", action="store_true", help="lock-time rules (stricter)")
    args = ap.parse_args()
    res = check(args.year, args.week, args.lock)
    print(f"\n  freshness check, {args.year} week {args.week}" + (" (lock)" if args.lock else ""))
    for level, name, msg in res:
        print(f"  {level:6}{name:20}{msg}")
    bad = [r for r in res if r[0] == "STALE"]
    if bad:
        print(f"\n  STOP: {len(bad)} stale input(s) -- refresh before projecting.\n")
        sys.exit(1)
    print()


if __name__ == "__main__":
    main()
