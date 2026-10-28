"""Neutral-situation pass rate per team-game, from play-by-play.

A team's raw pass rate mixes two things: how it WANTS to play, and the game
script it got. A team that trailed by 17 all afternoon threw 45 times, and
that says little about next week. Counting only competitive snaps --
win probability between 20% and 80%, outside the last two minutes of each
half -- isolates the tendency; the game script is handled separately, from
the Vegas spread.

2026 wk2-4 the model under-projected pass attempts by 1.6 a team-game, worst
for teams whose offence changed (GB 51% -> 69% pass rate, CAR 54% -> 65%, LA),
and over-projected the ones that moved the other way (ATL, SF).
"""

import collections
import csv
import os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # research/ -> ff_weekly_model
PBP = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")
WP_LO, WP_HI, CLOCK = 0.20, 0.80, 120


def season(year):
    """(team, week) -> [neutral dropbacks, neutral plays]; cached."""
    cache = os.path.join(HERE, "data", f"neutral_{year}.csv")
    src = os.path.join(PBP, f"pbp_{year}.csv")
    out = {}
    if os.path.exists(cache) and (not os.path.exists(src) or
                                  os.path.getmtime(cache) >= os.path.getmtime(src)):
        with open(cache, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                out[(r["team"], int(r["week"]))] = [int(r["db"]), int(r["plays"])]
        return out
    if not os.path.exists(src):
        return out
    agg = collections.defaultdict(lambda: [0, 0])
    with open(src, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("season_type") != "REG" or r.get("two_point_attempt") == "1":
                continue
            try:
                wp = float(r.get("wp") or "nan")
                secs = float(r.get("half_seconds_remaining") or "nan")
            except ValueError:
                continue
            if not (WP_LO <= wp <= WP_HI) or not secs > CLOCK:
                continue
            db = r.get("qb_dropback") == "1"
            run = r.get("rush") == "1" and not db and r.get("qb_kneel") != "1"
            if not (db or run):
                continue
            a = agg[(r["posteam"], int(r["week"]))]
            a[0] += db
            a[1] += 1
    with open(cache, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["team", "week", "db", "plays"])
        for (tm, wk), (d, n) in agg.items():
            w.writerow([tm, wk, d, n])
    return dict(agg)
