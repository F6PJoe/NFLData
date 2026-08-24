#!/usr/bin/env python3
"""
Pull Sleeper ADP directly from Sleeper's own API.

api.sleeper.app/projections/nfl/{season} returns per-player projection
records that include ADP fields (adp_std, adp_half_ppr, adp_ppr, ...).
We use adp_ppr to match the PPR scoring used by most other sources in
this project (NFFC, BB10s, FFPC, Underdog, ESPN).

Note: the underlying ADP numbers in this feed are sourced/labeled
"rotowire" by Sleeper's API, but they are served directly from
api.sleeper.app with no scraping or third-party aggregator site involved.

Usage:
    python fetch_sleeper_adp.py            # -> sleeper_adp.csv
    python fetch_sleeper_adp.py -o my_sleeper.csv
    python fetch_sleeper_adp.py --season 2026

Requires: requests
"""

import argparse
import csv
import sys
from datetime import datetime

import requests

URL_TMPL = "https://api.sleeper.app/projections/nfl/{season}"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

# Positions we care about (kickers excluded; DEF kept for DST normalisation)
KEEP_POS = {"QB", "RB", "WR", "TE", "DEF"}

# Primary sort field — PPR is most comparable to other sources in consensus
ADP_SORT_FIELD = "adp_ppr"

# All four Sleeper scoring formats: output column -> API stats field
ADP_FIELDS = {
    "Sleeper":      "adp_ppr",
    "Sleeper_STD":  "adp_std",
    "Sleeper_Half": "adp_half_ppr",
    "Sleeper_2QB":  "adp_2qb",
}


def fetch_data(season: str):
    params = {"season_type": "regular", "order_by": ADP_SORT_FIELD}
    resp = requests.get(URL_TMPL.format(season=season), params=params,
                         headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse(data):
    rows = []
    for entry in data:
        player = entry.get("player") or {}
        pos = (player.get("position") or "").strip().upper()
        if pos not in KEEP_POS:
            continue

        stats = entry.get("stats") or {}

        # Must have a valid PPR ADP to include the player at all
        ppr = stats.get(ADP_SORT_FIELD)
        if ppr is None:
            continue
        try:
            ppr = float(ppr)
        except (TypeError, ValueError):
            continue
        if ppr > 300:
            continue

        first = (player.get("first_name") or "").strip()
        last  = (player.get("last_name") or "").strip()
        name  = f"{first} {last}".strip()
        if not name:
            continue

        record = {
            "Player":      name,
            "Position(s)": "DST" if pos == "DEF" else pos,
            "Team":        (player.get("team") or "").strip(),
        }
        for col, field in ADP_FIELDS.items():
            try:
                val = float(stats.get(field) or 999)
            except (TypeError, ValueError):
                val = 999.0
            record[col] = round(val, 2) if val < 999 else 999.0

        rows.append(record)

    rows.sort(key=lambda r: r["Sleeper"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="sleeper_adp.csv")
    ap.add_argument("--season", default=str(datetime.now().year),
                    help="NFL season year (default: current year)")
    args = ap.parse_args()

    print(f"Fetching Sleeper ADP (all formats) from api.sleeper.app (season {args.season})...")
    data = fetch_data(args.season)
    rows = parse(data)

    if not rows:
        sys.exit("No Sleeper ADP data found.")

    fieldnames = ["Player", "Position(s)", "Team", "Sleeper", "Sleeper_STD", "Sleeper_Half", "Sleeper_2QB"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} players -> {args.output}  (PPR / STD / Half / 2QB)")


if __name__ == "__main__":
    main()
