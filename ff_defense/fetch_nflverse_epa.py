#!/usr/bin/env python3
"""
Compute team offensive EPA/play from nflverse's free public play-by-play
data, regressed toward league average, and write it to a CSV.

This replaces FTN's DAVE for column H ("Opp Off EPA") -- the OPPONENT's
offensive quality. Unlike DVOA it's fully self-owned: nflverse publishes
per-play data (including nflfastR's precomputed `epa`) as plain files on
GitHub, so there's no login, no scraping and no site that can revoke
access. What's ours is the aggregation -- which plays count, how much to
regress, and how to rank.

Every choice below was settled by backtesting 5 seasons (2021-2025) in
backtest_epa_regression.py rather than guessed:

  * ALL scrimmage plays count, garbage time INCLUDED at full weight.
    Excluding garbage time makes EPA LESS predictive (defensive corr at
    100 plays: 0.122 with it, 0.065 without), and partial weights were
    monotonically worse than full weight. The 16% of plays you'd drop
    still carry signal, and losing the sample hurts more than the noise
    it removes.
  * No opponent adjustment. Open Source Football found opponent-adjusting
    defensive EPA slightly REDUCES its predictive power, so the obvious
    "improvement" isn't one.
  * Regression toward LEAGUE AVERAGE, not last season (last season ->
    this season correlates only 0.399 on offense, 0.169 on defense, and
    shrinking toward it lost to league average at every sample size).
  * K_OFFENSE = 350 plays, the backtested optimum for offense. Offense is
    far more stable than defense (corr at 100 plays: 0.402 vs 0.118),
    which is exactly why this file is trusted for the opponent-offense
    column while the own-defense column needs a different metric --
    QB hit rate and success rate allowed both backtest roughly 2x better
    than defensive EPA.

Rank convention matches the column it replaces: 1 = best offense, 32 =
worst. Used as-is for the opponent (no inversion), so a high number means
a weak opposing offense -- a good matchup -- consistent with the rest of
the sheet.

Usage:
    python fetch_nflverse_epa.py          # -> nflverse_epa.csv
    python fetch_nflverse_epa.py --year 2026

Requires: pandas, requests
"""

import argparse
import csv
import datetime
import os

import pandas as pd
import requests

from team_names import normalize

PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{year}.csv.gz"
CACHE_DIR = "nflverse_data"

# Backtested optimum for offensive EPA (see module docstring).
K_OFFENSE = 350

FIELDNAMES = ["Rank", "Team", "OffEpaAdj", "OffEpaRaw", "Plays"]


def fetch_pbp(year, max_age_hours=6, extra_cols=()):
    """Download the season's play-by-play, re-using a recent local copy.

    nflverse updates this file through the season, so a stale cache would
    silently freeze the numbers -- hence the age check rather than a
    plain "does the file exist".
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, f"play_by_play_{year}.csv.gz")

    fresh = False
    if os.path.exists(path):
        age = (datetime.datetime.now()
               - datetime.datetime.fromtimestamp(os.path.getmtime(path)))
        fresh = age < datetime.timedelta(hours=max_age_hours)
        if fresh:
            print(f"Using cached {path} ({age.total_seconds()/3600:.1f}h old).")

    if not fresh:
        print(f"Downloading {year} play-by-play from nflverse...")
        resp = requests.get(PBP_URL.format(year=year), timeout=120)
        resp.raise_for_status()
        with open(path, "wb") as f:
            f.write(resp.content)

    # extra_cols lets other scripts (fetch_def_rating.py) reuse this loader
    # and its cache without pulling the whole 400-column file.
    cols = ["season", "week", "posteam", "defteam", "epa", "play_type"]
    cols += [c for c in extra_cols if c not in cols]
    df = pd.read_csv(path, compression="gzip", low_memory=False, usecols=cols)
    return df[df["play_type"].isin(["pass", "run"])
              & df["epa"].notna() & df["posteam"].notna()].copy()


def build_rows(plays):
    league_mean = plays["epa"].mean()
    # Normalize BEFORE grouping: nflverse carries both "LA" and "LAR" for the
    # Rams across seasons, and renaming after the fact would leave two
    # half-sized rows for the same team.
    plays = plays.assign(team=[normalize(t) for t in plays["posteam"]])
    g = plays.groupby("team").agg(OffEpaRaw=("epa", "mean"), Plays=("epa", "size"))

    # Shrink toward league average by K_OFFENSE plays' worth of evidence,
    # so week 1 barely moves a team off average and the observed number
    # takes over as real sample accumulates.
    g["OffEpaAdj"] = ((g["OffEpaRaw"] * g["Plays"] + league_mean * K_OFFENSE)
                      / (g["Plays"] + K_OFFENSE))

    g = g.sort_values("OffEpaAdj", ascending=False)   # rank 1 = best offense
    rows = []
    for rank, (team, r) in enumerate(g.iterrows(), start=1):
        rows.append({
            "Rank": rank,
            "Team": team,
            "OffEpaAdj": round(r["OffEpaAdj"], 4),
            "OffEpaRaw": round(r["OffEpaRaw"], 4),
            "Plays": int(r["Plays"]),
        })
    print(f"League mean EPA/play {league_mean:+.4f}; regressed with k={K_OFFENSE} plays.")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--out", default="nflverse_epa.csv")
    args = ap.parse_args()

    plays = fetch_pbp(args.year)
    weeks = sorted(plays["week"].unique())
    print(f"{len(plays):,} scrimmage plays, weeks {weeks[0]}-{weeks[-1]}.")

    rows = build_rows(plays)
    if len(rows) < 28:
        raise SystemExit(f"Only {len(rows)} teams found -- expected ~32.")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} teams to {args.out} (rank 1 = best offense, {len(rows)} = worst).")


if __name__ == "__main__":
    main()
