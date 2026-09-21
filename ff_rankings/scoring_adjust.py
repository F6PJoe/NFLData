"""
Synthesize a PPR/Standard rankings list for an analyst who only publishes
half-PPR, using real reception totals from ff_draft_proj's projections.

This is now used ONLY for Justin Boone — Hill, Ratcliffe, and Draft Sharks
all turned out to publish genuinely separate PPR/STD personal rankings (not
derived), confirmed by directly querying each source with scoring=PPR/STD
and seeing real, distinct results — Boone's FantasyPros endpoint returns an
empty player list for scoring=PPR/STD (he evidently only submits half-PPR).
Earlier this module adjusted the already-BLENDED 4-source consensus
directly, which over-corrected: it applied the reception-based math to
sources that didn't need it (their real PPR/STD submissions already reflect
each analyst's own judgment about how much weight receptions deserve, which
isn't always the pure-math answer). Per-source synthesis, only for the one
source actually missing real data, is more faithful.

`adjust_raw` is intentionally generic — it takes any list of
(key, avg, record-with-a-"Position") tuples, so it works equally on a
single source's own rank list (avg = that source's own Rank) or, if ever
needed again, a blended multi-source list. Players are never added — this
only re-orders/shifts whatever's already in the input list.

Method: the input rank order is kept as the backbone. For RB/WR/TE players
with a name match in ff_draft_proj's consensus_<pos>.csv (which already has
each player's projected half-PPR points and receptions), the points swing
from changing the per-reception value (PPR: +0.5/rec, STD: -0.5/rec
relative to half-PPR) is converted into an equivalent shift in the rank
value, using the LOCAL relationship between points and rank for that
position (a flat global rate would be wrong — the points gap between rank 1
and 2 is much bigger than between rank 80 and 81). That local rate is
estimated via a windowed linear regression of projected points vs. rank,
over nearby players (by rank) who also have a projections match.

Critically, the shift uses each player's delta RELATIVE to their
neighbors' average delta in that same window, not their own delta in
isolation — every player's points change when the format changes (everyone
gains/loses some amount from their own receptions), so what should move a
player's rank is whether they gain/lose MORE or LESS than the players
around them. A below-average-target back loses less than his neighbors
when receptions get devalued in STD, so he should RISE even though his own
points also went down. (An earlier version of this used the raw per-player
delta with no neighbor baseline, which moved players in the wrong
direction — e.g. a low-target RB incorrectly fell in STD instead of rising,
caught via a Saquon Barkley spot-check against a source's REAL STD
rankings, which showed him improving slightly, not worsening.)

Players without a projections match (deep sleepers/rookies projections
didn't cover) are left at their original rank value — i.e. unadjusted, not
dropped. QB/K/DST rows are never adjusted (receptions ~0), but still take
part in the final re-sort for OVR/FLX slots, since some of their RB/WR/TE
poolmates will have shifted around them.
"""

import csv
import os

import name_match

PROJECTIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "ff_draft_proj")

PROJECTION_FILES = {
    "RB": ("RB", "consensus_rb.csv", "Fantasy Points (Half-PPR)"),
    "WR": ("WR", "consensus_wr.csv", "Fantasy Points (Half)"),
    "TE": ("TE", "consensus_te.csv", "Fantasy Points (Half-PPR)"),
}

ADJUSTABLE_POSITIONS = set(PROJECTION_FILES.keys())

PPR_DELTA_PER_REC = {"PPR": 0.5, "STD": -0.5}

REGRESSION_WINDOW = 5  # neighbors on each side
MAX_RANK_SHIFT = REGRESSION_WINDOW * 3  # safety clamp against noisy/flat local slopes


