#!/usr/bin/env python3
"""
Move a just-downloaded PFF export out of Downloads and into the project,
overwriting a fixed filename instead of letting Chrome pile up
"Week-1-rankings-export (12).csv", "(13).csv", ... forever.

    python capture_pff_export.py --slot RB --scoring HALF
    # -> moves the newest matching file in Downloads to
    #    weekly/<year>-wk<NN>/pff_raw/RB_HALF.csv

Finds the most recently modified file in Downloads matching PFF's export
name pattern (`*rankings-export*.csv`, case-insensitive) and requires it be
newer than --max-age-seconds (default 120) old. That age check is the whole
safety net: without it, a click that silently failed to trigger a download
would go undetected and this would just re-move the PREVIOUS capture under
the new name, quietly overwriting a fresh format with stale data. Refusing
to guess is safer than reporting success on a false one.
"""

import argparse
import glob
import os
import shutil
import time

DOWNLOADS_GLOB_DEFAULT = "*rankings-export*.csv"


def find_latest(downloads_dir, pattern):
    candidates = glob.glob(os.path.join(downloads_dir, pattern))
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                  formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slot", required=True,
                    choices=["FLX", "QB", "RB", "WR", "TE", "K", "DST"])
    ap.add_argument("--scoring", default="HALF",
                    choices=["HALF", "PPR", "STD", "ANY"])
    ap.add_argument("--downloads-dir",
                    default=os.path.join(os.path.expanduser("~"), "Downloads"))
    ap.add_argument("--pattern", default=DOWNLOADS_GLOB_DEFAULT,
                    help="glob (case-insensitive) matched against Downloads")
    ap.add_argument("--max-age-seconds", type=int, default=120,
                    help="refuse a match older than this -- likely means the "
                         "download never actually happened")
    ap.add_argument("--week-dir", help="defaults to the newest weekly/<year>-wk<NN>")
    ap.add_argument("--out-root", default="weekly")
    args = ap.parse_args()

    # glob() is case-sensitive on the parts that matter here (rankings-export
    # vs Rankings-Export); match both cases since PFF's own capitalization
    # isn't something to depend on.
    pattern_variants = {args.pattern, args.pattern.lower(), args.pattern.upper(),
                        args.pattern.capitalize()}
    found = None
    for variant in pattern_variants:
        candidate = find_latest(args.downloads_dir, variant)
        if candidate and (found is None or os.path.getmtime(candidate) > os.path.getmtime(found)):
            found = candidate

    if not found:
        raise SystemExit(f"No file matching {args.pattern!r} in {args.downloads_dir}")

    age = time.time() - os.path.getmtime(found)
    if age > args.max_age_seconds:
        raise SystemExit(
            f"Newest match is {found} but it's {age:.0f}s old (max "
            f"{args.max_age_seconds}s) -- the CSV click probably didn't "
            f"actually trigger a download. Not moving a stale file silently.")

    week_dir = args.week_dir
    if not week_dir:
        candidates = sorted(
            d for d in (os.path.join(args.out_root, n)
                        for n in os.listdir(args.out_root))
            if os.path.isdir(d)) if os.path.isdir(args.out_root) else []
        if not candidates:
            raise SystemExit(f"No week directory under {args.out_root}/ -- "
                             f"run run_weekly.py once first, or pass --week-dir.")
        week_dir = candidates[-1]

    dest_dir = os.path.join(week_dir, "pff_raw")
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{args.slot}_{args.scoring}.csv")

    shutil.move(found, dest)
    print(f"{found} ({age:.0f}s old) -> {dest}")


if __name__ == "__main__":
    main()
