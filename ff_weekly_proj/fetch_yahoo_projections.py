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

Usage:
    python fetch_yahoo_projections.py
    python fetch_yahoo_projections.py --year 2026 --week 3 --league-id 84385

Requires: requests, beautifulsoup4
"""

import argparse
import csv
import datetime
import sys

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
    text = (text or "").replace(",", "").strip()
    if not text or text == "-":
        return 0.0
    return float(text)


def get_html(pos, week, league_id, offset, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    import requests
    url = PAGE_URL.format(league_id=league_id, pos=pos, week=week, offset=offset)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def fetch_position(pos, week, league_id, opponents):
    rows = []
    offset = 0
    while True:
        html = get_html(pos, week, league_id, offset)
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
            teampos_span = player_cell.find("span", class_="Fz-xxs")
            if name_a is None or teampos_span is None:
                continue
            name = name_a.get_text(strip=True)
            team = teampos_span.get_text(strip=True).split(" - ")[0].upper()
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

            if pos == "QB":
                s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
                     "rush_yds": rush_yds, "rush_td": rush_td, "fum": fum_lost}
                rows.append((scoring.qb_points(s), {
                    "QB": name, "Team": team, "Opp": opp,
                    "Pass Att": "", "Pass Comp": "",
                    "Pass Yds": pass_yds, "Pass TD": pass_td, "Pass Int": pass_int,
                    "Rush Att": rush_att, "Rush Yds": rush_yds, "Rush TD": rush_td,
                    "Fumbles": fum_lost,
                }))
            elif pos == "RB":
                s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
                     "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum_lost}
                rows.append((scoring.ppr_points(s), {
                    "RB": name, "Team": team, "Opp": opp,
                    "Rush Att": rush_att, "Rush Yds": rush_yds, "Rush TD": rush_td,
                    "Targets": targets, "Rec": rec, "Rec Yds": rec_yds, "Rec TD": rec_td,
                    "Fum": fum_lost,
                }))
            elif pos == "WR":
                s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
                     "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum_lost}
                rows.append((scoring.ppr_points(s), {
                    "WR": name, "Team": team, "Opp": opp,
                    "Targets": targets, "Rec": rec, "Rec Yds": rec_yds, "Rec TD": rec_td,
                    "Rush Att": rush_att, "Rush Yds": rush_yds, "Rush TD": rush_td,
                    "Fum": fum_lost,
                }))
            elif pos == "TE":
                s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum_lost}
                rows.append((scoring.ppr_points(s), {
                    "TE": name, "Team": team, "Opp": opp,
                    "Targets": targets, "Rec": rec, "Rec Yds": rec_yds, "Rec TD": rec_td,
                    "Rush Att": rush_att, "Rush Yds": rush_yds, "Rush TD": rush_td,
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
