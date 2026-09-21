#!/usr/bin/env python3
"""
Run the whole weekly cycle in one command: fetch both sources, merge, build
both teaser views, then upload all 3 files over SFTP.

Equivalent to running by hand:
    python fetch_nflverse_utilization.py --year Y --weeks 1-N
    python fetch_fantasylife_utilization.py --year Y --weeks 1-N
    python build_published.py --year Y --weeks 1-N
    python build_teaser.py --year Y --weeks 1-N --view weekly
    python build_teaser.py --year Y --weeks 1-N --view season
    python sftp_upload.py --dry-run
    python sftp_upload.py

Stops immediately if any build step fails (non-zero exit) -- it will not
upload half-built or missing data.

By default it still pauses before the actual upload: it runs the dry-run,
shows you what would change, and asks for a yes. That checkpoint is the one
thing this script deliberately does NOT automate away -- a bad week's source
data (a broken feed, a missing game) is something you want to notice before
it goes out, not something that silently ships because one command happened
to string every step together. Pass --yes to skip the prompt if you're
confident and want a true single unattended command.

Usage:
    python run_weekly.py --year 2026 --weeks 1-2
    python run_weekly.py --year 2026 --weeks 1-2 --yes
"""

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run(cmd):
    print(f"\n$ {' '.join(cmd)}", flush=True)
    result = subprocess.run([sys.executable] + cmd, cwd=HERE)
    if result.returncode != 0:
        sys.exit(f"\nFAILED: {' '.join(cmd)} (exit {result.returncode}) -- "
                 f"stopping here, nothing uploaded.")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--weeks", required=True,
                    help="ALWAYS 1-N, N = the current week -- never just the "
                         "new week alone (see CLAUDE.md)")
    ap.add_argument("--yes", action="store_true",
                    help="skip the confirmation prompt and upload immediately")
    args = ap.parse_args()

    y, w = str(args.year), args.weeks

    run(["fetch_nflverse_utilization.py", "--year", y, "--weeks", w])
    run(["fetch_fantasylife_utilization.py", "--year", y, "--weeks", w])
    run(["build_published.py", "--year", y, "--weeks", w])
    run(["build_teaser.py", "--year", y, "--weeks", w, "--view", "weekly"])
    run(["build_teaser.py", "--year", y, "--weeks", w, "--view", "season"])

    print("\n--- build done, checking what the upload would change ---", flush=True)
    run(["sftp_upload.py", "--dry-run"])

    if not args.yes:
        reply = input("\nUpload these 3 files now? [y/N] ").strip().lower()
        if reply != "y":
            print("Not uploading. Re-run with --yes, or `python sftp_upload.py` "
                  "when you're ready.")
            return

    run(["sftp_upload.py"])
    print("\nDone -- data built and uploaded.")


if __name__ == "__main__":
    main()
