#!/usr/bin/env python3
"""
Pull Yahoo Fantasy ADP from Yahoo's public draft analysis API.

Uses the pub-api-ro.fantasysports.yahoo.com endpoint which is public —
no OAuth or credentials required.

Pages through players sorted by average_pick and stops when a page returns
no players with a valid ADP value.

Usage:
    python fetch_yahoo_adp.py          # -> yahoo_adp.csv
    python fetch_yahoo_adp.py -o my_yahoo.csv

Requires: requests
"""

import argparse
import csv
import sys
import time

import requests

BASE_URL = (
    "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2"
    "/league/470.l.public;out=settings"
    "/players;position=ALL;start={start};count={count};sort=average_pick"
    ";search=;out=auction_values,ranks;ranks=o-rank"
    ";out=expert_ranks;expert_ranks.rank_type=projected_season_remaining"
    "/draft_analysis;cut_types=diamond;slices=last7days"
    "?format=json_f"
)

PAGE_SIZE = 30

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

KEEP_POS = {"QB", "WR", "RB", "TE", "DEF", "K"}


def fetch_page(start: int) -> list:
    url = BASE_URL.format(start=start, count=PAGE_SIZE)
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data.get("fantasy_content", {}).get("league", {}).get("players", [])


def parse_page(players: list) -> tuple[list, int]:
    rows = []
    for p in players:
        player = p.get("player", {})
        name = player.get("name", {}).get("full", "").strip()
        pos  = player.get("display_position", "").strip().upper()
        team = player.get("editorial_team_abbr", "").strip().upper()

        da = player.get("draft_analysis", {})
        adp_raw = da.get("average_pick", "")
        try:
            adp = round(float(adp_raw), 2)
        except (ValueError, TypeError):
            continue
        if adp <= 0:
            continue

        if not name:
            continue

        rows.append({
            "Player":      name,
            "Position(s)": pos,
            "Team":        team,
            "Yahoo!":      adp,
        })

    return rows, len(players)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="yahoo_adp.csv")
    args = ap.parse_args()

    print("Fetching Yahoo Fantasy ADP (public endpoint, no auth)...")
    all_rows = []
    start = 0

    while True:
        print(f"  Fetching players {start}–{start + PAGE_SIZE - 1}...")
        try:
            players = fetch_page(start)
        except requests.RequestException as e:
            sys.exit(f"Request failed: {e}")

        if not players:
            print("  No more players returned — done.")
            break

        rows, page_count = parse_page(players)
        all_rows.extend(rows)
        print(f"  Got {len(rows)} players with ADP on this page")

        # Stop when no players on this page had a valid ADP
        if len(rows) == 0:
            print("  No valid ADP values on this page — stopping.")
            break

        start += PAGE_SIZE
        time.sleep(0.5)  # be polite

    if not all_rows:
        sys.exit("No Yahoo ADP data found.")

    all_rows.sort(key=lambda r: r["Yahoo!"])

    fieldnames = ["Player", "Position(s)", "Team", "Yahoo!"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)

    print(f"Wrote {len(all_rows)} players -> {args.output}")


if __name__ == "__main__":
    main()
