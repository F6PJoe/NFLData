#!/usr/bin/env python3
"""
Run the whole weekly cycle in one command: fetch both sources, merge, build
both teaser views, then upload all 3 files over SFTP.

Equivalent to running by hand:
    python fetch_nflverse_utilization.py --year Y --weeks 1-N
    python fetch_fantasylife_utilization.py --year Y --weeks 1-N
    python build_published.py --year Y --weeks 1-N
    python build_teaser.py --year Y --weeks 1-N --view weekly
    python build_teaser.py --year Y --weeks 1-N --view season
    python sftp_upload.py --dry-run
    python sftp_upload.py

Stops immediately if any build step fails (non-zero exit) -- it will not
upload half-built or missing data.

By default it still pauses before the actual upload: it runs the dry-run,
shows you what would change, and asks for a yes. That checkpoint is the one
thing this script deliberately does NOT automate away -- a bad week's source
data (a broken feed, a missing game) is something you want to notice before
it goes out, not something that silently ships because one command happened
to string every step together. Pass --yes to skip the prompt if you're
confident and want a true single unattended command (e.g. from a scheduled
CI run, where nothing can answer the prompt anyway).

--year/--weeks are optional. Omit either (or both) and the current NFL
season/week are auto-detected from the league's own schedule data -- so a
scheduled run (cron-job.org -> workflow_dispatch, say) never needs its
payload edited week to week. Always printed loudly before anything runs, so
a bad guess is visible in the log rather than silently shipping the wrong
week. Pass them explicitly to pin a specific week (backfilling, testing,
or just not trusting the auto-detect for a given week).

Usage:
    python run_weekly.py                        # auto-detect year + week
    python run_weekly.py --yes                   # same, unattended
    python run_weekly.py --year 2026 --weeks 1-2 # pinned
    python run_weekly.py --year 2026 --weeks 1-2 --yes
"""

import argparse
import csv
import datetime
import io
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(cmd):
    print(f"\n$ {' '.join(cmd)}", flush=True)
    result = subprocess.run([sys.executable] + cmd, cwd=HERE)
    if result.returncode != 0:
        sys.exit(f"\nFAILED: {' '.join(cmd)} (exit {result.returncode}) -- "
                 f"stopping here, nothing uploaded.")


def auto_current_week():
    """(year, week) for "right now", from the NFL's own published schedule --
    not a calendar-math guess. Season year: NFL seasons are named for the
    year they START in, so a January/February/March game is still part of
    LAST year's season (season "2026" runs Sep 2026 - Feb 2027). Week: the
    highest week whose earliest game has already kicked off -- deliberately
    "started", not "finished", so a Friday-morning run (only Thursday's game
    played) still resolves to the current week rather than the prior one."""
    today = datetime.date.today()
    year = today.year - 1 if today.month <= 3 else today.year

    url = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()

    by_week = {}
    for row in csv.DictReader(io.StringIO(data.decode("utf-8"))):
        if row["season"] != str(year) or row["game_type"] != "REG":
            continue
        wk = int(row["week"])
        by_week.setdefault(wk, []).append(datetime.date.fromisoformat(row["gameday"]))

    started = [wk for wk, dates in by_week.items() if min(dates) <= today]
    if not started:
        sys.exit(f"Could not auto-detect the current NFL week -- no {year} "
                 f"season games have started yet. Pass --year/--weeks explicitly.")
    return year, max(started)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, default=None)
    ap.add_argument("--weeks", default=None,
                    help="ALWAYS 1-N, N = the current week -- never just the "
                         "new week alone (see CLAUDE.md). Omit to auto-detect.")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt and upload immediately")
    args = ap.parse_args()

    if args.year is None or args.weeks is None:
        auto_year, auto_week = auto_current_week()
        year = args.year if args.year is not None else auto_year
        weeks = args.weeks if args.weeks is not None else f"1-{auto_week}"
        print(f"Auto-detected: year={year}, current week={auto_week} "
              f"(weeks={weeks})", flush=True)
    else:
        year, weeks = args.year, args.weeks

    y, w = str(year), weeks

    run(["fetch_nflverse_utilization.py", "--year", y, "--weeks", w])
    run(["fetch_fantasylife_utilization.py", "--year", y, "--weeks", w])
    run(["build_published.py", "--year", y, "--weeks", w])
    run(["build_teaser.py", "--year", y, "--weeks", w, "--view", "weekly"])
    run(["build_teaser.py", "--year", y, "--weeks", w, "--view", "season"])

    print("\n--- build done, checking what the upload would change ---", flush=True)
    run(["sftp_upload.py", "--dry-run"])

    if not args.yes:
        reply = input("\nUpload these 3 files now? [y/N] ").strip().lower()
        if reply != "y":
            print("Not uploading. Re-run with --yes, or `python sftp_upload.py` "
                  "when you're ready.")
            return

    run(["sftp_upload.py"])
    print("\nDone -- data built and uploaded.")


if __name__ == "__main__":
    main()
