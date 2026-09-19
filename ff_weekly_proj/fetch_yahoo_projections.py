#!/usr/bin/env python3
"""
Pull Yahoo's weekly projections for QB/RB/WR/TE from a Yahoo Fantasy Football
league's "Players" page, using stat1=S_PW_<week> (Season Projected Week N).

Page (25 players per request, paginated via &count=0,25,50,...):
  https://football.fantasysports.yahoo.com/f1/<LEAGUE_ID>/players
    ?status=A&eteam=ALL&fteam=NONE&pos=<QB|RB|WR|TE>
    &stat1=S_PW_<WEEK>&myteam=0&sort=OR&sdir=1&count=<OFFSET>

No login needed — this page is publicly viewable.
Yahoo doesn't expose Pass Att/Comp for QBs — left blank.

Yahoo lists its whole player database, so the tail is padded with players who
carry no projection for the week (every stat cell renders as "-"). Those are
skipped. They are not cleanly sorted to the end — a projected player can sit
below a page of blank ones — so every page is still walked.

A players page that keeps erroring (Yahoo throws intermittent 500s) is retried,
then given up on, keeping whatever rows that position already collected rather
than losing the positions that have not been fetched yet.

Usage:
    python fetch_yahoo_projections.py
    python fetch_yahoo_projections.py --year 2026 --week 3 --league-id 84385

Requires: requests, beautifulsoup4
"""

import argparse
import csv
import datetime
import sys
import time

from bs4 import BeautifulSoup

import schedule as nfl_schedule
import scoring

PAGE_URL = ("https://football.fantasysports.yahoo.com/f1/{league_id}/players"
            "?status=A&eteam=ALL&fteam=NONE&pos={pos}&cut_type=9"
            "&stat1=S_PW_{week}&myteam=0&sort=OR&sdir=1&count={offset}")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

TEAM_ALIASES = {"WAS": "WSH"}

MAX_ATTEMPTS = 3
RETRY_BACKOFF = 2  # seconds, doubled after each failed attempt

