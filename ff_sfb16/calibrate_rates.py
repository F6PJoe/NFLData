"""Calibrate the two statistical models used to project SFB16 bonus-event
occurrence counts, from the cached historical data in
historical_weekly.csv / historical_pbp_plays.csv (see fetch_historical_data.py).

Writes calibration_params.json:
  sigma: per-position lognormal sigma for per-game yardage (captures
    game-to-game variance independent of a player's average, so we can
    estimate how often they clear a fixed yardage threshold).
  big_play_rate: per-play-type linear fit of (play rate per opportunity)
    vs. (yards per opportunity) — more efficient players post more big
    plays per attempt/target, not just a flat league rate. "pass"/"rush"
    are 40+ yard buckets; "rec" is a 20+ yard bucket (this league's
    receiving bonus threshold is lower than its passing/rushing one).

Both models weight by season recency (SEASON_WEIGHTS, a Marcel-style 5:4:3
ratio favoring the most recent of the 3 seasons) and, for the rate fits,
by sample size (sqrt of that player-season's opportunities) — so an
injury-shortened or backup-spot-start season isn't specially detected, it's
just naturally down-weighted for having fewer qualifying attempts/targets,
same as any small sample would be.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
MIN_GAMES_FOR_SIGMA = 8
MIN_OPPORTUNITIES = {"pass": 50, "rush": 20, "rec": 20}

# Recency weighting, Marcel-style ratio (most recent season weighted highest).
# Update this if the season range in fetch_historical_data.py ever changes.
SEASON_WEIGHTS = {2024: 5, 2023: 4, 2022: 3}


def _pooled_log_sigma(df, value_col, group_cols, season_col="season"):
    """Pool log(value+1) residuals (value minus that player-season's own
    mean in log space) across all qualifying player-seasons, return the
    season-recency-weighted std. Each game is already one row, so games
    naturally carry more total weight for players with bigger samples —
    only the recency multiplier needs to be applied explicitly here."""
    logs = np.log(np.maximum(df[value_col], 0) + 1)
    group_mean = logs.groupby([df[c] for c in group_cols]).transform("mean")
    residuals = logs - group_mean
    weights = df[season_col].map(SEASON_WEIGHTS).astype(float)
    weighted_var = float((weights * residuals**2).sum() / weights.sum())
    return weighted_var**0.5


def calibrate_sigmas(weekly):
    weekly = weekly[weekly["week"] <= 18]  # regular season only, drop playoffs
    sigmas = {}

    qb = weekly[(weekly["position"] == "QB") & (weekly["attempts"] > 0)].copy()
    qb_counts = qb.groupby(["player_id", "season"]).size()
    qb_keep = qb_counts[qb_counts >= MIN_GAMES_FOR_SIGMA].index
    qb = qb.set_index(["player_id", "season"]).loc[qb.set_index(["player_id", "season"]).index.isin(qb_keep)].reset_index()
    sigmas["qb_pass"] = _pooled_log_sigma(qb, "passing_yards", ["player_id", "season"])

    # QB rush+rec ("scrim") yards/game — separate from RB/WR/TE since a
    # running QB's week-to-week scramble/rush yardage has a different
    # variance profile than a feature back's.
    qb_scrim = weekly[(weekly["position"] == "QB") & ((weekly["carries"] > 0) | (weekly["targets"] > 0))].copy()
    qb_scrim["scrim_yards"] = qb_scrim["rushing_yards"] + qb_scrim["receiving_yards"]
    qb_scrim_counts = qb_scrim.groupby(["player_id", "season"]).size()
    qb_scrim_keep = qb_scrim_counts[qb_scrim_counts >= MIN_GAMES_FOR_SIGMA].index
    qb_scrim = qb_scrim.set_index(["player_id", "season"]).loc[
        qb_scrim.set_index(["player_id", "season"]).index.isin(qb_scrim_keep)
    ].reset_index()
    sigmas["qb_scrim"] = _pooled_log_sigma(qb_scrim, "scrim_yards", ["player_id", "season"])

    for pos in ["RB", "WR", "TE"]:
        df = weekly[(weekly["position"] == pos) & ((weekly["carries"] > 0) | (weekly["targets"] > 0))].copy()
        df["scrim_yards"] = df["rushing_yards"] + df["receiving_yards"]
        counts = df.groupby(["player_id", "season"]).size()
        keep = counts[counts >= MIN_GAMES_FOR_SIGMA].index
        df = df.set_index(["player_id", "season"]).loc[df.set_index(["player_id", "season"]).index.isin(keep)].reset_index()
        sigmas[f"{pos.lower()}_scrim"] = _pooled_log_sigma(df, "scrim_yards", ["player_id", "season"])

    return sigmas


def _fit_bucket_rate(weekly, pbp, opp_col, yds_col, pbp_play_type, pbp_player_col,
                      min_opportunities, low, high=None):
    """Linear fit of (plays landing in [low, high] yards / opportunities)
    vs. yards-per-opportunity, for one player/play-type combination. high=None
    means "low or more" (open-ended bucket, e.g. 40+)."""
    season = weekly.groupby(["player_id", "season"]).agg(
        opportunities=(opp_col, "sum"), yards=(yds_col, "sum")
    ).reset_index()
    season = season[season["opportunities"] >= min_opportunities]
    season["ypo"] = season["yards"] / season["opportunities"]

    mask = (pbp["play_type"] == pbp_play_type) & (pbp["yards_gained"] >= low)
    if high is not None:
        mask &= pbp["yards_gained"] <= high
    bucket_counts = pbp[mask].groupby([pbp_player_col, "season"]).size().rename("bucket_plays")

    season = season.merge(
        bucket_counts, left_on=["player_id", "season"], right_index=True, how="left"
    )
    season["bucket_plays"] = season["bucket_plays"].fillna(0)
    season["rate"] = season["bucket_plays"] / season["opportunities"]

    # Weight each player-season by recency (Marcel-style ratio) and by
    # sample size (sqrt of opportunities, so a 380-carry workhorse doesn't
    # swamp a 60-carry committee back, but still counts for more than them).
    # This is the standard fix for injury-shortened/small-sample seasons:
    # rather than guessing which seasons were "hurt," a season with fewer
    # qualifying opportunities is automatically down-weighted on its own.
    recency = season["season"].map(SEASON_WEIGHTS).astype(float)
    weights = recency * np.sqrt(season["opportunities"])

    slope, intercept = np.polyfit(season["ypo"], season["rate"], 1, w=weights)
    return {"slope": float(slope), "intercept": float(intercept)}


def calibrate_big_play_rates(weekly, pbp):
    weekly = weekly[weekly["week"] <= 18]
    rates = {}

    # Passing 40+ plays vs. yards-per-attempt
    rates["pass"] = _fit_bucket_rate(
        weekly, pbp, "attempts", "passing_yards", "pass", "passer_player_id",
        MIN_OPPORTUNITIES["pass"], low=40,
    )

    # Rushing 40+ plays vs. yards-per-carry
    rates["rush"] = _fit_bucket_rate(
        weekly, pbp, "carries", "rushing_yards", "run", "rusher_player_id",
        MIN_OPPORTUNITIES["rush"], low=40,
    )

    # Receiving 20+ yard catches vs. yards-per-target. This league's bonus
    # is a single "20+ yard reception" bracket worth 10 pts — Sleeper's API
    # happens to expose it as three internal sub-ranges (rec_20_29/30_39/40p)
    # that are all worth 10 and partition the same 20+ population, not three
    # separate stacking bonuses, so one combined >=20 threshold is correct.
    rates["rec"] = _fit_bucket_rate(
        weekly, pbp, "targets", "receiving_yards", "pass", "receiver_player_id",
        MIN_OPPORTUNITIES["rec"], low=20,
    )

    return rates


if __name__ == "__main__":
    weekly = pd.read_csv(BASE / "historical_weekly.csv")
    pbp = pd.read_csv(BASE / "historical_pbp_plays.csv")

    sigmas = calibrate_sigmas(weekly)
    big_play_rates = calibrate_big_play_rates(weekly, pbp)

    params = {"sigma": sigmas, "big_play_rate": big_play_rates}
    out_path = BASE / "calibration_params.json"
    out_path.write_text(json.dumps(params, indent=2))

    print(json.dumps(params, indent=2))
    print(f"\nWrote {out_path}")
