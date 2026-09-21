#!/usr/bin/env python3
"""
Run the full weekly Stream-O-Matic refresh: every fetch/push pair, in
order, then finalize_live_sheet.py last.

Usage:
    python run_all.py            # week auto-detected from today's date
    python run_all.py --week 2   # explicit override
"""

import argparse
import subprocess
import sys
from pathlib import Path

from current_week import current_week

HERE = Path(__file__).parent

# (script, extra_args) -- in the order they must run. fetch_schedule.py
# has to come first: it establishes the team list (column B) that every
# other push matches its rows against.
#
# Columns H and I used to come from FTN's DAVE and the team list from
# Subvertadown; both are gone (see CLAUDE.md). They're now built here from
# nflverse's free play-by-play and schedule releases, so nothing in this
# pipeline depends on a login that can be revoked.
#
# No step stops the
# pipeline on failure -- Joe's call: a failure on any one source (a lapsed
# subscription, a CI/datacenter IP block like FTN's -- see
# fetch_weekly_projections.yml's own comment about that exact issue) should
# still leave every OTHER source's push to run, so at least most of the
# sheet gets refreshed instead of nothing at all. Every push_*.py script
# checks its input CSV exists first and no-ops cleanly (prints a warning,
# leaves its columns as whatever they already were) if the matching
# fetch_*.py failed to produce one -- so a missing file here is never a
# crash, just a skipped column. finalize_live_sheet.py separately falls
# back to the sheet's own current row count if schedule.csv is missing, so
# bye-week row cleanup / SCORE formula / sort still run even when the
# schedule fetch is down.
STEPS = [
    ("fetch_schedule.py", ["--week", "{week}"]),
    ("push_schedule_to_sheet.py", []),
    ("fetch_def_rating.py", []),
    ("push_def_rating_to_sheet.py", []),
    ("fetch_nflverse_epa.py", []),
    ("push_nflverse_epa_to_sheet.py", []),
    ("fetch_implied_totals.py", []),
    ("push_implied_totals_to_sheet.py", []),
    ("fetch_yahoo_def.py", ["--week", "{week}"]),
    ("push_yahoo_def_to_sheet.py", []),
    ("fetch_fantasypros_dst_ecr.py", ["--week", "{week}"]),
    ("push_fantasypros_ecr_to_sheet.py", []),
    ("fetch_pressure_rate.py", []),
    ("push_pressure_rate_to_sheet.py", []),
    ("finalize_live_sheet.py", []),
    ("generate_reddit_post.py", ["--week", "{week}"]),
]


def run_steps(steps, week):
    """Runs every step regardless of earlier failures; returns the list of
    (script, exit_code) for any that failed, so the caller can report a
    summary and still exit non-zero without having stopped early."""
    failures = []
    for script, args in steps:
        resolved_args = [a.format(week=week) for a in args]
        print(f"\n=== {script} {' '.join(resolved_args)} ===", flush=True)
        result = subprocess.run(
            [sys.executable, str(HERE / script)] + resolved_args, cwd=HERE
        )
        if result.returncode != 0:
            print(f"[WARN] {script} failed (exit {result.returncode}) -- "
                  f"continuing with the rest of the run.", flush=True)
            failures.append((script, result.returncode))
    return failures


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None,
                     help="NFL week, e.g. 2 (default: auto-detected from today's date)")
    args = ap.parse_args()

    week = args.week if args.week is not None else current_week()
    print(f"Week: {week}" + (" (auto-detected)" if args.week is None else " (explicit)"))

    failures = run_steps(STEPS, week)

    if failures:
        print(f"\nDone, but {len(failures)} step(s) failed:")
        for script, code in failures:
            print(f"  - {script} (exit {code})")
        sys.exit(1)

    print("\nAll done.")


if __name__ == "__main__":
    main()
