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

/v4/sports/americanfootball_nfl/odds/ returns every UPCOMING game and
drops games once they kick off, so "this week's slate" has to be carved
out by date, not by taking the soonest N games.

An earlier version took the soonest 16 games, on the assumption the API
returns a clean 16-game block per week. That holds early in the week but
breaks badly later: checked live on Sunday afternoon of week 2, only 6 of
the week's games were still upcoming, so "soonest 16" was 6 real games
plus 10 games from WEEK 3 -- writing next week's lines into the sheet as
if they were this week's. Now filtered to current_week.week_window_utc(),
the Tue-to-Tue ET window that current_week() itself uses.

Teams whose game has already kicked off simply won't appear in the
output -- expected and correct. push_implied_totals_to_sheet.py banks
every fetched value on the sheet's IMP tab, so those teams are filled
back in from the last number seen before kickoff (which is the final,
correct one for that week) and the ranking still covers the full slate.

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

import datetime

import requests

from current_week import current_week, week_window_utc
from team_names import nickname_to_abbr

ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
PREFERRED_BOOKMAKER = "fanduel"
GAMES_PER_WEEK = 16

# No Rank column on purpose: a rank is only meaningful across the FULL
# slate, and late in the week this fetch only sees the games that haven't
# kicked off yet. push_implied_totals_to_sheet.py merges these live values
# with the ones banked on the sheet's IMP tab and ranks the complete set
# there. This file is just "what the book says right now."
FIELDNAMES = ["Week", "Team", "ImpliedTotal", "Spread", "OU", "Opponent"]


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


def fetch_games(week=None):
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

    start, end = week_window_utc(week)
    in_week = []
    for g in games:
        kickoff = datetime.datetime.fromisoformat(g["commence_time"].replace("Z", "+00:00"))
        if start <= kickoff < end:
            in_week.append(g)
    in_week.sort(key=lambda g: g["commence_time"])
    print(f"{len(games)} upcoming games returned; {len(in_week)} fall in this week's "
          f"window ({start:%a %m/%d} - {end:%a %m/%d} UTC).")
    return in_week


def build_rows(games, week):
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
                "Week": week,
                "Team": nickname_to_abbr(team),
                "ImpliedTotal": round(ou / 2 - spread / 2, 2),
                "Spread": spread,
                "OU": ou,
                "Opponent": nickname_to_abbr(opponent),
            })

    rows.sort(key=lambda r: r["ImpliedTotal"], reverse=True)  # highest first
    return rows


def write_csv(rows, out_file):
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="implied_totals.csv")
    ap.add_argument("--week", type=int, default=None,
                     help="NFL week (default: auto-detected from today's date)")
    args = ap.parse_args()

    week = args.week or current_week()
    games = fetch_games(week)
    rows = build_rows(games, week)
    if not rows:
        # Not fatal: every game this week may simply have kicked off
        # already. The push still produces a full ranking from the IMP
        # tab's banked values, so write the (empty) file and let it.
        print("No live lines in this week's window -- the whole slate has "
              "already kicked off. The push will rank entirely from the "
              "IMP tab's banked values.")

    # A partial slate is NORMAL from Thursday night onward -- the API drops
    # each game at kickoff. The push fills those teams in from the IMP tab.
    if len(rows) < 2 * GAMES_PER_WEEK:
        print(f"NOTE: {len(rows)} of {2 * GAMES_PER_WEEK} team slots have live "
              "lines; the rest have kicked off and will come from the IMP tab.")

    write_csv(rows, args.out)
    print(f"Wrote {len(rows)} teams to {args.out} (week {week}, raw values, unranked).")


if __name__ == "__main__":
    main()
