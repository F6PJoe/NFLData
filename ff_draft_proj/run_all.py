#!/usr/bin/env python3
"""
Run every per-source projection fetcher, build the consensus CSVs, and push
them to the live Google Sheet.

Usage:
    python run_all.py
"""

import subprocess
import sys

FETCHERS = [
    "fetch_espn_projections.py",
    "fetch_cbs_projections.py",
    "fetch_ftn_projections.py",
    "fetch_yahoo_projections.py",
    "fetch_fantasysharks_projections.py",
    "fetch_draftsharks_projections.py",
    "fetch_fantasydata_projections.py",
    "fetch_4for4_projections.py",
    "fetch_fantasylife_projections.py",
    "fetch_fftoday_projections.py",
]


def run(script, required=True):
    print(f"\n=== {script} ===")
    result = subprocess.run([sys.executable, script])
    if result.returncode != 0:
        print(f"[WARN] {script} exited {result.returncode}")
        if required:
            sys.exit(result.returncode)


def main():
    for script in FETCHERS:
        run(script, required=False)

    run("build_consensus.py")
    run("push_to_sheets.py")


if __name__ == "__main__":
    main()
