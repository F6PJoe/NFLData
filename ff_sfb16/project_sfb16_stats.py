"""Project season-long SFB16 bonus-event occurrence counts per player, from
the same consensus season-total projections the cheat sheet uses
(`ff_draft_proj/consensus_<pos>.csv`).

Season totals alone don't reveal how many individual games/plays clear a
fixed threshold — that depends on game-to-game variance and big-play rate,
calibrated from historical data in calibrate_rates.py. See calibration_params.json.

Writes sfb16_qb.csv / sfb16_rb.csv / sfb16_wr.csv / sfb16_te.csv: every
column from the source consensus CSV, plus new "Exp ..." occurrence-count
columns appended at the end. These are occurrence counts only — SFB16 point
values per bonus and the final point total are left for a later pass.
"""
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

BASE = Path(__file__).resolve().parent
DRAFT_PROJ_DIR = BASE.parent / "ff_draft_proj"
GAMES_PER_SEASON = 17


def _norm_cdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def prob_game_over(threshold, mu_game, sigma):
    """P(per-game yards >= threshold), modeling a game as lognormal with
    mean mu_game and log-scale spread sigma."""
    if mu_game <= 0:
        return 0.0
    mu_log = math.log(mu_game) - sigma**2 / 2
    z = (math.log(threshold) - mu_log) / sigma
    return 1 - _norm_cdf(z)


def expected_games_over(threshold, mu_game, sigma):
    return GAMES_PER_SEASON * prob_game_over(threshold, mu_game, sigma)


def expected_big_plays(opportunities, yards_per_opportunity, slope, intercept):
    if opportunities <= 0:
        return 0.0
    rate = max(0.0, slope * yards_per_opportunity + intercept)
    return opportunities * rate


def _fillna_stat_cols(df, cols):
    """Some consensus sources don't report every stat for every position
    (e.g. WR/TE rushing) — an all-missing stat averages to NaN rather than 0,
    which would otherwise propagate NaN through the math below."""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].fillna(0.0)
    return df


def project_qb(df, params):
    df = _fillna_stat_cols(df, ["Pass Att", "Pass Yds", "Rush Att", "Rush Yds"])
    pass_sigma = params["sigma"]["qb_pass"]
    pass_rate = params["big_play_rate"]["pass"]

    mu_game = df["Pass Yds"] / GAMES_PER_SEASON
    df["Exp 300+ Pass Yd Games"] = mu_game.apply(lambda m: expected_games_over(300, m, pass_sigma)).round(2)
    df["Exp 400+ Pass Yd Games"] = mu_game.apply(lambda m: expected_games_over(400, m, pass_sigma)).round(2)

    ypa = np.where(df["Pass Att"] > 0, df["Pass Yds"] / df["Pass Att"], 0.0)
    df["Exp 40+ Pass Plays"] = [
        round(expected_big_plays(att, y, pass_rate["slope"], pass_rate["intercept"]), 2)
        for att, y in zip(df["Pass Att"], ypa)
    ]

    # QBs who run: scrim yards here is rush yards only — the consensus QB
    # schema has no Rec Yds/Targets columns (QB receiving is essentially
    # nonexistent), so Exp 20+ Yd Rec Plays is always 0 for QBs.
    rush_sigma = params["sigma"]["qb_scrim"]
    rush_rate = params["big_play_rate"]["rush"]

    scrim_mu_game = df["Rush Yds"] / GAMES_PER_SEASON
    df["Exp 100+ Scrim Yd Games"] = scrim_mu_game.apply(lambda m: expected_games_over(100, m, rush_sigma)).round(2)
    df["Exp 200+ Scrim Yd Games"] = scrim_mu_game.apply(lambda m: expected_games_over(200, m, rush_sigma)).round(2)

    ypc = np.where(df["Rush Att"] > 0, df["Rush Yds"] / df["Rush Att"], 0.0)
    df["Exp 40+ Rush Plays"] = [
        round(expected_big_plays(att, y, rush_rate["slope"], rush_rate["intercept"]), 2)
        for att, y in zip(df["Rush Att"], ypc)
    ]
    df["Exp 20+ Yd Rec Plays"] = 0.0
    return df


def project_skill_position(df, position, params):
    df = _fillna_stat_cols(df, ["Rush Att", "Rush Yds", "Targets", "Rec Yds"])
    sigma = params["sigma"][f"{position.lower()}_scrim"]
    rush_rate = params["big_play_rate"]["rush"]
    rec_rate = params["big_play_rate"]["rec"]

    scrim_yds = df["Rush Yds"] + df["Rec Yds"]
    mu_game = scrim_yds / GAMES_PER_SEASON
    df["Exp 100+ Scrim Yd Games"] = mu_game.apply(lambda m: expected_games_over(100, m, sigma)).round(2)
    df["Exp 200+ Scrim Yd Games"] = mu_game.apply(lambda m: expected_games_over(200, m, sigma)).round(2)

    ypc = np.where(df["Rush Att"] > 0, df["Rush Yds"] / df["Rush Att"], 0.0)
    df["Exp 40+ Rush Plays"] = [
        round(expected_big_plays(att, y, rush_rate["slope"], rush_rate["intercept"]), 2)
        for att, y in zip(df["Rush Att"], ypc)
    ]

    ypt = np.where(df["Targets"] > 0, df["Rec Yds"] / df["Targets"], 0.0)
    df["Exp 20+ Yd Rec Plays"] = [
        round(expected_big_plays(tgt, y, rec_rate["slope"], rec_rate["intercept"]), 2)
        for tgt, y in zip(df["Targets"], ypt)
    ]
    return df


if __name__ == "__main__":
    params = json.loads((BASE / "calibration_params.json").read_text())

    qb = pd.read_csv(DRAFT_PROJ_DIR / "consensus_qb.csv")
    qb = project_qb(qb, params)
    qb.to_csv(BASE / "sfb16_qb.csv", index=False)
    print(f"Wrote sfb16_qb.csv ({len(qb)} players)")

    for pos in ["rb", "wr", "te"]:
        df = pd.read_csv(DRAFT_PROJ_DIR / f"consensus_{pos}.csv")
        df = project_skill_position(df, pos.upper(), params)
        df.to_csv(BASE / f"sfb16_{pos}.csv", index=False)
        print(f"Wrote sfb16_{pos}.csv ({len(df)} players)")