def load_projections():
    """Returns {position: {normalized_name: (half_ppr_points, rec)}}."""
    projections = {}
    for pos, (name_col, filename, points_col) in PROJECTION_FILES.items():
        path = os.path.join(PROJECTIONS_DIR, filename)
        table = {}
        try:
            with open(path, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    name = name_match.clean_name(row[name_col])
                    key = name_match.normalize_name(name)
                    try:
                        points = float(row[points_col])
                        rec = float(row["Rec"])
                    except (KeyError, ValueError):
                        continue
                    table[key] = (points, rec)
        except FileNotFoundError:
            pass
        projections[pos] = table
    return projections


def _local_slopes_and_mean_deltas(seq):
    """seq: list of (key, avg, points, delta_points), sorted by avg
    ascending. Returns {key: (slope, mean_delta)}.

    `slope` is a windowed linear regression of points vs avg, with a
    global-slope fallback for any window with ~zero avg-variance.

    `mean_delta` is the window-local average of delta_points (each
    neighbor's OWN points change from this format switch, e.g. -0.5*their
    receptions for STD) — needed because every player's points shift when
    the scoring format changes, not just the one being adjusted. What
    should move a player's RANK is their delta relative to their
    neighbors' deltas, not their raw delta in isolation — e.g. a back with
    below-average receptions for his tier loses LESS than his neighbors in
    STD, so he should rise even though his own points also went down."""
    n = len(seq)
    if n < 2:
        return {seq[0][0]: (None, 0.0)} if n == 1 else {}

    def slope_of(sub):
        avgs = [s[1] for s in sub]
        pts = [s[2] for s in sub]
        mean_a = sum(avgs) / len(avgs)
        mean_p = sum(pts) / len(pts)
        var = sum((a - mean_a) ** 2 for a in avgs)
        if var < 1e-9:
            return None
        cov = sum((a - mean_a) * (p - mean_p) for a, p in zip(avgs, pts))
        return cov / var

    global_slope = slope_of([(k, a, p) for k, a, p, _d in seq])

    out = {}
    for i in range(n):
        lo, hi = max(0, i - REGRESSION_WINDOW), min(n, i + REGRESSION_WINDOW + 1)
        window = seq[lo:hi]
        s = slope_of([(k, a, p) for k, a, p, _d in window])
        # Points should decrease as avg-rank increases (worse rank = fewer
        # points) — a slope that's missing, zero, or (noisily) positive
        # isn't trustworthy locally, so fall back to the position's overall
        # slope instead of risking a division blowup or a backwards shift.
        if s is None or s >= 0:
            s = global_slope if global_slope and global_slope < 0 else None
        mean_delta = sum(d for _k, _a, _p, d in window) / len(window)
        out[seq[i][0]] = (s, mean_delta)
    return out


def adjust_raw(raw, scoring):
    """raw: build_consensus.build_slot_raw(slot) output. scoring: "PPR" or
    "STD". Returns a new raw list (same shape) with `avg` nudged for
    matched RB/WR/TE players."""
    if scoring not in PPR_DELTA_PER_REC:
        return raw

    projections = load_projections()
    per_rec = PPR_DELTA_PER_REC[scoring]

    by_pos = {}
    for key, avg, rec in raw:
        by_pos.setdefault(rec["Position"], []).append((key, avg, rec))

    points_by_key = {}
    for pos, items in by_pos.items():
        if pos not in ADJUSTABLE_POSITIONS:
            continue
        table = projections.get(pos, {})
        for key, _avg, _rec in items:
            if key in table:
                points_by_key[key] = table[key]

    shift_by_key = {}
    for pos, items in by_pos.items():
        if pos not in ADJUSTABLE_POSITIONS:
            continue
        items_sorted = sorted(items, key=lambda r: r[1])
        seq = [(key, avg, points_by_key[key][0], per_rec * points_by_key[key][1])
               for key, avg, _rec in items_sorted if key in points_by_key]
        if len(seq) < 2:
            continue
        slopes_and_means = _local_slopes_and_mean_deltas(seq)
        for key, _avg, _points, delta_points in seq:
            slope, mean_delta = slopes_and_means.get(key, (None, 0.0))
            if not slope:
                continue
            # Relative delta: how much MORE (or less) this player's points
            # change than their neighbors', not their delta in isolation —
            # everyone's points shift when the format changes.
            shift = (delta_points - mean_delta) / slope
            shift = max(-MAX_RANK_SHIFT, min(MAX_RANK_SHIFT, shift))
            shift_by_key[key] = shift

    adjusted = []
    for key, avg, rec in raw:
        new_avg = avg + shift_by_key.get(key, 0.0)
        adjusted.append((key, new_avg, rec))
    return adjusted


def rows_to_raw(rows, name_col):
    """Convert a plain fetch_*.py row list (dicts with a "Rank", a
    "Position", and a name column) into adjust_raw's (key, avg, record)
    shape, using that row's own Rank as the avg/value to shift."""
    raw = []
    for row in rows:
        name = name_match.clean_name(row[name_col])
        key = name_match.normalize_name(name)
        raw.append((key, row["Rank"], row))
    return raw


def raw_to_rows(raw):
    """Inverse of rows_to_raw: sort by the (possibly shifted) avg and
    reassign a clean 1..N Rank."""
    rows = sorted(raw, key=lambda r: r[1])
    out = []
    for i, (_key, _avg, rec) in enumerate(rows):
        rec = dict(rec)
        rec["Rank"] = i + 1
        out.append(rec)
    return out
