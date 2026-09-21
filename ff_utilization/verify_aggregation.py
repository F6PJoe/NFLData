#!/usr/bin/env python3
"""Prove the Season view can be rebuilt from weekly rows.

The site shows one table two ways from ONE file: weekly rows as-is, and a
season view aggregated client-side over whatever week range is selected. That
only holds if aggregating weeks N..M locally reproduces what FL's own
`season-stats` endpoint returns for `weeksMin=N&weeksMax=M`.

This runs exactly the aggregation `usage_table.html` does (sum the counting
stats, recompute every rate from summed numerator/denominator -- never average
weekly percentages) and diffs it against FL's own season file.

Usage:
    python fetch_fantasylife_utilization.py --year 2025 --weeks 1-2
    python verify_aggregation.py --year 2025 --weeks 1-2
"""

import argparse
import csv
import collections
from pathlib import Path

HERE = Path(__file__).resolve().parent

SUM_COLS = ["snaps", "routes", "rush_att", "targets", "catchable_tgts",
            "ez_tgts", "inside5_rush", "sdd_snaps", "ldd_snaps",
            "two_min_snaps", "team_snaps", "team_routes", "team_targets",
            "team_rush_att", "team_two_min_snaps", "team_ez_tgts",
            "team_inside5_rush", "team_sdd_snaps", "team_ldd_snaps"]

RATES = {
    "snaps_pct":          ("snaps", "team_snaps"),
    "routes_pct":         ("routes", "team_routes"),
    "rush_att_pct":       ("rush_att", "team_rush_att"),
    "targets_pct":        ("targets", "team_targets"),
    "ez_tgts_pct":        ("ez_tgts", "team_ez_tgts"),
    "inside5_rush_pct":   ("inside5_rush", "team_inside5_rush"),
    "sdd_snaps_pct":      ("sdd_snaps", "team_sdd_snaps"),
    "ldd_snaps_pct":      ("ldd_snaps", "team_ldd_snaps"),
    "two_min_snaps_pct":  ("two_min_snaps", "team_two_min_snaps"),
    "catchable_tgts_pct": ("catchable_tgts", "targets"),
    "tprr":               ("targets", "routes"),
}

COUNT_COLS = ["snaps", "routes", "rush_att", "targets", "catchable_tgts",
              "ez_tgts", "inside5_rush", "sdd_snaps", "ldd_snaps",
              "two_min_snaps"]


def load(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def aggregate(weekly):
    out = {}
    for row in weekly:
        key = row["player_id"]
        acc = out.get(key)
        if acc is None:
            acc = out[key] = {c: 0 for c in SUM_COLS}
            acc["games"] = 0
        acc["games"] += 1
        for col in SUM_COLS:
            acc[col] += float(row.get(col) or 0)
    for acc in out.values():
        for name, (num, den) in RATES.items():
            acc[name] = round(acc[num] / acc[den] * 100, 1) if acc[den] else 0.0
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--weeks", default="1-2")
    ap.add_argument("--tol", type=float, default=1.0,
                    help="percentage-point tolerance for rates (default 1.0)")
    args = ap.parse_args()

    suffix = f"{args.year}_wk{args.weeks.replace('-', '-')}"
    data = HERE / "data"
    weekly = load(data / f"utilization_weekly_{suffix}.csv")
    season = load(data / f"utilization_season_{suffix}.csv")

    agg = aggregate(weekly)
    print(f"aggregated {len(weekly)} weekly rows -> {len(agg)} players")
    print(f"FL season file has {len(season)} players\n")

    missing = counts = rates = 0
    worst = collections.defaultdict(float)
    checked_counts = checked_rates = 0
    notable = []

    for srow in season:
        acc = agg.get(srow["player_id"])
        if acc is None:
            missing += 1
            # Only worth flagging if the player actually did something.
            if int(float(srow["rush_att"])) > 2 or int(float(srow["targets"])) > 5:
                notable.append(f"{srow['player']} ({srow['pos']}, {srow['team']}) "
                               f"rush {srow['rush_att']} tgts {srow['targets']}")
            continue

        for col in COUNT_COLS:
            checked_counts += 1
            got, want = round(acc[col]), int(float(srow[col]))
            if abs(got - want) > 1:            # 1 for FL's own rounding
                counts += 1
                if counts <= 6:
                    print(f"  COUNT {srow['player']:<22} {col:<16} "
                          f"agg {got} vs FL {want}")

        for name in RATES:
            checked_rates += 1
            got, want = acc[name], float(srow[name])
            diff = abs(got - want)
            worst[name] = max(worst[name], diff)
            if diff > args.tol:
                rates += 1
                if rates <= 6:
                    print(f"  RATE  {srow['player']:<22} {name:<20} "
                          f"agg {got} vs FL {want}")

    print(f"counting stats: {checked_counts} checked, {counts} off by >1")
    print(f"rates:          {checked_rates} checked, {rates} off by >{args.tol}pp")
    print("\nworst rate deviation per column (percentage points):")
    for name in sorted(worst, key=lambda k: -worst[k]):
        print(f"  {name:<20} {worst[name]:.1f}")

    # Expected, not a failure: `season-stats` lists some players `game-logs`
    # omits -- fullbacks (Juszczyk, Ingold), emergency/gadget players
    # (Cooper DeJean, Jalen Ramsey), and camp bodies. Every one measured has 0
    # rush attempts and near-zero targets, so FL is filtering game-logs to
    # fantasy-relevant players. They can't appear in a weekly-derived season
    # view, which is fine -- flagged if one ever has real usage.
    print(f"\nin season feed but absent from game-logs: {missing} "
          f"(expected: FBs / gadget players FL filters out)")
    if notable:
        print("  WARNING - some have real usage, investigate:")
        for name in notable:
            print(f"    {name}")

    ok = (counts == 0 and rates == 0 and not notable)
    print("\n" + ("PASS - season view is reproducible from weekly rows"
                  if ok else "FAIL - see deviations above"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
