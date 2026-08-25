#!/usr/bin/env python3
"""
Estimate REPLACEMENT_RANK/VORP_EXPONENT/POSITION_BUDGET_SHARE for a roster
shape within the realistic bounded range: QB 1 starter + 0-1 additional
QB-eligible (superflex) flex slot, RB 2, WR 2-3, TE 1, 1-2 total FLEX
slots (standard RB/WR/TE-eligible, with at most one of them being
superflex-type), DEF/K/bench free (mechanical only, no calibration
needed). See CLAUDE.md, "Round 7: roster configuration" for the full
account of why this needs two different treatments for rank vs.
budget-share/exponent.

## Two different models, because rank and budget-share behave differently

**REPLACEMENT_RANK**: a smooth "required demand" formula, anchored to
whichever (teams, fmt) baseline is already real-calibrated:

    demand(pos) = starters[pos]
                  + FLEX_SHARE_STANDARD[pos] * standard_flex_slots
                  + FLEX_SHARE_SUPERFLEX[pos] * superflex_slots
    rank_estimate(pos) = rank_calibrated(pos) * demand(pos) / demand(pos; BASELINE)

FLEX_SHARE_STANDARD (RB 0.182, WR 0.250, TE 0.083) is derived from real
data: comparing the user's real 14-team/PPR league at 1-FLEX (already
calibrated) against 3-FLEX (calibrate_3flex.py, same team count/format/
starters, only flex count differs) isolates the split cleanly. QB
correctly showed exactly 0 in that comparison (not flex-eligible in that
shape) -- a real internal consistency check, not assumed.

FLEX_SHARE_SUPERFLEX decomposes a QB-eligible flex slot's demand into a
QB portion (0.625, derived from comparing the 12-team/half-PPR baseline
against real superflex data -- calibrate_superflex.py) and a remaining
RB/WR/TE portion (the leftover 0.375, split across RB/WR/TE using the
SAME relative proportions as FLEX_SHARE_STANDARD -- an ASSUMPTION, not
independently verified, since the superflex rank data alone is confounded
by budget share moving dramatically at the same time and can't cleanly
isolate the RB/WR/TE split the way the 3-flex comparison could).

**POSITION_BUDGET_SHARE and VORP_EXPONENT**: NOT the same smooth formula
as rank, but not a flat hold either (see the update below) -- a hybrid.

Tested directly (see CLAUDE.md): a naive "scales with demand ratio" model
predicted superflex QB should get ~11.6% of budget; the real number is
29.7% -- off by 2.5x. Real auction budget allocation responds to
positional scarcity in a way that's NOT proportional to demand once a
position crosses a genuine scarcity threshold. That's the REGIME SWITCH
piece: no superflex-level QB demand (QB starters=1 and 0 superflex slots)
uses the (teams, fmt) baseline as a starting point; >=1 superflex slot (or
QB starters=2) applies the REAL observed superflex shift (measured once,
at 12-team/half-PPR) as a per-position multiplicative adjustment on top of
whatever (teams, fmt) baseline is active -- an EXTRAPOLATION for any
(teams, fmt) other than 12-team/half-PPR itself, flagged as such.

Within the non-superflex regime, exponent/budget_share are NOT flat-held
anymore either -- an earlier version of this file did that, and building
it into the live Excel workbook exposed a real gap: the user's own 3-flex
league (calibrate_3flex.py) landed $5-6 off from a flat hold, traced to
VORP_EXPONENT actually shifting a meaningful amount with flex count (TE's
exponent moved a full 0.85->1.10 between 1-flex and 3-flex, not the small
drift budget_share showed). Fixed with a LINEAR INTERPOLATION by flex
count, fit through the two real anchors this project has (1-flex baseline
and 3-flex, same 14-team/PPR/1QB/2RB/3WR/1TE, RB/WR/TE-type flex only --
EXPONENT_SLOPE_PER_FLEX / BUDGET_SHARE_SLOPE_PER_FLEX below). Only applies
when the standard flex is RB/WR/TE-type -- no data exists for how
exponent/budget_share move under an RB/WR-only or WR/TE-only flex, so
those still flat-hold at baseline. Two real data points is a thin basis
for a slope (it's a line, not a curve -- extrapolating far past 3 flex
slots is weaker evidence than the 1-3 range it was fit on), but it's a
real, measured improvement over ignoring the effect entirely.

Usage (as a library, not a script):
    from roster_formula import estimate_roster_shape
    result = estimate_roster_shape(
        teams=14, fmt="ppr",
        starters={"QB": 1, "RB": 2, "WR": 3, "TE": 1},
        standard_flex_slots=3, superflex_slots=0)
    # result == {"ranks": {...}, "exponents": {...}, "budget_share": {...},
    #            "confidence": {...}}
"""

