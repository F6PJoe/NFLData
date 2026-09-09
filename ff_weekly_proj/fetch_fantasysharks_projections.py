#!/usr/bin/env python3
"""
Pull Fantasy Sharks' weekly projected stat lines for QB/RB/WR/TE.

Attempts the weekly CSV endpoint first:
  https://www.fantasysharks.com/apps/Projections/WeeklyProjections.php
    ?pos=<QB|RB|WR|TE>&week=<N>&format=csv

Falls back to noting the failure — Fantasy Sharks' domain may be IP-blocked
from GitHub Actions runners (same issue as the draft version).

Usage:
    python fetch_fantasysharks_projections.py
    python fetch_fantasysharks_projections.py --year 2026 --week 3

Requires: requests
"""

import argparse
import csv
import datetime
import io
import os
import sys
import time

import schedule as nfl_schedule
import scoring

CSV_URL = ("https://www.fantasysharks.com/apps/Projections/WeeklyProjections.php"
           "?pos={pos}&week={week}&format=csv")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

TEAM_ALIASES = {
    "GBP": "GB", "KCC": "KC", "LVR": "LV", "NEP": "NE", "NOS": "NO",
    "SFO": "SF", "TBB": "TB", "JAC": "JAX", "WAS": "WSH",
}

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


class Blocked(Exception):
    pass


def num(value):
    value = (value or "").replace(",", "").strip()
    if not value or value == "-":
        return 0.0
    return float(value)


def format_name(name):
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return name.strip()


def fetch_csv(pos, week, csv_file=None):
    if csv_file:
        with open(csv_file, encoding="utf-8") as f:
            text = f.read()
        return list(csv.reader(io.StringIO(text)))
    import requests
    last = None
    for attempt in range(3):
        try:
            resp = requests.get(
                CSV_URL.format(pos=pos, week=week), headers=HEADERS, timeout=30,
            )
            if resp.status_code == 403:
                last = Blocked(f"403 Forbidden for {pos} week {week}")
                time.sleep(2 * (attempt + 1))
                continue
            resp.raise_for_status()
            return list(csv.reader(io.StringIO(resp.text)))
        except requests.RequestException as e:
            last = e
            time.sleep(2 * (attempt + 1))
    raise last


def build_record(pos, row, opponents):
    # Weekly CSV column layout (cols 0-4 are always Rank, ID, Name, Team, Opp):
    # QB (13): Rank,ID,Name,Team,Opp, PassComp,PassYds,PassTD,PassInt, RushAtt,RushYds,RushTD, FPts
    # RB (13): Rank,ID,Name,Team,Opp, RushAtt,RushYds,RushTD, Tgt,Rec,RecYds,RecTD, FPts
    # WR (10): Rank,ID,Name,Team,Opp, Tgt,Rec,RecYds,RecTD, FPts
    # TE (10): Rank,ID,Name,Team,Opp, Tgt,Rec,RecYds,RecTD, FPts
    name = format_name(row[2])
    team = TEAM_ALIASES.get(row[3].upper(), row[3].upper())
    opp = opponents.get(team, "")

    if pos == "QB":
        pass_comp, pass_yds, pass_td, pass_int = num(row[5]), num(row[6]), num(row[7]), num(row[8])
        rush_att, rush_yds, rush_td = num(row[9]), num(row[10]), num(row[11])
        s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
             "rush_yds": rush_yds, "rush_td": rush_td, "fum": 0}
        return scoring.qb_points(s), {
            "QB": name, "Team": team, "Opp": opp,
            "Pass Att": "", "Pass Comp": scoring.round2(pass_comp),
            "Pass Yds": scoring.round2(pass_yds), "Pass TD": scoring.round2(pass_td),
            "Pass Int": scoring.round2(pass_int), "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds), "Rush TD": scoring.round2(rush_td),
            "Fumbles": "",
        }
    elif pos == "RB":
        rush_att, rush_yds, rush_td = num(row[5]), num(row[6]), num(row[7])
        tgt, rec, rec_yds, rec_td = num(row[8]), num(row[9]), num(row[10]), num(row[11])
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": 0}
        return scoring.ppr_points(s), {
            "RB": name, "Team": team, "Opp": opp,
            "Rush Att": scoring.round2(rush_att), "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td), "Targets": scoring.round2(tgt),
            "Rec": scoring.round2(rec), "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td), "Fum": "",
        }
    elif pos == "WR":
        # WR/TE weekly CSV: Rank,ID,Name,Team,Opp, Rec,RecYds,RecTD  (no targets column)
        rec, rec_yds, rec_td = num(row[5]), num(row[6]), num(row[7])
        s = {"rush_yds": 0, "rush_td": 0, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": 0}
        return scoring.ppr_points(s), {
            "WR": name, "Team": team, "Opp": opp,
            "Targets": "", "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds), "Rec TD": scoring.round2(rec_td),
            "Rush Att": "", "Rush Yds": "", "Rush TD": "", "Fum": "",
        }
    elif pos == "TE":
        rec, rec_yds, rec_td = num(row[5]), num(row[6]), num(row[7])
        s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": 0}
        return scoring.ppr_points(s), {
            "TE": name, "Team": team, "Opp": opp,
            "Targets": "", "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds), "Rec TD": scoring.round2(rec_td),
            "Rush Att": "", "Rush Yds": "", "Rush TD": "",
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--prefix", default="fantasysharks")
    ap.add_argument("--csv-dir")
    args = ap.parse_args()

    week, opponents = nfl_schedule.get_schedule(args.year, args.week)
    print(f"FantasySharks: week {week}")

    wrote_any = False
    blocked = []
    for pos in ("QB", "RB", "WR", "TE"):
        csv_file = f"{args.csv_dir}/{pos.lower()}.csv" if args.csv_dir else None
        out_path = f"{args.prefix}_{pos.lower()}.csv"
        try:
            rows = fetch_csv(pos, week, csv_file)
        except Exception as e:
            print(f"[WARN] fantasysharks {pos}: {type(e).__name__}: {e} — source dropped")
            blocked.append(pos)
            continue
        data_rows = rows[1:]
        recs = []
        min_cols = 9 if pos in ("WR", "TE") else 12
        for row in data_rows:
            if len(row) < min_cols or not row[2].strip():
                continue
            recs.append(build_record(pos, row, opponents))
        recs.sort(key=lambda r: r[0], reverse=True)
        recs = [r for _, r in recs]
        if not recs:
            print(f"No rows parsed for {pos}.")
            continue
        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OUT_COLUMNS[pos])
            w.writeheader()
            w.writerows(recs)
        print(f"Wrote {len(recs)} {pos}s to {out_path}.")
        wrote_any = True

    if blocked:
        print(f"[WARN] fantasysharks: {len(blocked)}/4 positions unavailable ({', '.join(blocked)})")

    if not wrote_any:
        sys.exit("No data parsed for any position.")


if __name__ == "__main__":
    main()
