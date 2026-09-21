#!/usr/bin/env python3
"""Build the team-volume and QB layers from nflverse weekly player stats.

Two artifacts, both SLOW-LAYER (they only change after games are played, so
the multi-times-a-day model run reads these from disk and never rebuilds them):

  data/team_weekly_<year>.csv  -- per team-week: plays, pass/rush attempts,
      pass rate, and the QB share of the rush denominator.
  data/qb_weekly_<year>.csv    -- per QB-week: stat line plus that QB's share
      of team pass attempts and team rush attempts.

The QB layer is an INTERNAL reconciliation input, never published. It exists
because team_rush_att (the denominator behind every RB's rush_att_pct)
INCLUDES quarterback carries -- up to ~45% of it on BUF/PHI. Projecting RB
carries without first projecting QB carries silently misprices every mobile-QB
backfield, and misprices it worst exactly when that QB's status changes.

Usage:
    python build_team_qb_features.py --year 2025
"""

import argparse
import collections
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def num(v):
    return float(v) if v not in (None, "") else 0.0


def load(year):
    path = os.path.join(DATA, f"stats_player_week_{year}.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def build(rows):
    """Aggregate to (team, week) totals and collect QB-week stat lines."""
    team = collections.defaultdict(lambda: collections.Counter())
    qbs = []

    for r in rows:
        if r.get("season_type") != "REG":
            continue
        key = (r["team"], int(r["week"]))
        t = team[key]
        att, sacks, carries = num(r["attempts"]), num(r["sacks_suffered"]), num(r["carries"])

        t["pass_att"] += att
        t["sacks"] += sacks
        t["rush_att"] += carries
        t["pass_yds"] += num(r["passing_yards"])
        t["rush_yds"] += num(r["rushing_yards"])
        t["pass_td"] += num(r["passing_tds"])
        t["rush_td"] += num(r["rushing_tds"])
        if r["position"] == "QB":
            t["qb_rush_att"] += carries
            t["qb_pass_att"] += att

        if r["position"] == "QB" and (att or carries):
            qbs.append(r)

    return team, qbs


def write_team(team, year):
    out = os.path.join(DATA, f"team_weekly_{year}.csv")
    cols = ["team", "week", "plays", "pass_att", "sacks", "dropbacks", "rush_att",
            "qb_rush_att", "nonqb_rush_att", "qb_rush_share", "pass_rate",
            "pass_yds", "rush_yds", "pass_td", "rush_td", "total_td"]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for (tm, wk), t in sorted(team.items()):
            dropbacks = t["pass_att"] + t["sacks"]
            plays = dropbacks + t["rush_att"]
            if not plays:
                continue
            w.writerow({
                "team": tm, "week": wk, "plays": int(plays),
                "pass_att": int(t["pass_att"]), "sacks": int(t["sacks"]),
                "dropbacks": int(dropbacks), "rush_att": int(t["rush_att"]),
                "qb_rush_att": int(t["qb_rush_att"]),
                "nonqb_rush_att": int(t["rush_att"] - t["qb_rush_att"]),
                "qb_rush_share": round(t["qb_rush_att"] / t["rush_att"], 4) if t["rush_att"] else 0,
                "pass_rate": round(dropbacks / plays, 4),
                "pass_yds": int(t["pass_yds"]), "rush_yds": int(t["rush_yds"]),
                "pass_td": int(t["pass_td"]), "rush_td": int(t["rush_td"]),
                "total_td": int(t["pass_td"] + t["rush_td"]),
            })
    return out


def write_qb(qbs, team, year):
    out = os.path.join(DATA, f"qb_weekly_{year}.csv")
    cols = ["player_id", "player", "team", "week", "opponent", "pass_att", "comp",
            "pass_yds", "pass_td", "pass_int", "sacks", "air_yards", "adot",
            "rush_att", "rush_yds", "rush_td",
            "team_pass_att", "team_rush_att", "pass_att_share", "rush_att_share"]
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in sorted(qbs, key=lambda r: (r["team"], int(r["week"]))):
            t = team[(r["team"], int(r["week"]))]
            att, air = num(r["attempts"]), num(r["passing_air_yards"])
            w.writerow({
                "player_id": r["player_id"], "player": r["player_display_name"],
                "team": r["team"], "week": int(r["week"]),
                "opponent": r.get("opponent_team", ""),
                "pass_att": int(att), "comp": int(num(r["completions"])),
                "pass_yds": int(num(r["passing_yards"])),
                "pass_td": int(num(r["passing_tds"])),
                "pass_int": int(num(r["passing_interceptions"])),
                "sacks": int(num(r["sacks_suffered"])), "air_yards": int(air),
                "adot": round(air / att, 2) if att else 0,
                "rush_att": int(num(r["carries"])),
                "rush_yds": int(num(r["rushing_yards"])),
                "rush_td": int(num(r["rushing_tds"])),
                "team_pass_att": int(t["pass_att"]), "team_rush_att": int(t["rush_att"]),
                "pass_att_share": round(att / t["pass_att"], 4) if t["pass_att"] else 0,
                "rush_att_share": round(num(r["carries"]) / t["rush_att"], 4) if t["rush_att"] else 0,
            })
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    rows = load(args.year)
    team, qbs = build(rows)
    tp, qp = write_team(team, args.year), write_qb(qbs, team, args.year)
    print(f"  {os.path.basename(tp)}  ({len(team)} team-weeks)")
    print(f"  {os.path.basename(qp)}  ({len(qbs)} QB-weeks)")


if __name__ == "__main__":
    main()