from build_auction_values import STARTERS as BASELINE_STARTERS, FLEX_SLOTS as BASELINE_FLEX_SLOTS
from build_teamcount_estimate import CALIBRATED

# Derived from real data (calibrate_3flex.py vs. the (14, ppr) baseline)
# -- see module docstring. Round 8 (2026-07): re-derived after the
# 15-combo baseline refresh moved (14, ppr)'s own WR/TE ranks (65->70,
# 26->28) -- these shares are SOLVED so the demand-ratio formula still
# lands exactly on calibrate_3flex.py's real (unchanged) 75/30, not
# independently re-measured. RB unchanged (its baseline rank didn't move,
# so the old share still round-trips exactly). WR dropped 0.25->0.111 and
# TE dropped 0.0833->0.037 -- a big swing, but it's solving the same
# equation against a baseline that shifted closer to the 3-flex target on
# its own, so less additional flex-driven demand is needed to bridge the
# (now smaller) remaining gap.
FLEX_SHARE_STANDARD = {"QB": 0.0, "RB": 0.1818, "WR": 0.1111, "TE": 0.037}

# QB portion derived from real data (calibrate_superflex.py vs. the
# 12-team/half-PPR baseline). Round 8 (2026-07): re-derived after both the
# (12, half_ppr) baseline (QB rank 16->20) and the superflex anchor itself
# (QB rank 26->28) moved -- re-solved so QB still round-trips exactly:
# 0.625->0.40. The RB/WR/TE remainder is still split using
# FLEX_SHARE_STANDARD's own (also just-updated) proportions -- an
# assumption, see module docstring; RB/WR/TE were never independently
# verified to round-trip exactly here even before this update (confirmed:
# the pre-update RB/WR/TE misses were already nonzero -- 7.5%/1.7%/
# structurally the same "assumption" gap, not something this round broke).
_SF_QB_SHARE = 0.40
_standard_total = FLEX_SHARE_STANDARD["RB"] + FLEX_SHARE_STANDARD["WR"] + FLEX_SHARE_STANDARD["TE"]
FLEX_SHARE_SUPERFLEX = {
    "QB": _SF_QB_SHARE,
    "RB": FLEX_SHARE_STANDARD["RB"] / _standard_total * (1 - _SF_QB_SHARE),
    "WR": FLEX_SHARE_STANDARD["WR"] / _standard_total * (1 - _SF_QB_SHARE),
    "TE": FLEX_SHARE_STANDARD["TE"] / _standard_total * (1 - _SF_QB_SHARE),
}

