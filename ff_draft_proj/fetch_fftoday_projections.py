#!/usr/bin/env python3
"""
Pull FFToday's season-long (preseason/draft) stat-line projections for
QB/RB/WR/TE.

  https://www.fftoday.com/rankings/playerproj.php
    ?Season=<YEAR>&PosID=<10|20|30|40>&LeagueID=
    &order_by=FFPts&sort_order=DESC&cur_page=<N>

No login required. Server-rendered table, 50 rows/page; cur_page=0,1,2,...
until a page returns no rows (QB/RB/TE need 2 pages, WR needs 3).

Column layout per position (cells in each <TR>, after the leading blank
"Chg" cell and the player-name cell):
  QB (13 cells): Chg, Player, Team, Bye, PaComp, PaAtt, PaYds, PaTD, PaInt,
                 RuAtt, RuYds, RuTD, FPts
  RB (11 cells): Chg, Player, Team, Bye, RuAtt, RuYds, RuTD, Rec, RecYds,
                 RecTD, FPts
  WR (11 cells): Chg, Player, Team, Bye, Rec, RecYds, RecTD, RuAtt, RuYds,
                 RuTD, FPts
  TE (8 cells):  Chg, Player, Team, Bye, Rec, RecYds, RecTD, FPts

FFToday doesn't report Targets or Fumbles for any position — left blank.
Bye week is provided directly by the table.

Usage:
    python fetch_fftoday_projections.py
    python fetch_fftoday_projections.py --year 2026

Requires: requests
"""

import argparse
import csv
import datetime
import re
import sys

import scoring

BASE = "https://www.fftoday.com/rankings/playerproj.php"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

POS_ID = {"QB": 10, "RB": 20, "WR": 30, "TE": 40}
NUM_CELLS = {"QB": 13, "RB": 11, "WR": 11, "TE": 8}

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

TAG_RE = re.compile(r"<[^>]+>")
CELL_RE = re.compile(r'<TD class="smallbody"[^>]*>(.*?)</TD>', re.S)
ROW_RE = re.compile(r'<TR>(.*?)</TR>', re.S)


def num(text):
    text = (text or "").replace(",", "").strip()
    if not text or text == "-" or text == "\xa0":
        return 0.0
    return float(text)


def get_html(year, pos, page, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    import requests
    params = {"Season": year, "PosID": POS_ID[pos], "LeagueID": "",
              "order_by": "FFPts", "sort_order": "DESC", "cur_page": page}
    resp = requests.get(BASE, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_rows(pos, html):
    rows = []
    for row_m in ROW_RE.finditer(html):
        cells = CELL_RE.findall(row_m.group(1))
        if len(cells) != NUM_CELLS[pos]:
            continue
        values = [TAG_RE.sub("", c).strip() for c in cells]
        rows.append(values)
    return rows


def fetch_position(year, pos, html_dir=None):
    all_rows = []
    page = 0
    while True:
        html_file = f"{html_dir}/ff_{pos.lower()}_page{page}.html" if html_dir else None
        html = get_html(year, pos, page, html_file)
        rows = parse_rows(pos, html)
        if not rows:
            break
        all_rows.extend(rows)
        if html_dir:
            break
        page += 1
    return all_rows


def build_record(pos, cells):
    name = cells[1].replace("\xa0", "").replace("&nbsp;", "").strip()
    team = cells[2]
    bye = cells[3]

    if pos == "QB":
        pass_comp, pass_att, pass_yds, pass_td, pass_int = (num(cells[4]), num(cells[5]),
            num(cells[6]), num(cells[7]), num(cells[8]))
        rush_att, rush_yds, rush_td = num(cells[9]), num(cells[10]), num(cells[11])
        s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
             "rush_yds": rush_yds, "rush_td": rush_td, "fum": 0}
        return scoring.qb_points(s), {
            "QB": name, "Team": team, "Bye": bye,
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
        rush_att, rush_yds, rush_td = num(cells[4]), num(cells[5]), num(cells[6])
        rec, rec_yds, rec_td = num(cells[7]), num(cells[8]), num(cells[9])
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": 0}
        return scoring.ppr_points(s), {
            "RB": name, "Team": team, "Bye": bye,
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
        rec, rec_yds, rec_td = num(cells[4]), num(cells[5]), num(cells[6])
        rush_att, rush_yds, rush_td = num(cells[7]), num(cells[8]), num(cells[9])
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": 0}
        return scoring.ppr_points(s), {
            "WR": name, "Team": team, "Bye": bye,
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
        rec, rec_yds, rec_td = num(cells[4]), num(cells[5]), num(cells[6])
        s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": 0}
        return scoring.ppr_points(s), {
            "TE": name, "Team": team, "Bye": bye,
            "Targets": "",
            "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td),
            "Rush Att": "",
            "Rush Yds": "",
            "Rush TD": "",
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--prefix", default="fftoday")
    ap.add_argument("--html-dir", help="dir with saved ff_<pos>_page0.html files instead of fetching (single page only)")
    args = ap.parse_args()

    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        rows = fetch_position(args.year, pos, args.html_dir)
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
