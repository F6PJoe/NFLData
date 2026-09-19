#!/usr/bin/env python3
"""
Run every per-source weekly projection fetcher, build the consensus CSVs,
and (by default) push them to the live Google Sheet.

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

# Minimum expected rows per position — roughly half of a normal week's count.
# Fantasy Sharks is intentionally low because it's often blocked from CI
# (datacenter IP blocks). Yahoo's are measured against its post-filter counts:
# the fetcher drops players Yahoo lists with no projection for the week, which
# takes it from 140/264/465/246 raw down to roughly 32/111/165/106.
MIN_ROWS = {
    "espn":          {"qb": 20, "rb": 35, "wr": 60, "te": 25},
    "cbs":           {"qb": 20, "rb": 30, "wr": 30, "te": 25},
    "ftn":           {"qb": 10, "rb": 25, "wr": 40, "te": 15},
    "yahoo":         {"qb": 15, "rb": 55, "wr": 80, "te": 50},
    "fantasysharks": {"qb": 15, "rb": 30, "wr": 45, "te": 25},
    "draftsharks":   {"qb": 15, "rb": 35, "wr": 55, "te": 25},
    "fantasydata":   {"qb": 25, "rb": 45, "wr": 65, "te": 35},
    "4for4":         {"qb": 15, "rb": 30, "wr": 45, "te": 20},
    "fantasylife":   {"qb": 15, "rb": 30, "wr": 50, "te": 20},
    "fftoday":       {"qb": 15, "rb": 25, "wr": 35, "te": 15},
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
            return sum(1 for _ in f) - 1
    except FileNotFoundError:
        return 0


def check_row_counts(script):
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
