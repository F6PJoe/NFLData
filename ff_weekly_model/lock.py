#!/usr/bin/env python3
"""Lock this week's projections before a kickoff window -- one command.

    python lock.py --year 2026 --week 7

Built 2026-10-24 so a lock is the same every time (and can be scheduled):
  1. archive the newest site projections from the CI run "Fetch Weekly
     Projections" into ff_weekly_proj/weekly/<yr>-wk<NN>, after checking
     the files are for THIS week (a team / opponent pair from the schedule)
  1b. refresh betting lines (they move after late QB news)
  2. freshness check, lock rules              -> stop if anything is stale
  3. late-news check: rebuilds the status sheet (every call kept), applies
     official inactives and new OUT / IR news
  4. projections, every version
  5. known-case checks                        -> stop BEFORE freezing if any fail
  6. freeze (teams already under way keep their earlier lock)
  7. comparison workbook + gap report

Exit code 1 at the first failure; nothing is frozen after a failed check.
"""

import argparse
import csv
import glob
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)


def step(label, *cmd, cwd=HERE, fatal=True):
    print(f"\n  == {label}")
    r = subprocess.run(list(cmd), cwd=cwd)
    if r.returncode != 0:
        if not fatal:
            # after the freeze: the lock stands, the extra just did not get made
            # (e.g. the workbook open in Excel)
            print(f"\n  WARNING: {label} failed -- the projections ARE locked; re-run it when you can\n")
            return
        print(f"\n  LOCK STOPPED at: {label}\n")
        sys.exit(1)


def archive_site_projections(year, week):
    """Newest CI artifact -> weekly/<yr>-wk<NN>, verified against the schedule."""
    run_id = subprocess.run(["gh", "run", "list", "--workflow", "fetch_weekly_projections.yml",
                             "--limit", "1", "--json", "databaseId", "--jq", ".[0].databaseId"],
                            capture_output=True, text=True, cwd=ROOT).stdout.strip()
    if not run_id:
        print("  could not find a CI run -- keeping the current archive")
        return False
    tmp = tempfile.mkdtemp(prefix="ci_proj_")
    r = subprocess.run(["gh", "run", "download", run_id, "--name", "weekly-projection-csvs",
                        "--dir", tmp], cwd=ROOT)
    if r.returncode != 0:
        print("  download failed -- keeping the current archive")
        return False
    pairs = set()
    with open(os.path.join(HERE, "data", "games.csv"), newline="", encoding="utf-8") as fh:
        for g in csv.DictReader(fh):
            if g["season"] == str(year) and g["week"] == str(week):
                pairs |= {(g["home_team"], g["away_team"]), (g["away_team"], g["home_team"])}
    fp = os.path.join(tmp, "espn_qb.csv")
    with open(fp, newline="", encoding="utf-8-sig") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("Team") and r.get("Opp")]
    hits = sum(1 for r in rows if (r["Team"], r["Opp"].lstrip("@")) in pairs)
    if not rows or hits < 0.8 * len(rows):
        print(f"  CI files are not week {week} ({hits}/{len(rows)} match the schedule) -- not archived")
        return False
    dest = os.path.join(ROOT, "ff_weekly_proj", "weekly", f"{year}-wk{week:02d}")
    os.makedirs(dest, exist_ok=True)
    for f in glob.glob(os.path.join(tmp, "*.csv")):
        shutil.copy(f, dest)
    print(f"  archived CI run {run_id} -> {os.path.relpath(dest, ROOT)}  ({hits}/{len(rows)} QBs match week {week})")
    return True


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--no-freeze", action="store_true", help="every step except the freeze (a test run)")
    args = ap.parse_args()
    y, w = str(args.year), str(args.week)
    py = sys.executable

    print("\n  == site projections")
    archive_site_projections(args.year, args.week)
    # BETTING LINES move after late news (2026-10-24: CIN@BAL went from BAL -1.5 /
    # 48.5 to CIN -3 / 46.5 once Lamar was ruled out) -- refresh before projecting
    print("\n  == betting lines")
    import refresh_inputs
    refresh_inputs.swap_csv("games + lines", "https://github.com/nflverse/nfldata/raw/master/data/games.csv",
                            os.path.join(HERE, "data", "games.csv"), 5000, args.year)
    # the late-news check refreshes the injury report, rosters, Sleeper and news
    # first, so the freshness check comes AFTER it (2026-10-25: run before it,
    # it saw yesterday's Sleeper file and stopped the lock)
    step("late-news check", py, "late_news.py", "--year", y, "--week", w)
    step("freshness check (lock rules)", py, "check_freshness.py", "--year", y, "--week", w, "--lock")
    import project
    for name in project.VARIANTS:
        extra = [] if name == "current" else ["--version", name]
        step(f"projections ({name})", py, "project.py", "--year", y, "--week", w, "--live", *extra)
    step("known-case checks", py, "check_projections.py", "--year", y, "--week", w)
    if not args.no_freeze:
        step("freeze", py, "score_week.py", "--year", y, "--week", w, "--freeze")
    step("comparison workbook", py, "build_comparison_xlsx.py", "--year", y, "--week", w, fatal=False)
    step("gap report", py, "gap_report.py", "--year", y, "--week", w, fatal=False)
    print("\n  " + ("TEST RUN DONE (not frozen)." if args.no_freeze else "LOCKED.") + "\n")


if __name__ == "__main__":
    main()