OUT_COLUMNS = {
    "QB": ["QB", "Team", "Opp", "Pass Att", "Pass Comp", "Pass Yds", "Pass TD",
           "Pass Int", "Rush Att", "Rush Yds", "Rush TD", "Fumbles"],
    "RB": ["RB", "Team", "Opp", "Rush Att", "Rush Yds", "Rush TD", "Targets", "Rec",
           "Rec Yds", "Rec TD", "Fum"],
    "WR": ["WR", "Team", "Opp", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD", "Fum"],
    "TE": ["TE", "Team", "Opp", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD"],
}


def num(text):
    """Parse a stat cell. None for "-" — Yahoo's marker for "no projection"."""
    text = (text or "").replace(",", "").strip()
    if not text or text == "-":
        return None
    return float(text)


def cell(value):
    """Format a stat for the CSV — blank when Yahoo doesn't project it.

    build_consensus averages each column across the sources that supply it, so
    a blank abstains where a 0 would drag every player's average down.
    """
    return "" if value is None else value


def parse_team(player_cell):
    """Pull the team abbreviation out of a player cell's "Team - POS" span.

    Injured players get an extra span carrying the same Fz-xxs class ahead of
    that one, holding just the status letter ("Q", "O", ...), so match on the
    text shape instead of taking the first hit -- otherwise every questionable
    starter comes through with a team of "Q" and no opponent.
    """
    for span in player_cell.find_all("span", class_="Fz-xxs"):
        text = span.get_text(strip=True)
        if " - " in text:
            return text.split(" - ")[0].upper()
    return ""


class PageFetchError(Exception):
    """A players page still failed after every retry."""


def get_html(pos, week, league_id, offset, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    import requests
    url = PAGE_URL.format(league_id=league_id, pos=pos, week=week, offset=offset)
    delay = RETRY_BACKOFF
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as exc:
            if attempt == MAX_ATTEMPTS:
                raise PageFetchError(
                    f"{pos} page at offset {offset} failed "
                    f"{MAX_ATTEMPTS}x: {exc}") from exc
            print(f"[WARN] {pos} offset {offset}: {exc} "
                  f"(attempt {attempt}/{MAX_ATTEMPTS}, retrying in {delay}s)", flush=True)
            time.sleep(delay)
            delay *= 2


def fetch_position(pos, week, league_id, opponents):
    rows = []
    offset = 0
    while True:
        try:
            html = get_html(pos, week, league_id, offset)
        except PageFetchError as exc:
            # Keep what this position already has instead of aborting the run
            # and losing the positions that haven't been fetched yet.
            print(f"[WARN] {exc} — keeping the {len(rows)} {pos}s collected so far.",
                  flush=True)
            break
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if table is None:
            break
        tbody = table.find("tbody")
        if tbody is None:
            break
        trs = tbody.find_all("tr")
        if not trs:
            break

        for tr in trs:
            tds = tr.find_all("td")
            if len(tds) < 23:
                continue
            player_cell = tds[2]
            name_a = player_cell.find("a", class_="name")
            if name_a is None:
                continue
            name = name_a.get_text(strip=True)
            team = parse_team(player_cell)
            team = TEAM_ALIASES.get(team, team)
            opp = opponents.get(team, "")

            pass_yds = num(tds[10].get_text())
            pass_td = num(tds[11].get_text())
            pass_int = num(tds[12].get_text())
            rush_att = num(tds[13].get_text())
            rush_yds = num(tds[14].get_text())
            rush_td = num(tds[15].get_text())
            targets = num(tds[16].get_text())
            rec = num(tds[17].get_text())
            rec_yds = num(tds[18].get_text())
            rec_td = num(tds[19].get_text())
            fum_lost = num(tds[22].get_text())

            if all(v is None for v in (pass_yds, pass_td, pass_int, rush_att,
                                       rush_yds, rush_td, targets, rec, rec_yds,
                                       rec_td, fum_lost)):
                continue  # in Yahoo's database, but no projection this week

            if pos == "QB":
                s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
                     "rush_yds": rush_yds, "rush_td": rush_td, "fum": fum_lost}
                rows.append((scoring.qb_points(s), {
                    "QB": name, "Team": team, "Opp": opp,
                    "Pass Att": "", "Pass Comp": "",
                    "Pass Yds": cell(pass_yds), "Pass TD": cell(pass_td),
                    "Pass Int": cell(pass_int), "Rush Att": cell(rush_att),
                    "Rush Yds": cell(rush_yds), "Rush TD": cell(rush_td),
                    "Fumbles": cell(fum_lost),
                }))
            elif pos == "RB":
                s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
                     "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum_lost}
                rows.append((scoring.ppr_points(s), {
                    "RB": name, "Team": team, "Opp": opp,
                    "Rush Att": cell(rush_att), "Rush Yds": cell(rush_yds),
                    "Rush TD": cell(rush_td), "Targets": cell(targets),
                    "Rec": cell(rec), "Rec Yds": cell(rec_yds),
                    "Rec TD": cell(rec_td), "Fum": cell(fum_lost),
                }))
            elif pos == "WR":
                s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
                     "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum_lost}
                rows.append((scoring.ppr_points(s), {
                    "WR": name, "Team": team, "Opp": opp,
                    "Targets": cell(targets), "Rec": cell(rec),
                    "Rec Yds": cell(rec_yds), "Rec TD": cell(rec_td),
                    "Rush Att": cell(rush_att), "Rush Yds": cell(rush_yds),
                    "Rush TD": cell(rush_td), "Fum": cell(fum_lost),
                }))
            elif pos == "TE":
                s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum_lost}
                rows.append((scoring.ppr_points(s), {
                    "TE": name, "Team": team, "Opp": opp,
                    "Targets": cell(targets), "Rec": cell(rec),
                    "Rec Yds": cell(rec_yds), "Rec TD": cell(rec_td),
                    "Rush Att": cell(rush_att), "Rush Yds": cell(rush_yds),
                    "Rush TD": cell(rush_td),
                }))

        if len(trs) < 25:
            break
        offset += 25

    rows.sort(key=lambda r: r[0], reverse=True)
    return [r for _, r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--league-id", default="84385")
    ap.add_argument("--prefix", default="yahoo")
    args = ap.parse_args()

    week, opponents = nfl_schedule.get_schedule(args.year, args.week)
    print(f"Yahoo: week {week}")

    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        rows = fetch_position(pos, week, args.league_id, opponents)
        if not rows:
            print(f"No rows parsed for {pos}.")
            continue
        out = f"{args.prefix}_{pos.lower()}.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OUT_COLUMNS[pos])
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {len(rows)} {pos}s to {out}.")
        wrote_any = True

    if not wrote_any:
        sys.exit("No data parsed for any position.")


if __name__ == "__main__":
    main()
