#!/usr/bin/env python3
"""
Pull CBS Sports' season-long (draft) projections for QB/RB/WR/TE directly
from CBS's own fantasy stats pages.

Pages (server-rendered HTML, no login needed):
  https://www.cbssports.com/fantasy/football/stats/QB/<YEAR>/season/projections/ppr/
  https://www.cbssports.com/fantasy/football/stats/RB/<YEAR>/season/projections/ppr/
  https://www.cbssports.com/fantasy/football/stats/WR/<YEAR>/season/projections/ppr/
  https://www.cbssports.com/fantasy/football/stats/TE/<YEAR>/season/projections/ppr/

Each page has a single <table class="TableBase-table"> with one row per
player. Column order differs by position (see *_COLS below).

Fantasy points are computed locally with scoring.py from the stat line, same
as every other source, so all sources are comparable under one scoring set.

Bye weeks come from ESPN's public proTeamSchedules endpoint (same one used by
fetch_espn_projections.py) since CBS's projection pages don't include bye week.

Usage:
    python fetch_cbs_projections.py
    python fetch_cbs_projections.py --year 2026

Requires: requests, beautifulsoup4
"""

import argparse
import csv
import datetime
import json
import sys

from bs4 import BeautifulSoup

import scoring

PAGE_URL = "https://www.cbssports.com/fantasy/football/stats/{pos}/{year}/season/projections/ppr/"
SCHEDULE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}?view=proTeamSchedules"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

ESPN_TEAM = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}
# CBS uses a couple of different team abbreviations than ESPN.
TEAM_ALIASES = {"WAS": "WSH", "JAC": "JAX"}

# Column order of the numeric <td>s after the player-name cell, per position.
QB_COLS = ["gp", "pass_att", "pass_cmp", "pass_yds", "pass_ypg", "pass_td",
           "pass_int", "rate", "rush_att", "rush_yds", "rush_avg", "rush_td",
           "fum", "fpts", "fppg"]
RB_COLS = ["gp", "rush_att", "rush_yds", "rush_avg", "rush_td", "targets",
           "rec", "rec_yds", "rec_ypg", "rec_avg", "rec_td", "fum", "fpts", "fppg"]
WR_COLS = ["gp", "targets", "rec", "rec_yds", "rec_ypg", "rec_avg", "rec_td",
           "rush_att", "rush_yds", "rush_avg", "rush_td", "fum", "fpts", "fppg"]
TE_COLS = ["gp", "targets", "rec", "rec_yds", "rec_ypg", "rec_avg", "rec_td",
           "fum", "fpts", "fppg"]
POS_COLS = {"qb": QB_COLS, "rb": RB_COLS, "wr": WR_COLS, "te": TE_COLS}

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
    text = text.replace(",", "").strip()
    if not text or text == "-":
        return 0.0
    return float(text)


