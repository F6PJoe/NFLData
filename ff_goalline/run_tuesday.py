#!/usr/bin/env python3
"""
Tuesday-morning half of the weekly goal-line cadence: finishes the week
that just played by picking up whichever game(s) weren't final yet when
Monday's run went out -- almost always just Monday Night Football.

Targets LATEST-1, not LATEST: run_monday.py already duplicated the sheet
forward to LATEST (the new week's tab), so "the week that just played" is
one behind whatever the sheet's highest "W<N>" tab is right now.

update_weekly.py is per-game de-duped (data/counted_games.json), so this
is just the exact same command Monday already ran for that week -- it will
naturally find nothing new for games Monday already counted, and add just
the newly-final one(s).

Relies on Monday's run having actually created the new week tab. If it
didn't (e.g. Monday's job failed), this targets the wrong week -- and
because update_weekly.py just no-ops when it finds nothing new rather than
erroring, that failure mode is SILENT: check the run's own output (it
prints which week it's targeting and whether anything new was found), not
just whether the job went green.

Usage:
    python run_tuesday.py
    python run_tuesday.py --dry-run
"""

import argparse
import subprocess
import sys
from pathlib import Path

from sheet_state import sheets_service, latest_week_tab

HERE = Path(__file__).resolve().parent


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    service = sheets_service()
    latest = latest_week_tab(service)
    played_week = latest - 1
    if played_week < 1:
        print(f"Latest tab is W{latest} -- nothing before it to finish.", file=sys.stderr)
        return 1
    print(f"Latest tab: W{latest}. Finishing week {played_week}.")

    dr = ["--dry-run"] if args.dry_run else []
    result = subprocess.run(
        [sys.executable, str(HERE / "update_weekly.py"), "--week", str(played_week)] + dr,
        cwd=HERE,
    )
    if result.returncode != 0:
        sys.exit(result.returncode)
    print("\nTuesday run complete.")


if __name__ == "__main__":
    main()
