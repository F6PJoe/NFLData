#!/usr/bin/env python3
"""
Pull Sleeper ADP from beatadp.com/platform-adp.

BeatADP aggregates real Sleeper draft data and publishes it as a
server-rendered HTML table — no login, no API key, updated daily.

The table also has ESPN, Yahoo, Underdog, and FantasyPros columns
but we only extract Sleeper here (other sources have dedicated scripts).

Usage:
    python fetch_sleeper_adp.py          # -> sleeper_adp.csv
    python fetch_sleeper_adp.py -o my_sleeper.csv

Requires: requests, beautifulsoup4, lxml
"""

import argparse
import csv
import re
import sys

import requests
from bs4 import BeautifulSoup

URL = "https://www.beatadp.com/platform-adp"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
}

# Column index in the table (0-based after rank col)
# Headers: # | Player | Consensus | Sleeper | ESPN | Yahoo | Underdog | FantasyPros
SLEEPER_COL = 3


def fetch_html():
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse(html):
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        sys.exit("No table found on beatadp.com — page structure may have changed.")

    # Verify column positions from header row
    headers = [th.get_text(strip=True) for th in table.find_all("th")]
    print(f"Columns found: {headers}")
    try:
        sleeper_idx = headers.index("Sleeper")
    except ValueError:
        sys.exit(f"'Sleeper' column not found in headers: {headers}")

    # Also grab player name and try to split team from it
    # Player cell text is like "Bijan RobinsonATL" — team is the last 2-3 uppercase chars
    rows = []
    for tr in table.find_all("tr")[1:]:   # skip header
        tds = tr.find_all("td")
        if len(tds) <= sleeper_idx:
            continue

        # Player name + team are run together in td[1]
        player_td = tds[1]
        player_link = player_td.find("a")
        full_text = player_td.get_text(strip=True)

        # Try to get clean name from the link text
        player_name = player_link.get_text(strip=True) if player_link else full_text
        # Team is the remaining text after the player name
        team = full_text.replace(player_name, "").strip()
        # Clean up any non-alpha chars
        team = re.sub(r"[^A-Z]", "", team)

        # Position isn't in the table — we'll leave it blank;
        # player matching in the sheet uses name anyway
        adp_raw = tds[sleeper_idx].get_text(strip=True)
        try:
            adp = round(float(adp_raw), 2)
        except ValueError:
            continue  # skip players with no Sleeper ADP (shown as —)
        if adp <= 0:
            continue

        rows.append({
            "Player":      player_name,
            "Position(s)": "",    # not available in this table
            "Team":        team,
            "Sleeper":     adp,
        })

    rows.sort(key=lambda r: r["Sleeper"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="sleeper_adp.csv")
    args = ap.parse_args()

    print("Fetching Sleeper ADP from beatadp.com...")
    html  = fetch_html()
    rows  = parse(html)

    if not rows:
        sys.exit("No Sleeper ADP data found.")

    fieldnames = ["Player", "Position(s)", "Team", "Sleeper"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} players to {args.output}.")


if __name__ == "__main__":
    main()