def load_byes(year, json_file=None):
    if json_file:
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)
    else:
        import requests
        resp = requests.get(SCHEDULE_URL.format(year=year), headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    teams = data.get("settings", {}).get("proTeams", []) or data.get("proTeams", [])
    return {ESPN_TEAM.get(t["id"], ""): t.get("byeWeek", "") for t in teams if t["id"] in ESPN_TEAM}


def get_html(pos, year, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    import requests
    resp = requests.get(PAGE_URL.format(pos=pos.upper(), year=year), headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def fetch_position(pos, year, byes, html_file=None):
    html = get_html(pos, year, html_file)
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    body_rows = table.find("tbody").find_all("tr")
    cols = POS_COLS[pos]

    rows = []
    for tr in body_rows:
        tds = tr.find_all("td")
        if not tds:
            continue
        long_span = tds[0].find("span", class_="CellPlayerName--long")
        if long_span is None:
            continue
        name = long_span.find("a").get_text(strip=True)
        team = long_span.find("span", class_="CellPlayerName-team").get_text(strip=True)
        team = TEAM_ALIASES.get(team, team)
        vals = {col: num(td.get_text(strip=True)) for col, td in zip(cols, tds[1:])}
        bye = byes.get(team, "")

        if pos == "qb":
            s = {"pass_yds": vals["pass_yds"], "pass_td": vals["pass_td"],
                 "pass_int": vals["pass_int"], "rush_yds": vals["rush_yds"],
                 "rush_td": vals["rush_td"], "fum": vals["fum"]}
            rows.append((scoring.qb_points(s), {
                "QB": name, "Team": team, "Bye": bye,
                "Pass Att": vals["pass_att"], "Pass Comp": vals["pass_cmp"],
                "Pass Yds": vals["pass_yds"], "Pass TD": vals["pass_td"],
                "Pass Int": vals["pass_int"], "Rush Att": vals["rush_att"],
                "Rush Yds": vals["rush_yds"], "Rush TD": vals["rush_td"],
                "Fumbles": vals["fum"],
            }))
        elif pos == "rb":
            s = {"rush_yds": vals["rush_yds"], "rush_td": vals["rush_td"],
                 "rec": vals["rec"], "rec_yds": vals["rec_yds"],
                 "rec_td": vals["rec_td"], "fum": vals["fum"]}
            rows.append((scoring.ppr_points(s), {
                "RB": name, "Team": team, "Bye": bye,
                "Rush Att": vals["rush_att"], "Rush Yds": vals["rush_yds"],
                "Rush TD": vals["rush_td"], "Targets": vals["targets"],
                "Rec": vals["rec"], "Rec Yds": vals["rec_yds"], "Rec TD": vals["rec_td"],
                "Fum": vals["fum"],
            }))
        elif pos == "wr":
            s = {"rush_yds": vals["rush_yds"], "rush_td": vals["rush_td"],
                 "rec": vals["rec"], "rec_yds": vals["rec_yds"],
                 "rec_td": vals["rec_td"], "fum": vals["fum"]}
            rows.append((scoring.ppr_points(s), {
                "WR": name, "Team": team, "Bye": bye,
                "Targets": vals["targets"], "Rec": vals["rec"],
                "Rec Yds": vals["rec_yds"], "Rec TD": vals["rec_td"],
                "Rush Att": vals["rush_att"], "Rush Yds": vals["rush_yds"],
                "Rush TD": vals["rush_td"], "Fum": vals["fum"],
            }))
        elif pos == "te":
            s = {"rec": vals["rec"], "rec_yds": vals["rec_yds"],
                 "rec_td": vals["rec_td"], "fum": vals["fum"]}
            rows.append((scoring.ppr_points(s), {
                "TE": name, "Team": team, "Bye": bye,
                "Targets": vals["targets"], "Rec": vals["rec"],
                "Rec Yds": vals["rec_yds"], "Rec TD": vals["rec_td"],
                "Rush Att": "", "Rush Yds": "", "Rush TD": "",
            }))

    rows.sort(key=lambda r: r[0], reverse=True)
    return [r for _, r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--prefix", default="cbs")
    ap.add_argument("--byes-json-file", help="offline ESPN proTeamSchedules JSON")
    ap.add_argument("--html-dir", help="dir with saved <pos>.html files instead of fetching")
    args = ap.parse_args()

    byes = load_byes(args.year, args.byes_json_file)

    wrote_any = False
    for pos in ("qb", "rb", "wr", "te"):
        html_file = f"{args.html_dir}/{pos}.html" if args.html_dir else None
        rows = fetch_position(pos, args.year, byes, html_file)
        if not rows:
            print(f"No rows parsed for {pos}.")
            continue
        out = f"{args.prefix}_{pos}.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OUT_COLUMNS[pos.upper()])
            w.writeheader()
            w.writerows(rows)
        print(f"Wrote {len(rows)} {pos.upper()}s to {out}.")
        wrote_any = True

    if not wrote_any:
        sys.exit("No data parsed for any position.")


if __name__ == "__main__":
    main()
