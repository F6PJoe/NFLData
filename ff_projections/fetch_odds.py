#!/usr/bin/env python3
"""Vegas implied team totals -> vegas_team_totals_<season>.csv

Why this exists
---------------
Team touchdowns is the single highest-leverage number in the v3 workbook -
every player's TD projection is a market share of it. Deriving it from 3 years
of the team's own history means last year's roster is projecting next year's
scoring, which is exactly the thing that goes stale when a team changes its QB.
The betting market has already priced all of that in.

Method
------
the-odds-api has NO season win-totals market for the NFL (verified: only
`americanfootball_nfl_super_bowl_winner` carries outrights). But it does carry
spreads and totals for all 272 regular-season games, which is strictly better -
we can compute implied points per game directly rather than inferring them from
a win total:

    implied team total = (game total / 2) - (spread / 2)

A -3.5 favorite in a 44.5-point game is implied for 24.0, its opponent 20.5.
Sum a team's 17 games and you have its projected season points, straight from
the market. Then, validated against 96 real team-seasons in cached/sr:

    offensive TDs = points x 0.729 / 7      (actual TD share of points: 72.9%)

That 0.729 is measured, not assumed - Gemini's suggested 0.72 was very close,
and the method carries only -0.9 TDs of bias across those 96 seasons.

Deliberately NOT used for yardage. The same data says yards-per-point ranges
11.8 to 21.4 across teams (mean 15.8), so predicting team yards from points
carries ~574 yards of mean error, 2,095 worst case. Offensive efficiency is
precisely what differs between teams. Yardage stays historical.

Cost: 1 API credit per run (one call covers all 272 games). Cached to disk;
re-runs are free unless --refresh.

Usage:
    python fetch_odds.py
    python fetch_odds.py --refresh
"""

import argparse
import csv
import datetime
import json
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict

from teams import TEAMS, clean_team

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cached", "odds")
ENV = os.path.join(HERE, ".env")
SEASON = 2026

API = ("https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"
       "?apiKey={key}&regions=us&markets=spreads,totals&oddsFormat=american")

# Measured from 96 team-seasons in cached/sr (2023-2025): share of a team's
# points that come from offensive TDs, valuing each at 7 (TD + typical XP).
TD_POINT_SHARE = 0.729
POINTS_PER_TD = 7.0

# the-odds-api uses full franchise names; map to our 3-letter codes.
NAME_TO_ABBR = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN",
    "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAC", "Kansas City Chiefs": "KC",
    "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC",
    "Los Angeles Rams": "LAR", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE",
    "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
    "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}


def load_key():
    key = os.environ.get("ODDS_API_KEY", "").strip()
    if not key and os.path.exists(ENV):
        for line in open(ENV, encoding="utf-8"):
            if line.strip().startswith("ODDS_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit(f"No ODDS_API_KEY found. Add it to {ENV}:\n"
                 f"  ODDS_API_KEY=your-key-here")
    return key


def fetch(refresh=False):
    """One call covers all 272 games. Cached by date."""
    os.makedirs(CACHE, exist_ok=True)
    day = datetime.date.today().isoformat()
    dest = os.path.join(CACHE, f"nfl_lines_{day}.json")
    if os.path.exists(dest) and not refresh:
        print(f"  cached  {os.path.basename(dest)}")
        return json.load(open(dest, encoding="utf-8"))

    url = API.format(key=load_key())
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            raw = resp.read()
            remaining = resp.headers.get("x-requests-remaining")
    except urllib.error.HTTPError as exc:
        if exc.code == 401:
            sys.exit("HTTP 401 - odds-api key rejected.")
        if exc.code == 429:
            sys.exit("HTTP 429 - odds-api quota exhausted.")
        raise
    with open(dest, "wb") as fh:
        fh.write(raw)
    print(f"  fetched {os.path.basename(dest)}  "
          f"({remaining} API credits remaining)")
    return json.loads(raw)


def median(vals):
    vals = sorted(vals)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2


def implied_totals(games):
    """Per-team implied points, summed over its games.

    Books disagree, so take the median line across bookmakers per game rather
    than trusting whichever one happens to be listed first.
    """
    per_team = defaultdict(lambda: {"pts": 0.0, "games": 0, "no_line": 0})
    skipped = 0

    for g in games:
        home = NAME_TO_ABBR.get(g.get("home_team"))
        away = NAME_TO_ABBR.get(g.get("away_team"))
        if not home or not away:
            skipped += 1
            continue

        totals, spreads = [], {}
        for bk in g.get("bookmakers", []):
            for m in bk.get("markets", []):
                if m["key"] == "totals":
                    pts = [o.get("point") for o in m.get("outcomes", [])
                           if o.get("point") is not None]
                    if pts:
                        totals.append(pts[0])
                elif m["key"] == "spreads":
                    for o in m.get("outcomes", []):
                        abbr = NAME_TO_ABBR.get(o.get("name"))
                        if abbr and o.get("point") is not None:
                            spreads.setdefault(abbr, []).append(o["point"])

        game_total = median(totals)
        if game_total is None:
            for t in (home, away):
                per_team[t]["no_line"] += 1
            continue

        for team, opp in ((home, away), (away, home)):
            sp = median(spreads.get(team, []))
            if sp is None:
                per_team[team]["no_line"] += 1
                continue
            # favorite has a negative spread -> subtracting a negative adds
            per_team[team]["pts"] += (game_total / 2) - (sp / 2)
            per_team[team]["games"] += 1

    return per_team, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true")
    ap.add_argument("--season", type=int, default=SEASON)
    args = ap.parse_args()

    print("Vegas lines (the-odds-api):")
    games = fetch(args.refresh)
    print(f"  {len(games)} games returned")

    per_team, skipped = implied_totals(games)
    if skipped:
        print(f"  WARNING: {skipped} games had unrecognized team names")

    rows = []
    for team in TEAMS:
        rec = per_team.get(team)
        if not rec or not rec["games"]:
            print(f"  WARNING: no lines found for {team}")
            continue
        pts = rec["pts"]
        # Scale to a full 17-game season if some games lacked a usable line,
        # rather than silently under-projecting that team.
        if rec["games"] < 17:
            pts = pts / rec["games"] * 17
        off_td = pts * TD_POINT_SHARE / POINTS_PER_TD
        rows.append({
            "team": team,
            "games_with_lines": rec["games"],
            "implied_points": round(pts, 1),
            "points_per_game": round(pts / 17, 2),
            "offensive_td": round(off_td, 1),
        })

    out = os.path.join(HERE, f"vegas_team_totals_{args.season}.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["team", "games_with_lines",
                                           "implied_points", "points_per_game",
                                           "offensive_td"])
        w.writeheader()
        w.writerows(rows)

    print(f"\nWrote {os.path.basename(out)} - {len(rows)} teams\n")
    rows.sort(key=lambda r: -r["offensive_td"])
    print(f"  {'TM':<5}{'pts/g':>7}{'season pts':>12}{'off TDs':>9}")
    for r in rows[:6]:
        print(f"  {r['team']:<5}{r['points_per_game']:>7.1f}"
              f"{r['implied_points']:>12.0f}{r['offensive_td']:>9.1f}")
    print("  ...")
    for r in rows[-4:]:
        print(f"  {r['team']:<5}{r['points_per_game']:>7.1f}"
              f"{r['implied_points']:>12.0f}{r['offensive_td']:>9.1f}")


if __name__ == "__main__":
    sys.exit(main())