# The one real superflex data point (12-team, half-PPR) -- calibrate_superflex.py.
# Round 8 (2026-07): re-run against current reference data along with the
# 15-combo refresh in build_teamcount_estimate.py -- QB rank 26->28, QB
# exponent 1.0->1.4 (a real, meaningful shift; RB/WR/TE unchanged). Needed
# alongside the (12, half_ppr) baseline update since this shift ratio is
# computed relative to that baseline -- leaving this stale while the
# baseline moved would have thrown off the sf_ratio_exp/sf_ratio_share
# computation below. Budget share unchanged (matched exactly on re-run).
SUPERFLEX_ANCHOR = {
    "teams": 12, "fmt": "half_ppr",
    "ranks": {"QB": 28, "RB": 40, "WR": 60, "TE": 22},
    "exponents": {"QB": 1.4, "RB": 1.2, "WR": 1.3, "TE": 1.0},
    "budget_share": {"QB": 0.2971, "RB": 0.2936, "WR": 0.3306, "TE": 0.0787},
}

# Linear interpolation by flex COUNT, fit through the two real anchors at
# 14-team/PPR/1QB/2RB/3WR/1TE with RB/WR/TE-type flex: 1-flex (the
# existing calibrated baseline) and 3-flex (calibrate_3flex.py). Only
# valid for RB_WR_TE-type flex -- see module docstring.
_FLEX3_EXPONENTS = {"QB": 1.2, "RB": 1.15, "WR": 1.2, "TE": 1.1}
_FLEX3_BUDGET_SHARE = {"QB": 0.06, "RB": 0.421, "WR": 0.4279, "TE": 0.0911}
_FLEX3_ANCHOR_TEAMS_FMT = (14, "ppr")

EXPONENT_SLOPE_PER_FLEX = {
    pos: (_FLEX3_EXPONENTS[pos] - CALIBRATED[_FLEX3_ANCHOR_TEAMS_FMT]["exponents"][pos]) / 2
    for pos in ("QB", "RB", "WR", "TE")
}
BUDGET_SHARE_SLOPE_PER_FLEX = {
    pos: (_FLEX3_BUDGET_SHARE[pos] - CALIBRATED[_FLEX3_ANCHOR_TEAMS_FMT]["budget_share"][pos]) / 2
    for pos in ("QB", "RB", "WR", "TE")
}


def _renormalize_excluding(shares, excluded_pos):
    """Redistribute an excluded position's flex share onto the remaining
    eligible positions, proportional to their existing relative split.
    ASSUMPTION, not independently verified against real data -- no
    reference source pull exists for an RB/WR-only or WR/TE-only flex
    league, unlike the RB/WR/TE case (calibrate_3flex.py) and the
    QB-inclusive case (calibrate_superflex.py). If real data for either
    ever gets pulled, replace this with a direct measurement the same way
    those two were."""
    remaining = {p: v for p, v in shares.items() if p != excluded_pos and p != "QB"}
    total_remaining = sum(remaining.values())
    total_all = sum(v for p, v in shares.items() if p != "QB")
    return {p: v * total_all / total_remaining for p, v in remaining.items()}


# Flex-eligibility types this project can represent. RB_WR_TE and
# SUPERFLEX are grounded in real data (see above); RB_WR and WR_TE are
# derived by renormalization (see _renormalize_excluding) since no real
# reference data exists for either -- always "estimated" confidence.
FLEX_TYPES = {
    "RB_WR_TE": FLEX_SHARE_STANDARD,
    "RB_WR": {**_renormalize_excluding(FLEX_SHARE_STANDARD, "TE"), "QB": 0.0, "TE": 0.0},
    "WR_TE": {**_renormalize_excluding(FLEX_SHARE_STANDARD, "RB"), "QB": 0.0, "RB": 0.0},
    "SUPERFLEX": FLEX_SHARE_SUPERFLEX,
}


def _demand(pos, starters, flex_slots):
    """flex_slots: list of (flex_type, count) pairs, e.g.
    [("RB_WR_TE", 1), ("SUPERFLEX", 1)] for a league with one standard
    flex and one superflex slot together."""
    total = starters.get(pos, 0)
    for flex_type, count in flex_slots:
        total += FLEX_TYPES[flex_type].get(pos, 0.0) * count
    return total


_BASELINE_FLEX = [("RB_WR_TE", BASELINE_FLEX_SLOTS)]

