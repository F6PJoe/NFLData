#!/usr/bin/env python3
"""
Build a static fantasy football auction value table (v1, half-PPR, standard
league). See CLAUDE.md for full methodology writeup.

Pipeline:
  1. Load consensus projected points per position from ff_draft_proj.
  2. Load personal (joe_bond) positional ranks from ff_cheatsheet.
  3. Nudge each player's points toward what their personal rank implies,
     using that position's own points-vs-rank curve (damped blend).
  4. Compute per-position replacement level from league/roster settings.
  5. VORP = nudged points - replacement level (floored at 0).
  6. Convert VORP to dollars via the standard discretionary-money formula.

Usage:
    python build_auction_values.py
"""

import csv
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "ff_rankings"))
from name_match import normalize_name  # noqa: E402
from tiers import assign_tiers_with_zero_floor  # noqa: E402

PROJ_DIR = BASE / "ff_draft_proj"
PERSONAL_RANKINGS = BASE / "ff_cheatsheet" / "joe_bond_half_ppr.csv"
OUT_FILE = Path(__file__).resolve().parent / "auction_values_half_ppr.csv"

POINTS_COL = {
    "QB": "Fantasy Points",
    "RB": "Fantasy Points (Half-PPR)",
    "WR": "Fantasy Points (Half)",
    "TE": "Fantasy Points (Half-PPR)",
}

# ── League settings (v1 static, standard league) ────────────────────────────
TEAMS = 12
BUDGET = 200
BENCH_SPOTS = 6
STARTERS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1}
FLEX_SLOTS = 1  # RB/WR/TE-eligible
NON_SKILL_SLOTS_PER_TEAM = 2  # 1 DEF + 1 K, assigned flat $1 (no projections source)

# Replacement rank per position: NOT "teams x starters" (that undercounts —
# byes and injuries force real rosters to start far more players over a
# season than the naive math implies). Started from the real-season-data
# baselines in Bryan Harstad's "A Better Way to Determine VBD Baselines"
# (footballguys.com/article/HarstadVBDBaselines): QB 19, RB 34, WR 54, TE 21.
#
# Went through 3 calibration rounds against real $200 half-PPR market data
# (calibrate_replacement_rank.py, full history in CLAUDE.md) — short
# version: an early rescale bug (comparing Draft Sharks' ~1000-player export
# totals against FantasyPros' ~150-200-player totals conflated "is DS
# inflated at the top" with "does DS just list more $1-$5 filler") got
# caught by the user cross-checking raw numbers directly, and a later round
# dropped Draft Sharks' own model column ("Auction $") from the calibration
# target entirely, keeping only real tracked-price data (FantasyPros, 4for4,
# Draft Sharks' "Market $") — the model column was the one source
# disagreeing with the other three on RB-vs-WR ordering at the very top.
# Final (round 3): WR (54) and TE (21) landed exactly on Harstad's numbers;
# QB and RB moved modestly (19->16, 34->40).
#
# Round 4: user re-pulled all 3 sources weeks later, suspecting a settings
# error in the original pull (top-end $ values had shifted down noticeably
# at FantasyPros/4for4 — Draft Sharks stayed close to its original numbers).
# Treated the new pull as the more current signal and recalibrated against
# it. RB/WR moved deeper (40->42, 54->60); QB/TE kept at round-3 values
# after their grid-search optimum turned out to hurt the single
# most-scrutinized player (Josh Allen) specifically.
#
# Round 5: user supplied a full, internally-consistent set of real
# $200/half-PPR pulls (FantasyPros + 4for4 + Draft Sharks "Market $") for
# ALL FIVE team-count options at once (8/10/12/14/16 — see
# CALIBRATED in build_teamcount_estimate.py for the other 4), all pulled
# in the same ~45-minute window, replacing the mixed-vintage data rounds
# 1-4 were built on. Recalibrated 12 (this project's baseline) against it
# with calibrate_teamcount.py, widening the search past round 4's numbers
# once RB/WR's optimum kept landing at the edge of the tested range (a
# recurring pattern worth remembering — always re-test with a wider range
# when the "best" candidate is the deepest/shallowest one tried). This time
# QB's own grid-search optimum (19) held up under individual verification
# (unlike round 4) — Josh Allen and Lamar Jackson both moved CLOSER to the
# real FantasyPros/4for4 values at QB19 than at the round-4 value of 16, so
# it was adopted rather than overridden. Also caught and fixed a real
# reproducibility bug in the calibration tooling itself during this round:
# score()'s top-12 selection had non-deterministic tie-breaking (Python's
# per-process hash randomization affects set/dict iteration order), which
# could select a different "top 12" and thus a different "best" candidate
# on different runs of the identical search — fixed by sorting on
# (-value, key) instead of just (-value,) in all 3 calibration scripts.
REPLACEMENT_RANK = {"QB": 19, "RB": 44, "WR": 64, "TE": 24}

