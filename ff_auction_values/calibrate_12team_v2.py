#!/usr/bin/env python3
"""
One-off: re-run the same REPLACEMENT_RANK/VORP_EXPONENT grid search used
to originally calibrate the 12-team baseline, against a NEW pull of real
$200/half-PPR/12-team data (reference_*_12team_v2.csv) — user flagged a
possible source-setting issue in the original 12-team pull and supplied a
fresh set from all three sources. See CLAUDE.md for how this compares to
the original calibration and what was ultimately decided.

Not a permanent script — same one-off pattern as calibrate_teamcount.py,
just pointed at the v2 files and using the raw-site-export FP loader
(compare_teamcount.load_fp_raw_export) since this pull is in that format,
not the manually-transcribed one used originally.

Usage:
    python calibrate_12team_v2.py
"""

from pathlib import Path

import compare_to_market as mkt
import compare_teamcount as tc
from build_auction_values import (
    POINTS_COL, REPLACEMENT_RANK, VORP_EXPONENT, blend_with_personal_ranks,
    load_personal_ranks, load_projections, compute_auction_values,
)
from name_match import normalize_name

HERE = Path(__file__).resolve().parent

RANK_CANDIDATES = {
    "QB": [10, 13, 16, 19, 22, 26],
    "RB": [26, 30, 34, 36, 38, 40, 42, 46, 50, 55, 60],
    "WR": [30, 36, 40, 46, 50, 54, 60, 66, 70],
    "TE": [8, 10, 12, 14, 17, 21, 26, 32, 40],
}
EXPONENT_CANDIDATES = {
    "QB": [1.0, 1.05, 1.1, 1.15, 1.2, 1.3],
    "RB": [0.9, 1.0, 1.05, 1.1, 1.15, 1.2],
    "WR": [1.0, 1.1, 1.15, 1.2, 1.25, 1.3],
    "TE": [0.9, 1.0, 1.1, 1.2],
}


def build_target():
    fp = tc.load_fp_raw_export(HERE / "reference_fantasypros_12team_v2.csv")
    for4 = mkt.load_4for4(HERE / "reference_4for4_12team_v2.csv")
    ds_market = mkt.load_draftsharks(HERE / "reference_draftsharks_12team_v2.csv", "Market $")

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
    target = build_target()

    projections = load_projections()
    personal_ranks = load_personal_ranks()
    blended = blend_with_personal_ranks(projections, personal_ranks)

    print("=== Calibrating REPLACEMENT_RANK (12 teams, NEW v2 data) ===")
    print(f"{'Pos':4} {'Rank':>5} {'RMSE(top12)':>12}")
    best_ranks = {}
    for pos in POINTS_COL:
        best_rank, best_err = None, float("inf")
        for cand in RANK_CANDIDATES[pos]:
            ranks = dict(REPLACEMENT_RANK)
            ranks[pos] = cand
            players, _ = compute_auction_values(blended, ranks=ranks, verbose=False)
            ours_by_key = {normalize_name(p["name"]): p["auction_value"]
                           for p in players if p["position"] == pos}
            err = score(ours_by_key, target[pos])
            marker = ""
            if err < best_err:
                best_err, best_rank = err, cand
                marker = "  <-- best so far"
            print(f"{pos:4} {cand:>5} {err**0.5:>12.2f}{marker}")
        best_ranks[pos] = best_rank
        print(f"  best {pos} replacement rank: {best_rank} (RMSE {best_err**0.5:.2f}) "
              f"[current production: {REPLACEMENT_RANK[pos]}]\n")

    print("=== Calibrating VORP_EXPONENT (12 teams, NEW v2 data) ===")
    print(f"{'Pos':4} {'Exp':>5} {'RMSE(top12)':>12}")
    best_exps = {}
    for pos in POINTS_COL:
        best_exp, best_err = None, float("inf")
        for cand in EXPONENT_CANDIDATES[pos]:
            exps = dict(VORP_EXPONENT)
            exps[pos] = cand
            players, _ = compute_auction_values(blended, ranks=best_ranks, exponents=exps, verbose=False)
            ours_by_key = {normalize_name(p["name"]): p["auction_value"]
                           for p in players if p["position"] == pos}
            err = score(ours_by_key, target[pos])
            marker = ""
            if err < best_err:
                best_err, best_exp = err, cand
                marker = "  <-- best so far"
            print(f"{pos:4} {cand:>5.2f} {err**0.5:>12.2f}{marker}")
        best_exps[pos] = best_exp
        print(f"  best {pos} exponent: {best_exp} (RMSE {best_err**0.5:.2f}) "
              f"[current production: {VORP_EXPONENT[pos]}]\n")

    print("Suggested REPLACEMENT_RANK (12 teams, v2 data) =", best_ranks)
    print("Current production REPLACEMENT_RANK               =", REPLACEMENT_RANK)
    print("Suggested VORP_EXPONENT (12 teams, v2 data)   =", best_exps)
    print("Current production VORP_EXPONENT                   =", VORP_EXPONENT)


if __name__ == "__main__":
    main()
