#!/usr/bin/env python3
"""The weekly judgement call sheet -- Questionable skill players, nothing else.

The model does NOT predict injuries. Official designations and news decide who
plays. But "Questionable" is genuinely ambiguous -- most of them play, some
don't -- and that call is football judgement, not something to infer from
data. So the model surfaces exactly those players and gets out of the way.

Everything here is DEFAULTED so the sheet is optional: leave a row blank and
the player is treated as playing, which is what usually happens. Filling a row
in only overrides a default. Skipping the sheet in a busy week costs accuracy
on a handful of players, never correctness.

Columns you fill:
    decision   OUT | LIMITED | PLAY   (blank = PLAY)
    note       free text, for your own reference later

Usage:
    python build_review_queue.py --year 2026 --week 2
"""

import argparse
import collections
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
POSITIONS = ("QB", "RB", "WR", "TE")
PRACTICE_SHORT = {"Did Not Participate In Practice": "DNP",
                  "Limited Participation in Practice": "LIMITED",
                  "Full Participation in Practice": "FULL"}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    args = ap.parse_args()

    inj_path = os.path.join(DATA, f"injuries_{args.year}.csv")
    with open(inj_path, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh)
                if r["week"] == str(args.week) and r["position"] in POSITIONS]

    # projected points, so the sheet is ordered by who actually matters
    proj = {}
    pp = os.path.join(DATA, f"projections_{args.year}_wk{args.week:02d}.csv")
    if os.path.exists(pp):
        with open(pp, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                proj[r["player_id"]] = float(r["half_ppr"])

    q = [r for r in rows if r["report_status"] == "Questionable"]
    q.sort(key=lambda r: -proj.get(r["gsis_id"], 0))

    dest = os.path.join(DATA, f"review_{args.year}_wk{args.week:02d}.csv")
    existing = {}
    if os.path.exists(dest):          # never clobber calls already made
        with open(dest, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("decision") or r.get("note"):
                    existing[r["player_id"]] = (r.get("decision", ""), r.get("note", ""))

    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["player_id", "player", "pos", "team", "injury", "practice",
                    "proj", "decision", "note"])
        for r in q:
            d, n = existing.get(r["gsis_id"], ("", ""))
            w.writerow([r["gsis_id"], r["full_name"], r["position"], r["team"],
                        r["report_primary_injury"],
                        PRACTICE_SHORT.get(r["practice_status"], r["practice_status"] or "-"),
                        round(proj.get(r["gsis_id"], 0), 1), d, n])

    other = collections.Counter(r["report_status"] for r in rows if r["report_status"])
    print(f"\n  week {args.week} judgement calls -- {len(q)} Questionable skill players")
    print(f"  (auto-handled: {other.get('Out', 0)} Out, {other.get('Doubtful', 0)} Doubtful)\n")
    print(f"  {'player':<24}{'pos':<5}{'tm':<5}{'injury':<14}{'practice':<10}{'proj':>6}")
    for r in q[:20]:
        print(f"  {r['full_name']:<24}{r['position']:<5}{r['team']:<5}"
              f"{(r['report_primary_injury'] or '-')[:13]:<14}"
              f"{PRACTICE_SHORT.get(r['practice_status'], '-'):<10}"
              f"{proj.get(r['gsis_id'], 0):>6.1f}")
    if len(q) > 20:
        print(f"  ... and {len(q) - 20} more")
    print(f"\n  -> {os.path.basename(dest)}   (blank decision = treated as PLAY)\n")


if __name__ == "__main__":
    main()
