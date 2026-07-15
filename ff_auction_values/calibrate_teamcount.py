#!/usr/bin/env python3
"""
Grid-search REPLACEMENT_RANK and VORP_EXPONENT for a (team count, scoring
format) combination, against real market data pulled at that exact
combination. Originally built for team-count-only recalibration (see
CLAUDE.md, "Team count: testing math-only scaling" / "Round 5"); extended
to also take a scoring format once the user supplied real STD/PPR
reference pulls (see CLAUDE.md, the STD/PPR round) — same reasoning as
team count: real market bidding behavior isn't safely derivable from
half-PPR data alone, especially for POSITION_BUDGET_SHARE (PPR/STD are
well known to shift real auction spend between RB and WR/pass-catchers,
not just reshuffle within a position the way team count does).

Same methodology as calibrate_replacement_rank.py/calibrate_vorp_exponent.py
(overlapping-key DS rescale, DS "Auction $" excluded from the target,
deterministic top-12 scoring window). Candidate ranges widened from the
original team-count-only version — the old ranges repeatedly forced the
"best" result to land at the edge of the tested window (a recurring
pattern documented in build_auction_values.py's REPLACEMENT_RANK/
VORP_EXPONENT comments: RB/WR at 12-team, 14-team's first pass, and
16-team's TE/RB exponents all needed 0.5-0.85, well outside the old
0.9-1.2 range) — this version also prints an explicit warning whenever the
chosen candidate is still at an edge, so that mistake can't silently repeat.

POSITION_BUDGET_SHARE is NOT assumed constant across formats (unlike team
count, where that assumption held up against real data) — this script
measures the REAL aggregate position $ split directly from the blended
target and prints it, so it can be compared against the current constant
before deciding whether a format needs its own budget-share override.

Usage:
    python calibrate_teamcount.py <teams> <format>
    python calibrate_teamcount.py 12 std
    python calibrate_teamcount.py 14 ppr
    python calibrate_teamcount.py 10           # format defaults to half_ppr
"""

import sys
from pathlib import Path

import compare_to_market as mkt
import compare_teamcount as tc
from build_auction_values import (
    POINTS_COL, REPLACEMENT_RANK, VORP_EXPONENT, POSITION_BUDGET_SHARE,
    blend_with_personal_ranks, load_personal_ranks, load_projections,
    compute_auction_values,
)
from name_match import normalize_name  # noqa: E402

# "" (half-PPR) reference files have no format suffix (original naming,
# predates the STD/PPR pull) — std/ppr files are reference_<source>_<teams>team_<suffix>.csv.
FILE_SUFFIX = {"half_ppr": "", "std": "_std", "ppr": "_ppr"}

# Widened past every value discovered across all 5 team counts x half-PPR
# (rank: QB 15-19, RB 34-44, WR 45-64, TE 16-24; exponent: QB 0.7-1.15,
# RB 0.7-1.2, WR 0.85-1.2, TE 0.5-1.0), plus headroom for format effects
# we haven't seen yet.
RANK_CANDIDATES = {
    "QB": [8, 10, 12, 14, 16, 18, 20, 22, 24, 26],
    "RB": [20, 24, 28, 32, 36, 40, 44, 48, 52, 56, 60, 65, 70, 75],
    "WR": [25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 100, 110, 120],
    "TE": [6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 34, 38],
}
# Format-level budget share: the AVERAGE of the real measured share across
# all 5 team counts within that format (mirroring how half-PPR's single
# POSITION_BUDGET_SHARE was derived — held constant across team counts,
# only format actually moves it). Computed from report_real_budget_share()
# output across teams=8/10/12/14/16 for each format. Must be used
# CONSISTENTLY between the calibration search and production — using a
# per-team-count-specific value during search but the average in
# production (or vice versa) reproduces the same overshoot bug this file's
# docstring describes, just smaller.
FORMAT_BUDGET_SHARE = {
    "std": {"QB": 0.0608, "RB": 0.4629, "WR": 0.4014, "TE": 0.0750},
    "ppr": {"QB": 0.0538, "RB": 0.4120, "WR": 0.4584, "TE": 0.0759},
}

EXPONENT_CANDIDATES = {
    "QB": [0.6, 0.7, 0.8, 0.9, 1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.4, 1.5],
    "RB": [0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 1.0, 1.05, 1.1, 1.15, 1.2, 1.3, 1.4],
    "WR": [0.6, 0.7, 0.8, 0.85, 0.9, 1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3],
    "TE": [0.4, 0.5, 0.6, 0.7, 0.8, 0.85, 0.9, 1.0, 1.1, 1.2],
}


def build_target(teams, fmt):
    suffix = FILE_SUFFIX[fmt]
    fp = tc.load_fp_raw_export(tc.HERE / f"reference_fantasypros_{teams}team{suffix}.csv")
    for4 = mkt.load_4for4(tc.HERE / f"reference_4for4_{teams}team{suffix}.csv")
    ds_market = mkt.load_draftsharks(tc.HERE / f"reference_draftsharks_{teams}team{suffix}.csv", "Market $")

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