# Exponent on the starter-demand ratio when scaling replacement rank.
# 1.0 = fully proportional: replacement rank tracks roster demand exactly,
# which is the same structure ff_cheatsheet uses (teams x starters + a
# small buffer) and the same structure the calibrated ranks themselves
# already have -- rank / (teams x demand) lands at ~1.6-1.7 across every
# position and team count, i.e. a flat depth multiplier on top of demand.
#
# This was briefly set to 0.45, fitted against per-player DOLLAR ratios
# from a FantasyPros 3WR-vs-2WR A/B. That was a mistake worth recording:
# dollars conflate replacement rank, budget share AND exponent, so the
# rank parameter silently absorbed error that actually belonged to a
# too-flat exponent, and the fit "succeeded" while making absolute values
# worse (it pushed Puka Nacua to $55 in a 2WR league where the real
# market says ~$64).
#
# Refitted against structure instead of dollars, which cannot be
# confounded that way: counting how many players carry positive value in
# each FantasyPros export gives their implied replacement depth directly.
# WR depth moves 59 -> 41 going 3WR -> 2WR (ratio 0.695 and 0.667 in the
# two RB variants); the linear demand ratio predicts 0.679, while 0.45
# damping predicts 0.840. Linear is essentially exact. RB implies ~0.70
# rather than 1.0, but that dimension is measured off a $0/$1 cutoff and
# is the noisier read, so the structurally-consistent 1.0 is kept.
STARTER_RANK_DAMPING = 1.0

