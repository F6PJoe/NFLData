#!/usr/bin/env python3
"""
Fallback fetcher for Nick Mariano's RotoBaller rankings, used only when his
FP page (ID 766) has no data yet.

Uses RotoBaller's internal rankings API (wp-json/rb/v1/rankings) which returns
full player data including name, team, position, rank, tier, and bye week.
Fetches all 3 scoring formats (half-ppr, ppr, standard) directly.

Exit codes:
    0  = data written
    2  = page unavailable or no players parsed
    1  = unexpected error

Usage: python fetch_rotoballer_rankings.py
"""

import csv
import sys
from datetime import datetime, timezone

import requests

import name_match
import source_timestamps

API_URL = "https://www.rotoballer.com/wp-json/rb/v1/rankings"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal rankings consensus tool)"}

PREFIX = "mariano"
LABEL = "Nick Mariano"

# (scoring key, spreadsheet param)
SCORINGS = [
    ("HALF", "half-ppr"),
    ("PPR",  "ppr"),
    ("STD",  "standard"),
]

# league param per position slot
LEAGUE_PARAMS = {
    "ALL":  "Overall",
    "QB":   "QB",
    "RB":   "RB",
    "WR":   "WR",
    "TE":   "TE",
    "FLX":  "FLEX",
}

OUT_NAME = {"ALL": "ovr", "QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "FLX": "flx"}
SCORING_SUFFIX = {"HALF": "", "PPR": "_ppr", "STD": "_std"}

FIELDNAMES = ["Rank", "Pos Rank", "Player", "Team", "Position", "Bye",
              "Tier", "Rank Min", "Rank Max", "Rank Std"]


def fetch_slot(spreadsheet, league):
    """Fetch one position/scoring combo from the API. Returns list of row dicts."""
    params = {"league": league, "perPage": 600, "spreadsheet": spreadsheet}
    try:
        resp = requests.get(API_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        print(f"RotoBaller API error (spreadsheet={spreadsheet}, league={league}): {e}")
        return []

    players = data.get("data", [])
    rows = []
    for p in players:
        name = name_match.display_name(name_match.clean_name(p.get("player", {}).get("name", "")))
        team = name_match.clean_team(p.get("team", ""))
        pos = p.get("position", "")
        if pos == "DST":
            canonical = name_match.dst_name(team)
            if canonical:
                name = canonical
        rows.append({
            "Rank":     p.get("resolved_rank") or p.get("rank", ""),
            "Pos Rank": "",
            "Player":   name,
            "Team":     team,
            "Position": pos,
            "Bye":      p.get("bye_week", ""),
            "Tier":     p.get("tier", ""),
            "Rank Min": "",
            "Rank Max": "",
            "Rank Std": "",
        })
    return rows


def write_slot(rows, out_file):
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} players to {out_file}.")


def main():
    any_written = False

    for scoring_key, spreadsheet in SCORINGS:
        suffix = SCORING_SUFFIX[scoring_key]
        scoring_ok = False

        for slot_key, league in LEAGUE_PARAMS.items():
            rows = fetch_slot(spreadsheet, league)
            if not rows and slot_key == "ALL":
                print(f"RotoBaller: no players returned for {scoring_key}/Overall — skipping format.")
                break
            out_file = f"{PREFIX}_{OUT_NAME[slot_key]}{suffix}.csv"
            write_slot(rows, out_file)
            scoring_ok = True

        if scoring_ok:
            any_written = True
            print(f"RotoBaller: {scoring_key} done.")

    if not any_written:
        print("RotoBaller: no data from any scoring format — API may be down.")
        sys.exit(2)

    _now = datetime.now(timezone.utc)
    ts = f"{_now.month}/{_now.day}/{_now.year} {_now.strftime('%H:%M')} UTC"
    source_timestamps.save_timestamp(LABEL, ts)
    print(f"RotoBaller: saved timestamp {ts} for {LABEL}.")


if __name__ == "__main__":
    main()
