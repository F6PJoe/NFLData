#!/usr/bin/env python3
"""
Run the Stream-O-Matic refresh, skipping the one source that only needs
updating once a week: pressure rate (column J).

This used to skip the DAVE fetch too, since FTN's login was slow and the
numbers only moved weekly. Columns H and I now come from nflverse
play-by-play instead -- a cached file download with no login -- so they
cost little to refresh and they genuinely change as each week's games
finish. They stay in.

Also skips generate_reddit_post.py -- Joe only wants that generated once,
on the main/full run_all.py run, not on every quick refresh.

Usage:
    python run_frequent.py            # week auto-detected from today's date
    python run_frequent.py --week 2   # explicit override
"""

import argparse
import sys

from current_week import current_week
from run_all import STEPS, run_steps

SKIP = {"fetch_pressure_rate.py", "push_pressure_rate_to_sheet.py",
        "generate_reddit_post.py"}

FREQUENT_STEPS = [(script, args) for script, args in STEPS if script not in SKIP]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None,
                     help="NFL week, e.g. 2 (default: auto-detected from today's date)")
    args = ap.parse_args()

    week = args.week if args.week is not None else current_week()
    print(f"Week: {week}" + (" (auto-detected)" if args.week is None else " (explicit)"))

    failures = run_steps(FREQUENT_STEPS, week)

    if failures:
        print(f"\nDone (pressure rate skipped -- weekly-only), "
              f"but {len(failures)} step(s) failed:")
        for script, code in failures:
            print(f"  - {script} (exit {code})")
        sys.exit(1)

    print("\nAll done (pressure rate skipped -- weekly-only).")


if __name__ == "__main__":
    main()
