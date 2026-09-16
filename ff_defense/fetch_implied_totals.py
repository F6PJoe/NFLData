#!/usr/bin/env python3
"""
Pull this week's NFL implied team totals from The Odds API
(https://the-odds-api.com), computed from live spreads + totals, and
write them to a CSV.

Joe originally pointed this at eatdrinkandsleepfootball.com (a free,
no-key page the sheet's own "IMP" tab already linked to), but that's a
manually-curated page with no guaranteed update cadence -- switched to
The Odds API instead so this always reflects live sportsbook lines
whenever it's run, not whatever the page last happened to show.

/v4/sports/americanfootball_nfl/odds/ returns every upcoming game, not
just this week's -- confirmed live (2026-09-16) it comes back as two
clean 16-game blocks (this week's slate, then next week's, with a
multi-day gap between the last game of one and the first of the next),
so the soonest 16 games by commence_time are unambiguously the current
week's slate.

Implied total = O/U / 2 - team's own spread / 2 (spread is negative for
the favorite) -- verified against the eatdrinkandsleepfootball numbers
this replaces, e.g. a -11.5 favorite in a 47.5 O/U works out to 29.5,
matching that page's own math exactly.

Uses FanDuel's line when available (matches what eatdrinkandsleepfootball
itself used), falling back to whatever bookmaker The Odds API returns
first for a game FanDuel hasn't posted.

Credentials: ODDS_API_KEY, read from a local .env.

Usage:
    python fetch_implied_totals.py   # -> implied_totals.csv

Requires: requests
"""

import argparse
import csv
import os

import requests

from team_names import nickname_to_abbr

ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
PREFERRED_BOOKMAKER = "fanduel"
GAMES_PER_WEEK = 16

FIELDNAMES = ["Rank", "Team", "ImpliedTotal", "Spread", "OU", "Opponent"]


def _load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def _pick_bookmaker(game):
    books = {b["key"]: b for b in game["bookmakers"]}
    return books.get(PREFERRED_BOOKMAKER) or (game["bookmakers"][0] if game["bookmakers"] else None)


def fetch_games():
    _load_dotenv()
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        raise RuntimeError("Set ODDS_API_KEY (e.g. in a local .env file) to use The Odds API.")

    resp = requests.get(
        ODDS_URL,
        params={"apiKey": api_key, "regions": "us", "markets": "spreads,totals", "oddsFormat": "american"},
        timeout=30,
    )
    resp.raise_for_status()
    games = resp.json()
    games.sort(key=lambda g: g["commence_time"])
    return games[:GAMES_PER_WEEK]


def build_rows(games):
    rows = []
    for game in games:
        book = _pick_bookmaker(game)
        if not book:
            continue
        markets = {m["key"]: m for m in book["markets"]}
        if "spreads" not in markets or "totals" not in markets:
            continue

        spread_by_team = {o["name"]: o["point"] for o in markets["spreads"]["outcomes"]}
        ou = markets["totals"]["outcomes"][0]["point"]

        home, away = game["home_team"], game["away_team"]
        for team, opponent in ((home, away), (away, home)):
            spread = spread_by_team.get(team)
            if spread is None:
                continue
            rows.append({
                "Team": nickname_to_abbr(team),
                "ImpliedTotal": round(ou / 2 - spread / 2, 2),
                "Spread": spread,
                "OU": ou,
                "Opponent": nickname_to_abbr(opponent),
            })

    rows.sort(key=lambda r: r["ImpliedTotal"], reverse=True)  # highest first
    for i, r in enumerate(rows, start=1):
        r["Rank"] = i
    return rows


def write_csv(rows, out_file):
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="implied_totals.csv")
    args = ap.parse_args()

    games = fetch_games()
    rows = build_rows(games)
    if len(rows) < 2 * GAMES_PER_WEEK:
        raise SystemExit(
            f"Only built {len(rows)} team rows (expected {2 * GAMES_PER_WEEK}) -- "
            "some games may be missing spreads/totals odds yet."
        )

    write_csv(rows, args.out)
    print(f"Wrote {len(rows)} teams to {args.out} "
          "(rank 1 = highest implied total, 32 = lowest).")


if __name__ == "__main__":
    main()
