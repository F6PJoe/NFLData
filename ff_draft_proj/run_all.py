#!/usr/bin/env python3
"""
Run every per-source projection fetcher, build the consensus CSVs, and (by
default) push them to the live Google Sheet.

The Google Sheet push is scheduled separately via cron-job.org and should
stay on its own cadence. When this script is invoked by another local
pipeline (e.g. the cheat sheet updater) that only needs fresh consensus_*.csv
files, pass --no-sheets to skip the push.

Usage:
    python run_all.py                # fetch, build consensus, push to Sheets
    python run_all.py --no-sheets    # fetch, build consensus, skip the push
"""

import argparse
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
    print(f"\n=== {script} ===", flush=True)
    result = subprocess.run([sys.executable, script])
    if result.returncode != 0:
        print(f"[WARN] {script} exited {result.returncode}", flush=True)
        if required:
            sys.exit(result.returncode)
        return False
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sheets", action="store_true",
                     help="Skip pushing consensus CSVs to the Google Sheet")
    args = ap.parse_args()

    failed = [script for script in FETCHERS if not run(script, required=False)]

    run("build_consensus.py")
    if not args.no_sheets:
        run("push_to_sheets.py")
    else:
        print("\n[SKIP] push_to_sheets.py (--no-sheets)")

    if failed:
        names = ", ".join(s.replace("fetch_", "").replace("_projections.py", "") for s in failed)
        print(f"\n::warning::{len(failed)} of {len(FETCHERS)} sources failed and were skipped: {names}")
        print(f"[SUMMARY] Pushed consensus built from {len(FETCHERS) - len(failed)}/{len(FETCHERS)} sources "
              f"(failed: {names})")
    else:
        print(f"\n[SUMMARY] Pushed consensus built from all {len(FETCHERS)}/{len(FETCHERS)} sources.")


if __name__ == "__main__":
    main()
