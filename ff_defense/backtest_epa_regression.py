#!/usr/bin/env python3
"""
Backtest: how much should early-season defensive EPA/play be regressed
toward league average before it's trustworthy?

This is the self-owned answer to the problem FTN solves with DAVE (which
is ~98% preseason projection for defense after week 1). Rather than
borrowing someone's preseason projections, shrink each team's observed
EPA toward the league mean by an amount that depends on how many plays
we've actually seen:

    adjusted = (n * observed + k * league_mean) / (n + k)

k is "how many plays of league-average evidence to add." Small k = trust
the observed number quickly; large k = stay near average longer. This
script derives k from history instead of guessing it.

Method: for each team-season, take the first n defensive plays as the
"observed" sample and the REST of that season as the thing we're trying
to predict. Grid-search the k that minimizes RMSE of the shrunken
prediction against that rest-of-season actual, pooled across all
team-seasons.

Also reports the same thing with and without a garbage-time filter, which
tests whether excluding blowout snaps actually makes EPA more predictive
or just feels like it should.

Usage:
    python backtest_epa_regression.py
"""

import numpy as np
import pandas as pd

SEASONS = [2021, 2022, 2023, 2024, 2025]
PBP = "nflverse_data/play_by_play_{season}.csv.gz"
COLS = ["season", "week", "game_id", "play_id", "defteam", "epa", "play_type", "wp"]

SAMPLE_SIZES = [100, 200, 300, 400, 500, 600]
K_GRID = list(range(0, 2001, 25))


def load(filter_garbage):
    frames = []
    for season in SEASONS:
        df = pd.read_csv(PBP.format(season=season), compression="gzip",
                         usecols=COLS, low_memory=False)
        df = df[df["play_type"].isin(["pass", "run"])]
        df = df[df["epa"].notna() & df["defteam"].notna()]
        if filter_garbage:
            df = df[(df["wp"] >= 0.05) & (df["wp"] <= 0.95)]
        frames.append(df)
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["season", "week", "game_id", "play_id"])


def pairs_for(df, n):
    """(observed EPA over first n plays, actual EPA over the rest) per team-season."""
    rows = []
    for (season, team), g in df.groupby(["season", "defteam"], sort=False):
        vals = g["epa"].to_numpy()
        if len(vals) < n + 200:      # need a meaningful holdout to predict
            continue
        rows.append((vals[:n].mean(), vals[n:].mean()))
    return np.array(rows)


for filter_garbage in (False, True):
    label = "competitive plays only" if filter_garbage else "all scrimmage plays"
    df = load(filter_garbage)
    league_mean = df["epa"].mean()
    print(f"\n=== {label} ===")
    print(f"plays: {len(df):,}   league mean EPA/play: {league_mean:+.4f}")
    print(f"{'n plays':>8} {'teams':>6} {'raw corr':>9} {'best k':>7} "
          f"{'RMSE@k':>8} {'RMSE@k=0':>9} {'improve':>8}")
    for n_plays in SAMPLE_SIZES:
        p = pairs_for(df, n_plays)
        if len(p) < 30:
            continue
        obs, future = p[:, 0], p[:, 1]
        corr = np.corrcoef(obs, future)[0, 1]
        best_kv, best_rmse = None, np.inf
        for k in K_GRID:
            pred = (obs * n_plays + k * league_mean) / (n_plays + k)
            rmse = np.sqrt(np.mean((pred - future) ** 2))
            if rmse < best_rmse:
                best_kv, best_rmse = k, rmse
        rmse0 = np.sqrt(np.mean((obs - future) ** 2))
        print(f"{n_plays:>8} {len(p):>6} {corr:>9.3f} {best_kv:>7} "
              f"{best_rmse:>8.4f} {rmse0:>9.4f} {100*(rmse0-best_rmse)/rmse0:>7.1f}%")