# Position budget shares: what fraction of the skill-position discretionary
# pool goes to each position, BEFORE distributing within a position by VORP.
# A single shared $/VORP-point rate across all 4 positions assumes pure
# points-based VORP already reflects cross-position scarcity correctly — it
# doesn't. Real money treats RB waiver-wire replacements as qualitatively
# worse than backup QBs/TEs (the "spend up at RB, punt QB/TE" pattern every
# serious auction strategy piece repeats), which plain points-above-
# replacement math doesn't capture on its own. These shares are the average
# of FantasyPros' and 4for4's actual $200 half-PPR position totals (sum of
# $ across all matched QB/RB/WR/TE, normalized to 100%) — anchoring
# cross-position balance to real auction money instead of hoping it falls
# out of replacement-level choices. Within a position, dollars are still
# distributed proportional to VORP (using REPLACEMENT_RANK/VORP_EXPONENT
# below for shape).
POSITION_BUDGET_SHARE = {"QB": 0.0585, "RB": 0.431, "WR": 0.4345, "TE": 0.076}

# Convexity exponent applied to VORP before converting to dollars:
# weighted_vorp = VORP ** exponent (1.0 = pure linear). Added after
# comparing rank-banded totals against real market data (FantasyPros/4for4)
# exposed a real shape problem a replacement-rank choice alone can't fix —
# depth tiers were carrying 14-48% MORE money than FantasyPros/4for4 give
# them, which (since each position's total $ is fixed by
# POSITION_BUDGET_SHARE) directly steals budget from that position's top 10.
# Real auction markets apply a "stud premium" to elite talent that linear
# points-above-replacement math doesn't capture.
#
# First calibration pass (VORP_EXPONENT = 1.1/1.0/1.2/1.2) fixed the depth
# overshoot but created a new problem: WR's steeper exponent alone pushed
# Puka Nacua/Ja'Marr Chase ($65/$55) above Jahmyr Gibbs/Bijan Robinson
# ($61/$61) in raw dollars, despite Gibbs/Bijan having ~22% higher VORP AND
# ranking #1/#2 in the user's own personal rankings. The calibration target
# at the time included Draft Sharks' "Auction $" column (their own 3D-model
# output) as if it were equally-trustworthy market data — it was the only
# one of 4 references favoring WR at the very top; the other 3 (FantasyPros,
# 4for4, Draft Sharks' own "Market $" tracked-price column) all favor RB.
# Dropping the model column from the calibration target and re-running gave
# RB its own convexity too (1.1, not 1.0) — Gibbs/Bijan and Nacua/Chase now
# land tied at $65, preserving RB >= WR at the top (matching the VORP/
# personal-rank signal and 3 of 4 real-price sources) while keeping the WR
# depth-tier fix intact. Calibrated by calibrate_vorp_exponent.py the same
# way REPLACEMENT_RANK is.
#
# Round 4 (see REPLACEMENT_RANK comment above for the full account):
# re-derived with QB/RB/WR/TE ranks fixed at their (partly updated) round-4
# values, against the new v2 market data. RB moved 1.1->1.15, TE moved
# 1.0->0.9, QB moved 1.1->1.0, WR unchanged at 1.2. Verified against
# individual players, not just the aggregate metric: Amon-Ra St. Brown $45
# (exact match to FantasyPros' $45), Brock Bowers $22 (exact match to
# FantasyPros' $22), Gibbs/Bijan/Chase/Nacua all landed centered within the
# FantasyPros/4for4/Draft-Sharks spread rather than outside it.
#
# Round 5 (see REPLACEMENT_RANK above — same fresh 5-team-count data pull):
# re-derived against the new REPLACEMENT_RANK values with the deterministic
# scoring fix in place. QB moved 1.0->1.05, RB unchanged at 1.15, WR moved
# 1.2->1.15, TE unchanged at 0.9. Re-verified with an ITERATIVE method this
# time (hold the other 3 positions at their already-converged values, not
# stale defaults, then loop until stable) after discovering that method
# matters: the original one-position-at-a-time search (holding others at
# whatever was in this constant at search time) let 14-team's RB/WR
# exponents converge to values that overshot Gibbs/Chase by $11-12 against
# every single real reference simultaneously — a real bug in the search
# methodology, not just an aggressive-fit judgment call like round 4's.
# 12-team's values were re-verified this way and confirmed stable (did not
# change under the iterative method), but this is why the methodology note
# is here: don't trust a single one-shot exponent search again without
# iterating to convergence.
VORP_EXPONENT = {"QB": 1.05, "RB": 1.15, "WR": 1.15, "TE": 0.9}

