#!/usr/bin/env python3
"""
Build an auction value table for a team count OTHER than the original
12-team baseline. Uses REAL, validated REPLACEMENT_RANK/VORP_EXPONENT for
team counts that have been calibrated against real market data (see
CALIBRATED below); falls back to a math-only proportional-scaling
approximation for any team count that hasn't been calibrated yet.

## History (see CLAUDE.md for the full account)

First attempt: scale REPLACEMENT_RANK proportionally by team count
(rank * teams/12) from the validated 12-team values, holding
POSITION_BUDGET_SHARE/VORP_EXPONENT constant — a hypothesis, testable
against real market data. Tested at 10 teams: the aggregate position
split held up reasonably (comparable to the 12-team FP/4for4 disagreement
pattern), but individual top-of-position values were badly off (Puka
Nacua $70 estimated vs. $52-62 real; Jahmyr Gibbs $68 vs. $57-61 real) —
holding VORP_EXPONENT constant while shrinking replacement rank
compounded rather than offset, over-concentrating value at the top.

Real recalibration (calibrate_teamcount.py) against actual $200/half-PPR/
10-team data from FantasyPros/4for4/Draft Sharks produced a genuine
surprise: REPLACEMENT_RANK barely moved from the 12-team values (QB
19 [from 16], RB 38 [from 40], WR 54 [unchanged], TE 24 [from 21]) — NOT
the much-shallower QB13/RB33/WR45/TE18 the naive proportional scaling
predicted. Likely explanation: the real games-played curve underlying
Harstad's methodology isn't linear — a modest team-count change (10 vs
12, ~17%) may land in a relatively flat part of that curve, so the
resulting rank shift is much smaller than proportional math assumes.
VORP_EXPONENT moved only modestly too (QB 1.1->1.2, RB 1.1->1.05, WR
unchanged at 1.2, TE 1.0->1.1). Re-verified against the real 10-team data
after applying these: Nacua $53 vs. $52/$54 real, Gibbs $60 vs. $57/$60
real, Josh Allen $22 vs. $24/$24 real — all now closely matched.

Lesson confirmed, not just theorized: proportional scaling is NOT safe to
trust for other team counts without checking. When the user later supplied
a full, internally-consistent set of real $200/half-PPR pulls for all 5
team-count options at once (8/10/12/14/16, all in the same ~45-minute
session — replacing the earlier mixed-vintage 10/12-team-only data), every
one of them needed real recalibration; none behaved as a clean scale-down
from 12. See CALIBRATED below for the final validated numbers, and
CLAUDE.md for the full account, including two real bugs caught along the
way: (1) `calibrate_teamcount.py`'s `score()` had non-deterministic
tie-breaking from Python's per-process hash randomization, occasionally
picking a different "best" candidate across runs of the identical search
— fixed by sorting on `(-value, key)`. (2) The exponent search's
one-position-at-a-time method (holding the other 3 at whatever was in the
production constant at search time, not each other's already-converged
values for THIS team count) let 14-team's RB/WR exponents converge to
values that overshot Gibbs/Chase by $11-12 against every real reference
simultaneously — fixed by iterating to convergence instead of trusting a
single pass.

Usage:
    python build_teamcount_estimate.py <teams>
    python build_teamcount_estimate.py 10
"""

import csv
import sys
from pathlib import Path

from build_auction_values import (
    POINTS_COL, REPLACEMENT_RANK, VORP_EXPONENT, TEAMS as BASELINE_TEAMS,
    blend_with_personal_ranks, load_personal_ranks,
    load_projections, compute_auction_values,
)

# Real, validated calibration per team count (from calibrate_teamcount.py
# against actual market data, all 5 pulled in one consistent session — see
# CLAUDE.md "Round 5"). Every team count in this dict has been verified
# player-by-player against FantasyPros/4for4/Draft Sharks, not just by
# aggregate RMSE (see the module docstring for why that distinction
# matters). Any team count NOT in this dict falls back to proportional
# scaling, clearly flagged as unverified — don't add an entry here without
# doing the real calibration.
CALIBRATED = {
    8: {
        "ranks": {"QB": 15, "RB": 34, "WR": 45, "TE": 16},
        "exponents": {"QB": 1.15, "RB": 1.2, "WR": 1.15, "TE": 1.0},
    },
    10: {
        "ranks": {"QB": 16, "RB": 40, "WR": 54, "TE": 18},
        "exponents": {"QB": 1.0, "RB": 1.2, "WR": 1.15, "TE": 0.9},
    },
    12: {
        "ranks": {"QB": 19, "RB": 44, "WR": 64, "TE": 24},
        "exponents": {"QB": 1.05, "RB": 1.15, "WR": 1.15, "TE": 0.9},
    },
    14: {
        "ranks": {"QB": 19, "RB": 44, "WR": 60, "TE": 24},
        "exponents": {"QB": 0.9, "RB": 0.85, "WR": 1.0, "TE": 0.7},
    },
    16: {
        "ranks": {"QB": 16, "RB": 44, "WR": 60, "TE": 24},
        "exponents": {"QB": 0.7, "RB": 0.7, "WR": 0.85, "TE": 0.5},
    },
}
TEAM_COUNTS = sorted(CALIBRATED)


def scaled_replacement_rank(teams):
    return {pos: max(1, round(rank * teams / BASELINE_TEAMS))
            for pos, rank in REPLACEMENT_RANK.items()}


def write_csv(players, out_file):
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Player", "Position", "Team", "Position Rank", "Auction Value ($)"])
        pos_rank_counter = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
        for p in players:
            pos_rank_counter[p["position"]] += 1
            w.writerow([p["name"], p["position"], p["team"],
                        pos_rank_counter[p["position"]], round(p["auction_value"])])
    print(f"Wrote {len(players)} players to {out_file}")


def main():
    teams = int(sys.argv[1]) if len(sys.argv) > 1 else 10

    if teams in CALIBRATED:
        ranks = CALIBRATED[teams]["ranks"]
        exponents = CALIBRATED[teams]["exponents"]
        print(f"Building VALIDATED estimate for {teams} teams "
              f"(calibrated against real market data — see calibrate_teamcount.py).")
    else:
        ranks = scaled_replacement_rank(teams)
        exponents = VORP_EXPONENT
        print(f"Building UNVALIDATED math-only estimate for {teams} teams "
              f"(proportional scaling from the {BASELINE_TEAMS}-team baseline — "
              f"not yet checked against real market data, treat with caution).")

    print(f"REPLACEMENT_RANK: {ranks}")
    print(f"VORP_EXPONENT: {exponents}")

    projections = load_projections()
    personal_ranks = load_personal_ranks()
    blended = blend_with_personal_ranks(projections, personal_ranks)
    players, pos_stats = compute_auction_values(blended, ranks=ranks, exponents=exponents, teams=teams)

    out_file = Path(__file__).resolve().parent / f"auction_values_{teams}team_half_ppr.csv"
    write_csv(players, out_file)


if __name__ == "__main__":
    main()