def report_real_budget_share(target):
    """Real aggregate position $ split, measured directly from the blended
    target (every player, not just top 12) — not assumed constant across
    formats, unlike team count. Compare against POSITION_BUDGET_SHARE to
    decide whether this format needs its own override."""
    totals = {pos: sum(target[pos].values()) for pos in POINTS_COL}
    grand_total = sum(totals.values())
    print("=== Real aggregate position budget share (measured from target) ===")
    for pos in POINTS_COL:
        real_share = totals[pos] / grand_total
        current = POSITION_BUDGET_SHARE[pos]
        print(f"  {pos}: real {real_share*100:5.1f}%  vs. current constant {current*100:5.1f}%  "
              f"(delta {(real_share-current)*100:+5.1f}pt)")
    return {pos: totals[pos] / grand_total for pos in POINTS_COL}


def main():
    teams = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    fmt = sys.argv[2] if len(sys.argv) > 2 else "half_ppr"
    target = build_target(teams, fmt)
    real_budget_share = report_real_budget_share(target)

    projections = load_projections(fmt)
    personal_ranks = load_personal_ranks(fmt)
    blended = blend_with_personal_ranks(projections, personal_ranks)

    # CRITICAL: rank/exponent search must use the SAME budget share that
    # will actually be used in production (FORMAT_BUDGET_SHARE, the
    # cross-team-count average) — not the half-PPR default, and not the
    # per-team-count real_budget_share measured above either.
    # budget_share directly scales a position's total dollar pool, so
    # calibrating against a different pool size than what's ultimately
    # applied lets the exponent search silently compensate (over-
    # concentrating value at the top to hit the top-12 target despite too
    # little/too much total money), producing a shape that overshoots once
    # a different budget share is applied for real. Caught by individual-
    # player verification (Gibbs/Bijan $10+ over real at 12-team STD)
    # before this fix — not a hypothetical concern.
    budget_share = FORMAT_BUDGET_SHARE.get(fmt, POSITION_BUDGET_SHARE)

    print(f"\n=== Calibrating REPLACEMENT_RANK for {teams} teams, {fmt} ===")
    print(f"{'Pos':4} {'Rank':>5} {'RMSE(top12)':>12}")
    best_ranks = {}
    for pos in POINTS_COL:
        best_rank, best_err = None, float("inf")
        for cand in RANK_CANDIDATES[pos]:
            ranks = dict(REPLACEMENT_RANK)
            ranks[pos] = cand
            players, _ = compute_auction_values(blended, ranks=ranks, teams=teams,
                                                  budget_share=budget_share, verbose=False)
            ours_by_key = {normalize_name(p["name"]): p["auction_value"]
                           for p in players if p["position"] == pos}
            err = score(ours_by_key, target[pos])
            marker = ""
            if err < best_err:
                best_err, best_rank = err, cand
                marker = "  <-- best so far"
            print(f"{pos:4} {cand:>5} {err**0.5:>12.2f}{marker}")
        best_ranks[pos] = best_rank
        cands = RANK_CANDIDATES[pos]
        edge_warning = "  *** AT EDGE OF RANGE, WIDEN AND RE-TEST ***" if best_rank in (cands[0], cands[-1]) else ""
        print(f"  best {pos} replacement rank: {best_rank} (RMSE {best_err**0.5:.2f}){edge_warning}\n")

    print(f"=== Calibrating VORP_EXPONENT for {teams} teams, {fmt} (using best ranks above) ===")
    print(f"{'Pos':4} {'Exp':>5} {'RMSE(top12)':>12}")
    best_exps = {}
    for pos in POINTS_COL:
        best_exp, best_err = None, float("inf")
        for cand in EXPONENT_CANDIDATES[pos]:
            exps = dict(VORP_EXPONENT)
            exps[pos] = cand
            players, _ = compute_auction_values(blended, ranks=best_ranks, exponents=exps,
                                                  teams=teams, budget_share=budget_share, verbose=False)
            ours_by_key = {normalize_name(p["name"]): p["auction_value"]
                           for p in players if p["position"] == pos}
            err = score(ours_by_key, target[pos])
            marker = ""
            if err < best_err:
                best_err, best_exp = err, cand
                marker = "  <-- best so far"
            print(f"{pos:4} {cand:>5.2f} {err**0.5:>12.2f}{marker}")
        best_exps[pos] = best_exp
        cands = EXPONENT_CANDIDATES[pos]
        edge_warning = "  *** AT EDGE OF RANGE, WIDEN AND RE-TEST ***" if best_exp in (cands[0], cands[-1]) else ""
        print(f"  best {pos} exponent: {best_exp} (RMSE {best_err**0.5:.2f}){edge_warning}\n")

    print(f"Suggested REPLACEMENT_RANK ({teams} teams, {fmt}) =", best_ranks)
    print(f"Suggested VORP_EXPONENT ({teams} teams, {fmt}) =", best_exps)
    print(f"Real budget share ({teams} teams, {fmt}) =",
          {pos: round(v, 4) for pos, v in real_budget_share.items()})


if __name__ == "__main__":
    main()
