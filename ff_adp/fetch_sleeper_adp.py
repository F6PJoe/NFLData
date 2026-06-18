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

ADP_FIELD = "adp_ppr"


def fetch_data(season: str):
    params = {"season_type": "regular", "order_by": ADP_FIELD}
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
        adp = stats.get(ADP_FIELD)
        if adp is None:
            continue
        try:
            adp = float(adp)
        except (TypeError, ValueError):
            continue

        # 999 = no ADP available for this player from Sleeper's feed
        if adp >= 999:
            continue

        # adp_2qb: Sleeper's 2QB/superflex ADP — 999 if not available
        try:
            adp_2qb = float(stats.get("adp_2qb") or 999)
            if adp_2qb >= 999:
                adp_2qb = 999.0
        except (TypeError, ValueError):
            adp_2qb = 999.0

        first = (player.get("first_name") or "").strip()
        last  = (player.get("last_name") or "").strip()
        name  = f"{first} {last}".strip()
        if not name:
            continue

        team = (player.get("team") or "").strip()

        rows.append({
            "Player":      name,
            "Position(s)": "DST" if pos == "DEF" else pos,
            "Team":        team,
            "Sleeper":     round(adp, 2),
            "Sleeper_2QB": round(adp_2qb, 2),
        })

    rows.sort(key=lambda r: r["Sleeper"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="sleeper_adp.csv")
    ap.add_argument("--season", default=str(datetime.now().year),
                    help="NFL season year (default: current year)")
    args = ap.parse_args()

    print(f"Fetching Sleeper {ADP_FIELD} from api.sleeper.app (season {args.season})...")
    data = fetch_data(args.season)
    rows = parse(data)

    if not rows:
        sys.exit("No Sleeper ADP data found.")

    fieldnames = ["Player", "Position(s)", "Team", "Sleeper", "Sleeper_2QB"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} players to {args.output}.")


if __name__ == "__main__":
    main()