# Floor on VORP_EXPONENT, applied per position after the (teams, fmt)
# lookup and any flex interpolation.
#
# The exponent controls how steeply a position's money concentrates at its
# top. The stored calibration gives TE the LOWEST exponent of all four
# positions in 14 of 15 combos (1.0 or below, vs 1.05-1.40 for QB/RB/WR).
# That is backwards on its face: TE is the most top-heavy position in
# fantasy football -- the cliff from the elite tier to streamers is the
# steepest of any position -- so it should carry the HIGHEST convexity,
# not the lowest.
#
# Read as a fitting artifact rather than a real finding: TE's dollar range
# is compressed (roughly $1-$33), so a grid search minimising absolute
# error barely feels the difference between exponents and drifts low.
# CLAUDE.md records TE exponent bouncing 0.5-1.1 across calibration rounds
# and repeatedly flags TE depth as never fully resolved -- the signature of
# a parameter the search cannot pin down, not a stable measurement.
#
# Corroborated by the symptom: at the 12-team/half-PPR baseline the stored
# TE exponent of 1.0 prices Trey McBride at $23 while FantasyPros AND
# Draft Sharks -- two unrelated sources -- both independently say $33.
# A floor of 1.6 lands him exactly on $33 and leaves every other position
# untouched. This is a floor, not an override: any combo already
# calibrated above it keeps its own fitted value.
#
# Remove this once a real recalibration against fresh reference data
# produces a TE exponent that is no longer the lowest of the four.
# WR floor added for the same reason, found the same way. With the stored
# WR exponent of 1.25 the WR top-12 came in 14.1% BELOW the real market at
# the default 12-team 2RB/3WR shape, while RB landed +1.8% and TE +0.3% --
# WR was the clear outlier, not TE/QB. Since WR's budget share already
# matches (42.2% vs a real 43.1%), the position's total money was right and
# it was purely spread too far down the list.
#
# That flatness is also what made TE and QB LOOK expensive: with the top
# WRs understated, Trey McBride and Josh Allen floated too high on the
# combined board relative to where the real market puts them (~19th-20th
# overall). Correcting WR fixes the board ordering without touching either.
#
# Swept on top-12 POSITION TOTALS rather than a single player, to avoid
# fitting the curve to one name: 1.25 -> -14.1%, 1.45 -> -6.9%,
# 1.55 -> -3.4%, 1.65 -> +0.1% at the default shape. 1.5 sits mid-plateau
# and lands WR within a few points of RB/TE at both 3WR and 2WR, which is
# the actual goal -- parity across positions, not matching any one site.
# TE floor lowered 1.6 -> 1.45. The 1.6 was set by tuning to a SINGLE
# player (Trey McBride hitting $33) -- the same single-point fitting error
# that produced the bad 0.45 rank damping, repeated. Re-swept on the top-2
# combined AND top-12 total instead, at both 3WR and 2WR:
#
#   TEexp   3WR top2 / top12   2WR top2 / top12
#   1.40        60 / 180           69 / 206
#   1.45       ~62 / 181          ~71 / 207
#   1.60        67 / 185           77 / 212
#
# Real spread: 3WR top-2 is 62 (Draft Sharks) to 64 (FantasyPros); 2WR
# top-2 is 70 (FantasyPros). 1.6 overshot BOTH sources at both shapes
# (67 and 77); 1.45 sits inside the DS-to-FP range at both. Note the top-12
# total barely moves across this range (180-185) -- the exponent is almost
# entirely a top-of-position knob, which is why fitting it to one player
# is so easy to get wrong.
# WR floor REMOVED (was briefly 1.5). It was added to close a -14.1% gap
# in the WR top-12 total, but that was the wrong instrument and it broke
# something more important than it fixed:
#
#   - It pushed the top WRs ABOVE both reference sources, not between them
#     (Puka Nacua $62 at 3WR and $77 at 2WR, against a real range of
#     $54 Draft Sharks / $60 FantasyPros at 3WR and ~$64 at 2WR).
#   - It inverted the RB/WR ordering. At 2WR it put Puka ($77) ABOVE Gibbs
#     ($72), which is backwards on its face: cutting a WR starter should
#     make WRs relatively CHEAPER, and both sources keep the top RB above
#     the top WR in both shapes.
#
# The interaction is why: at 2WR the WR replacement rank shallows 60 -> 41,
# and a raised exponent amplifies top-end concentration on top of an
# already-concentrating pool, so an exponent that merely overshoots at 3WR
# badly overshoots at 2WR.
#
# The underlying -14.1% WR top-12 gap is REAL and still open, but it is not
# an exponent problem -- WR budget share already matches (42.2% vs 43.1%
# real) and WR replacement depth already matches (60 vs a real 59). With
# share and depth both correct, the remaining gap points at the projection
# curve, not the valuation math. Left alone rather than papered over with
# an exponent that damages the cross-position ordering.
MIN_EXPONENT = {"QB": 0.0, "RB": 0.0, "WR": 0.0, "TE": 1.45}


def _scale_share_by_starter_demand(raw_share, starters, flex_slots):
    """Scale each position's budget share by how its STARTER demand
    compares to the calibrated baseline shape.

    Fixes a real, user-reported bug: `ranks` scaled with demand (including
    starter-count changes) but budget_share responded ONLY to flex count,
    so changing a starter count moved the replacement line without moving
    the money. Concretely, dropping WR starters 3->2 at 12-team/half-PPR
    raised the WR replacement rank 60->41, which zeroed out 19 players'
    weighted VORP and collapsed the WR pool 11282->5278 (-53%) -- while
    WR kept its full ~42% of the discretionary budget. Since
    rate = discretionary * share / pool, halving the denominator with a
    fixed numerator DOUBLED the rate (0.083->0.177) and Puka Nacua went
    UP from $52 to $83 for having FEWER startable WRs, which is backwards.

    The ratio deliberately holds flex_slots constant in both numerator and
    denominator so this isolates the starters dimension only -- the flex
    dimension is already handled by BUDGET_SHARE_SLOPE_PER_FLEX above, and
    a full demand ratio would double-count it.

    Verified to leave all three real anchors bit-exact (baseline, 3-flex,
    superflex all use BASELINE_STARTERS, so every ratio here is exactly
    1.0 and this is a no-op for them) -- it only engages for the
    starter-count shapes that previously had no budget-share response at
    all. Note this is an ESTIMATE for those shapes: no real market data
    exists for e.g. a 2-WR league, and the demand-proportional assumption
    is known NOT to hold across a genuine scarcity regime change (the
    superflex QB case, see module docstring) -- it's applied here only
    within the non-superflex regime, where positions stay in the same
    scarcity class and demand-proportional is a reasonable first order.
    """
    scaled = {}
    for pos in ("QB", "RB", "WR", "TE"):
        base_demand = _demand(pos, BASELINE_STARTERS, flex_slots)
        new_demand = _demand(pos, starters, flex_slots)
        ratio = (new_demand / base_demand) if base_demand else 1.0
        scaled[pos] = raw_share[pos] * ratio
    return scaled


