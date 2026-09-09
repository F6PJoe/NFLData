#!/usr/bin/env python3
"""
Pull FFToday's weekly projected stat lines for QB/RB/WR/TE.

  https://www.fftoday.com/rankings/playerwkproj.php
    ?Season=<YEAR>&GameWeek=<WEEK>&PosID=<10|20|30|40>&LeagueID=
    &order_by=FFPts&sort_order=DESC&cur_page=<N>

No login required. Server-rendered table, 50 rows/page.

Column layout per position (cells after the leading "Chg" and player-name cell):
  QB: Team, Opp, PaComp, PaAtt, PaYds, PaTD, PaInt, RuAtt, RuYds, RuTD, FPts
  RB: Team, Opp, RuAtt, RuYds, RuTD, Rec, RecYds, RecTD, FPts
  WR: Team, Opp, Rec, RecYds, RecTD, RuAtt, RuYds, RuTD, FPts
  TE: Team, Opp, Rec, RecYds, RecTD, FPts

FFToday doesn't report Targets or Fumbles — left blank.
Opp is included directly in the weekly table (unlike the season version which has Bye).

Usage:
    python fetch_fftoday_projections.py
    python fetch_fftoday_projections.py --year 2026 --week 3

Requires: requests
"""

import argparse
import csv
import datetime
import re
import sys

import schedule as nfl_schedule
import scoring

BASE = "https://www.fftoday.com/rankings/playerwkproj.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

POS_ID = {"QB": 10, "RB": 20, "WR": 30, "TE": 40}
# Observed cell counts on the weekly page (smallbody cells only, not the bodycontent rank cell):
# QB:  name, team, opp, pass_comp, pass_att, pass_yds, pass_td, pass_int, rush_att, rush_yds, rush_td, fpts  = 12
# RB:  name, team, opp, rush_att, rush_yds, rush_td, rec, rec_yds, rec_td, fpts                              = 10
# WR:  name, team, opp, rush_att, rush_yds, rush_td, rec, rec_yds, rec_td, fpts                              = 10
# TE:  name, team, opp, rush_att, rush_yds, rush_td, rec, rec_yds, rec_td, fpts                              = 10
NUM_CELLS = {"QB": 12, "RB": 10, "WR": 10, "TE": 10}

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

TAG_RE = re.compile(r"<[^>]+>")
CELL_RE = re.compile(r'<TD class="smallbody"[^>]*>(.*?)</TD>', re.S)
ROW_RE = re.compile(r'<TR>(.*?)</TR>', re.S)


def num(text):
    text = (text or "").replace(",", "").strip()
    if not text or text == "-" or text == "\xa0":
        return 0.0
    return float(text)


def get_html(year, week, pos, page, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    import requests, time
    params = {"Season": year, "GameWeek": week, "PosID": POS_ID[pos], "LeagueID": "",
              "order_by": "FFPts", "sort_order": "DESC", "cur_page": page}
    for attempt in range(3):
        resp = requests.get(BASE, params=params, headers=HEADERS, timeout=30)
        if resp.status_code == 403:
            time.sleep(3 * (attempt + 1))
            continue
        resp.raise_for_status()
        return resp.text
    resp.raise_for_status()


def parse_rows(pos, html):
    rows = []
    for row_m in ROW_RE.finditer(html):
        cells = CELL_RE.findall(row_m.group(1))
        if len(cells) != NUM_CELLS[pos]:
            continue
        values = [TAG_RE.sub("", c).strip() for c in cells]
        rows.append(values)
    return rows


def fetch_position(year, week, pos, html_dir=None):
    all_rows = []
    page = 0
    while True:
        html_file = f"{html_dir}/ff_{pos.lower()}_page{page}.html" if html_dir else None
        html = get_html(year, week, pos, page, html_file)
        rows = parse_rows(pos, html)
        if not rows:
            break
        all_rows.extend(rows)
        if html_dir:
            break
        page += 1
    return all_rows


def build_record(pos, cells):
    # cells[0] = name (with leading &nbsp;), cells[1] = team, cells[2] = opp, cells[3+] = stats
    name = cells[0].replace("\xa0", "").replace("&nbsp;", "").strip()
    team = cells[1]
    opp = cells[2]

    if pos == "QB":
        # cells: name, team, opp, pass_comp, pass_att, pass_yds, pass_td, pass_int, rush_att, rush_yds, rush_td, fpts
        pass_comp, pass_att = num(cells[3]), num(cells[4])
        pass_yds, pass_td, pass_int = num(cells[5]), num(cells[6]), num(cells[7])
        rush_att, rush_yds, rush_td = num(cells[8]), num(cells[9]), num(cells[10])
        s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
             "rush_yds": rush_yds, "rush_td": rush_td, "fum": 0}
        return scoring.qb_points(s), {
            "QB": name, "Team": team, "Opp": opp,
            "Pass Att": scoring.round2(pass_att),
            "Pass Comp": scoring.round2(pass_comp),
            "Pass Yds": scoring.round2(pass_yds),
            "Pass TD": scoring.round2(pass_td),
            "Pass Int": scoring.round2(pass_int),
            "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
            "Fumbles": "",
        }
    elif pos == "RB":
        # cells: name, team, opp, rush_att, rush_yds, rush_td, rec, rec_yds, rec_td, fpts
        rush_att, rush_yds, rush_td = num(cells[3]), num(cells[4]), num(cells[5])
        rec, rec_yds, rec_td = num(cells[6]), num(cells[7]), num(cells[8])
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": 0}
        return scoring.ppr_points(s), {
            "RB": name, "Team": team, "Opp": opp,
            "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
            "Targets": "",
            "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td),
            "Fum": "",
        }
    elif pos == "WR":
        # cells: name, team, opp, rush_att, rush_yds, rush_td, rec, rec_yds, rec_td, fpts
        rush_att, rush_yds, rush_td = num(cells[3]), num(cells[4]), num(cells[5])
        rec, rec_yds, rec_td = num(cells[6]), num(cells[7]), num(cells[8])
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": 0}
        return scoring.ppr_points(s), {
            "WR": name, "Team": team, "Opp": opp,
            "Targets": "",
            "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td),
            "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
            "Fum": "",
        }
    elif pos == "TE":
        # cells: name, team, opp, rush_att, rush_yds, rush_td, rec, rec_yds, rec_td, fpts
        rush_att, rush_yds, rush_td = num(cells[3]), num(cells[4]), num(cells[5])
        rec, rec_yds, rec_td = num(cells[6]), num(cells[7]), num(cells[8])
        s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": 0}
        return scoring.ppr_points(s), {
            "TE": name, "Team": team, "Opp": opp,
            "Targets": "",
            "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td),
            "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--prefix", default="fftoday")
    ap.add_argument("--html-dir")
    args = ap.parse_args()

    week, _opponents = nfl_schedule.get_schedule(args.year, args.week)
    print(f"FFToday: week {week}")

    import time
    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        if pos != "QB":
            time.sleep(2)
        rows = fetch_position(args.year, week, pos, args.html_dir)
        recs = [build_record(pos, row) for row in rows]
        recs.sort(key=lambda r: r[0], reverse=True)
        recs = [r for _, r in recs]
        if not recs:
            print(f"No rows parsed for {pos}.")
            continue
        out = f"{args.prefix}_{pos.lower()}.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OUT_COLUMNS[pos])
            w.writeheader()
            w.writerows(recs)
        print(f"Wrote {len(recs)} {pos}s to {out}.")
        wrote_any = True

    if not wrote_any:
        sys.exit("No data parsed for any position.")


if __name__ == "__main__":
    main()
