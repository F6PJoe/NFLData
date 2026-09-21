#!/usr/bin/env python3
"""Replay the whole pipeline after a manual/overrides.csv edit.

For a trade, cut, or signing, add one line to manual/overrides.csv:

    player,team,pos,depth,status,note
    Kayshon Boutte,HOU,WR,4,ACT,Traded from NE Aug 2026 - depth is a guess

`team` is his NEW team - that's what moves him. `depth` is his slot there
(an explicit number wins ties against whoever's already in it); leave it
blank to let his old depth carry over and compete on its own. For a release
or retirement, leave `team` alone and set `status,OUT`.

That edit is the one step this script can't do for you - which team a
player belongs to is exactly the judgment call this whole project exists to
keep in your hands. Once it's in the file, run this to replay everything
downstream of it in order:

    rosters -> history -> shares -> workbook (--merge) -> rankings

Always merges - a roster move should never discard your existing work.
Stops at the first failed step instead of pressing on with stale data, so
whatever ran before it is left in place.

Usage:
    python refresh.py
"""

import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    ["build_rosters.py"],
    ["build_history.py"],
    ["build_shares.py"],
    ["build_workbook_v3.py", "--merge"],
    ["build_rankings_v3.py"],
]


def main():
    for script, *args in STEPS:
        print(f"\n{'=' * 70}\n$ python {script} {' '.join(args)}\n{'=' * 70}")
        result = subprocess.run([sys.executable, os.path.join(HERE, script), *args])
        if result.returncode != 0:
            sys.exit(f"\nStopped - {script} failed (see above). Fix that, "
                     f"then re-run refresh.py; the earlier steps already "
                     f"ran and don't need repeating.")

    print(f"\n{'=' * 70}")
    print("Done. Open my_projections_v3.xlsx and rankings_v3.xlsx.")


if __name__ == "__main__":
    sys.exit(main())
