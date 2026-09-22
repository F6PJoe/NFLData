#!/usr/bin/env python3
"""
Build a self-owned "how good is this defense" rating for column G -- the
replacement for FTN's DAVE.

This is a general quality rating, deliberately, not a narrow stat. It
blends two per-play measures from nflverse's free play-by-play:

  * EPA/play allowed      -- value surrendered per play
  * Success rate allowed  -- how often the offense wins a down

Success rate is included because it's conceptually what DVOA is built on
underneath, and it backtests better than EPA early in the season (corr to
rest-of-season at 100 plays: 0.220 vs 0.118). The 50/50 z-blend is the
most stable of the three options late (0.316 at 600 plays vs 0.297 EPA /
0.276 success), and competitive early.

THE PRESEASON PRIOR IS THE OTHER HALF. Defensive performance barely
carries over -- last season predicts this season at only 0.169 -- so a
few games of data is mostly noise. Rather than shrink toward league
average (which makes every team nearly identical, leaving the 1-32
ranking to be decided by that noise), observed play is blended with Joe's
own preseason defensive ranks, exactly the role FTN's preseason
projections play inside DAVE.

Backtested: blending a weak prior (rho ~= 0.15, the level Joe's ranks
plausibly sit at) beats BOTH components on ranking correlation --

    after 100 plays: observed 0.118, prior 0.161, blended 0.204
    after 300 plays: observed 0.223, prior 0.155, blended 0.276

Note this is a RANKING result. An earlier RMSE test suggested a prior
needed rho >= 0.45 to be worth using, but that measured value accuracy,
and this tool only ever uses the rank -- a distinction that flips the
conclusion.

K_PRIOR = 100 plays, the backtested optimum (see backtest_prior_decay.py):
the prior carries the rating in September and fades to a low single-digit
weight by December without ever being switched off.

Rank convention matches the column it replaces: 1 = worst defense,
32 = best, so higher is better, same as everywhere else on the sheet.

Usage:
    python fetch_def_rating.py          # -> def_rating.csv

Requires: pandas, requests
"""

import argparse
import csv
import datetime
import os

import pandas as pd

from fetch_nflverse_epa import fetch_pbp
from team_names import normalize

PRESEASON_FILE = "preseason_def_ranks.csv"

# Backtested in backtest_prior_decay.py over 2021-25. K=300 was too heavy --
# it left the prior at 28% of the rating in week 13 and lost to a lower K in
# every part of the season. K=100 and K=150 tie on accuracy; 100 is used
# because it decays faster (45% at week 2, 25% by week 5, 11% by week 13).
#
# Deliberately NOT ramped to zero. Every ramp-to-zero schedule tested lost to
# a small constant prior, and a DAVE-style week-13 cliff barely beat using no
# prior at all. Past ~600 plays the prior is worth ~12%, where it acts as mild
# regularization rather than a preseason opinion -- removing it measurably
# costs ranking accuracy.
K_PRIOR = 100

FIELDNAMES = ["Rank", "Team", "Rating", "EpaAllowed", "SuccessAllowed",
              "PreseasonRank", "Plays"]


def load_preseason():
    """Joe's preseason defensive ranks, 1 = best."""
    if not os.path.exists(PRESEASON_FILE):
        print(f"[WARN] {PRESEASON_FILE} not found -- falling back to league "
              "average as the prior (rankings will be noisy early season).")
        return {}
    with open(PRESEASON_FILE, newline="", encoding="utf-8") as f:
        return {normalize(r["Team"]): int(r["Rank"]) for r in csv.DictReader(f)}


def zscore(s):
    return (s - s.mean()) / s.std(ddof=0)


def build_rows(plays, preseason):
    # Normalize BEFORE grouping: nflverse carries both "LA" and "LAR" for
    # the Rams across seasons, and renaming after the fact would leave two
    # half-sized rows for the same team.
    plays = plays.assign(team=[normalize(t) for t in plays["defteam"]])
    g = plays.groupby("team").agg(
        EpaAllowed=("epa", "mean"),
        SuccessAllowed=("success", "mean"),
        Plays=("epa", "size"),
    )

    # Observed quality: higher = better defense, so flip the sign on both
    # (less EPA allowed and a lower success rate allowed are both good).
    observed = -(zscore(g["EpaAllowed"]) + zscore(g["SuccessAllowed"])) / 2

    if preseason:
        # Preseason rank 1 = best. Map to the same z-ish scale, higher =
        # better, so it can be blended directly against observed.
        pr = pd.Series({t: preseason.get(t) for t in g.index}, dtype="float")
        if pr.isna().any():
            missing = sorted(pr[pr.isna()].index)
            print(f"[WARN] no preseason rank for {missing} -- using league average "
                  "for those teams.")
            pr = pr.fillna(pr.mean())
        prior = -zscore(pr)          # rank 1 -> highest value
    else:
        prior = pd.Series(0.0, index=g.index)

    n = g["Plays"]
    rating = (observed * n + prior * K_PRIOR) / (n + K_PRIOR)

    out = pd.DataFrame({
        "Rating": rating, "EpaAllowed": g["EpaAllowed"],
        "SuccessAllowed": g["SuccessAllowed"], "Plays": n,
    })
    out["PreseasonRank"] = [preseason.get(t, "") for t in out.index]
    # Ascending: worst defense (lowest rating) gets rank 1, best gets 32 --
    # the same direction as the Def DAVE column this replaces.
    out = out.sort_values("Rating")
    out["Rank"] = range(1, len(out) + 1)

    weight = float((n / (n + K_PRIOR)).mean())
    print(f"Prior weight: observed play is {weight*100:.0f}% of the rating right now "
          f"(k={K_PRIOR} plays, avg {n.mean():.0f} plays/team).")

    rows = []
    for team, r in out.iterrows():
        rows.append({
            "Rank": int(r["Rank"]), "Team": team,
            "Rating": round(r["Rating"], 4),
            "EpaAllowed": round(r["EpaAllowed"], 4),
            "SuccessAllowed": round(r["SuccessAllowed"], 4),
            "PreseasonRank": r["PreseasonRank"], "Plays": int(r["Plays"]),
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--out", default="def_rating.csv")
    args = ap.parse_args()

    plays = fetch_pbp(args.year, extra_cols=["success"])
    plays = plays[plays["success"].notna() & plays["defteam"].notna()]
    rows = build_rows(plays, load_preseason())
    if len(rows) < 28:
        raise SystemExit(f"Only {len(rows)} teams found -- expected ~32.")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} teams to {args.out} "
          f"(rank 1 = worst defense, {len(rows)} = best).")


if __name__ == "__main__":
    main()
