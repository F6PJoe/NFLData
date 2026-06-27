#!/usr/bin/env python3
"""
Pull Yahoo's season-long (preseason/draft) projections for QB/RB/WR/TE from a
Yahoo Fantasy Football league's "Players" page, sorted/filtered by season
projected stats (stat1=S_PS_<year>). This page is publicly viewable (no login
needed) even though it lives under a private league's URL.

Yahoo's official Fantasy API (fantasysports.yahooapis.com) does NOT expose
preseason stat-line projections — `stats;type=season` returns all-zero actual
stats and `type=projected_season` is rejected (400). The web "Players" table
is the only place Yahoo's own season projections are exposed.

Page (25 players per request, paginated via &count=0,25,50,...):
  https://football.fantasysports.yahoo.com/f1/<LEAGUE_ID>/players
    ?status=A&eteam=ALL&fteam=NONE&pos=<QB|RB|WR|TE>&cut_type=9
    &stat1=S_PS_<YEAR>&myteam=0&sort=OR&sdir=1&count=<OFFSET>

Table columns (after the player-info cell): Roster Status, GP, Bye, Fan Pts,
Pre-Season rank, Actual rank, % Ros, Pass Yds, Pass TD, Pass Int, Rush Att,
Rush Yds, Rush TD, Targets, Rec, Rec Yds, Rec TD, Ret TD, 2PT, Fum Lost.

Yahoo's table doesn't expose Pass Att / Pass Comp for QBs — those columns are
left blank for this source.

Usage:
    python fetch_yahoo_projections.py
    python fetch_yahoo_projections.py --year 2026 --league-id 84385

Requires: requests, beautifulsoup4
"""

import argparse
import csv
import datetime
import sys

from bs4 import BeautifulSoup

import scoring

PAGE_URL = ("https://football.fantasysports.yahoo.com/f1/{league_id}/players"
            "?status=A&eteam=ALL&fteam=NONE&pos={pos}&cut_type=9"
            "&stat1=S_PS_{year}&myteam=0&sort=OR&sdir=1&count={offset}")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

# Yahoo uses a couple of different team abbreviations than ESPN.
TEAM_ALIASES = {"WAS": "WSH"}

OUT_COLUMNS = {
    "QB": ["QB", "Team", "Bye", "Pass Att", "Pass Comp", "Pass Yds", "Pass TD",
           "Pass Int", "Rush Att", "Rush Yds", "Rush TD", "Fumbles"],
    "RB": ["RB", "Team", "Bye", "Rush Att", "Rush Yds", "Rush TD", "Targets", "Rec",
           "Rec Yds", "Rec TD", "Fum"],
    "WR": ["WR", "Team", "Bye", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD", "Fum"],
    "TE": ["TE", "Team", "Bye", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD"],
}


def num(text):
    text = (text or "").replace(",", "").strip()
    if not text or text == "-":
        return 0.0
    return float(text)


def get_html(pos, year, league_id, offset, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    import requests
    url = PAGE_URL.format(league_id=league_id, pos=pos, year=year, offset=offset)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def fetch_position(pos, year, league_id):
    rows = []
    offset = 0
    while True:
        html = get_html(pos, year, league_id, offset)
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table")
        if table is None:
            break
        tbody = table.find("tbody")
        # An offset past the end of the actual player list renders the
        # table header with no <tbody> at all (not an empty one) — that's
        # Yahoo's real "no more pages" signal here, same as `table is None`.
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
            bye = tds[5].get_text(strip=True)

            pass_yds, pass_td, pass_int = num(tds[10].get_text()), num(tds[11].get_text()), num(tds[12].get_text())
            rush_att, rush_yds, rush_td = num(tds[13].get_text()), num(tds[14].get_text()), num(tds[15].get_text())
            targets, rec, rec_yds, rec_td = num(tds[16].get_text()), num(tds[17].get_text()), num(tds[18].get_text()), num(tds[19].get_text())
            fum_lost = num(tds[22].get_text())

            if pos == "QB":
                s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
                     "rush_yds": rush_yds, "rush_td": rush_td, "fum": fum_lost}
                rows.append((scoring.qb_points(s), {
                    "QB": name, "Team": team, "Bye": bye,
                    "Pass Att": "", "Pass Comp": "",
                    "Pass Yds": pass_yds, "Pass TD": pass_td, "Pass Int": pass_int,
                    "Rush Att": rush_att, "Rush Yds": rush_yds, "Rush TD": rush_td,
                    "Fumbles": fum_lost,
                }))
            elif pos == "RB":
                s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
                     "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum_lost}
                rows.append((scoring.ppr_points(s), {
                    "RB": name, "Team": team, "Bye": bye,
                    "Rush Att": rush_att, "Rush Yds": rush_yds, "Rush TD": rush_td,
                    "Targets": targets, "Rec": rec, "Rec Yds": rec_yds, "Rec TD": rec_td,
                    "Fum": fum_lost,
                }))
            elif pos == "WR":
                s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
                     "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum_lost}
                rows.append((scoring.ppr_points(s), {
                    "WR": name, "Team": team, "Bye": bye,
                    "Targets": targets, "Rec": rec, "Rec Yds": rec_yds, "Rec TD": rec_td,
                    "Rush Att": rush_att, "Rush Yds": rush_yds, "Rush TD": rush_td,
                    "Fum": fum_lost,
                }))
            elif pos == "TE":
                s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum_lost}
                rows.append((scoring.ppr_points(s), {
                    "TE": name, "Team": team, "Bye": bye,
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
    ap.add_argument("--league-id", default="84385")
    ap.add_argument("--prefix", default="yahoo")
    args = ap.parse_args()

    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        rows = fetch_position(pos, args.year, args.league_id)
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
