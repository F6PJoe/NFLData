#!/usr/bin/env python3
"""
Grid-search VORP_EXPONENT per position against the same blended real-market
target used by calibrate_replacement_rank.py (see that script's build_target
docstring), holding REPLACEMENT_RANK and POSITION_BUDGET_SHARE fixed.

Unlike REPLACEMENT_RANK (which shapes the whole curve fairly uniformly),
the exponent directly controls how much a position's top tier gets paid
relative to its depth tier — added after rank-banded comparisons against
FantasyPros/4for4 showed real overshoot in the depth tiers of QB/WR/TE
(11-48% too much money in ranks 11+), stealing budget from the top 10 at
those same positions. RB's depth tier was already thin, not fat, so RB is
expected to want an exponent near 1.0.

Usage:
    python calibrate_vorp_exponent.py [path/to/4for4_export.csv]
"""

import sys
from pathlib import Path

import compare_to_market as mkt
from calibrate_replacement_rank import build_target, score
from build_auction_values import (
    POINTS_COL, REPLACEMENT_RANK, VORP_EXPONENT, blend_with_personal_ranks,
    load_personal_ranks, load_projections, compute_auction_values,
)
from name_match import normalize_name  # noqa: E402

CANDIDATE_EXPONENTS = {
    "QB": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
    "RB": [0.9, 1.0, 1.1],
    "WR": [1.0, 1.1, 1.2, 1.3, 1.4, 1.5],
    "TE": [1.0, 1.2, 1.4, 1.6, 1.8, 2.0],
}


def main():
    for4_path = Path(sys.argv[1]) if len(sys.argv) > 1 else mkt.DEFAULT_4FOR4
    target = build_target(for4_path)

    projections = load_projections()
    personal_ranks = load_personal_ranks()
    blended = blend_with_personal_ranks(projections, personal_ranks)

    print(f"{'Pos':4} {'Exp':>5} {'RMSE(full pool)':>16}")
    best = {}
    for pos in POINTS_COL:
        best_exp, best_err = None, float("inf")
        full_n = len(target[pos])
        for cand in CANDIDATE_EXPONENTS[pos]:
            exps = dict(VORP_EXPONENT)
            exps[pos] = cand
            players, _ = compute_auction_values(blended, exponents=exps, verbose=False)
            ours_by_key = {normalize_name(p["name"]): p["auction_value"]
                           for p in players if p["position"] == pos}
            err = score(ours_by_key, target[pos], top_n=full_n)
            marker = ""
            if err < best_err:
                best_err, best_exp = err, cand
                marker = "  <-- best so far"
            print(f"{pos:4} {cand:>5.2f} {err**0.5:>16.2f}{marker}")
        best[pos] = best_exp
        print(f"  best {pos} exponent: {best_exp} (RMSE {best_err**0.5:.2f})\n")

    print("Suggested VORP_EXPONENT =", best)


if __name__ == "__main__":
    main()
