#!/usr/bin/env python3
"""
Grid-search REPLACEMENT_RANK per position against a blended real-market
target, holding POSITION_BUDGET_SHARE fixed (that's already calibrated —
see CLAUDE.md). This tunes within-position curve SHAPE (how top-heavy a
position's dollars are), not cross-position balance.

Target per position = average of FantasyPros, 4for4, and Draft Sharks'
"balanced roster" export's "Market $" column ONLY (their tracked real
auction-price consensus), rescaled to FantasyPros' total-per-position just
in case (should already be close to 1.0). Draft Sharks' "Auction $" column
(their own 3D-model output, not real tracked prices) is deliberately
excluded from the target — it was the one column of the four disagreeing
with the other three on RB-vs-WR ordering at the very top (Gibbs/Bijan vs.
Nacua/Chase; user caught this by comparing against 4for4's full top-10,
where RB1-5 all clear $60 and only WR1-3 do — a real, broad pattern, not
noise). Treating a model's own output as equally-trustworthy "market data"
alongside three sources of real tracked/crowd prices was the mistake;
"Auction $" is still shown in compare_to_market.py for reference, just not
used to calibrate against.

Usage:
    python calibrate_replacement_rank.py [path/to/4for4_export.csv]
"""

import sys
from pathlib import Path

import compare_to_market as mkt
from build_auction_values import (
    POINTS_COL, REPLACEMENT_RANK, blend_with_personal_ranks,
    load_personal_ranks, load_projections, compute_auction_values,
)
from name_match import normalize_name  # noqa: E402 (path set up by compare_to_market import)

CANDIDATE_RANKS = {
    "QB": [10, 13, 16, 19, 22, 26],
    "RB": [26, 30, 34, 36, 38, 40, 42, 46, 50, 55, 60],
    "WR": [24, 30, 36, 40, 46, 54, 62, 70],
    "TE": [8, 10, 12, 14, 17, 21, 26, 32, 40],
}


def build_target(for4_path):
    fp = mkt.load_fp()
    for4 = mkt.load_4for4(for4_path)
    ds_market = mkt.load_draftsharks(mkt.DS_BALANCED_FILE, "Market $")

    # Rescale factor for DS Market: match totals on the OVERLAPPING player
    # set only (FP's own list), not each source's full independent total.
    # Draft Sharks' export covers ~1000 players vs. FantasyPros' ~150-200,
    # so comparing whole-source totals conflates "is DS inflated at the
    # top" with "does DS just list way more $1-$5 bench filler than FP" —
    # the latter has nothing to do with top-of-curve accuracy and was
    # dragging the blended target down where it shouldn't (caught because
    # raw FP/4for4/DS-balanced top values already agreed closely on their
    # own, e.g. Puka Nacua $65/$62/$62-63 — no rescaling should have moved
    # that at all).
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
            vals = []
            if k in fp:
                vals.append(fp[k]["value"])
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
    for4_path = Path(sys.argv[1]) if len(sys.argv) > 1 else mkt.DEFAULT_4FOR4
    target = build_target(for4_path)

    projections = load_projections()
    personal_ranks = load_personal_ranks()
    blended = blend_with_personal_ranks(projections, personal_ranks)

    print(f"{'Pos':4} {'Rank':>5} {'RMSE(full pool)':>16}")
    best = {}
    for pos in POINTS_COL:
        best_rank, best_err = None, float("inf")
        full_n = len(target[pos])
        for cand in CANDIDATE_RANKS[pos]:
            ranks = dict(REPLACEMENT_RANK)
            ranks[pos] = cand
            players, _ = compute_auction_values(blended, ranks=ranks, verbose=False)
            ours_by_key = {normalize_name(p["name"]): p["auction_value"]
                           for p in players if p["position"] == pos}
            err = score(ours_by_key, target[pos], top_n=full_n)
            marker = ""
            if err < best_err:
                best_err, best_rank = err, cand
                marker = "  <-- best so far"
            print(f"{pos:4} {cand:>5} {err**0.5:>16.2f}{marker}")
        best[pos] = best_rank
        print(f"  best {pos} replacement rank: {best_rank} (RMSE {best_err**0.5:.2f})\n")

    print("Suggested REPLACEMENT_RANK =", best)


if __name__ == "__main__":
    main()
