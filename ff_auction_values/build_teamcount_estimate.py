#!/usr/bin/env python3
"""
Build an auction value table for a (team count, scoring format) combination
OTHER than the original 12-team/half-PPR baseline. Uses REAL, validated
REPLACEMENT_RANK/VORP_EXPONENT/POSITION_BUDGET_SHARE for combinations that
have been calibrated against real market data (see CALIBRATED below); falls
back to a math-only proportional-scaling approximation (from that format's
own 12-team baseline) for any team count that hasn't been calibrated yet.

## History (see CLAUDE.md for the full account)

Team count (half-PPR only, "Round 5"): proportional rank scaling was tested
first and failed against real data for every team count checked — real
recalibration (calibrate_teamcount.py) was needed for all 5 team counts,
none behaved as a clean scale-down from 12. See CLAUDE.md "Round 5" for the
full account, including two real bugs caught in the calibration tooling:
(1) non-deterministic scoring tie-breaks from Python's hash randomization,
fixed by sorting on `(-value, key)`; (2) an exponent-search methodology bug
that let some team counts' RB/WR exponents overshoot real prices by
$11-12 before being caught by individual-player verification.

Scoring format (STD/PPR, added later — this file's CALIBRATED dict now
holds all 5 team counts x 3 formats = 15 combinations): unlike team count,
POSITION_BUDGET_SHARE genuinely does shift by scoring format (real auction
markets pay noticeably more for RB in STD leagues and more for WR in full
PPR — a well-known effect, not a project-specific finding), so it's no
longer a single constant — see FORMAT_BUDGET_SHARE in calibrate_teamcount.py
(the format-level average across all 5 team counts, since team count itself
still doesn't move budget share meaningfully within a format).

**Real bug caught and fixed during the STD/PPR calibration round**: the
rank/exponent grid search was initially run using the OLD half-PPR
POSITION_BUDGET_SHARE default for every format (a real budget-share
override existed as a compute_auction_values() parameter but the search
loop never actually passed it in) — calibrating against the wrong-sized
dollar pool let the exponent search silently over-concentrate value at the
top to compensate, then overshot badly once the correct, larger real
budget share was applied afterward (Gibbs $67/Bijan $66 at 12-team STD,
vs. $56-61/$53-63 real — a $10+ miss). Fixed by computing the real
per-format budget share FIRST and using it consistently throughout the
entire search, not just for reporting. Re-verified after the fix: same two
players landed at $61/$61, squarely inside the real reference spread.

Usage:
    python build_teamcount_estimate.py <teams> <format>
    python build_teamcount_estimate.py 10 half_ppr
    python build_teamcount_estimate.py 12 std
"""

import csv
import sys
from pathlib import Path

from build_auction_values import (
    POINTS_COL, REPLACEMENT_RANK, VORP_EXPONENT, POSITION_BUDGET_SHARE,
    TEAMS as BASELINE_TEAMS,
    blend_with_personal_ranks, load_personal_ranks,
    load_projections, compute_auction_values,
)

FORMATS = ["std", "half_ppr", "ppr"]

# Format-level budget share — see calibrate_teamcount.py's FORMAT_BUDGET_SHARE
# comment for why this varies by format but not by team count.
_STD_SHARE = {"QB": 0.0608, "RB": 0.4629, "WR": 0.4014, "TE": 0.0750}
_PPR_SHARE = {"QB": 0.0538, "RB": 0.4120, "WR": 0.4584, "TE": 0.0759}

