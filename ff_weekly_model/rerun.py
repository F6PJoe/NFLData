#!/usr/bin/env python3
"""Rerun this week's projections after making calls in the review workbook.

    python rerun.py                       # this week
    python rerun.py --year 2026 --week 8

Joe, 2026-10-31: make the calls on the team tabs of "F6P Week N Review.xlsx",
save and close it, then rerun ("Rerun projections.bat" runs this):
  0. FRESH REPORTS (Joe, 2026-11-01: "if reruns are on a new day, we should
     pull fresh reports, and then again for sure after 11:30 AM ET on game
     day"). The first rerun of a day runs the daily refresh (stats, injury
     report, rosters, depth charts, lines, Sleeper, news) and rebuilds the
     status sheet; on a game day at or after 11:30 AM ET, if nothing was
     pulled since 11:30, it runs the lock's late-news check (official
     inactives + late news -- only ever switches a player OFF) and refreshes
     the lines. The refresh, the late-news check and the lock all record when
     they pulled (data/reports_pulled.txt), so nothing is pulled twice.
  1. the workbook's calls are copied into the sheet (review_book.sync)
  2. projections, every version
  3. output checks
  4. comparison workbook and gap report
  5. the review workbook is rebuilt (with the model-only column)
Games already under way keep their lock -- freezing is lock.py's job.
"""

import argparse
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def this_week():
    """(season, week): the first week of the season with a game today or later."""
    import csv
    today = datetime.date.today().isoformat()
    season = datetime.date.today().year - (datetime.date.today().month < 3)
    last = {}
    with open(os.path.join(HERE, "data", "games.csv"), newline="", encoding="utf-8") as fh:
        for g in csv.DictReader(fh):
            if g["season"] == str(season) and g["game_type"] == "REG":
                w = int(g["week"])
                last[w] = max(last.get(w, ""), g["gameday"])
    return season, min((w for w, d in last.items() if d >= today), default=max(last))


INACTIVES_AT = datetime.time(11, 30)   # ET, game day


def game_day(year, week, day):
    import csv
    with open(os.path.join(HERE, "data", "games.csv"), newline="", encoding="utf-8") as fh:
        return any(g["season"] == str(year) and g["week"] == str(week) and g["gameday"] == day.isoformat()
                   for g in csv.DictReader(fh))


def pull_needed(year, week, now, last):
    """None, "day" (the first rerun of a new day) or "inactives" (game day,
    11:30 AM ET or later, nothing pulled since 11:30)."""
    if last is None or last.date() < now.date():
        return "day"
    cut = datetime.datetime.combine(now.date(), INACTIVES_AT)
    if now >= cut and last < cut and game_day(year, week, now.date()):
        return "inactives"
    return None


def run_parallel(jobs):
    """[(label, [script, args...])] all at once, each its own process -> all ok?
    Joe, 2026-11-01: "7.5 minutes is not going to cut it" -- the versions and
    the model-only run do not depend on each other. The workbook is synced
    once beforehand; REVIEW_SYNCED stops each run syncing it again at the same
    time. Output goes to temp files (a full pipe would stall a run)."""
    import tempfile
    env = dict(os.environ, REVIEW_SYNCED="1")
    procs = []
    for label, args in jobs:
        out_, err_ = tempfile.TemporaryFile(mode="w+"), tempfile.TemporaryFile(mode="w+")
        procs.append((label, subprocess.Popen([sys.executable, *args], cwd=HERE, env=env, stdout=out_,
                                              stderr=err_, text=True), out_, err_))
    ok = True
    for label, p, out_, err_ in procs:
        p.wait()
        out_.seek(0); err_.seek(0)
        lines = [l for l in out_.read().strip().splitlines() if l.strip()]
        print(f"  {'ok' if p.returncode == 0 else 'FAIL':<5} {label:<22} {(lines[-1].strip() if lines else '')[:90]}")
        if p.returncode != 0:
            print("        " + (err_.read().strip().splitlines() or lines or ["(no error text)"])[-1][:150])
            ok = False
    return ok


def run(label, *args):
    r = subprocess.run([sys.executable, *args], cwd=HERE, capture_output=True, text=True)
    lines = [l for l in r.stdout.strip().splitlines() if l.strip()]
    print(f"  {'ok' if r.returncode == 0 else 'FAIL':<5} {label:<22} {(lines[-1].strip() if lines else '')[:90]}")
    if r.returncode != 0:
        print("        " + (r.stderr.strip().splitlines() or lines or ["(no error text)"])[-1][:150])
    return r.returncode == 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int)
    ap.add_argument("--week", type=int)
    args = ap.parse_args()
    y, w = (args.year, args.week) if args.year and args.week else this_week()
    import review_book
    import project
    book = review_book.book_path(y, w)
    print(f"\n  rerunning week {w} projections ({datetime.datetime.now():%a %I:%M %p})\n")
    if os.path.exists(book):
        try:
            open(book, "r+b").close()
        except PermissionError:
            print(f"  {os.path.basename(book)} is still open in Excel -- save and close it, then run again.\n")
            sys.exit(1)
    if review_book.sync(y, w) is None:
        sys.exit("  STOPPED: the workbook's calls could not be copied into the sheet (above)\n")
    ys, ws = str(y), str(w)
    ok = True
    import refresh_inputs
    now, last = refresh_inputs.now_et(), refresh_inputs.last_pulled()
    kind = pull_needed(y, w, now, last)
    if kind:
        print(f"  fresh reports: {'first rerun today' if kind == 'day' else 'game day, past 11:30 AM ET'}"
              f" (last pulled {last:%a %I:%M %p})" if last else "  fresh reports: never pulled")
        if kind == "day":
            ok = run("daily refresh", "refresh_inputs.py", "--year", ys) and ok
        cut = datetime.datetime.combine(now.date(), INACTIVES_AT)
        if now >= cut and game_day(y, w, now.date()):
            refresh_inputs.swap_csv("games + lines", "https://github.com/nflverse/nfldata/raw/master/data/games.csv",
                                    os.path.join(HERE, "data", "games.csv"), 5000, y)
            ok = run("late news + inactives", "late_news.py", "--year", ys, "--week", ws) and ok
        else:
            ok = refresh_inputs.refresh_sheet(y, w) and ok
        refresh_inputs.mark_pulled()
        print()
    if kind and review_book.sync(y, w) is None:     # the late-news check may have edited the sheet
        sys.exit("  STOPPED: the workbook's calls could not be copied into the sheet (above)\n")
    nocalls = os.path.join(HERE, "data", f"projections_{y}_wk{w:02d}_nocalls.csv")
    ok = run_parallel([(f"projections ({name})", ["project.py", "--year", ys, "--week", ws, "--live"]
                        + ([] if name == "current" else ["--version", name])) for name in project.VARIANTS]
                      + [("model only (no calls)", ["project.py", "--year", ys, "--week", ws, "--live",
                                                     "--ignore-sheet", "--out", nocalls])]) and ok
    ok = run("output checks", "check_projections.py", "--year", ys, "--week", ws, "--output-only") and ok
    run_parallel([("comparison workbook", ["build_comparison_xlsx.py", "--year", ys, "--week", ws]),
                  ("gap report", ["gap_report.py", "--year", ys, "--week", ws])])
    ok = run("review workbook", "review_book.py", "--year", ys, "--week", ws, "--no-model-run") and ok
    print("\n  " + ("DONE -- open " + os.path.basename(book) + " to see the new numbers."
                    if ok else "FINISHED WITH PROBLEMS -- see above.") + "\n")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
