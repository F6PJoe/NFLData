#!/usr/bin/env python3
"""
Run the mid-week Stream-O-Matic refresh: only the columns that actually
move between Wednesday and Sunday.

Skipped here, because run_all.py already did them on Tuesday and rerunning
them mid-week would make the chart WORSE, not just waste time:

  * Team list and matchups (columns B/E). Opponents don't change once a
    week's slate is set -- a flexed game moves the kickoff time, not who's
    playing whom.

  * Def Rating and Opp Off EPA (columns G/H). These are season-to-date
    per-play numbers. Refreshing them on a Friday would fold in Thursday
    night's game -- and ONLY Thursday night's game, so 2 of 32 teams would
    be rated on a sample the other 30 don't have yet. Freezing them at
    Tuesday means every team's rating covers the same set of completed
    weeks, which is the comparison the 1-32 ranking actually needs.

  * Pressure rate (column J). Weekly-only at the source.

  * generate_reddit_post.py -- Joe posts the top 10 once, off the Tuesday
    run.

What's left is the stuff that genuinely changes day to day: live odds,
Yahoo roster/start%/projection, and FantasyPros ECR -- plus
finalize_live_sheet.py to re-score and re-sort.

Note finalize_live_sheet.py needs no schedule.csv here. It falls back to
the sheet's own row count, which Tuesday's run already trimmed to this
week's team count (bye weeks included) -- so a fresh CI checkout with no
CSVs on disk still finalizes correctly.

Usage:
    python run_frequent.py            # week auto-detected from today's date
    python run_frequent.py --week 3   # explicit override
"""

import argparse
import sys

from current_week import current_week
from run_all import STEPS, run_steps

SKIP = {"fetch_schedule.py", "push_schedule_to_sheet.py",
        "fetch_def_rating.py", "push_def_rating_to_sheet.py",
        "fetch_nflverse_epa.py", "push_nflverse_epa_to_sheet.py",
        "fetch_pressure_rate.py", "push_pressure_rate_to_sheet.py",
        "generate_reddit_post.py"}

FREQUENT_STEPS = [(script, args) for script, args in STEPS if script not in SKIP]

SUMMARY = "schedule, ratings and pressure skipped -- Tuesday-only"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None,
                     help="NFL week, e.g. 3 (default: auto-detected from today's date)")
    args = ap.parse_args()

    week = args.week if args.week is not None else current_week()
    print(f"Week: {week}" + (" (auto-detected)" if args.week is None else " (explicit)"))

    failures = run_steps(FREQUENT_STEPS, week)

    if failures:
        print(f"\nDone ({SUMMARY}), but {len(failures)} step(s) failed:")
        for script, code in failures:
            print(f"  - {script} (exit {code})")
        sys.exit(1)

    print(f"\nAll done ({SUMMARY}).")


if __name__ == "__main__":
    main()
