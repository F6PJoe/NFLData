#!/usr/bin/env python3
"""
One-off: calibrate REPLACEMENT_RANK/VORP_EXPONENT/POSITION_BUDGET_SHARE for
a 12-team/half-PPR/$200 SUPERFLEX league, against real market data — the
first roster-shape (not team-count/format) calibration in this project, see
CLAUDE.md "Round 7: roster configuration."

4for4's superflex export is EXCLUDED from the target — verified unreliable,
not just uncertain about PPR/half-PPR scoring: QB values were crushed low
($29 for Josh Allen, falling to single digits by QB5) while RB/WR values
were simultaneously INFLATED above even this project's regular single-QB
calibration (Gibbs $68, Chase $64) — backwards from real superflex behavior
(QB should surge, RB/WR should give up budget share to it). FantasyPros and
Draft Sharks' Market $ agree closely with each other and show the expected
pattern (Josh Allen $54/$75, RB/WR down from single-QB levels), so the
target here blends only those two, same "keep tracked real prices, drop
what doesn't hold up" principle already used earlier in this project when
Draft Sharks' own "Auction $" model column was dropped for disagreeing with
3 real-price sources on RB-vs-WR ordering.

Usage:
    python calibrate_superflex.py
"""

import compare_to_market as mkt
import compare_teamcount as tc
from build_auction_values import (
    POINTS_COL, REPLACEMENT_RANK, VORP_EXPONENT,
    blend_with_personal_ranks, load_personal_ranks, load_projections,
    compute_auction_values,
)
from name_match import normalize_name
from calibrate_teamcount import RANK_CANDIDATES, EXPONENT_CANDIDATES, score

TEAMS = 12
FMT = "half_ppr"


def build_target():
    fp = tc.load_fp_raw_export(tc.HERE / "reference_fantasypros_12team_superflex.csv")
    ds_market = mkt.load_draftsharks(tc.HERE / "reference_draftsharks_12team_superflex.csv", "Market $")

    # NO per-position total-based DS rescale — see calibrate_teamcount.py's
    # build_target() docstring for the full account of why that rescale was
    # a real bug (erased DS's independent opinion on QB/TE instead of
    # correcting a real artifact), first caught here specifically because
    # this 2-source blend had no 4for4 to mask the distortion.
    target = {}
    for pos in POINTS_COL:
        fp_keys = {k for k, v in fp.items() if v["pos"] == pos}
        pos_target = {}
        for k in fp_keys:
            vals = [fp[k]["value"]]
            if k in ds_market and ds_market[k]["pos"] == pos:
                vals.append(ds_market[k]["value"])
            pos_target[k] = sum(vals) / len(vals)
        target[pos] = pos_target
    return target


def report_real_budget_share(target):
    totals = {pos: sum(target[pos].values()) for pos in POINTS_COL}
    grand_total = sum(totals.values())
    print("=== Real superflex budget share (FantasyPros + Draft Sharks Market only) ===")
    share = {}
    for pos in POINTS_COL:
        share[pos] = totals[pos] / grand_total
        print(f"  {pos}: {share[pos]*100:5.1f}%")
    return share


def main():
    target = build_target()
    budget_share = report_real_budget_share(target)

    projections = load_projections(FMT)
    personal_ranks = load_personal_ranks(FMT)
    blended = blend_with_personal_ranks(projections, personal_ranks)

    print(f"\n=== Calibrating REPLACEMENT_RANK (12-team superflex) ===")
    print(f"{'Pos':4} {'Rank':>5} {'RMSE(top12)':>12}")
    best_ranks = {}
    # QB needs a much wider/shallower-friendly range than usual — superflex
    # QB replacement level should be dramatically deeper (more QBs startable).
    qb_candidates = [8, 10, 12, 14, 16, 18, 20, 22, 24, 26, 28, 30, 32, 34, 36, 40, 44]
    rank_candidates = dict(RANK_CANDIDATES)
    rank_candidates["QB"] = qb_candidates
    for pos in POINTS_COL:
        best_rank, best_err = None, float("inf")
        for cand in rank_candidates[pos]:
            ranks = dict(REPLACEMENT_RANK)
            ranks[pos] = cand
            players, _ = compute_auction_values(blended, ranks=ranks, teams=TEAMS,
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
        cands = rank_candidates[pos]
        edge = "  *** AT EDGE, WIDEN ***" if best_rank in (cands[0], cands[-1]) else ""
        print(f"  best {pos}: {best_rank} (RMSE {best_err**0.5:.2f}){edge}\n")

    print(f"=== Calibrating VORP_EXPONENT (12-team superflex) ===")
    print(f"{'Pos':4} {'Exp':>5} {'RMSE(top12)':>12}")
    best_exps = {}
    for pos in POINTS_COL:
        best_exp, best_err = None, float("inf")
        for cand in EXPONENT_CANDIDATES[pos]:
            exps = dict(VORP_EXPONENT)
            exps[pos] = cand
            players, _ = compute_auction_values(blended, ranks=best_ranks, exponents=exps,
                                                  teams=TEAMS, budget_share=budget_share, verbose=False)
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
        edge = "  *** AT EDGE, WIDEN ***" if best_exp in (cands[0], cands[-1]) else ""
        print(f"  best {pos}: {best_exp} (RMSE {best_err**0.5:.2f}){edge}\n")

    print("Suggested REPLACEMENT_RANK (superflex) =", best_ranks)
    print("Suggested VORP_EXPONENT (superflex) =", best_exps)
    print("Real budget share (superflex) =", {pos: round(v, 4) for pos, v in budget_share.items()})


if __name__ == "__main__":
    main()
