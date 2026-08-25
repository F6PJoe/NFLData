#!/usr/bin/env python3
"""
Broad regression sweep across the league-config space, checking INTERNAL
invariants that don't require real market data at every point.

Run this after ANY change to roster_formula.py or build_auction_values.py,
before trusting the change beyond the handful of configs that happen to
have real reference data. Real anchors only cover ~3 points in a space of
hundreds of possible (teams, format, starters, flex) combos -- everything
else is extrapolated by formula, and this is how to catch a broken
extrapolation without needing a fresh market data pull for every config.

Checks (see each block below for the full reasoning):
  1. estimate_roster_shape doesn't raise, and returns finite positive
     ranks/exponents and budget shares that sum to 1.0
  2. compute_auction_values doesn't raise
  3. No player prices negative
  4. Discretionary budget is conserved EXACTLY (closed-form: rate is
     defined by division so this must hold algebraically, not just
     approximately -- if it doesn't, something is structurally broken)
  5. Within each position, value is monotonic non-increasing in points
     (a worse projected player can never outprice a better one at the
     same position)
  6. Top player's price stays under a sane ceiling (45% of one team's
     budget) for realistic roster shapes

Usage:
    python verify_formula_invariants.py
"""
import sys
sys.path.insert(0, r"C:\Users\jbond\OneDrive\Documents\FF_ADP\ff_auction_values")

from build_auction_values import (
    load_projections, load_personal_ranks, blend_with_personal_ranks,
    compute_auction_values, BUDGET, BENCH_SPOTS, NON_SKILL_SLOTS_PER_TEAM,
)
from build_teamcount_estimate import CALIBRATED
from roster_formula import estimate_roster_shape

CACHE = {}
def blended(fmt):
    if fmt not in CACHE:
        proj = load_projections(fmt)
        pr = load_personal_ranks(fmt)
        CACHE[fmt] = blend_with_personal_ranks(proj, pr)
    return CACHE[fmt]

TEAMS = (8, 10, 12, 14, 16)
FMTS = ("std", "half_ppr", "ppr")

# A broad set of roster shapes: baseline, then one-dimension-at-a-time
# variations, then some combined/extreme shapes.
def shapes():
    base = {"QB": 1, "RB": 2, "WR": 3, "TE": 1}
    yield base, [("RB_WR_TE", 1)]
    for wr in (1, 2, 4):
        yield {**base, "WR": wr}, [("RB_WR_TE", 1)]
    for rb in (1, 3):
        yield {**base, "RB": rb}, [("RB_WR_TE", 1)]
    for te in (0, 2):
        yield {**base, "TE": te}, [("RB_WR_TE", 1)]
    for flex in (0, 2, 3):
        yield base, [("RB_WR_TE", flex)] if flex else []
    yield base, [("SUPERFLEX", 1)]
    yield {**base, "QB": 2}, [("RB_WR_TE", 1)]
    yield {**base, "QB": 2}, [("SUPERFLEX", 1)]
    # extreme / stress shapes
    yield {"QB": 1, "RB": 1, "WR": 1, "TE": 1}, []
    yield {"QB": 1, "RB": 3, "WR": 4, "TE": 2}, [("RB_WR_TE", 3)]
    yield {"QB": 2, "RB": 3, "WR": 2, "TE": 0}, [("SUPERFLEX", 1)]
    yield base, [("RB_WR", 1)]
    yield base, [("WR_TE", 1)]


failures = []
total = 0
n_estimated = 0
n_verified = 0

