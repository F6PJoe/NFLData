#!/usr/bin/env python3
"""
Pull Fantrax ADP from the Fantrax fantasy API.

Uses the getPlayerStats endpoint with sortType=OVERVIEW_AVG_DRAFT_POSITION.
ADP is in cells[6] of each player row.

Requires FX_RM session cookie in .env.  The cookie expires when you log out
of Fantrax — if you get auth errors, copy a fresh FX_RM value from DevTools.

Usage:
    python fetch_fantrax_adp.py               # -> fantrax_adp.csv
    python fetch_fantrax_adp.py --league-id XXXX

Requires: requests, python-dotenv
"""

import argparse
import csv
import os
import sys
import time

import requests
from dotenv import load_dotenv

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_FILE)

FX_RM     = os.environ.get("FANTRAX_FX_RM", "")
LEAGUE_ID = "1q16zx26mpbv3yb3"   # your dummy league; override with --league-id
API_URL   = "https://www.fantrax.com/fxpa/req"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Content-Type": "application/json",
}

# Column index for ADP in cells[] (0-based)
# Header: Rk(0) Sta(1) Opp(2) FPts(3) FP/G(4) %D(5) ADP(6) Bye(7) Ros(8) +/-(9)
ADP_CELL_IDX = 6


def make_session():
    s = requests.Session()
    s.cookies.set("FX_RM", FX_RM, domain="fantrax.com")
    s.headers.update(HEADERS)
    return s


def fetch_page(session, league_id, page=1):
    r = session.post(
        API_URL,
        params={"leagueId": league_id},
        json={
            "msgs": [{
                "method": "getPlayerStats",
                "data": {
                    "reload":   "2",
                    "sortType": "OVERVIEW_AVG_DRAFT_POSITION",
                    "pageNumber": str(page),
                },
            }],
            "uiv": 3, "dt": 1, "at": 0, "tz": "America/New_York",
        },
        timeout=30,
    )
    r.raise_for_status()
    resp = r.json()
    page_err = resp.get("responses", [{}])[0].get("pageError", {})
    if page_err.get("code"):
        raise RuntimeError(f"Fantrax API error: {page_err.get('text')}")
    return resp["responses"][0]["data"]


def parse_page(data):
    rows = []
    for entry in data.get("statsTable", []):
        scorer = entry.get("scorer", {})
        cells  = entry.get("cells", [])

        name = scorer.get("name", "")
        pos  = scorer.get("posShortNames", "")
        team = scorer.get("teamShortName", "")

        if ADP_CELL_IDX >= len(cells):
            continue
        adp_raw = cells[ADP_CELL_IDX].get("content", "")
        try:
            adp = round(float(adp_raw), 2)
        except (ValueError, TypeError):
            continue
        if adp <= 0:
            continue

        rows.append({
            "Player":      name,
            "Position(s)": pos,
            "Team":        team,
            "Fantrax":     adp,
        })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--league-id", default=LEAGUE_ID)
    ap.add_argument("-o", "--output", default="fantrax_adp.csv")
    ap.add_argument("--max-pages", type=int, default=50,
                    help="Safety cap on pages (20 players each)")
    args = ap.parse_args()

    if not FX_RM:
        sys.exit("FANTRAX_FX_RM not set in .env — copy the FX_RM cookie from DevTools → Application → Cookies → fantrax.com")

    session   = make_session()
    all_rows  = []
    page      = 1

    while page <= args.max_pages:
        print(f"  Fetching page {page}...")
        data       = fetch_page(session, args.league_id, page)
        pagination = data.get("paginatedResultSet", {})
        total_pages = int(pagination.get("totalNumPages", 1))

        rows = parse_page(data)
        if not rows:
            break
        all_rows.extend(rows)

        if page >= total_pages:
            break
        page += 1
        time.sleep(0.3)   # be polite

    if not all_rows:
        sys.exit("No players with ADP found — FX_RM cookie may have expired.")

    all_rows.sort(key=lambda r: r["Fantrax"])

    fieldnames = ["Player", "Position(s)", "Team", "Fantrax"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)

    print(f"Wrote {len(all_rows)} players to {args.output}.")


if __name__ == "__main__":
    main()
