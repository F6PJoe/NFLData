#!/usr/bin/env python3
"""Refresh every input the weekly model reads -- meant to run at least daily.

Until now every one of these was fetched by hand, which is how week 3 was
nearly built on a Tuesday injury file with no Out/Doubtful designations in it.

Fetched (each to a temp file, sanity-checked, and only then swapped in, so a
failed or partial download can never overwrite good data):

  data/stats_player_week_<yr>.csv   nflverse player stats
  data/injuries_<yr>.csv            official NFL injury report
  data/depth_charts_<yr>.csv        nflverse depth charts
  data/games.csv                    schedule + betting lines (nfldata)
  ff_utilization/cached/nflverse/pbp_<yr>.csv, snaps_<yr>.csv
                                    same files, same names ff_utilization's own
                                    fetcher writes -- WITHOUT running that
                                    fetcher, which also rebuilds its tables
  ff_projections/cached/sleeper/players_nfl_<date>.json
                                    Sleeper injury tags

Then rebuilt: team/QB features, and play-by-play injury exits.

With --week N it also re-runs the week's projections, review sheet and
comparison workbook, so one command leaves everything current.

Usage:
    python refresh_inputs.py --year 2026
    python refresh_inputs.py --year 2026 --week 3
"""

import argparse
import csv
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(HERE, "data")
UTIL = os.path.join(ROOT, "ff_utilization", "cached", "nflverse")
SLEEPER = os.path.join(ROOT, "ff_projections", "cached", "sleeper")
REL = "https://github.com/nflverse/nflverse-data/releases/download"
UA = {"User-Agent": "Mozilla/5.0 (F6P weekly model refresh)"}


def download(url, timeout=300):
    fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(url)[1] or ".tmp")
    os.close(fd)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as fh:
        shutil.copyfileobj(r, fh)
    return tmp


def csv_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def max_week(path, season=None):
    best = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if season and r.get("season") and r["season"] != str(season):
                continue
            try:
                best = max(best, int(r.get("week") or 0))
            except ValueError:
                pass
    return best


def swap_csv(label, url, dest, min_rows, season=None, week_col=True):
    """Download, check, replace. Refuses to move backwards in weeks."""
    try:
        tmp = download(url)
    except Exception as e:  # noqa: BLE001 -- report and keep the old file
        print(f"  FAIL  {label:<18} download error: {e}  (kept existing file)")
        return False
    n = csv_rows(tmp)
    if n < min_rows:
        print(f"  FAIL  {label:<18} only {n} rows, expected {min_rows}+  (kept existing)")
        os.remove(tmp)
        return False
    if week_col and os.path.exists(dest):
        old_w, new_w = max_week(dest, season), max_week(tmp, season)
        if new_w < old_w:
            print(f"  FAIL  {label:<18} new file reaches wk{new_w}, current wk{old_w}  "
                  f"(kept existing)")
            os.remove(tmp)
            return False
    shutil.move(tmp, dest)
    extra = f", through wk{max_week(dest, season)}" if week_col else ""
    print(f"  ok    {label:<18} {n:>7,} rows{extra}")
    return True


def refresh_sleeper():
    try:
        tmp = download("https://api.sleeper.app/v1/players/nfl", timeout=180)
        with open(tmp, encoding="utf-8") as fh:
            blob = json.load(fh)
        if len(blob) < 5000:
            raise ValueError(f"only {len(blob)} players")
        os.makedirs(SLEEPER, exist_ok=True)
        dest = os.path.join(SLEEPER, f"players_nfl_{datetime.date.today():%Y-%m-%d}.json")
        shutil.move(tmp, dest)
        tagged = sum(1 for v in blob.values() if isinstance(v, dict) and v.get("injury_status"))
        print(f"  ok    {'sleeper tags':<18} {len(blob):>7,} players, {tagged:,} tagged")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL  {'sleeper tags':<18} {e}  (kept existing snapshot)")


def refresh_sheet(year, week):
    """The injury/status sheet, brought fully up to date -- used by the full
    refresh AND before every lock (late_news.py), so a Friday status or a
    Saturday downgrade is never missed (Joe, 2026-10-22). Pulls the official
    report, Sleeper and news, rebuilds the sheet (every call kept, practice
    filled in) and rewrites its history/news columns. -> True if the sheet
    was rebuilt; False (loudly) if it could not be, e.g. open in Excel."""
    swap_csv("injury report", f"{REL}/injuries/injuries_{year}.csv",
             os.path.join(DATA, f"injuries_{year}.csv"), 50, year)
    swap_csv("weekly rosters", f"{REL}/weekly_rosters/roster_weekly_{year}.csv",
             os.path.join(DATA, f"roster_{year}.csv"), 1000, year)
    refresh_sleeper()
    run("news.py", "--year", str(year))
    ok = run("build_review_queue.py", "--year", str(year), "--week", str(week))
    ok = run("player_log.py", "--year", str(year), "--week", str(week)) and ok
    if not ok:
        print("  !!! the status sheet was NOT fully updated -- see above")
    return ok


