#!/usr/bin/env python3
"""
Pull an FTN analyst's personal half-PPR rankings (overall + per position)
directly from FTN's backend (ls.ftnfantasy.com), which requires a logged-in
FTN account. Defaults to Jeff Ratcliffe; pass --analyst for others available
in the same payload (e.g. Tyler Orginski — keyed as "Orginski").

Auth: ftn_auth.get_access_token() logs in via
  POST https://api.ftnfantasy.com/users/login  {"email":..., "password":...}
using FTN_EMAIL / FTN_PASSWORD from a local .env file (see .env.example) —
same credentials already used for FTN projections in ff_draft_proj.

Data: GET https://ls.ftnfantasy.com/api/rankings/redraft
  Authorization: Bearer <access_token>
(found in tools.ftnfantasy.com's rankings.js bundle — the rankings page at
ftnfantasy.com/fantasy/nfl/rankings?type=redraft calls this same endpoint).
Returns one blob covering every scoring format and position at once:
  {"PPR": [...], "Half": [...], "Std": [...], "SF": [...], "timestamps": {...}}
Each player entry has a `rankings` dict keyed by analyst last name
(Ratcliffe, Orginski, Popielarz, Loechner, Sousa, ...) — note some are
inactive: Loechner had a blank timestamp across every ranking set as of
2026-06, meaning no live rankings despite being listed. `timestamps` gives a
precise per-analyst, per-ranking-set last-updated datetime (e.g.
timestamps["Redraft Half"]["Ratcliffe"] = "6/26/2026 16:33:55") — much more
precise than FantasyPros' date-only field, useful for checking staleness
before trusting an in-season/weekly pull, and for confirming an analyst is
actually active before relying on them.

OVR is the "Half" list as returned (already cross-position ranked, true
Rank values kept as-is). FTN's API has no separate per-position list, so
QB/RB/WR/TE are derived: that same OVR list filtered by position, then
RENUMBERED 1..N (not left at the original overall Rank — e.g. without
renumbering, an analyst's QB1 would show up at whatever their actual overall
rank was, like 39, instead of 1). FLX is RB/WR/TE filtered from OVR (true
overall rank preserved for sort order, so a flex player ranked just above a
QB stays just above where a non-flex-eligible player would've been) then
also renumbered 1..N for a clean flex-only board.

FTN's single response already contains genuinely separate PPR/Half/Std
lists per analyst (confirmed: e.g. Ratcliffe's real Saquon Barkley RB rank
is 14/24/11 for Half/PPR/Std respectively — distinct submissions, not a
derived/computed spread) — so each run writes all 3 real formats from the
one fetch, no extra requests and no synthesis needed (unlike
fetch_fantasypros_rankings.py, where Boone's site has no real PPR/STD and
has to fall back to scoring_adjust.py).

Usage:
    python fetch_ftn_rankings.py                       # Ratcliffe -> ratcliffe_ovr.csv / _qb / _rb / _wr / _te / _flx.csv x3 formats
    python fetch_ftn_rankings.py --analyst Orginski     # Tyler Orginski -> orginski_*.csv

Requires: requests
"""

import argparse
import csv
import sys

import ftn_auth
import requests

import source_timestamps

DATA_URL = "https://ls.ftnfantasy.com/api/rankings/redraft"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal rankings consensus tool)"}

SCORING_KEY = {"HALF": "Half", "PPR": "PPR", "STD": "Std"}
TIMESTAMP_SET = {"HALF": "Redraft Half", "PPR": "Redraft PPR", "STD": "Redraft Standard"}

