#!/usr/bin/env python3
"""
Grid-search REPLACEMENT_RANK and VORP_EXPONENT for a team count OTHER than
12, against real market data pulled at that team count — the follow-up to
build_teamcount_estimate.py's math-only scaling test, once real data shows
the scaling hypothesis doesn't hold up well enough at the top of the curve
(see CLAUDE.md, "Team count: testing math-only scaling").

Same methodology as calibrate_replacement_rank.py/calibrate_vorp_exponent.py
(overlapping-key DS rescale, DS "Auction $" excluded from the target, top-12
scoring window), generalized to accept a team count and reference-file set
instead of being hardcoded to the 12-team files. POSITION_BUDGET_SHARE is
still held constant across team counts — that hypothesis wasn't
contradicted by the real 10-team data (aggregate position split was in a
similar ballpark to the 12-team pattern); only replacement rank/exponent
needed real recalibration.

Usage:
    python calibrate_teamcount.py 10
"""

import sys
from pathlib import Path

import compare_to_market as mkt
import compare_teamcount as tc
from build_auction_values import (
    POINTS_COL, REPLACEMENT_RANK, VORP_EXPONENT, blend_with_personal_ranks,
    load_personal_ranks, load_projections, compute_auction_values,
)
from name_match import normalize_name  # noqa: E402

RANK_CANDIDATES = {
    "QB": [8, 10, 11, 13, 15, 16, 19, 22],
    "RB": [22, 26, 28, 30, 33, 34, 36, 38, 40],
    "WR": [30, 36, 40, 42, 45, 46, 50, 54],
    "TE": [8, 10, 12, 14, 16, 18, 21, 24],
}
EXPONENT_CANDIDATES = {
    "QB": [1.0, 1.05, 1.1, 1.15, 1.2, 1.3],
    "RB": [0.9, 1.0, 1.05, 1.1, 1.15],
    "WR": [1.0, 1.1, 1.15, 1.2, 1.25, 1.3],
    "TE": [0.9, 1.0, 1.1, 1.2],
}


def build_target(teams):
    fp = tc.load_fp_raw_export(tc.HERE / f"reference_fantasypros_{teams}team.csv")
    for4 = mkt.load_4for4(tc.HERE / f"reference_4for4_{teams}team.csv")
    ds_market = mkt.load_draftsharks(tc.HERE / f"reference_draftsharks_{teams}team.csv", "Market $")

    def total_on_keys(src, pos, keys):
        return sum(src[k]["value"] for k in keys if k in src and src[k]["pos"] == pos)

    target = {}
    for pos in POINTS_COL:
        fp_keys = {k for k, v in fp.items() if v["pos"] == pos}
        fp_total = total_on_keys(fp, pos, fp_keys)
        ds_scale = (fp_total / total_on_keys(ds_market, pos, fp_keys)
                    if total_on_keys(ds_market, pos, fp_keys) else 1.0)
        pos_target = {}
        for k in fp_keys:
            vals = [fp[k]["value"]]
            if k in for4 and for4[k]["pos"] == pos:
                vals.append(for4[k]["value"])
            if k in ds_market and ds_market[k]["pos"] == pos:
                vals.append(ds_market[k]["value"] * ds_scale)
            pos_target[k] = sum(vals) / len(vals)
        target[pos] = pos_target
    return target


def score(ours_by_key, target_pos, top_n=12):
    ranked = sorted(target_pos, key=lambda k: (-target_pos[k], k))[:top_n]  # deterministic tie-break
    err = 0.0
    for k in ranked:
        o = ours_by_key.get(k, 1.0)
        err += (o - target_pos[k]) ** 2
    return err / len(ranked)


def main():
    teams = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    target = build_target(teams)

    projections = load_projections()
    personal_ranks = load_personal_ranks()
    blended = blend_with_personal_ranks(projections, personal_ranks)

    print(f"=== Calibrating REPLACEMENT_RANK for {teams} teams ===")
    print(f"{'Pos':4} {'Rank':>5} {'RMSE(top12)':>12}")
    best_ranks = {}
    for pos in POINTS_COL:
        best_rank, best_err = None, float("inf")
        for cand in RANK_CANDIDATES[pos]:
            ranks = dict(REPLACEMENT_RANK)
            ranks[pos] = cand
            players, _ = compute_auction_values(blended, ranks=ranks, teams=teams, verbose=False)
            ours_by_key = {normalize_name(p["name"]): p["auction_value"]
                           for p in players if p["position"] == pos}
            err = score(ours_by_key, target[pos])
            marker = ""
            if err < best_err:
                best_err, best_rank = err, cand
                marker = "  <-- best so far"
            print(f"{pos:4} {cand:>5} {err**0.5:>12.2f}{marker}")
        best_ranks[pos] = best_rank
        print(f"  best {pos} replacement rank: {best_rank} (RMSE {best_err**0.5:.2f})\n")

    print(f"=== Calibrating VORP_EXPONENT for {teams} teams (using best ranks above) ===")
    print(f"{'Pos':4} {'Exp':>5} {'RMSE(top12)':>12}")
    best_exps = {}
    for pos in POINTS_COL:
        best_exp, best_err = None, float("inf")
        for cand in EXPONENT_CANDIDATES[pos]:
            exps = dict(VORP_EXPONENT)
            exps[pos] = cand
            players, _ = compute_auction_values(blended, ranks=best_ranks, exponents=exps,
                                                  teams=teams, verbose=False)
            ours_by_key = {normalize_name(p["name"]): p["auction_value"]
                           for p in players if p["position"] == pos}
            err = score(ours_by_key, target[pos])
            marker = ""
            if err < best_err:
                best_err, best_exp = err, cand
                marker = "  <-- best so far"
            print(f"{pos:4} {cand:>5.2f} {err**0.5:>12.2f}{marker}")
        best_exps[pos] = best_exp
        print(f"  best {pos} exponent: {best_exp} (RMSE {best_err**0.5:.2f})\n")

    print(f"Suggested REPLACEMENT_RANK ({teams} teams) =", best_ranks)
    print(f"Suggested VORP_EXPONENT ({teams} teams) =", best_exps)


if __name__ == "__main__":
    main()
