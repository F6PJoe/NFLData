#!/usr/bin/env python3
"""
Blend the 4 rankings sources (Ratcliffe, Hill, Boone, Draft Sharks) into a
consensus rank per slot (OVR/QB/RB/WR/TE/FLX).

Players are matched across sources by a normalized name (name_match.py,
ported from ff_draft_proj/build_consensus.py).

Handling players missing from a source's list ("gap filling"):
A flat average over only the sources that ranked a player rewards thin
coverage too much (a deep sleeper ranked by only 1 of 4 sources would get an
artificially good average). Instead, each source's rank list is first
extended to cover every player appearing in ANY source, with missing players
appended at the bottom in rank order continuing from that source's own last
rank (so a source that only ranked 300 players has its "gap" players start
at rank 301, 302, ... rather than some arbitrary large number) — this
penalizes an unranked player by roughly "worse than anyone this analyst
actually evaluated," scaled to that analyst's own list depth, rather than a
shared worst-case number that would penalize shallow lists unfairly.

The 4 sources have a priority order (Ratcliffe, Hill, Boone, Draft Sharks)
used only to build a single canonical "union" player order, so gap-filling
is deterministic:
  1. Start from Ratcliffe's own list, in Ratcliffe's order.
  2. Append players found in Hill but not yet in that list (in Hill's order).
  3. Append players found in Boone but not yet in that list (in Boone's
     order).
  4. Append players found in Draft Sharks but not yet in that list (in
     Draft Sharks' order).
  -> this combined order is the "union order" — every player who appears in
     at least one source, in a single consistent order.
  5. For each of Hill/Boone/Draft Sharks individually: take that source's
     own list, then append any union-order player missing from it (in union
     order), assigning continuation ranks starting at len(that source's own
     list) + 1.
  6. Ratcliffe's own extended list is just the union order itself, with
     continuation ranks the same way (Ratcliffe's original ranks 1..N
     unchanged, then the appended players numbered N+1, N+2, ...).

Every player now has a rank (real or continuation) in all 4 extended lists.
The consensus rank is the average of those 4 (real-or-continuation) ranks,
re-ranked 1..N ascending. The output CSV shows each player's REAL reported
rank per source where available; where a source didn't actually rank them,
it shows the calculated/continuation rank instead, as a NEGATIVE number
(e.g. -312), so the gap-fill math is visible/checkable rather than hidden
behind a blank, while keeping the column numeric/sortable (parentheses were
tried first, but spreadsheet software auto-converts "(312)" into the
negative number -312 anyway via accounting-format auto-detection — so this
just emits that directly instead of fighting it). The `Sources` count only
counts sources that REALLY ranked the player, not gap-filled ones.

Team is picked by majority vote across the sources that have the player
(not "first non-FA source wins") — a single stale source shouldn't outvote
3 others that agree (e.g. FTN had David Njoku on CLE while Boone/Hill/Draft
Sharks all correctly had LAC).

Column headers for the 4 source columns include each source's precise
last-updated timestamp (e.g. "Ratcliffe (6/27/2026 9:48:13)"), read from
source_timestamps.json — written by each fetch_*.py after it runs, so run
the fetchers before this script to get current timestamps.

One run writes all 3 scoring formats per slot: `consensus_<slot>.csv`
(half-PPR), `consensus_<slot>_ppr.csv`, `consensus_<slot>_std.csv` — each
blended independently from that format's own per-source files (same
gap-fill/majority-vote logic, just pointed at `<source>_<slot>_ppr.csv` etc
instead of the half files). 3 of the 4 sources (Ratcliffe, Hill, Draft
Sharks) publish genuinely separate PPR/STD rankings; Boone's are
synthesized from his half-PPR list by fetch_fantasypros_rankings.py (see
scoring_adjust.py) since FantasyPros has no real PPR/STD submission from
him — by the time this script runs, boone_<slot>_ppr.csv/_std.csv already
exist and are indistinguishable from "real" files to the blending logic
here. (An earlier version of this script instead adjusted the already-
BLENDED half-PPR consensus for every source — replaced once it turned out
3 of 4 sources have real separate PPR/STD data that's better not to
override with estimated math.)

Usage:
    python build_consensus.py
"""

import csv
import json
import os
from collections import Counter

import name_match
import source_timestamps

SLOTS = ["ovr", "qb", "rb", "wr", "te", "flx"]
SCORING_SUFFIX = {"HALF": "", "PPR": "_ppr", "STD": "_std"}


def load_active_sources():
    """Read active_sources.json written by run_all.py. Falls back to a
    legacy default list so build_consensus.py can still be run standalone
    if active_sources.json is present from a previous run."""
    path = os.path.join(os.path.dirname(__file__), "active_sources.json")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise SystemExit(
            "active_sources.json not found — run run_all.py first, or create "
            "the file manually with the list of active sources."
        )


_active = load_active_sources()
# priority order (union-building order) = order in active_sources.json
PRIORITY = [s["label"] for s in _active]
SOURCE_FILES = {s["label"]: f"{s['prefix']}_{{slot}}{{suffix}}.csv" for s in _active}
OUT_FIELDNAMES = ["Rank", "Player", "Team", "Position", "Sources"] + PRIORITY