def run(script, *args):
    r = subprocess.run([sys.executable, os.path.join(HERE, script), *args],
                       capture_output=True, text=True)
    tail = (r.stdout.strip().splitlines() or [""])[-1]
    print(f"  {'ok' if r.returncode == 0 else 'FAIL':<5} {script:<28} {tail.strip()[:70]}")
    if r.returncode != 0:
        print("       " + (r.stderr.strip().splitlines() or ["(no error text)"])[-1][:120])
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, help="also rebuild this week's outputs")
    args = ap.parse_args()
    y = args.year
    print(f"\n  refreshing inputs for {y}  ({datetime.datetime.now():%Y-%m-%d %H:%M})\n")

    swap_csv("player stats", f"{REL}/stats_player/stats_player_week_{y}.csv",
             os.path.join(DATA, f"stats_player_week_{y}.csv"), 500, y)
    swap_csv("injury report", f"{REL}/injuries/injuries_{y}.csv",
             os.path.join(DATA, f"injuries_{y}.csv"), 50, y)
    # roster STATUS (ACT / RES / EXE / PUP ...): availability reads it first, and
    # it had not been refreshed since wk2 (2026-10-24: Jordan Mason still "RES"
    # after being designated to return)
    swap_csv("weekly rosters", f"{REL}/weekly_rosters/roster_weekly_{y}.csv",
             os.path.join(DATA, f"roster_{y}.csv"), 1000, y)
    swap_csv("depth charts", f"{REL}/depth_charts/depth_charts_{y}.csv",
             os.path.join(DATA, f"depth_charts_{y}.csv"), 10000, week_col=False)
    swap_csv("games + lines", "https://github.com/nflverse/nfldata/raw/master/data/games.csv",
             os.path.join(DATA, "games.csv"), 5000, y)
    os.makedirs(UTIL, exist_ok=True)
    swap_csv("play-by-play", f"{REL}/pbp/play_by_play_{y}.csv",
             os.path.join(UTIL, f"pbp_{y}.csv"), 1000, y)
    swap_csv("snap counts", f"{REL}/snap_counts/snap_counts_{y}.csv",
             os.path.join(UTIL, f"snaps_{y}.csv"), 500, y)
    refresh_sleeper()

    print()
    run("build_team_qb_features.py", "--year", str(y))
    run("build_injury_exits.py", "--year", str(y))
    run("news.py", "--year", str(y))
    if not args.week:
        run("player_log.py", "--year", str(y))

    if args.week:
        print()
        # FRESHNESS (2026-10-24): never project from a stale input -- the roster
        # file sat at week 2 for five weeks before anyone noticed
        if not run("check_freshness.py", "--year", str(y), "--week", str(args.week)):
            subprocess.run([sys.executable, os.path.join(HERE, "check_freshness.py"),
                            "--year", str(y), "--week", str(args.week)])
            print("  STOPPED before projecting: an input is stale (above).")
            sys.exit(1)
        run("project.py", "--year", str(y), "--week", str(args.week), "--live")
        run("build_review_queue.py", "--year", str(y), "--week", str(args.week))
        # history + news columns on the sheet, fresh-news players added (decisions untouched)
        run("player_log.py", "--year", str(y), "--week", str(args.week))
        run("project.py", "--year", str(y), "--week", str(args.week), "--live")
        # every test version, projected from the same inputs (see project.VARIANTS)
        sys.path.insert(0, HERE)
        import project
        for name in project.VARIANTS:
            if name != "current":
                run("project.py", "--year", str(y), "--week", str(args.week), "--live",
                    "--version", name)
        run("build_comparison_xlsx.py", "--year", str(y), "--week", str(args.week))
        # known-case output checks + the gap report (2026-10-24)
        if not run("check_projections.py", "--year", str(y), "--week", str(args.week), "--output-only"):
            subprocess.run([sys.executable, os.path.join(HERE, "check_projections.py"),
                            "--year", str(y), "--week", str(args.week), "--output-only"])
        run("gap_report.py", "--year", str(y), "--week", str(args.week))
    print()


if __name__ == "__main__":
    main()
