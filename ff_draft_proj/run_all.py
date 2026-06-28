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
import csv
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

# source-CSV prefix -> minimum expected row count per position. Roughly half
# of a normal day's count for each source/position, so a real outage or a
# partial/cached response from the source gets flagged even when the script
# exits 0 (e.g. the FTN run that quietly returned 1 QB/24 RB/26 WR/2 TE
# instead of its usual ~66/114/146/68).
MIN_ROWS = {
    "espn":          {"qb": 35, "rb": 55, "wr": 95, "te": 50},
    "cbs":           {"qb": 35, "rb": 45, "wr": 45, "te": 45},
    "ftn":           {"qb": 30, "rb": 55, "wr": 70, "te": 30},
    "yahoo":         {"qb": 65, "rb": 120, "wr": 215, "te": 110},
    "fantasysharks": {"qb": 40, "rb": 65, "wr": 95, "te": 60},
    "draftsharks":   {"qb": 20, "rb": 60, "wr": 95, "te": 50},
    "fantasydata":   {"qb": 50, "rb": 80, "wr": 120, "te": 70},
    "4for4":         {"qb": 30, "rb": 55, "wr": 85, "te": 45},
    "fantasylife":   {"qb": 30, "rb": 50, "wr": 85, "te": 45},
    "fftoday":       {"qb": 30, "rb": 45, "wr": 60, "te": 30},
}


def run(script, required=True):
    print(f"\n=== {script} ===", flush=True)
    result = subprocess.run([sys.executable, script])
    if result.returncode != 0:
        print(f"[WARN] {script} exited {result.returncode}", flush=True)
        if required:
            sys.exit(result.returncode)
        return False
    return True


def row_count(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return sum(1 for _ in f) - 1  # minus header
    except FileNotFoundError:
        return 0


def check_row_counts(script):
    """Returns a list of 'prefix_pos: got N, expected >= M' warnings for any
    position whose output CSV came back suspiciously thin."""
    prefix = script.removeprefix("fetch_").removesuffix("_projections.py")
    thresholds = MIN_ROWS.get(prefix, {})
    warnings = []
    for pos, minimum in thresholds.items():
        n = row_count(f"{prefix}_{pos}.csv")
        if n < minimum:
            warnings.append(f"{prefix}_{pos}.csv: got {n} rows, expected >= {minimum}")
    return warnings


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-sheets", action="store_true",
                     help="Skip pushing consensus CSVs to the Google Sheet")
    args = ap.parse_args()

    failed = []
    thin = []
    for script in FETCHERS:
        if not run(script, required=False):
            failed.append(script)
            continue
        warnings = check_row_counts(script)
        if warnings:
            thin.append(script)
            for w in warnings:
                print(f"[WARN] {w}", flush=True)

    run("build_consensus.py")
    if not args.no_sheets:
        run("push_to_sheets.py")
    else:
        print("\n[SKIP] push_to_sheets.py (--no-sheets)")

    def names(scripts):
        return ", ".join(s.removeprefix("fetch_").removesuffix("_projections.py") for s in scripts)

    if failed:
        print(f"\n::warning::{len(failed)} of {len(FETCHERS)} sources failed and were skipped: {names(failed)}")
    if thin:
        print(f"\n::warning::{len(thin)} source(s) returned suspiciously few rows (see [WARN] lines above): "
              f"{names(thin)}")
    ok_count = len(FETCHERS) - len(failed)
    if not failed and not thin:
        print(f"\n[SUMMARY] Pushed consensus built from all {len(FETCHERS)}/{len(FETCHERS)} sources.")
    else:
        extra = f" (thin: {names(thin)})" if thin else ""
        print(f"\n[SUMMARY] Pushed consensus built from {ok_count}/{len(FETCHERS)} sources"
              f"{f' (failed: {names(failed)})' if failed else ''}{extra}.")


if __name__ == "__main__":
    main()