def load_source(source, slot, suffix):
    """Returns an ordered list of (key, rank, name, team, position),
    sorted by that source's own Rank column."""
    fn = SOURCE_FILES[source].format(slot=slot, suffix=suffix)
    try:
        with open(fn, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        return []
    out = []
    for row in rows:
        name = name_match.display_name(name_match.clean_name(row["Player"]))
        team = name_match.clean_team(row.get("Team", ""))
        pos = row.get("Position", "")
        if pos == "DST":
            canonical = name_match.dst_name(team)
            if canonical:
                name = canonical
        key = name_match.normalize_name(name)
        out.append((key, int(row["Rank"]), name, team, row.get("Position", "")))
    out.sort(key=lambda r: r[1])
    return out


def build_union_order(lists_by_source):
    ref = PRIORITY[0]
    union_order = [item[0] for item in lists_by_source[ref]]
    seen = set(union_order)
    for src in PRIORITY[1:]:
        for key, _rank, _name, _team, _pos in lists_by_source[src]:
            if key not in seen:
                union_order.append(key)
                seen.add(key)
    return union_order


def build_extended_ranks(lists_by_source, union_order):
    """Returns {source: {key: extended_rank}} — real rank where the source
    actually ranked the player, continuation rank otherwise."""
    extended = {}

    ref = PRIORITY[0]
    ref_keys = [item[0] for item in lists_by_source[ref]]
    ref_ranks = {key: i + 1 for i, key in enumerate(ref_keys)}
    next_rank = len(ref_keys) + 1
    for key in union_order[len(ref_keys):]:
        ref_ranks[key] = next_rank
        next_rank += 1
    extended[ref] = ref_ranks

    for src in PRIORITY[1:]:
        src_keys = [item[0] for item in lists_by_source[src]]
        src_set = set(src_keys)
        ranks = {key: i + 1 for i, key in enumerate(src_keys)}
        next_rank = len(src_keys) + 1
        for key in union_order:
            if key not in src_set:
                ranks[key] = next_rank
                next_rank += 1
                src_set.add(key)
        extended[src] = ranks

    return extended


def build_slot_raw(slot, suffix=""):
    """Returns a list of (key, avg, record) for every player in the union —
    NOT yet sorted/ranked. `avg` is the continuous consensus value for
    whichever format `suffix` points at (lower = better); `record` has
    everything except "Rank"."""
    lists_by_source = {src: load_source(src, slot, suffix) for src in PRIORITY}
    if not any(lists_by_source.values()):
        return []

    union_order = build_union_order(lists_by_source)
    extended_ranks = build_extended_ranks(lists_by_source, union_order)

    # real (non-extended) per-player info, for display and the "Sources" count
    real_rank = {src: {} for src in PRIORITY}
    info = {}  # key -> {name, team_votes: Counter, pos}
    for src in PRIORITY:
        for key, rank, name, team, pos in lists_by_source[src]:
            real_rank[src][key] = rank
            d = info.setdefault(key, {"name": name, "team_votes": Counter(), "pos": ""})
            if len(name) > len(d["name"]):
                d["name"] = name
            # Majority vote across sources rather than "first non-FA wins" —
            # a single stale source (e.g. FTN had David Njoku on CLE while
            # Boone/Hill/Draft Sharks all correctly had LAC) shouldn't
            # outvote the other 3 just by being processed first.
            if team != "FA":
                d["team_votes"][team] += 1
            if not d["pos"]:
                d["pos"] = pos

    # Top 2 sources weighted 1.5x, remainder 1.0x
    weights = [1.5 if i < 2 else 1.0 for i in range(len(PRIORITY))]
    total_weight = sum(weights)

    raw = []
    for key in union_order:
        avg = sum(weights[i] * extended_ranks[PRIORITY[i]][key]
                  for i in range(len(PRIORITY))) / total_weight
        n_sources = sum(1 for src in PRIORITY if key in real_rank[src])
        d = info[key]
        team = d["team_votes"].most_common(1)[0][0] if d["team_votes"] else "FA"

        def display_rank(src):
            # Real rank if the source actually ranked this player; otherwise
            # the calculated/gap-filled rank used internally for the
            # average, shown as a negative number so it's visually
            # distinguishable from a real rank (lets you sanity-check the
            # gap-fill logic instead of just seeing a blank) while staying
            # numeric/sortable.
            if key in real_rank[src]:
                return real_rank[src][key]
            return -extended_ranks[src][key]

        rec = {"Player": d["name"], "Team": team, "Position": d["pos"], "Sources": n_sources}
        rec.update({src: display_rank(src) for src in PRIORITY})
        raw.append((key, avg, rec))
    return raw


def finalize(raw):
    """Sort by avg ascending and assign the final 1..N Rank."""
    rows = sorted(raw, key=lambda r: r[1])
    records = []
    for i, (_key, _avg, rec) in enumerate(rows):
        rec = dict(rec)
        rec["Rank"] = i + 1
        records.append(rec)
    return records


def build_slot(slot, suffix=""):
    return finalize(build_slot_raw(slot, suffix))


def build_header(timestamps):
    header = ["Rank", "Player", "Team", "Position", "Sources"]
    for src in PRIORITY:
        ts = timestamps.get(src)
        header.append(f"{src} ({ts})" if ts else src)
    return header


def write_slot(records, header, out):
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(header)
        for rec in records:
            w.writerow(rec[col] for col in OUT_FIELDNAMES)
    print(f"Wrote {len(records)} players to {out}.")


def main():
    timestamps = source_timestamps.load_timestamps()
    header = build_header(timestamps)

    for scoring in ("HALF", "PPR", "STD"):
        suffix = SCORING_SUFFIX[scoring]
        for slot in SLOTS:
            records = build_slot(slot, suffix)
            if not records:
                print(f"No data found for {scoring}/{slot.upper()} "
                      f"(no per-source CSVs present?).")
                continue
            write_slot(records, header, f"consensus_{slot}{suffix}.csv")


if __name__ == "__main__":
    main()
