#!/usr/bin/env python3
"""
Pull one or more FantasyPros experts' personal rankings for a named source,
blend them when multiple IDs are supplied, and write per-slot CSVs.

Exit codes:
    0  = data found and written
    2  = no data available yet (source not yet published on FP)
    1  = unexpected error

Usage:
    python fetch_fantasypros_rankings.py --expert koerner
    python fetch_fantasypros_rankings.py --expert draftsharks   # blends IDs 93+145
    python fetch_fantasypros_rankings.py --expert footballguys  # blends 3900+3096+4187
"""

import argparse
import csv
import re
import sys
from collections import Counter

import requests

import name_match
import scoring_adjust
import source_timestamps

CONSENSUS_URL = "https://partners.fantasypros.com/api/v1/consensus-rankings.php"
EXPERTS_PAGE_URL = "https://www.fantasypros.com/nfl/rankings/half-point-ppr-cheatsheets.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal rankings consensus tool)"}

# Each entry: list of FP expert IDs (blended if multiple) + display label
EXPERT_CONFIGS = {
    "koerner":      {"ids": [120],              "label": "Koerner"},
    "ratcliffe":    {"ids": [125],              "label": "Ratcliffe"},
    "draftsharks":  {"ids": [145],               "label": "DraftSharks"},
    "mariano":      {"ids": [766],              "label": "Nick Mariano"},
    "footballguys": {"ids": [3900, 3096, 4187], "label": "FootballGuys"},
    "deldon":       {"ids": [285],              "label": "Del Don"},
}

