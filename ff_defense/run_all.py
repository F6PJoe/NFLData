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

# (script, extra_args, required) -- in the order they must run. required=False
# means a failure prints a warning and the run continues, same convention as
# ff_weekly_proj/run_all.py's FTN/Fantasy Sharks handling: FTN's login is
# often blocked from datacenter IPs (GitHub Actions runners use well-known,
# published IP ranges, which Cloudflare bot-management on FTN's login
# endpoint apparently flags) -- confirmed as a real, already-hit problem in
# this repo, not a hypothetical, via fetch_weekly_projections.yml's own
# comment. push_ftn_dave_to_sheet.py separately no-ops cleanly if
# ftn_dave.csv doesn't exist (e.g. this exact case, on an ephemeral CI
# runner with no leftover file from a prior run), so it doesn't need
# required=False itself -- it always exits 0.
STEPS = [
    ("fetch_subvertadown_defense.py", [], True),
    ("push_subvertadown_to_sheet.py", [], True),
    ("fetch_ftn_dave.py", [], False),
    ("push_ftn_dave_to_sheet.py", [], True),
    ("fetch_implied_totals.py", [], True),
    ("push_implied_totals_to_sheet.py", [], True),
    ("fetch_yahoo_def.py", ["--week", "{week}"], True),
    ("push_yahoo_def_to_sheet.py", [], True),
    ("fetch_fantasypros_dst_ecr.py", ["--week", "{week}"], True),
    ("push_fantasypros_ecr_to_sheet.py", [], True),
    ("fetch_pressure_rate.py", [], True),
    ("push_pressure_rate_to_sheet.py", [], True),
    ("finalize_live_sheet.py", [], True),
    ("generate_reddit_post.py", ["--week", "{week}"], True),
]


def run_steps(steps, week):
    for script, args, required in steps:
        resolved_args = [a.format(week=week) for a in args]
        print(f"\n=== {script} {' '.join(resolved_args)} ===", flush=True)
        result = subprocess.run(
            [sys.executable, str(HERE / script)] + resolved_args, cwd=HERE
        )
        if result.returncode != 0:
            if required:
                sys.exit(f"\n{script} failed (exit {result.returncode}) -- stopping.")
            print(f"[WARN] {script} failed (exit {result.returncode}) -- "
                  f"continuing, likely a CI/datacenter IP block.", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None,
                     help="NFL week, e.g. 2 (default: auto-detected from today's date)")
    args = ap.parse_args()

    week = args.week if args.week is not None else current_week()
    print(f"Week: {week}" + (" (auto-detected)" if args.week is None else " (explicit)"))

    run_steps(STEPS, week)
    print("\nAll done.")


if __name__ == "__main__":
    main()
