"""
Assign tiers to players within a position based on natural gaps in their
own weighted-VORP curve — NOT an external source's tiers (Draft Sharks'
tiers come from their own projections/valuation, which differs from ours
in specific, deliberate ways; there's no reason their tier boundaries would
line up with an actual gap in our curve).

Method: walk the position's players sorted descending by weighted_vorp.
A tier break is placed after player i if the gap to player i+1 is at least
GAP_RATIO times the LOCAL median gap (the WINDOW gaps on either side) —
relative, not absolute, since gap sizes shrink naturally as VORP flattens
out deeper in a position (a raw $2 gap matters a lot at the very top of a
curve and means nothing 40 players deep). This is a standard "look for the
elbow" approach, not a novel algorithm — kept deliberately simple/auditable
rather than reaching for full 1D clustering (Jenks natural breaks etc.),
since the goal here is a transparent, debuggable rule for a live draft
tool, not statistical optimality.
"""

import statistics

GAP_RATIO = 1.8
WINDOW = 5


def assign_tiers(players_sorted_desc, gap_ratio=GAP_RATIO, window=WINDOW):
    """players_sorted_desc: list of dicts with a 'weighted_vorp' key, already
    sorted descending, restricted to weighted_vorp > 0 (the draftable pool
    — deeper players with weighted_vorp == 0 all get lumped into one final
    tier, since there's no meaningful curve shape left to find breaks in).

    Returns a new list of ints (1-indexed tier per player, same order/length
    as the input)."""
    n = len(players_sorted_desc)
    if n == 0:
        return []
    gaps = [players_sorted_desc[i]["weighted_vorp"] - players_sorted_desc[i + 1]["weighted_vorp"]
            for i in range(n - 1)]

    tiers = [1] * n
    current_tier = 1
    for i, gap in enumerate(gaps):
        lo = max(0, i - window)
        hi = min(len(gaps), i + window + 1)
        neighborhood = gaps[lo:hi]
        local_median = statistics.median(neighborhood) if neighborhood else 0
        if local_median > 0 and gap >= gap_ratio * local_median:
            current_tier += 1
        tiers[i + 1] = current_tier
    return tiers


def assign_tiers_with_zero_floor(players_sorted_desc_all, gap_ratio=GAP_RATIO, window=WINDOW):
    """Same as assign_tiers, but takes the FULL position list (including
    weighted_vorp == 0 players) and puts all zero-VORP players in one final
    tier (tier count + 1) rather than running gap detection on a flat line
    of zeros, which would be meaningless."""
    positive = [p for p in players_sorted_desc_all if p["weighted_vorp"] > 0]
    zero = [p for p in players_sorted_desc_all if p["weighted_vorp"] <= 0]
    pos_tiers = assign_tiers(positive, gap_ratio, window)
    max_tier = max(pos_tiers) if pos_tiers else 0
    return pos_tiers + [max_tier + 1] * len(zero)