POSITIONS = ["ALL", "QB", "RB", "WR", "TE"]
OUT_NAME = {"ALL": "ovr", "QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "FLX": "flx"}
SCORING_SUFFIX = {"HALF": "", "PPR": "_ppr", "STD": "_std"}

FIELDNAMES = ["Rank", "Pos Rank", "Player", "Team", "Position", "Bye",
              "Tier", "Rank Min", "Rank Max", "Rank Std"]


# ---------------------------------------------------------------------------
# FP API helpers
# ---------------------------------------------------------------------------

def fetch_position(expert_id, position, year, week, scoring, type_):
    params = {
        "sport": "NFL", "year": year, "week": week,
        "id": expert_id, "position": position, "type": type_,
        "scoring": scoring, "filters": expert_id,
    }
    resp = requests.get(CONSENSUS_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    rows = [
        {
            "Rank": p["rank_ecr"], "Pos Rank": p["pos_rank"],
            "Player": p["player_name"], "Team": p["player_team_id"],
            "Position": p["player_position_id"], "Bye": p["player_bye_week"],
            "Tier": p["tier"], "Rank Min": p["rank_min"],
            "Rank Max": p["rank_max"], "Rank Std": p["rank_std"],
        }
        for p in data["players"]
    ]
    return rows, data.get("last_updated")


def fetch_all_positions_for_id(expert_id, year, week, scoring, type_):
    """Returns (by_position dict, last_updated) or (None, None) if no data."""
    by_pos = {}
    last_updated = None
    for pos in POSITIONS:
        rows, lu = fetch_position(expert_id, pos, year, week, scoring, type_)
        if not rows:
            return None, None
        by_pos[pos] = rows
        last_updated = lu
    by_pos["FLX"] = _build_flx(by_pos["ALL"])
    return by_pos, last_updated


def _build_flx(ovr_rows):
    flx = [dict(r) for r in ovr_rows if r["Position"] in ("RB", "WR", "TE")]
    flx.sort(key=lambda r: r["Rank"])
    for i, r in enumerate(flx):
        r["Rank"] = i + 1
    return flx


# ---------------------------------------------------------------------------
# Multi-ID blending
# ---------------------------------------------------------------------------

def _player_key(name):
    return name_match.normalize_name(
        name_match.display_name(name_match.clean_name(name))
    )


def blend_row_lists(lists_of_rows):
    """Average ranks from multiple ranked lists via gap-fill, return one list."""
    if len(lists_of_rows) == 1:
        return lists_of_rows[0]

    # Parse each list into {key: rank} and collect display info
    per_source_ranks = []
    info = {}  # key -> {name, team_votes, pos, secondary_row}
    for rows in lists_of_rows:
        key_to_rank = {}
        for r in sorted(rows, key=lambda x: x["Rank"]):
            key = _player_key(r["Player"])
            key_to_rank[key] = r["Rank"]
            d = info.setdefault(key, {"name": r["Player"], "team_votes": Counter(),
                                      "pos": r.get("Position", ""), "row": r})
            if len(r["Player"]) > len(d["name"]):
                d["name"] = r["Player"]
            team = name_match.clean_team(r.get("Team", ""))
            if team != "FA":
                d["team_votes"][team] += 1
        per_source_ranks.append(key_to_rank)

    # Build union order: keys in order of first appearance across all sources
    seen, union_order = set(), []
    for ktr in per_source_ranks:
        for key in ktr:
            if key not in seen:
                union_order.append(key)
                seen.add(key)

    # Extend each source's ranks with gap-fill at own_max+1 for missing players
    extended = []
    for ktr in per_source_ranks:
        next_r = (max(ktr.values()) + 1) if ktr else 1
        ext = dict(ktr)
        for key in union_order:
            if key not in ext:
                ext[key] = next_r
                next_r += 1
        extended.append(ext)

    # Average extended ranks, re-sort
    blended = sorted(union_order, key=lambda k: sum(e[k] for e in extended) / len(extended))

    result = []
    for i, key in enumerate(blended):
        d = info[key]
        team = d["team_votes"].most_common(1)[0][0] if d["team_votes"] else "FA"
        sec = d["row"]
        result.append({
            "Rank": i + 1, "Pos Rank": "",
            "Player": d["name"], "Team": team,
            "Position": d["pos"], "Bye": sec.get("Bye", ""),
            "Tier": "", "Rank Min": "", "Rank Max": "", "Rank Std": "",
        })
    return result


def blend_all_positions(all_by_pos_list):
    """Blend per-position dicts from multiple expert IDs into one."""
    blended = {}
    for pos in POSITIONS + ["FLX"]:
        lists = [bp[pos] for bp in all_by_pos_list if bp and pos in bp]
        blended[pos] = blend_row_lists(lists) if lists else []
    # Recompute FLX from blended OVR so ranks stay cross-positional
    if blended.get("ALL"):
        blended["FLX"] = _build_flx(blended["ALL"])
    return blended


# ---------------------------------------------------------------------------
# Timestamp scraping
# ---------------------------------------------------------------------------

def fetch_expert_timestamp(expert_id):
    resp = requests.get(EXPERTS_PAGE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    m = re.search(
        r'\{"id":%d,"name":"[^"]*".*?"updated_display":"([^"]+)".*?'
        r'"updated_display_time":"([^"]*)"' % expert_id,
        resp.text,
    )
    if not m:
        return None
    date_part = m.group(1).replace("\\/", "/")
    time_part = m.group(2)
    return f"{date_part} {time_part}".strip()


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------

def write_csv(rows, out_file):
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def write_scoring(by_position, prefix, scoring):
    suffix = SCORING_SUFFIX[scoring]
    for label in ("ALL", "QB", "RB", "WR", "TE", "FLX"):
        out_file = f"{prefix}_{OUT_NAME[label]}{suffix}.csv"
        rows = by_position.get(label, [])
        write_csv(rows, out_file)
        print(f"Wrote {len(rows)} players to {out_file}.")


def synthesize_scoring(half_by_position, scoring):
    """Build PPR/STD from HALF via scoring_adjust when real data isn't available."""
    synthesized = {}
    for label, rows in half_by_position.items():
        raw = scoring_adjust.rows_to_raw(rows, "Player")
        adjusted = scoring_adjust.adjust_raw(raw, scoring)
        new_rows = scoring_adjust.raw_to_rows(adjusted)
        for r in new_rows:
            for field in ("Pos Rank", "Tier", "Rank Min", "Rank Max", "Rank Std"):
                r[field] = ""
        synthesized[label] = new_rows
    return synthesized


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expert", required=True, choices=list(EXPERT_CONFIGS.keys()))
    ap.add_argument("--year", default="2026")
    ap.add_argument("--week", default="0")
    ap.add_argument("--type", default="PRESEASON", dest="type_")
    ap.add_argument("--skip-timestamp", action="store_true")
    args = ap.parse_args()

    cfg = EXPERT_CONFIGS[args.expert]
    ids, label, prefix = cfg["ids"], cfg["label"], args.expert

    # --- HALF ---
    half_results, last_updated = [], None
    for eid in ids:
        bp, lu = fetch_all_positions_for_id(eid, args.year, args.week, "HALF", args.type_)
        if bp:
            half_results.append(bp)
            if lu:
                last_updated = lu

    if not half_results:
        print(f"No HALF data available for {label} — not yet published on FP.")
        sys.exit(2)

    blended_half = blend_all_positions(half_results)
    write_scoring(blended_half, prefix, "HALF")

    # --- PPR ---
    ppr_results = []
    for eid in ids:
        bp, _ = fetch_all_positions_for_id(eid, args.year, args.week, "PPR", args.type_)
        if bp:
            ppr_results.append(bp)
    if ppr_results:
        write_scoring(blend_all_positions(ppr_results), prefix, "PPR")
    else:
        print(f"No real PPR rankings from {label} — synthesized from HALF via scoring_adjust.py.")
        write_scoring(synthesize_scoring(blended_half, "PPR"), prefix, "PPR")

    # --- STD ---
    std_results = []
    for eid in ids:
        bp, _ = fetch_all_positions_for_id(eid, args.year, args.week, "STD", args.type_)
        if bp:
            std_results.append(bp)
    if std_results:
        write_scoring(blend_all_positions(std_results), prefix, "STD")
    else:
        print(f"No real STD rankings from {label} — synthesized from HALF via scoring_adjust.py.")
        write_scoring(synthesize_scoring(blended_half, "STD"), prefix, "STD")

    print(f"last_updated (date only)={last_updated}")

    ts = None
    if not args.skip_timestamp:
        ts = fetch_expert_timestamp(ids[0])
        if ts:
            print(f"Precise last-updated for {label} (ID {ids[0]}): {ts}")
        else:
            print(f"Could not find precise timestamp for {label} on the rankings page.")

    source_timestamps.save_timestamp(label, ts or last_updated)


if __name__ == "__main__":
    main()
