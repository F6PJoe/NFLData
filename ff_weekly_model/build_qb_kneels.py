#!/usr/bin/env python3
"""Kneel-downs per QB-game, from nflverse play-by-play.

    python build_qb_kneels.py --year 2026
    python build_qb_kneels.py --year 2020 2021 2022 2023 2024 2025 2026

-> data/qb_kneels_<year>.csv (week, team, player_id, kneels, kneel_yds)

Joe, 2026-11-04 ("yes I was going to say take out the kneel downs"). The
official stat line counts a kneel-down as a QB carry -- 0.64 a starter game at
-1.1 yards -- so a pocket passer's carries were half kneels (Stafford 1.0 a
game vs 0.8 real runs) and every QB's yards per carry was dragged down. Kneels
are pure game script (odd-vs-even starts r .15, next game r .07), so the model
takes them out of QB carries, rushing yards and team plays (project.py
KNEELS_OUT) and adds back the league's kneel yards per game.
"""

import argparse
import collections
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UTIL = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")


def build(year):
    src = os.path.join(UTIL, f"pbp_{year}.csv")
    out = collections.defaultdict(lambda: [0, 0.0])
    nameless = 0
    with open(src, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("play_type") != "qb_kneel" or r.get("season_type") != "REG":
                continue
            pid = r.get("rusher_player_id") or r.get("passer_player_id") or ""
            if not pid or pid == "NA":
                nameless += 1
                continue
            k = (int(r["week"]), r["posteam"], pid)
            out[k][0] += 1
            out[k][1] += float(r.get("rushing_yards") or r.get("yards_gained") or 0)
    dest = os.path.join(DATA, f"qb_kneels_{year}.csv")
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["week", "team", "player_id", "kneels", "kneel_yds"])
        for (wk, tm, pid), (n, y) in sorted(out.items()):
            w.writerow([wk, tm, pid, n, round(y, 1)])
    n = sum(v[0] for v in out.values())
    print(f"  {os.path.basename(dest)}  ({n} kneels, {len(out)} QB-games"
          + (f", {nameless} with no player" if nameless else "") + ")")
    return dest


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, nargs="+", required=True)
    for y in ap.parse_args().year:
        build(y)


if __name__ == "__main__":
    main()
