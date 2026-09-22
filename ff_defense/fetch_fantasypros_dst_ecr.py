#!/usr/bin/env python3
"""
Pull FantasyPros' weekly D/ST Expert Consensus Ranking (ECR) -- the
blended consensus across their full analyst panel, not a single expert --
via the same public partner API already used in ff_rankings
(`partners.fantasypros.com/api/v1/consensus-rankings.php`). No login
needed; omitting the `filters` param (used elsewhere in this repo to
isolate one analyst) is what makes this the full consensus instead of one
expert's personal list -- confirmed live: `total_experts` came back 36.

FantasyPros' own rank_ecr is 1 = best defense, 32 = worst. Joe wants it
inverted here (highest number = best defense, matching every other
column on this sheet): inverted = 33 - rank_ecr.

`player_team_id` already matches this sheet's abbreviation convention
exactly (JAC, WAS, LAR, LAC, LV, etc.) -- confirmed live, no aliasing
needed.

Usage:
    python fetch_fantasypros_dst_ecr.py --week 2   # -> fantasypros_dst_ecr.csv

Requires: requests
"""

import argparse
import csv
import datetime

import requests

CONSENSUS_URL = "https://partners.fantasypros.com/api/v1/consensus-rankings.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (personal rankings consensus tool)"}

# Week is stamped so the push can refuse a leftover file -- see
# current_week.stale_week().
FIELDNAMES = ["Week", "Rank", "Team"]


def fetch_rows(year, week):
    params = {
        "sport": "NFL", "year": year, "week": week,
        "id": 1, "position": "DST", "type": "WEEK", "scoring": "HALF",
    }
    resp = requests.get(CONSENSUS_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    players = data.get("players", [])
    print(f"total_experts={data.get('total_experts')} last_updated={data.get('last_updated')}")

    # The API echoes the week back; trust that over what we asked for, so a
    # request that silently resolved to a different week can't be stamped
    # as this one. (Same reasoning as fetch_yahoo_def.selected_week.)
    echoed = data.get("week")
    if echoed is not None and int(echoed) != week:
        raise SystemExit(f"FantasyPros returned week {echoed}, not {week} -- "
                         "refusing to write mismatched ECR.")

    if (data.get("total_experts") or 0) < 10:
        print(f"[WARN] only {data.get('total_experts')} experts have submitted "
              f"week {week} DST ranks so far -- the consensus is thin this early. "
              "The mid-week reruns will pick up more.")

    return [{"Week": week, "Rank": 33 - p["rank_ecr"], "Team": p["player_team_id"]}
            for p in players]


def write_csv(rows, out_file):
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--out", default="fantasypros_dst_ecr.csv")
    args = ap.parse_args()

    rows = fetch_rows(args.year, args.week)
    if len(rows) < 28:
        raise SystemExit(
            f"Only found {len(rows)} D/ST rows (expected ~32) -- "
            "FantasyPros' API may have changed, or this week isn't published yet."
        )

    write_csv(rows, args.out)
    print(f"Week {args.week}: wrote {len(rows)} teams to {args.out} "
          f"(rank 1 = worst defense, {len(rows)} = best).")


if __name__ == "__main__":
    main()
