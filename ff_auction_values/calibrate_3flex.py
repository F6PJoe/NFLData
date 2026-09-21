#!/usr/bin/env python3
"""
One-off: calibrate REPLACEMENT_RANK/VORP_EXPONENT/POSITION_BUDGET_SHARE for
a 14-team/PPR/$200 league with 1QB/2RB/3WR/1TE/3FLEX(RB-WR-TE) — the
user's actual upcoming league, and the second roster-shape (not team-count/
format) calibration in this project after superflex (see CLAUDE.md,
"Round 7: roster configuration").

Unlike superflex, all 3 sources are usable here — 4for4 doesn't have a
true FLEX concept in its auction tool (confirmed: it only has raw
QB/RB/WR/TE-to-start number fields), but the user found their tool accepts
FRACTIONAL starter counts, and approximating 3 RB/WR/TE-flex spots as
weighted fractional additions (1QB, 3.2RB, 4.2WR, 1.6TE) produced values
that land plausibly between FantasyPros and Draft Sharks for every
player checked — unlike the superflex attempt (QB has no equivalent
fractional workaround, since flex-QB-eligibility isn't "more of the same"
the way flex-RB/WR/TE is).

Compared against the existing 14-team/PPR/1-FLEX calibration (same team
count, same format, same starters, ONLY flex count differs 1->3), this
isolates the flex-demand split across RB/WR/TE — the piece needed to
finish the general roster-shape formula.

Usage:
    python calibrate_3flex.py
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

TEAMS = 14
FMT = "ppr"


def build_target():
    fp = tc.load_fp_raw_export(tc.HERE / "reference_fantasypros_14team_ppr_3flex.csv")
    for4 = mkt.load_4for4(tc.HERE / "reference_4for4_14team_ppr_3flex.csv")
    ds_market = mkt.load_draftsharks(tc.HERE / "reference_draftsharks_14team_ppr_3flex.csv", "Market $")

    target = {}
    for pos in POINTS_COL:
        fp_keys = {k for k, v in fp.items() if v["pos"] == pos}
        pos_target = {}
        for k in fp_keys:
            vals = [fp[k]["value"]]
            if k in for4 and for4[k]["pos"] == pos:
                vals.append(for4[k]["value"])
            if k in ds_market and ds_market[k]["pos"] == pos:
                vals.append(ds_market[k]["value"])
            pos_target[k] = sum(vals) / len(vals)
        target[pos] = pos_target
    return target


def report_real_budget_share(target):
    totals = {pos: sum(target[pos].values()) for pos in POINTS_COL}
    grand_total = sum(totals.values())
    print("=== Real budget share (14-team, PPR, 3-FLEX) ===")
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

    print(f"\n=== Calibrating REPLACEMENT_RANK (14-team, PPR, 3-FLEX) ===")
    print(f"{'Pos':4} {'Rank':>5} {'RMSE(top12)':>12}")
    best_ranks = {}
    for pos in POINTS_COL:
        best_rank, best_err = None, float("inf")
        for cand in RANK_CANDIDATES[pos]:
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
        cands = RANK_CANDIDATES[pos]
        edge = "  *** AT EDGE, WIDEN ***" if best_rank in (cands[0], cands[-1]) else ""
        print(f"  best {pos}: {best_rank} (RMSE {best_err**0.5:.2f}){edge}\n")

    print(f"=== Calibrating VORP_EXPONENT (14-team, PPR, 3-FLEX) ===")
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

    print("Suggested REPLACEMENT_RANK (14-team, PPR, 3-FLEX) =", best_ranks)
    print("Suggested VORP_EXPONENT (14-team, PPR, 3-FLEX) =", best_exps)
    print("Real budget share (14-team, PPR, 3-FLEX) =", {pos: round(v, 4) for pos, v in budget_share.items()})


if __name__ == "__main__":
    main()
