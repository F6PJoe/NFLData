#!/usr/bin/env python3
"""
Monday-afternoon half of the weekly goal-line cadence -- everything about
the UPCOMING week, none of which needs the just-played week's Monday Night
Football game to be over yet:

  1. advance_week.py       -- duplicate the current week tab -> next week
                               (with live formulas), freeze the current one
  2. set_week_matchups.py  -- write the new week's real matchups
  3. fill_week_odds.py     -- live pre-game implied totals + O/U for it
  4. update_weekly.py      -- catch Off/Def up on whichever of the
                               just-played week's games are already final --
                               typically everything except that week's
                               Monday night game. Safe to run again Tuesday
                               for the rest (see update_weekly.py's
                               per-game de-dup) -- this is intentional, not
                               a gap to fix: it's reference data for a
                               write-up, and the writer gets a head start
                               with what's already in, then Tuesday's run
                               finishes the week once MNF posts.

The week number is never hardcoded -- it's read from the sheet itself
(sheet_state.latest_week_tab): the highest existing "W<N>" tab IS the
current week, so this always knows where to pick up.

Usage:
    python run_monday.py
    python run_monday.py --dry-run
"""

import argparse
import subprocess
import sys
from pathlib import Path

from sheet_state import sheets_service, latest_week_tab

HERE = Path(__file__).resolve().parent


def run(script, args):
    print(f"\n=== {script} {' '.join(args)} ===", flush=True)
    result = subprocess.run([sys.executable, str(HERE / script)] + args, cwd=HERE)
    return result.returncode


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    service = sheets_service()
    current = latest_week_tab(service)
    next_week = current + 1
    print(f"Current week tab: W{current}. Advancing to W{next_week}.")

    dr = ["--dry-run"] if args.dry_run else []
    failures = []

    # No step stops the run on failure (same policy as ff_defense/run_all.py)
    # -- a failure in one step (e.g. odds already exist, or the Odds API is
    # briefly down) shouldn't block the others from still updating.
    if run("advance_week.py", ["--from", str(current), "--to", str(next_week)] + dr) != 0:
        failures.append("advance_week.py")
    if run("set_week_matchups.py", ["--week", str(next_week)] + dr) != 0:
        failures.append("set_week_matchups.py")
    if run("fill_week_odds.py", ["--week", str(next_week)] + dr) != 0:
        failures.append("fill_week_odds.py")
    if run("update_weekly.py", ["--week", str(current)] + dr) != 0:
        failures.append("update_weekly.py")

    if failures:
        print(f"\nDone, but {len(failures)} step(s) failed: {', '.join(failures)}")
        sys.exit(1)
    print("\nMonday run complete.")


if __name__ == "__main__":
    main()
