#!/usr/bin/env python3
"""
Run the Stream-O-Matic refresh, skipping the two sources that only need
updating once a week: FTN DAVE (columns H/I) and pressure rate (column J).
Everything else here changes often enough to be worth rerunning more
often -- Subvertadown's weekly projection, implied totals (live odds),
Yahoo roster/start%/projection, and FantasyPros ECR.

Also skips generate_reddit_post.py -- Joe only wants that generated once,
on the main/full run_all.py run, not on every quick refresh.

Usage:
    python run_frequent.py            # week auto-detected from today's date
    python run_frequent.py --week 2   # explicit override
"""

import argparse

from current_week import current_week
from run_all import STEPS, run_steps

SKIP = {"fetch_ftn_dave.py", "push_ftn_dave_to_sheet.py",
        "fetch_pressure_rate.py", "push_pressure_rate_to_sheet.py",
        "generate_reddit_post.py"}

FREQUENT_STEPS = [(script, args, required) for script, args, required in STEPS if script not in SKIP]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None,
                     help="NFL week, e.g. 2 (default: auto-detected from today's date)")
    args = ap.parse_args()

    week = args.week if args.week is not None else current_week()
    print(f"Week: {week}" + (" (auto-detected)" if args.week is None else " (explicit)"))

    run_steps(FREQUENT_STEPS, week)
    print("\nAll done (DVOA and pressure rate skipped -- weekly-only).")


if __name__ == "__main__":
    main()