for teams in TEAMS:
    for fmt in FMTS:
        if (teams, fmt) not in CALIBRATED:
            continue
        b = blended(fmt)
        for starters, flex in shapes():
            total += 1
            label = f"{teams}T/{fmt} {starters} flex={flex}"
            try:
                est = estimate_roster_shape(teams, fmt, starters, flex)
            except Exception as e:
                failures.append((label, f"estimate_roster_shape raised: {e}"))
                continue

            ranks, exps, shares = est["ranks"], est["exponents"], est["budget_share"]
            if est["confidence"] == "verified":
                n_verified += 1
            else:
                n_estimated += 1

            for p in ("QB", "RB", "WR", "TE"):
                if ranks[p] < 1 or ranks[p] != int(ranks[p]):
                    failures.append((label, f"{p} rank invalid: {ranks[p]}"))
                if not (exps[p] > 0) or exps[p] != exps[p]:  # nan check
                    failures.append((label, f"{p} exponent invalid: {exps[p]}"))
                if shares[p] < 0 or shares[p] != shares[p]:
                    failures.append((label, f"{p} share invalid: {shares[p]}"))
            share_sum = sum(shares.values())
            if abs(share_sum - 1.0) > 0.001:
                failures.append((label, f"shares sum to {share_sum:.4f}, not 1.0"))

            n_flex_total = sum(n for _, n in flex)
            try:
                players, _ = compute_auction_values(
                    b, teams=teams, ranks=ranks, exponents=exps,
                    budget_share=shares, starters=starters,
                    flex_slots=n_flex_total, verbose=False)
            except Exception as e:
                failures.append((label, f"compute_auction_values raised: {e}"))
                continue

            neg = [p for p in players if p["auction_value"] < 0]
            if neg:
                failures.append((label, f"{len(neg)} negative-priced players"))

            # TRUE closed-form invariant: rate[pos] is defined by division
            # specifically so that summing weighted_vorp*rate over EVERY
            # player with positive weighted VORP at that position (not just
            # the drafted starters) exactly equals discretionary*share[pos].
            # Summing over positions gives exactly `discretionary`. This is
            # algebraic, not approximate -- unlike "top N drafted players
            # sum to the total budget" (an earlier, flawed version of this
            # check), which necessarily comes in UNDER budget because
            # players just past the roster cutoff still carry positive
            # VORP and get excluded from a "top N" slice.
            total_starters = sum(starters.values())
            n_flex = sum(n for _, n in flex)
            spots_total = teams * (total_starters + n_flex + BENCH_SPOTS + NON_SKILL_SLOTS_PER_TEAM)
            expected_discretionary = teams * BUDGET - spots_total * 1
            actual_pool_spend = sum(p["auction_value"] - 1 for p in players if p["auction_value"] > 1)
            tol = max(5, abs(expected_discretionary) * 0.005)
            if abs(actual_pool_spend - expected_discretionary) > tol:
                failures.append((label, f"discretionary not conserved: pool spend ${actual_pool_spend:.0f} vs expected ${expected_discretionary:.0f}"))

            top = max(players, key=lambda p: p["auction_value"])
            top_pct = top["auction_value"] / BUDGET * 100
            if top_pct > 45:
                failures.append((label, f"top player {top['name']} = {top_pct:.0f}% of budget (>45%)"))

            for pos in ("QB", "RB", "WR", "TE"):
                if starters.get(pos, 0) == 0 and not any(ft in ("RB_WR_TE",) and pos != "QB" for ft, n in flex):
                    continue  # position may legitimately be worthless
                pos_players = sorted(
                    [p for p in players if p["position"] == pos],
                    key=lambda p: -p["blended_points"])
                vals = [p["auction_value"] for p in pos_players]
                # monotonic non-increasing in points rank (allow tiny float slop)
                bad = [i for i in range(1, len(vals)) if vals[i] > vals[i-1] + 0.01]
                if bad:
                    failures.append((label, f"{pos} value not monotonic in points at index {bad[0]}"))

print(f"Swept {total} configs across {len(TEAMS)} team counts x {len(FMTS)} formats "
      f"x {total // (len(TEAMS)*len(FMTS)) if total else 0} roster shapes")
print(f"  {n_verified} landed exactly on a real anchor (verified)")
print(f"  {n_estimated} extrapolated from anchors (estimated)")
print()
if failures:
    print(f"FAILURES: {len(failures)}")
    for label, msg in failures[:40]:
        print(f"  [{label}]\n      {msg}")
    if len(failures) > 40:
        print(f"  ... and {len(failures)-40} more")
else:
    print("ALL INVARIANTS HELD across every swept config.")
    print("(This does not prove the DOLLAR VALUES are accurate anywhere")
    print(" except the anchors -- it proves the formula doesn't produce")
    print(" nonsense: no errors, budget always balances, no negative")
    print(" prices, no position blowing past a sane ceiling, and within")
    print(" every position a worse player never outprices a better one.)")

print()
print("=== FAILURE CATEGORY BREAKDOWN ===")
cats = {}
for label, msg in failures:
    key = msg.split(":")[0].split("(")[0].strip()
    cats.setdefault(key, []).append((label, msg))
for k, v in sorted(cats.items(), key=lambda kv: -len(kv[1])):
    print(f"  {k}: {len(v)}")
if "value not monotonic in points" in cats:
    print()
    print("MONOTONICITY VIOLATIONS (most concerning category):")
    for label, msg in cats["value not monotonic in points"][:10]:
        print(f"  [{label}] {msg}")