# How much personal rank pulls a player's points toward the personal-rank-
# implied value. 0 = pure projections, 1 = pure personal rank order.
#
# NOT 0.5: for any two players who simply swap ranks between projections
# and personal rankings (e.g. Gibbs projected #1/personal #2, Bijan
# projected #2/personal #1 — a common, not rare, pattern), the algebra
# works out so a 0.5 weight makes their blended points EXACTLY equal,
# regardless of how different their real point totals were:
#   A_new = P_i + w(P_j - P_i), B_new = P_j + w(P_i - P_j)
#   A_new == B_new  <=>  (1 - 2w)(P_i - P_j) == 0  <=>  w == 0.5 (since
#   P_i != P_j for two different players). This produced literal exact
#   ties (not just same-after-rounding) for Gibbs/Bijan and Nacua/Chase —
#   caught by the user asking why 4 clearly-different players all showed
#   identical $65 values. Any weight other than exactly 0.5 avoids this.
NUDGE_WEIGHT = 0.4


def load_projections():
    """Return {pos: [{"name":, "team":, "points": float}, ...]} sorted desc by points."""
    out = {}
    for pos, col in POINTS_COL.items():
        path = PROJ_DIR / f"consensus_{pos.lower()}.csv"
        players = []
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                name = row[pos].strip()
                if not name:
                    continue
                players.append({
                    "name": name,
                    "team": row.get("Team", "").strip(),
                    "points": float(row[col]),
                })
        players.sort(key=lambda p: p["points"], reverse=True)
        out[pos] = players
    return out


