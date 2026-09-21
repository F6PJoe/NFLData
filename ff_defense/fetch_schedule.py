#!/usr/bin/env python3
"""
Pull this week's NFL matchups from nflverse's free schedules release --
the replacement for Subvertadown as the source of the team list and
opponents (columns B and E on the Live tab).

Subvertadown used to define which teams play this week and who they play;
losing that access left the whole sheet without a team list, since every
other push matches against column B. nflverse's "schedules" release has
the full season (all 272 games, home/away, kickoff day), is free, needs
no login, and is the same source family already used for EPA -- so the
team list now comes from a file that can't be revoked.

Bye weeks fall out naturally: a team with no game that week simply isn't
in the output, so the sheet ends up with however many teams actually
play.

Opponent format matches what the sheet already used: "@ABBR" when the
team is on the road, plain "ABBR" at home -- push_schedule_to_sheet.py
keeps that convention, and finalize_live_sheet.py's SCORE formula reads
the "@" to award the home bonus.

Usage:
    python fetch_schedule.py            # week auto-detected
    python fetch_schedule.py --week 3

Requires: pandas, requests
"""

import argparse
import csv
import datetime
import os

import pandas as pd
import requests

from current_week import current_week
from team_names import normalize

SCHEDULE_URL = "https://github.com/nflverse/nflverse-data/releases/download/schedules/games.csv.gz"
CACHE_DIR = "nflverse_data"
CACHE_FILE = "games.csv.gz"

FIELDNAMES = ["Week", "Team", "Opp", "Home", "Kickoff"]


def fetch_schedule(max_age_hours=12):
    """Download the schedule file, re-using a recent local copy.

    Age-checked rather than existence-checked: nflverse updates this file
    through the season (flexed games, rescheduling), so a stale cache
    could quietly serve the wrong matchups.
    """
    os.makedirs(CACHE_DIR, exist_ok=True)
    path = os.path.join(CACHE_DIR, CACHE_FILE)

    fresh = False
    if os.path.exists(path):
        age = (datetime.datetime.now()
               - datetime.datetime.fromtimestamp(os.path.getmtime(path)))
        fresh = age < datetime.timedelta(hours=max_age_hours)
        if fresh:
            print(f"Using cached schedule ({age.total_seconds()/3600:.1f}h old).")

    if not fresh:
        print("Downloading schedule from nflverse...")
        resp = requests.get(SCHEDULE_URL, timeout=60)
        resp.raise_for_status()
        with open(path, "wb") as f:
            f.write(resp.content)

    return pd.read_csv(path, compression="gzip", low_memory=False)


def build_rows(games, season, week):
    slate = games[(games["season"] == season) & (games["week"] == week)]
    if slate.empty:
        raise SystemExit(f"No games found for {season} week {week}.")

    rows = []
    for _, g in slate.iterrows():
        home, away = normalize(g["home_team"]), normalize(g["away_team"])
        kickoff = g.get("gameday", "")
        # One row per team, from that team's own perspective.
        rows.append({"Week": week, "Team": home, "Opp": away,
                     "Home": 1, "Kickoff": kickoff})
        rows.append({"Week": week, "Team": away, "Opp": f"@{home}",
                     "Home": 0, "Kickoff": kickoff})

    rows.sort(key=lambda r: r["Team"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--season", type=int, default=datetime.date.today().year)
    ap.add_argument("--out", default="schedule.csv")
    args = ap.parse_args()

    week = args.week or current_week()
    games = fetch_schedule()
    rows = build_rows(games, args.season, week)

    byes = 32 - len(rows)
    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)

    print(f"Week {week}: wrote {len(rows)} teams to {args.out} "
          f"({len(rows)//2} games, {byes} team(s) on bye).")


if __name__ == "__main__":
    main()
