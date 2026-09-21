#!/usr/bin/env python3
"""
Build the small PUBLIC teaser file for non-members.

Reads the same published data the members' table uses and keeps only:
  * every RB/WR/TE, no player-count cap (see below) -- non-members get a real
    filter row (Position/Team/Search) in component_teaser.html, so there's no
    "top N" list to browse instead.
  * the columns the user is fine giving away for free: Snaps, Rush, Targets,
    Rec. His own reasoning: seeing four raw counting stats isn't enough of
    the actual product to justify ALSO capping how many players show up or
    hiding the filter row -- both of those restrictions existed only to ration
    a small list, and once the list isn't small there's nothing left to ration.
    Everything else (every %, Routes, I5, EZ, ADOT) is the actual product and
    stays locked.

This file must NOT go through the s2member gateway -- that gateway checks
membership before serving ANYTHING in its folder, so a non-member can't reach
it there even if the file itself is harmless. It needs its own plain, public,
FIXED path (see the printed upload instructions).

Two views, matching the member table's Weekly/Season split:
  weekly  every RB/WR/TE from the MOST RECENT week only
  season  every RB/WR/TE by SUMMED snaps/rush/targets/rec across every week
          present in the published file -- a plain sum, no rate to recompute,
          because none of the four shown columns is a percentage. That's what
          makes this simpler than the member table's season aggregation:
          nothing here is a ratio, so there's no numerator/denominator to
          keep paired.

--top is still available (e.g. for a smaller manual preview) but defaults to
no cap -- pass it explicitly to go back to a top-N-per-position list.

Usage:
    python build_teaser.py --year 2026 --weeks 1-1 --view weekly
    python build_teaser.py --year 2026 --weeks 1-1 --view season
"""

import argparse
import collections
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

# Order matters -- teaser column order on the page.
COLUMNS = ["player", "team", "pos", "snaps", "rush_att", "targets", "rec"]

OUT_NAME = {"weekly": "utilization_teaser_weekly.json",
            "season": "utilization_teaser_season.json"}


def rows_for_weekly(rows):
    latest = max(int(r["week"]) for r in rows)
    return [r for r in rows if int(r["week"]) == latest], f"Week {latest}"


def rows_for_season(rows):
    weeks = sorted({int(r["week"]) for r in rows})
    agg = {}
    for r in rows:
        key = (r["player"], r["team"], r["pos"])
        a = agg.setdefault(key, {"player": r["player"], "team": r["team"],
                                 "pos": r["pos"], "snaps": 0, "rush_att": 0,
                                 "targets": 0, "rec": 0})
        a["snaps"] += int(r["snaps"])
        a["rush_att"] += int(r["rush_att"])
        a["targets"] += int(r["targets"])
        a["rec"] += int(r["rec"])
    label = (f"Week {weeks[0]}" if len(weeks) == 1
             else f"Weeks {weeks[0]}-{weeks[-1]}")
    return list(agg.values()), f"Season ({label})"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--weeks", default="1-1")
    ap.add_argument("--view", choices=("weekly", "season"), default="weekly")
    ap.add_argument("--top", type=int, default=None,
                    help="cap to N players per position (default: no cap -- "
                         "the teaser has its own Position/Team/Search filter "
                         "row now, so there's no need to pre-trim the list)")
    args = ap.parse_args()

    src = DATA / f"published_{args.year}_wk{args.weeks}.csv"
    with open(src, encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))

    rows, label = (rows_for_weekly(rows) if args.view == "weekly"
                   else rows_for_season(rows))

    by_pos = collections.defaultdict(list)
    for r in rows:
        by_pos[r["pos"]].append(r)

    out = []
    for pos in ("RB", "WR", "TE"):
        ranked = sorted(by_pos.get(pos, []), key=lambda r: -int(r["snaps"]))
        out.extend(ranked[:args.top] if args.top else ranked)

    payload_rows = [[r["player"], r["team"], r["pos"], int(r["snaps"]),
                     int(r["rush_att"]), int(r["targets"]), int(r["rec"])]
                    for r in out]

    payload = {"cols": COLUMNS, "rows": payload_rows, "label": label, "top": args.top}
    out_path = DATA / OUT_NAME[args.view]
    out_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    cap_desc = f"top {args.top} per position x 3 positions" if args.top else "no cap"
    print(f"[{args.view}] {label}: {len(payload_rows)} players ({cap_desc})")
    print(f"{out_path.name}  ({out_path.stat().st_size/1024:.1f} KB)")
    print(f"\nUPLOAD -> a PLAIN PUBLIC path, e.g. "
          f"/wp-content/uploads/f6p-data/{out_path.name}")
    print("NOT the s2member-files gateway -- that requires membership to "
          "reach ANY file in it, including this one.")


if __name__ == "__main__":
    main()