def estimate_roster_shape(teams, fmt, starters, flex_slots):
    """flex_slots: list of (flex_type, count) pairs -- flex_type one of
    "RB_WR_TE", "RB_WR", "WR_TE", "SUPERFLEX". Multiple entries can be
    combined for a mixed league (e.g. 1 standard flex + 1 superflex slot).

    Returns {"ranks": {...}, "exponents": {...}, "budget_share": {...},
    "confidence": "verified"|"estimated (...)"}.

    Requires (teams, fmt) to already be a real-calibrated baseline in
    CALIBRATED -- that baseline's own roster shape (BASELINE_STARTERS /
    one RB_WR_TE flex, no superflex) is the anchor for the rank formula.
    """
    if (teams, fmt) not in CALIBRATED:
        raise ValueError(f"({teams}, {fmt}) has no real calibration to anchor from")
    baseline = CALIBRATED[(teams, fmt)]

    has_superflex = any(ft == "SUPERFLEX" and n > 0 for ft, n in flex_slots)
    has_nonstandard_flex = any(ft in ("RB_WR", "WR_TE") and n > 0 for ft, n in flex_slots)

    is_exact_baseline = (starters == BASELINE_STARTERS and flex_slots == _BASELINE_FLEX)
    is_exact_3flex = (
        teams == 14 and fmt == "ppr" and starters == {"QB": 1, "RB": 2, "WR": 3, "TE": 1}
        and flex_slots == [("RB_WR_TE", 3)]
    )
    is_exact_superflex = (
        teams == SUPERFLEX_ANCHOR["teams"] and fmt == SUPERFLEX_ANCHOR["fmt"]
        and starters == BASELINE_STARTERS and flex_slots == [("SUPERFLEX", 1)]
    )

    ranks = {}
    for pos in ("QB", "RB", "WR", "TE"):
        # Split the demand response into its two dimensions, because they
        # empirically do NOT respond the same way (see
        # STARTER_RANK_DAMPING). Flex stays fully proportional -- that's
        # what the real 3-flex and superflex anchors require to round-trip
        # exactly. Starters get damped.
        # Order matters: measure the starter change FIRST in its own
        # natural units (at baseline flex), then measure the flex change
        # on top of THIS shape's actual starter count.
        #
        # Evaluating the flex ratio at BASELINE_STARTERS instead (the
        # obvious-looking alternative) double-counts whenever both
        # dimensions move: for QB it always yields (1+0.40)/1 = 1.40x for a
        # superflex slot, even in a 2-QB league where that slot's real
        # marginal contribution is only (2+0.40)/2 = 1.20x. That pushed
        # 2QB+1SF to rank 36 and priced Josh Allen at $45, BELOW his $94 in
        # a plain 2QB league despite strictly more QB demand. This ordering
        # gives rank 33 and restores monotonicity.
        #
        # Both anchors are unaffected either way (they use
        # BASELINE_STARTERS, so the starter ratio is exactly 1.0 and the
        # flex ratio is identical under both orderings), and so is every
        # starters-only change (flex ratio is 1.0), which is what the
        # FantasyPros A/B fit was validated against.
        base_st = _demand(pos, BASELINE_STARTERS, _BASELINE_FLEX)
        new_st = _demand(pos, starters, _BASELINE_FLEX)
        starter_ratio = (new_st / base_st) if base_st else 1.0

        base_flex = _demand(pos, starters, _BASELINE_FLEX)
        new_flex = _demand(pos, starters, flex_slots)
        flex_ratio = (new_flex / base_flex) if base_flex else 1.0

        ranks[pos] = round(baseline["ranks"][pos] * flex_ratio
                            * starter_ratio ** STARTER_RANK_DAMPING)

    if not has_superflex:
        # Linear interpolation by RB_WR_TE-type flex count, fit through
        # the two real anchors (1-flex baseline, 3-flex) -- see module
        # docstring for why this replaced a flat hold. Only the RB_WR_TE
        # slot count moves this; RB_WR/WR_TE slots don't (no data).
        rb_wr_te_count = sum(n for ft, n in flex_slots if ft == "RB_WR_TE")
        flex_delta = rb_wr_te_count - BASELINE_FLEX_SLOTS
        exponents = {pos: round(baseline["exponents"][pos] + EXPONENT_SLOPE_PER_FLEX[pos] * flex_delta, 3)
                     for pos in ("QB", "RB", "WR", "TE")}
        raw_share = {pos: baseline["budget_share"][pos] + BUDGET_SHARE_SLOPE_PER_FLEX[pos] * flex_delta
                     for pos in ("QB", "RB", "WR", "TE")}
        raw_share = _scale_share_by_starter_demand(raw_share, starters, flex_slots)
        total_raw = sum(raw_share.values())
        budget_share = {pos: v / total_raw for pos, v in raw_share.items()}
        if is_exact_baseline or is_exact_3flex:
            confidence = "verified"
        elif has_nonstandard_flex:
            confidence = "estimated (rank AND flex-share both estimated -- no real data for RB/WR-only or WR/TE-only flex; budget share/exponent held at real baseline, no flex-count interpolation applied to the non-standard portion)"
        else:
            confidence = "estimated (rank verified-adjacent; exponent/budget-share linearly interpolated from 2 real anchors -- weaker evidence further from 1-3 flex slots)"
    else:
        # Regime switch: apply the REAL observed superflex shift (a
        # per-position multiplicative ratio, measured once at 12-team/
        # half-PPR) on top of whichever (teams, fmt) baseline is active.
        exponents = {}
        budget_share = {}
        sf_anchor_baseline = CALIBRATED[(SUPERFLEX_ANCHOR["teams"], SUPERFLEX_ANCHOR["fmt"])]
        for pos in ("QB", "RB", "WR", "TE"):
            sf_ratio_exp = SUPERFLEX_ANCHOR["exponents"][pos] / sf_anchor_baseline["exponents"][pos]
            sf_ratio_share = SUPERFLEX_ANCHOR["budget_share"][pos] / sf_anchor_baseline["budget_share"][pos]
            exponents[pos] = round(baseline["exponents"][pos] * sf_ratio_exp, 3)
            budget_share[pos] = baseline["budget_share"][pos] * sf_ratio_share
        # The superflex shift above is a FIXED per-position ratio measured
        # at one specific shape: 1 QB starter + 1 superflex slot. It does
        # not know how much QB demand the actual configured shape has, so
        # on its own it hands e.g. "2 QB starters PLUS a superflex slot"
        # the exact same 29.7% QB share as a plain 1QB superflex -- while
        # the rank formula above correctly keeps deepening QB replacement
        # level for that extra demand. Same failure mode as the original
        # starter-count bug: pool grows, money doesn't, so every QB gets
        # CHEAPER the more QBs you're required to start. Confirmed in the
        # workbook before fixing: 2QB+1SF put Josh Allen at $33, BELOW his
        # $66 plain-superflex and barely above his $31 single-QB value.
        # Scaling by starter demand here (measured against BASELINE_STARTERS
        # carrying this same flex config, exactly as the non-superflex
        # branch does) makes QB share respond to that extra demand. No-op
        # at the real superflex anchor itself, which uses BASELINE_STARTERS,
        # so the anchor still round-trips exactly.
        # Scale by TOTAL demand vs the superflex anchor's own shape, not by
        # the starters-only ratio the non-superflex branch uses. Reason:
        # here the QB-eligible flex IS part of QB demand, so a
        # starters-only ratio (which holds flex constant on both sides)
        # actually SHRINKS as you add superflex slots, while the rank
        # formula simultaneously deepens QB replacement level for those
        # same slots. Those two pull opposite ways and produced a
        # nonsensical ordering: 2QB+1SF priced Josh Allen BELOW plain 2QB
        # ($46 vs $111) even though it has strictly more QB demand.
        # Measuring total demand against the anchor keeps the ordering
        # monotonic in demand, and is still an exact no-op at the anchor
        # itself (ratio 1.0), so that round-trip is preserved.
        sf_anchor_flex = [("SUPERFLEX", 1)]
        raw = {}
        for pos in ("QB", "RB", "WR", "TE"):
            anchor_demand = _demand(pos, BASELINE_STARTERS, sf_anchor_flex)
            this_demand = _demand(pos, starters, flex_slots)
            ratio = (this_demand / anchor_demand) if anchor_demand else 1.0
            raw[pos] = budget_share[pos] * ratio
        budget_share = raw
        # renormalize budget_share to sum to 1 (the two ratios were fit
        # independently per position, so the product isn't guaranteed to)
        total_share = sum(budget_share.values())
        budget_share = {pos: v / total_share for pos, v in budget_share.items()}
        confidence = "verified" if is_exact_superflex else "estimated (superflex shift extrapolated from the single 12-team/half-PPR anchor)"

    # Apply the per-position exponent floor (see MIN_EXPONENT) last, so it
    # covers both regime branches and any flex interpolation above it.
    exponents = {pos: max(exponents[pos], MIN_EXPONENT[pos]) for pos in exponents}

    return {"ranks": ranks, "exponents": exponents, "budget_share": budget_share, "confidence": confidence}


