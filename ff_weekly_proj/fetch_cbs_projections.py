#!/usr/bin/env python3
"""
Pull CBS Sports' weekly projections for QB/RB/WR/TE.

Pages (server-rendered HTML, no login needed):
  https://www.cbssports.com/fantasy/football/stats/QB/<YEAR>/week<N>/projections/ppr/
  https://www.cbssports.com/fantasy/football/stats/RB/<YEAR>/week<N>/projections/ppr/
  https://www.cbssports.com/fantasy/football/stats/WR/<YEAR>/week<N>/projections/ppr/
  https://www.cbssports.com/fantasy/football/stats/TE/<YEAR>/week<N>/projections/ppr/

Usage:
    python fetch_cbs_projections.py
    python fetch_cbs_projections.py --year 2026 --week 3

Requires: requests, beautifulsoup4
"""

import argparse
import csv
import datetime
import sys

from bs4 import BeautifulSoup

import schedule as nfl_schedule
import scoring

PAGE_URL = "https://www.cbssports.com/fantasy/football/stats/{pos}/{year}/week{week}/projections/ppr/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

TEAM_ALIASES = {"WAS": "WSH", "JAC": "JAX"}

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
    text = text.replace(",", "").strip()
    if not text or text == "-":
        return 0.0
    return float(text)


def get_html(pos, year, week, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    import requests
    resp = requests.get(
        PAGE_URL.format(pos=pos.upper(), year=year, week=week),
        headers=HEADERS, timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def fetch_position(pos, year, week, opponents, html_file=None):
    html = get_html(pos, year, week, html_file)
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []
    tbody = table.find("tbody")
    if tbody is None:
        return []
    body_rows = tbody.find_all("tr")
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
        opp = opponents.get(team, "")
        vals = {col: num(td.get_text(strip=True)) for col, td in zip(cols, tds[1:])}

        if pos == "qb":
            s = {"pass_yds": vals["pass_yds"], "pass_td": vals["pass_td"],
                 "pass_int": vals["pass_int"], "rush_yds": vals["rush_yds"],
                 "rush_td": vals["rush_td"], "fum": vals["fum"]}
            rows.append((scoring.qb_points(s), {
                "QB": name, "Team": team, "Opp": opp,
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
                "RB": name, "Team": team, "Opp": opp,
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
                "WR": name, "Team": team, "Opp": opp,
                "Targets": vals["targets"], "Rec": vals["rec"],
                "Rec Yds": vals["rec_yds"], "Rec TD": vals["rec_td"],
                "Rush Att": vals["rush_att"], "Rush Yds": vals["rush_yds"],
                "Rush TD": vals["rush_td"], "Fum": vals["fum"],
            }))
        elif pos == "te":
            s = {"rec": vals["rec"], "rec_yds": vals["rec_yds"],
                 "rec_td": vals["rec_td"], "fum": vals["fum"]}
            rows.append((scoring.ppr_points(s), {
                "TE": name, "Team": team, "Opp": opp,
                "Targets": vals["targets"], "Rec": vals["rec"],
                "Rec Yds": vals["rec_yds"], "Rec TD": vals["rec_td"],
                "Rush Att": "", "Rush Yds": "", "Rush TD": "",
            }))

    rows.sort(key=lambda r: r[0], reverse=True)
    return [r for _, r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--prefix", default="cbs")
    ap.add_argument("--html-dir")
    args = ap.parse_args()

    week, opponents = nfl_schedule.get_schedule(args.year, args.week)
    print(f"CBS: week {week}")

    wrote_any = False
    for pos in ("qb", "rb", "wr", "te"):
        html_file = f"{args.html_dir}/{pos}.html" if args.html_dir else None
        rows = fetch_position(pos, args.year, week, opponents, html_file)
        if not rows:
            print(f"No rows parsed for {pos.upper()}.")
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
