#!/usr/bin/env python3
"""
Pull Yahoo Fantasy ADP from the official Yahoo Fantasy Sports API.

Uses the draft analysis endpoint which returns averagePick (= ADP) for each
player.  Requires a refresh token in .env (run yahoo_auth.py once to get it).

The token is refreshed automatically on every run — no manual re-auth needed.

Usage:
    python fetch_yahoo_adp.py               # -> yahoo_adp.csv
    python fetch_yahoo_adp.py --game nfl --season 2026

Requires: requests, python-dotenv
"""

import argparse
import csv
import os
import sys

import requests
from dotenv import load_dotenv, set_key

ENV_FILE = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(ENV_FILE)

CLIENT_ID     = os.environ.get("YAHOO_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("YAHOO_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("YAHOO_REFRESH_TOKEN", "")

TOKEN_URL = "https://api.login.yahoo.com/oauth2/get_token"
API_BASE  = "https://fantasysports.yahooapis.com/fantasy/v2"

HEADERS = {"Accept": "application/json"}


def refresh_access_token():
    if not REFRESH_TOKEN:
        sys.exit("No YAHOO_REFRESH_TOKEN in .env — run yahoo_auth.py first.")
    resp = requests.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": REFRESH_TOKEN},
        auth=(CLIENT_ID, CLIENT_SECRET),
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    access_token = data["access_token"]
    new_refresh   = data.get("refresh_token", REFRESH_TOKEN)
    # Persist the (possibly rotated) refresh token
    if new_refresh != REFRESH_TOKEN:
        set_key(ENV_FILE, "YAHOO_REFRESH_TOKEN", new_refresh)
    return access_token


def get_game_key(session, game="nfl"):
    """Resolve the current season's game key (e.g. '423' for NFL 2026)."""
    url = f"{API_BASE}/game/{game}"
    r = session.get(url, params={"format": "json"}, timeout=30)
    r.raise_for_status()
    return r.json()["fantasy_content"]["game"][0]["game_key"]


def fetch_players(session, game_key, start=0, count=25):
    # ;out=draft_analysis must be part of the path, not a query param
    url = f"{API_BASE}/game/{game_key}/players;out=draft_analysis"
    params = {
        "format": "json",
        "start":  start,
        "count":  count,
        "sort":   "AR",   # sort by All Drafts rank (average pick)
        "status": "A",    # available players
    }
    r = session.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def _flatten(lst):
    """Flatten Yahoo's list-of-single-key-dicts into one dict."""
    out = {}
    for item in lst:
        if isinstance(item, dict):
            out.update(item)
    return out


def parse_players(data, game_key):
    content = data["fantasy_content"]["game"]
    players_blob = content[1]["players"]
    total = int(players_blob.get("count", 0))
    rows = []
    for i in range(total):
        p = players_blob.get(str(i), {}).get("player")
        if not p or len(p) < 2:
            continue

        # p[0] is a list of single-key dicts with player info
        info = _flatten(p[0])
        name_block = info.get("name", {})
        full_name  = name_block.get("full", "") if isinstance(name_block, dict) else ""

        # p[1] is {"draft_analysis": [{"average_pick": "x"}, ...]}
        da_list = p[1].get("draft_analysis", [])
        da      = _flatten(da_list) if isinstance(da_list, list) else da_list

        adp_raw = da.get("average_pick", "")
        try:
            adp = round(float(adp_raw), 2)
        except (ValueError, TypeError):
            continue
        if adp <= 0:
            continue

        rows.append({
            "Player":      full_name,
            "Position(s)": info.get("display_position", ""),
            "Team":        info.get("editorial_team_abbr", "").upper(),
            "Yahoo!":      adp,
        })
    return rows, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--game",    default="nfl")
    ap.add_argument("--output",  default="yahoo_adp.csv")
    ap.add_argument("--max-players", type=int, default=500)
    args = ap.parse_args()

    access_token = refresh_access_token()

    session = requests.Session()
    session.headers.update({
        **HEADERS,
        "Authorization": f"Bearer {access_token}",
    })

    print("Resolving current NFL game key...")
    game_key = get_game_key(session, args.game)
    print(f"Game key: {game_key}")

    all_rows = []
    start     = 0
    page_size = 25

    while start < args.max_players:
        print(f"  Fetching players {start}–{start + page_size - 1}...")
        data = fetch_players(session, game_key, start=start, count=page_size)
        rows, page_count = parse_players(data, game_key)
        all_rows.extend(rows)
        # Stop when the page returned fewer players than requested
        if page_count < page_size:
            break
        start += page_size

    if not all_rows:
        sys.exit("No players with ADP found.")

    all_rows.sort(key=lambda r: r["Yahoo!"])

    fieldnames = ["Player", "Position(s)", "Team", "Yahoo!"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(all_rows)

    print(f"Wrote {len(all_rows)} players to {args.output}.")


if __name__ == "__main__":
    main()