OUT_NAME = {"OVR": "ovr", "QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "FLX": "flx"}
FIELDNAMES = ["Rank", "Player", "Team", "Position"]


def fetch_data(json_file=None):
    if json_file:
        import json
        with open(json_file, encoding="utf-8") as f:
            return json.load(f)
    token = ftn_auth.get_access_token()
    headers = dict(HEADERS, Authorization=f"Bearer {token}")
    resp = requests.get(DATA_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def build_rows(players, analyst):
    rows = []
    for p in players:
        rank = p.get("rankings", {}).get(analyst)
        if rank in (None, ""):
            continue
        rows.append({
            "Rank": rank,
            "Player": p["name"],
            "Team": p.get("team", ""),
            "Position": p.get("position", ""),
        })
    rows.sort(key=lambda r: r["Rank"])
    return rows


def write_csv(rows, out_file):
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


SCORING_SUFFIX = {"HALF": "", "PPR": "_ppr", "STD": "_std"}


def process_scoring(data, analyst, scoring, prefix):
    scoring_key = SCORING_KEY[scoring]
    if scoring_key not in data:
        sys.exit(f"No '{scoring_key}' key in response — keys present: {list(data.keys())}")

    ovr_rows = build_rows(data[scoring_key], analyst)
    if not ovr_rows:
        sys.exit(f"No {analyst} rankings found in the '{scoring_key}' set.")

    suffix = SCORING_SUFFIX[scoring]
    write_csv(ovr_rows, f"{prefix}_{OUT_NAME['OVR']}{suffix}.csv")
    print(f"Wrote {len(ovr_rows)} players to {prefix}_{OUT_NAME['OVR']}{suffix}.csv.")

    # ovr_rows is already sorted by the analyst's true overall Rank. Filtering
    # it by position and renumbering 1..N gives a real within-position rank —
    # FTN's API has no separate per-position list, so this is derived, not
    # fetched. (Renumbering matters: just keeping the overall Rank value
    # would leave QB1 sitting at rank 39 instead of 1, etc.)
    by_pos = {}
    for pos in ("QB", "RB", "WR", "TE"):
        pos_rows = [dict(r) for r in ovr_rows if r["Position"] == pos]
        for i, r in enumerate(pos_rows):
            r["Rank"] = i + 1
        by_pos[pos] = pos_rows
        out_file = f"{prefix}_{OUT_NAME[pos]}{suffix}.csv"
        write_csv(pos_rows, out_file)
        print(f"Wrote {len(pos_rows)} players to {out_file}.")

    # FLX: filter ovr_rows (true overall rank, not the renumbered by_pos
    # lists above) to RB/WR/TE and renumber 1..N for a clean flex-specific
    # board, same convention as fetch_fantasypros_rankings.py's build_flx.
    flx_rows = [dict(r) for r in ovr_rows if r["Position"] in ("RB", "WR", "TE")]
    flx_rows.sort(key=lambda r: r["Rank"])
    for i, r in enumerate(flx_rows):
        r["Rank"] = i + 1
    flx_file = f"{prefix}_{OUT_NAME['FLX']}{suffix}.csv"
    write_csv(flx_rows, flx_file)
    print(f"Wrote {len(flx_rows)} players to {flx_file}.")

    ts_set = data.get("timestamps", {}).get(TIMESTAMP_SET[scoring], {})
    return ts_set.get(analyst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--analyst", default="Ratcliffe",
                     help="FTN analyst last name as keyed in the API, e.g. Ratcliffe, Orginski")
    ap.add_argument("--scoring", default=None, choices=["STD", "HALF", "PPR"],
                     help="Limit to one scoring format (default: fetch all 3)")
    ap.add_argument("--prefix", default=None, help="Output filename prefix (default: lowercased --analyst)")
    ap.add_argument("--json-file", help="offline FTN rankings JSON (for testing)")
    args = ap.parse_args()

    prefix = args.prefix or args.analyst.lower()
    scorings = [args.scoring] if args.scoring else ["HALF", "PPR", "STD"]

    data = fetch_data(args.json_file)

    ts = None
    for scoring in scorings:
        ts = process_scoring(data, args.analyst, scoring, prefix) or ts
        print(f"{args.analyst} last updated ({TIMESTAMP_SET[scoring]}): {ts or 'unknown'}")

    source_timestamps.save_timestamp(args.analyst, ts)


if __name__ == "__main__":
    main()
