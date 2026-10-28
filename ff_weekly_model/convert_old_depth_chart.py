#!/usr/bin/env python3
"""Convert an OLD-format nflverse depth chart (seasons through 2024) into the
format everything else in ff_weekly_model reads (2025 onward).

Old: one chart per WEEK, players by formation slot, several sharing a rank
     (two "WR 1"s, a fullback listed under RB with depth_position FB).
New: dated SNAPSHOTS, one ordinal rank per position -- dt, team, player_name,
     gsis_id, pos_abb, pos_rank.

Conversion:
  * Offense, regular season only.
  * pos_abb is the position, except a depth_position of FB/F becomes "FB",
    matching the new format, which lists fullbacks separately.
  * Within team-week-position, players are ranked by depth_team, then real
    slots before blank ones, then file order -> ranks 1, 2, 3 ...
  * Each week's chart is dated the day BEFORE that week's first game, so a
    walk-forward backtest only ever sees charts that existed before kickoff.

The original file is kept alongside as depth_charts_<yr>_oldschema.csv.

Usage:
    python convert_old_depth_chart.py --year 2024
"""

import argparse
import collections
import csv
import datetime
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
SKILL = ("QB", "RB", "WR", "TE")


def week_dates(year):
    first = {}
    with open(os.path.join(DATA, "games.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("season") == str(year) and r.get("game_type") == "REG" and r.get("gameday"):
                w = int(r["week"])
                first[w] = min(first.get(w, r["gameday"]), r["gameday"])
    return {w: (datetime.date.fromisoformat(d) - datetime.timedelta(days=1)).isoformat()
            + "T12:00:00Z" for w, d in first.items()}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    path = os.path.join(DATA, f"depth_charts_{args.year}.csv")
    old = path.replace(".csv", "_oldschema.csv")
    src = old if os.path.exists(old) else path
    with open(src, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if "pos_abb" in rows[0]:
        print("  already in the new format -- nothing to do"); return
    if src == path:
        shutil.copyfile(path, old)

    dates = week_dates(args.year)
    groups = collections.defaultdict(list)
    for i, r in enumerate(rows):
        if r.get("formation") != "Offense" or r.get("game_type") != "REG":
            continue
        if r.get("position") not in SKILL or not r.get("gsis_id"):
            continue
        w = int(r["week"])
        if w not in dates:
            continue
        slot = (r.get("depth_position") or "").strip()
        pos = "FB" if slot in ("FB", "F") else r["position"]
        groups[(w, r["club_code"], pos)].append(
            (int(r["depth_team"] or 9), 0 if slot else 1, i, r))

    out = []
    for (w, team, pos), v in groups.items():
        v.sort(key=lambda t: t[:3])
        seen = set()
        rank = 0
        for _, _, _, r in v:
            if r["gsis_id"] in seen:
                continue
            seen.add(r["gsis_id"]); rank += 1
            out.append({"dt": dates[w], "team": team, "player_name": r["full_name"],
                        "espn_id": "", "gsis_id": r["gsis_id"], "pos_grp_id": "",
                        "pos_grp": "", "pos_id": "", "pos_name": pos, "pos_abb": pos,
                        "pos_slot": "", "pos_rank": rank})
    cols = ["dt", "team", "player_name", "espn_id", "gsis_id", "pos_grp_id", "pos_grp",
            "pos_id", "pos_name", "pos_abb", "pos_slot", "pos_rank"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=cols)
        wr.writeheader(); wr.writerows(out)
    print(f"  {len(rows):,} old rows -> {len(out):,} snapshot rows over "
          f"{len({o['dt'] for o in out})} weeks -> {os.path.basename(path)}")


if __name__ == "__main__":
    main()