def _print_result(label, result):
    print(f"--- {label} ({result['confidence']}) ---")
    print("  ranks:", result["ranks"])
    print("  exponents:", result["exponents"])
    print("  budget_share:", {k: round(v, 4) for k, v in result["budget_share"].items()})


if __name__ == "__main__":
    # Self-checks: do the two REAL anchors round-trip exactly?
    _print_result(
        "14T/PPR/3-flex (should exactly match calibrate_3flex.py)",
        estimate_roster_shape(14, "ppr", {"QB": 1, "RB": 2, "WR": 3, "TE": 1}, [("RB_WR_TE", 3)]))
    _print_result(
        "12T/half-PPR, the 1 flex slot IS the superflex (should exactly match calibrate_superflex.py)",
        estimate_roster_shape(12, "half_ppr", {"QB": 1, "RB": 2, "WR": 3, "TE": 1}, [("SUPERFLEX", 1)]))
    print()
    # A mixed-flex shape with no real anchor at all -- purely estimated
    _print_result(
        "14T/PPR, 1QB/2RB/2WR/1TE, 1 standard flex + 1 superflex slot (no real anchor)",
        estimate_roster_shape(14, "ppr", {"QB": 1, "RB": 2, "WR": 2, "TE": 1},
                               [("RB_WR_TE", 1), ("SUPERFLEX", 1)]))
    # RB/WR-only flex -- also no real anchor, estimated via renormalization
    _print_result(
        "12T/half-PPR, 1QB/2RB/3WR/1TE, 1 RB/WR-only flex (no real anchor)",
        estimate_roster_shape(12, "half_ppr", {"QB": 1, "RB": 2, "WR": 3, "TE": 1},
                               [("RB_WR", 1)]))