# Real, validated calibration per (teams, format), from calibrate_teamcount.py
# against actual market data. Every combination here has been verified
# player-by-player against FantasyPros/4for4/Draft Sharks, not just by
# aggregate RMSE (see the module docstring for why that distinction
# matters). Any combination NOT in this dict falls back to proportional
# scaling from that format's own 12-team baseline, clearly flagged as
# unverified — don't add an entry here without doing the real calibration.
CALIBRATED = {
    (8, "half_ppr"): {
        "ranks": {"QB": 15, "RB": 34, "WR": 45, "TE": 16},
        "exponents": {"QB": 1.15, "RB": 1.2, "WR": 1.15, "TE": 1.0},
        "budget_share": POSITION_BUDGET_SHARE,
    },
    (10, "half_ppr"): {
        "ranks": {"QB": 16, "RB": 40, "WR": 54, "TE": 18},
        "exponents": {"QB": 1.0, "RB": 1.2, "WR": 1.15, "TE": 0.9},
        "budget_share": POSITION_BUDGET_SHARE,
    },
    (12, "half_ppr"): {
        "ranks": {"QB": 19, "RB": 44, "WR": 64, "TE": 24},
        "exponents": {"QB": 1.05, "RB": 1.15, "WR": 1.15, "TE": 0.9},
        "budget_share": POSITION_BUDGET_SHARE,
    },
    (14, "half_ppr"): {
        "ranks": {"QB": 19, "RB": 44, "WR": 60, "TE": 24},
        "exponents": {"QB": 0.9, "RB": 0.85, "WR": 1.0, "TE": 0.7},
        "budget_share": POSITION_BUDGET_SHARE,
    },
    (16, "half_ppr"): {
        "ranks": {"QB": 16, "RB": 44, "WR": 60, "TE": 24},
        "exponents": {"QB": 0.7, "RB": 0.7, "WR": 0.85, "TE": 0.5},
        "budget_share": POSITION_BUDGET_SHARE,
    },
    (8, "std"): {
        "ranks": {"QB": 14, "RB": 36, "WR": 40, "TE": 16},
        "exponents": {"QB": 1.05, "RB": 1.2, "WR": 1.15, "TE": 1.0},
        "budget_share": _STD_SHARE,
    },
    (10, "std"): {
        "ranks": {"QB": 16, "RB": 36, "WR": 55, "TE": 18},
        "exponents": {"QB": 1.1, "RB": 1.05, "WR": 1.15, "TE": 0.9},
        "budget_share": _STD_SHARE,
    },
    (12, "std"): {
        "ranks": {"QB": 20, "RB": 44, "WR": 65, "TE": 24},
        "exponents": {"QB": 1.2, "RB": 1.15, "WR": 1.15, "TE": 0.9},
        "budget_share": _STD_SHARE,
    },
    (14, "std"): {
        "ranks": {"QB": 20, "RB": 52, "WR": 70, "TE": 26},
        "exponents": {"QB": 1.05, "RB": 1.15, "WR": 1.2, "TE": 0.9},
        "budget_share": _STD_SHARE,
    },
    (16, "std"): {
        "ranks": {"QB": 18, "RB": 60, "WR": 80, "TE": 30},
        "exponents": {"QB": 1.05, "RB": 1.15, "WR": 1.15, "TE": 0.8},
        "budget_share": _STD_SHARE,
    },
    (8, "ppr"): {
        "ranks": {"QB": 14, "RB": 36, "WR": 45, "TE": 14},
        "exponents": {"QB": 1.0, "RB": 1.2, "WR": 1.2, "TE": 1.0},
        "budget_share": _PPR_SHARE,
    },
    (10, "ppr"): {
        "ranks": {"QB": 18, "RB": 40, "WR": 55, "TE": 18},
        "exponents": {"QB": 1.2, "RB": 1.3, "WR": 1.15, "TE": 0.9},
        "budget_share": _PPR_SHARE,
    },
    (12, "ppr"): {
        "ranks": {"QB": 20, "RB": 44, "WR": 60, "TE": 24},
        "exponents": {"QB": 1.1, "RB": 1.15, "WR": 1.15, "TE": 1.0},
        "budget_share": _PPR_SHARE,
    },
    (14, "ppr"): {
        "ranks": {"QB": 20, "RB": 52, "WR": 65, "TE": 28},
        "exponents": {"QB": 1.0, "RB": 1.15, "WR": 1.1, "TE": 1.0},
        "budget_share": _PPR_SHARE,
    },
    (16, "ppr"): {
        "ranks": {"QB": 20, "RB": 60, "WR": 75, "TE": 30},
        "exponents": {"QB": 1.0, "RB": 1.15, "WR": 1.15, "TE": 1.0},
        "budget_share": _PPR_SHARE,
    },
}
TEAM_COUNTS = sorted({teams for teams, fmt in CALIBRATED})


def scaled_replacement_rank(teams, fmt):
    baseline_ranks = CALIBRATED.get((BASELINE_TEAMS, fmt), CALIBRATED[(BASELINE_TEAMS, "half_ppr")])["ranks"]
    return {pos: max(1, round(rank * teams / BASELINE_TEAMS))
            for pos, rank in baseline_ranks.items()}


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
    fmt = sys.argv[2] if len(sys.argv) > 2 else "half_ppr"

    if (teams, fmt) in CALIBRATED:
        cal = CALIBRATED[(teams, fmt)]
        ranks, exponents, budget_share = cal["ranks"], cal["exponents"], cal["budget_share"]
        print(f"Building VALIDATED estimate for {teams} teams, {fmt} "
              f"(calibrated against real market data — see calibrate_teamcount.py).")
    else:
        ranks = scaled_replacement_rank(teams, fmt)
        exponents = CALIBRATED.get((BASELINE_TEAMS, fmt), CALIBRATED[(BASELINE_TEAMS, "half_ppr")])["exponents"]
        budget_share = CALIBRATED.get((BASELINE_TEAMS, fmt), CALIBRATED[(BASELINE_TEAMS, "half_ppr")])["budget_share"]
        print(f"Building UNVALIDATED math-only estimate for {teams} teams, {fmt} "
              f"(proportional scaling from the {BASELINE_TEAMS}-team {fmt} baseline — "
              f"not yet checked against real market data, treat with caution).")

    print(f"REPLACEMENT_RANK: {ranks}")
    print(f"VORP_EXPONENT: {exponents}")
    print(f"POSITION_BUDGET_SHARE: {budget_share}")

    projections = load_projections(fmt)
    personal_ranks = load_personal_ranks(fmt)
    blended = blend_with_personal_ranks(projections, personal_ranks)
    players, pos_stats = compute_auction_values(blended, ranks=ranks, exponents=exponents,
                                                  teams=teams, budget_share=budget_share)

    out_file = Path(__file__).resolve().parent / f"auction_values_{teams}team_{fmt}.csv"
    write_csv(players, out_file)


if __name__ == "__main__":
    main()
