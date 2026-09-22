#!/usr/bin/env python3
"""
Fill in the away/home implied totals and O/U for each matchup on a week's
tab (e.g. "W2") in the Goal-Line Guide sheet.

Sheet: https://docs.google.com/spreadsheets/d/1q-aklbeGgJ5gC0rdLbSpK7sdemIKEoao37LbooROfkI
Layout of a week tab (one row per game):
    A: Away | B: Im. Total (away) | ... | F: O/U | ... | H: Home | I: Im. Total (home)

Two sources, pick with --source:

  odds_api (default) -- The Odds API, same ODDS_API_KEY already used by
  ff_defense/fetch_implied_totals.py. Only has UPCOMING games, so this is
  the one to run EARLY IN THE WEEK, once, before kickoff -- which is the
  normal weekly cadence going forward. Matches games to the target week by
  team pair against nflverse's full-season schedule (already published for
  the whole year), not by a date window -- more precise than
  ff_defense's own date-window approach, and works just as well for a week
  that hasn't started yet as one that's mid-slate.

  nflverse -- nflverse's games.csv (nfldata repo), which carries
  spread_line/total_line for every game, including ones already final.
  Free, no API key, but only useful for BACKFILLING a week after the fact
  (that's what this was built for originally, to get week 2 in after the
  fact) -- once lines are actually live pre-game, odds_api is the better
  source and the point of this rewrite.

spread sign conventions differ between the two:
  - odds_api gives each team's OWN spread directly (negative = favored) --
    standard American odds convention.
  - nflverse's single spread_line is HOME-referenced; confirmed empirically
    against this sheet's own already-filled NYG@LAR row (away 20 / home
    28.5, O/U 48.5): POSITIVE spread_line means the HOME team is favored.
    home_implied = total/2 + spread_line/2 ; away_implied = total/2 - spread_line/2

Usage:
    python fill_week_odds.py --week 3                        # odds_api, writes W3
    python fill_week_odds.py --week 3 --dry-run               # preview only
    python fill_week_odds.py --week 2 --source nflverse        # backfill a final week
"""

