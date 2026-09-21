#!/usr/bin/env python3
"""
One-command refresh: pulls the latest consensus projections and personal
ranks (both already computed by the daily cloud automation, just pulled
down locally rather than re-scraped), then rebuilds the live draft board
workbook. Close the Dropbox file first -- the rebuild step can't write to
it while it's open in Excel.

Usage:
    python refresh_and_rebuild.py
"""

import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
HERE = Path(__file__).resolve().parent


def run(script, cwd):
    print(f"\n=== {script} ===", flush=True)
    result = subprocess.run([sys.executable, script], cwd=cwd)
    if result.returncode != 0:
        print(f"[FAILED] {script} exited {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)


def main():
    run("pull_from_sheets.py", cwd=BASE / "ff_draft_proj")
    run("pull_personal_ranks.py", cwd=HERE)
    run("build_live_draft_workbook.py", cwd=HERE)
    print("\nDone -- live_draft_board workbook rebuilt with today's data.")


if __name__ == "__main__":
    main()