def load_personal_ranks():
    """Return {pos: {normalized_name: rank}} from the wide joe_bond CSV."""
    with open(PERSONAL_RANKINGS, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    block_labels = rows[0]
    data_rows = rows[2:]

    ranks = {}
    for pos in POINTS_COL:
        name_col = block_labels.index(pos)
        pos_ranks = {}
        rank = 0
        for row in data_rows:
            if name_col >= len(row):
                continue
            name = row[name_col].strip()
            if not name:
                continue
            rank += 1
            pos_ranks[normalize_name(name)] = rank
        ranks[pos] = pos_ranks
    return ranks


def points_at_rank(sorted_points, rank):
    """Interpolate the points value at a (possibly fractional) rank."""
    n = len(sorted_points)
    if rank <= 1:
        return sorted_points[0]
    if rank >= n:
        return sorted_points[-1]
    floor_r = int(rank)
    frac = rank - floor_r
    lo_val = sorted_points[floor_r - 1]
    hi_val = sorted_points[floor_r]
    return lo_val + frac * (hi_val - lo_val)


def blend_with_personal_ranks(projections, personal_ranks):
    """Nudge each player's points toward their personal-rank-implied value."""
    blended = {}
    for pos, players in projections.items():
        curve = [p["points"] for p in players]
        pos_ranks = personal_ranks[pos]
        out = []
        for p in players:
            key = normalize_name(p["name"])
            personal_rank = pos_ranks.get(key)
            points = p["points"]
            if personal_rank is not None:
                target = points_at_rank(curve, personal_rank)
                points = points + NUDGE_WEIGHT * (target - points)
            out.append({**p, "blended_points": points, "personal_rank": personal_rank})
        out.sort(key=lambda p: p["blended_points"], reverse=True)
        blended[pos] = out
    return blended


def replacement_rank(pos, ranks=None):
    return (ranks or REPLACEMENT_RANK)[pos]


def compute_auction_values(blended, ranks=None, exponents=None, teams=None, verbose=True):
    """ranks/exponents/teams: optional overrides for REPLACEMENT_RANK/
    VORP_EXPONENT/TEAMS (used by calibrate_replacement_rank.py and
    calibrate_vorp_exponent.py to grid-search without editing the module
    constants, and by build_teamcount_estimate.py to test a different
    team count against POSITION_BUDGET_SHARE/VORP_EXPONENT held constant)."""
    exponents = exponents or VORP_EXPONENT
    teams = teams if teams is not None else TEAMS
    replacement_points = {}
    for pos, players in blended.items():
        curve = [p["blended_points"] for p in players]
        rank = replacement_rank(pos, ranks)
        replacement_points[pos] = points_at_rank(curve, rank)

    all_players = []
    for pos, players in blended.items():
        for i, p in enumerate(players, start=1):
            vorp = max(0.0, p["blended_points"] - replacement_points[pos])
            weighted_vorp = vorp ** exponents[pos] if vorp > 0 else 0.0
            all_players.append({
                **p,
                "position": pos,
                "proj_rank": i,
                "vorp": vorp,
                "weighted_vorp": weighted_vorp,
            })

    total_money = teams * BUDGET
    total_roster_spots = teams * (sum(STARTERS.values()) + FLEX_SLOTS
                                   + BENCH_SPOTS + NON_SKILL_SLOTS_PER_TEAM)
    discretionary = total_money - total_roster_spots * 1

    total_weighted_vorp_by_pos = {pos: 0.0 for pos in POINTS_COL}
    for p in all_players:
        if p["weighted_vorp"] > 0:
            total_weighted_vorp_by_pos[p["position"]] += p["weighted_vorp"]

    dollar_per_weighted_vorp = {
        pos: (discretionary * POSITION_BUDGET_SHARE[pos]) / total_weighted_vorp_by_pos[pos]
        for pos in POINTS_COL
    }

    for p in all_players:
        p["auction_value"] = 1 + p["weighted_vorp"] * dollar_per_weighted_vorp[p["position"]]

    all_players.sort(key=lambda p: p["auction_value"], reverse=True)

    pos_stats = {
        pos: {
            "replacement_rank": replacement_rank(pos, ranks),
            "replacement_points": replacement_points[pos],
            "exponent": exponents[pos],
            "budget_share": POSITION_BUDGET_SHARE[pos],
            "discretionary_dollars": discretionary * POSITION_BUDGET_SHARE[pos],
            "total_weighted_vorp": total_weighted_vorp_by_pos[pos],
            "dollar_per_weighted_vorp": dollar_per_weighted_vorp[pos],
        }
        for pos in POINTS_COL
    }

    if verbose:
        print(f"Total money: ${total_money} | Roster spots: {total_roster_spots} | "
              f"Discretionary: ${discretionary}")
        for pos in POINTS_COL:
            s = pos_stats[pos]
            print(f"  {pos}: replacement rank {s['replacement_rank']:.1f} -> "
                  f"{s['replacement_points']:.1f} pts | exponent {s['exponent']:.2f} | "
                  f"budget share {s['budget_share']*100:.1f}% "
                  f"(${s['discretionary_dollars']:.0f}) | "
                  f"total weighted VORP {s['total_weighted_vorp']:.1f} | "
                  f"$/weighted-VORP {s['dollar_per_weighted_vorp']:.3f}")

    return all_players, pos_stats


def assign_position_tiers(all_players, pos_stats):
    """Add a 'tier' key (1-indexed within each position) to every player,
    based on natural gaps in that position's own weighted-VORP curve (see
    tiers.py) — used by the live draft workbook so a pick's over/underpay
    signal ripples mainly within its own tier, not the whole position.

    Also computes per-(position, tier) discretionary $ and weighted VORP,
    splitting each position's existing totals proportional to each tier's
    share of that position's total weighted VORP. This is a pure split, not
    a new allocation — before any picks are entered, a tier's own rate
    (discretionary / weighted VORP) is mathematically identical to the
    position's rate, since both numerator and denominator scale by the same
    tier share. Static Auction Value is unaffected by tiering; only how
    LIVE recalibration ripples changes."""
    tier_stats = {}
    by_pos = {pos: sorted([p for p in all_players if p["position"] == pos],
                           key=lambda p: -p["weighted_vorp"])
              for pos in POINTS_COL}
    for pos, pos_players in by_pos.items():
        tier_list = assign_tiers_with_zero_floor(pos_players)
        for p, t in zip(pos_players, tier_list):
            p["tier"] = t

        pos_total_wvorp = pos_stats[pos]["total_weighted_vorp"]
        pos_discretionary = pos_stats[pos]["discretionary_dollars"]
        tier_wvorp_sums = {}
        for p in pos_players:
            tier_wvorp_sums[p["tier"]] = tier_wvorp_sums.get(p["tier"], 0.0) + p["weighted_vorp"]
        for tier, wvorp_sum in tier_wvorp_sums.items():
            share = wvorp_sum / pos_total_wvorp if pos_total_wvorp else 0.0
            tier_stats[(pos, tier)] = {
                "weighted_vorp": wvorp_sum,
                "discretionary_dollars": pos_discretionary * share,
            }
    return all_players, tier_stats


def write_csv(players):
    with open(OUT_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Overall Rank", "Player", "Position", "Team", "Position Rank",
                    "Proj Rank (Pos)", "Personal Rank (Pos)", "Blended Points",
                    "VORP", "Weighted VORP", "Tier", "Auction Value ($)"])
        pos_rank_counter = {"QB": 0, "RB": 0, "WR": 0, "TE": 0}
        for i, p in enumerate(players, start=1):
            pos_rank_counter[p["position"]] += 1
            w.writerow([
                i, p["name"], p["position"], p["team"],
                pos_rank_counter[p["position"]],
                p["proj_rank"],
                p["personal_rank"] if p["personal_rank"] is not None else "",
                round(p["blended_points"], 1),
                round(p["vorp"], 1),
                round(p["weighted_vorp"], 2),
                p["tier"],
                round(p["auction_value"]),
            ])
    print(f"Wrote {len(players)} players to {OUT_FILE}")


def main():
    projections = load_projections()
    personal_ranks = load_personal_ranks()
    blended = blend_with_personal_ranks(projections, personal_ranks)
    players, pos_stats = compute_auction_values(blended)
    players, tier_stats = assign_position_tiers(players, pos_stats)
    write_csv(players)


if __name__ == "__main__":
    main()