import argparse
import csv
import os
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE_ACCT = str(HERE.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
SHEET_ID = "1q-aklbeGgJ5gC0rdLbSpK7sdemIKEoao37LbooROfkI"

GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
PREFERRED_BOOKMAKER = "fanduel"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# nflverse spells three teams differently than this sheet does.
TEAM_FIX = {"ARI": "ARZ", "WAS": "WSH", "LA": "LAR"}

# Odds API gives full team names -- map straight to this sheet's codes
# (note JAX not JAC, ARZ not ARI, WSH not WAS -- this sheet's own quirks).
NAME_TO_ABBR = {
    "Arizona Cardinals": "ARZ", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL",
    "Buffalo Bills": "BUF", "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE", "Dallas Cowboys": "DAL",
    "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX",
    "Kansas City Chiefs": "KC", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LAR",
    "Las Vegas Raiders": "LV", "Miami Dolphins": "MIA", "Minnesota Vikings": "MIN",
    "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT",
    "Seattle Seahawks": "SEA", "San Francisco 49ers": "SF", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WSH",
}


def fetch_games():
    """Full-season schedule from nflverse -- future weeks' matchups are
    already published, so this works fine ahead of kickoff."""
    req = urllib.request.Request(GAMES_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8")
    return list(csv.DictReader(text.splitlines()))


def week_matchups(games, year, week):
    """-> {(away, home)} for one week, using this sheet's team codes."""
    out = set()
    for g in games:
        if g["season"] == str(year) and g["game_type"] == "REG" and int(g["week"]) == week:
            away = TEAM_FIX.get(g["away_team"], g["away_team"])
            home = TEAM_FIX.get(g["home_team"], g["home_team"])
            out.add((away, home))
    return out


def compute_odds_nflverse(games, year, week):
    """-> {(away, home): (away_implied, total, home_implied)}"""
    out = {}
    for g in games:
        if g["season"] != str(year) or g["game_type"] != "REG" or int(g["week"]) != week:
            continue
        if not g.get("spread_line") or not g.get("total_line"):
            continue  # line not posted yet
        away = TEAM_FIX.get(g["away_team"], g["away_team"])
        home = TEAM_FIX.get(g["home_team"], g["home_team"])
        spread = float(g["spread_line"])
        total = float(g["total_line"])
        home_imp = round(total / 2 + spread / 2, 2)
        away_imp = round(total / 2 - spread / 2, 2)
        out[(away, home)] = (away_imp, total, home_imp)
    return out


def _load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def compute_odds_live(target_games, year, week):
    """-> {(away, home): (away_implied, total, home_implied)}, matched by
    team pair against `target_games` rather than a date window -- works
    just as well days before kickoff as it does mid-week."""
    _load_dotenv(str(HERE.parent / "ff_defense" / ".env"))
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        raise RuntimeError("Set ODDS_API_KEY (e.g. in ff_defense/.env) to use the Odds API source.")

    import requests

    resp = requests.get(
        ODDS_URL,
        params={"apiKey": api_key, "regions": "us", "markets": "spreads,totals", "oddsFormat": "american"},
        timeout=30,
    )
    resp.raise_for_status()
    all_games = resp.json()
    print(f"  Odds API returned {len(all_games)} upcoming games.")

    out = {}
    for g in all_games:
        away = NAME_TO_ABBR.get(g["away_team"])
        home = NAME_TO_ABBR.get(g["home_team"])
        if (away, home) not in target_games:
            continue
        books = {b["key"]: b for b in g["bookmakers"]}
        book = books.get(PREFERRED_BOOKMAKER) or (g["bookmakers"][0] if g["bookmakers"] else None)
        if not book:
            continue
        markets = {m["key"]: m for m in book["markets"]}
        if "spreads" not in markets or "totals" not in markets:
            continue
        spread_by_team = {o["name"]: o["point"] for o in markets["spreads"]["outcomes"]}
        total = markets["totals"]["outcomes"][0]["point"]
        away_spread = spread_by_team.get(g["away_team"])
        home_spread = spread_by_team.get(g["home_team"])
        if away_spread is None or home_spread is None:
            continue
        away_imp = round(total / 2 - away_spread / 2, 2)
        home_imp = round(total / 2 - home_spread / 2, 2)
        out[(away, home)] = (away_imp, total, home_imp)
    return out


def sheets_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def fmt(v):
    return int(v) if v == int(v) else v


def update_tab(service, tab, odds, dry_run):
    existing = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"{tab}!A1:L41"
    ).execute().get("values", [])

    data = []
    print(f"\n{tab} tab:")
    matched = 0
    for i, row in enumerate(existing[1:], start=2):  # skip header row
        if not row or not row[0].strip():
            continue
        away = row[0].strip()
        home = row[7].strip() if len(row) > 7 else ""
        key = (away, home)
        if key not in odds:
            print(f"  {away:>4} @ {home:<4}  -- no line found, left unchanged")
            continue
        matched += 1
        away_imp, total, home_imp = odds[key]

        old_b = row[1] if len(row) > 1 else ""
        old_f = row[5] if len(row) > 5 else ""
        old_i = row[8] if len(row) > 8 else ""
        print(f"  {away:>4} @ {home:<4}  O/U {old_f or '-':>5} -> {fmt(total):<5}   "
              f"away {old_b or '-':>5} -> {fmt(away_imp):<5}   "
              f"home {old_i or '-':>5} -> {fmt(home_imp)}")

        data.append({"range": f"{tab}!B{i}", "values": [[fmt(away_imp)]]})
        data.append({"range": f"{tab}!F{i}", "values": [[fmt(total)]]})
        data.append({"range": f"{tab}!I{i}", "values": [[fmt(home_imp)]]})

    print(f"  {matched} of {sum(1 for r in existing[1:] if r and r[0].strip())} rows matched a line.")

    if dry_run:
        print(f"  (dry run -- {tab} tab not written)")
        return

    if data:
        service.spreadsheets().values().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"valueInputOption": "RAW", "data": data},
        ).execute()
    print(f"  wrote {tab} tab.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--tab", default=None, help="sheet tab name (default: 'W<week>')")
    ap.add_argument("--source", choices=("odds_api", "nflverse"), default="odds_api",
                     help="odds_api: live pre-game lines (use early in the week, the normal "
                          "case going forward). nflverse: free closing lines, only useful to "
                          "backfill a week that's already final.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tab = args.tab or f"W{args.week}"

    games = fetch_games()
    if args.source == "nflverse":
        odds = compute_odds_nflverse(games, args.year, args.week)
    else:
        target = week_matchups(games, args.year, args.week)
        if not target:
            print(f"No {args.year} week {args.week} games in the nflverse schedule.", file=sys.stderr)
            return 1
        odds = compute_odds_live(target, args.year, args.week)

    if not odds:
        print(f"No lines found for {args.year} week {args.week} via {args.source}.", file=sys.stderr)
        return 1
    print(f"Found lines for {len(odds)} week {args.week} games (source: {args.source}).")

    service = sheets_service()
    update_tab(service, tab, odds, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
