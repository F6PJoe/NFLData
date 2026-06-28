#!/usr/bin/env python3
"""
Pull Fantasy Sharks' season-long (preseason/draft) projections for QB/RB/WR/TE
directly from their public CSV export, no login needed.

  https://www.fantasysharks.com/apps/Projections/SeasonProjections.php?pos=<POS>&format=csv

This is the simple/legacy CSV export. The site's other projections export
(bert/forecasts/projections.php, used previously) started returning
403 Forbidden when called from non-residential IPs (e.g. GitHub Actions
runners) — confirmed it's IP-based blocking, not a User-Agent issue, since a
realistic browser UA didn't help. This endpoint includes bye week directly
(no separate ESPN schedule lookup needed) but does not report Pass Att (QB)
or Targets (RB/WR/TE) — left blank for those fields, same treatment as other
sources missing a stat.

Usage:
    python fetch_fantasysharks_projections.py

Requires: requests
"""

import argparse
import csv
import io
import sys

import scoring

CSV_URL = "https://www.fantasysharks.com/apps/Projections/SeasonProjections.php?pos={pos}&format=csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# Fantasy Sharks uses different team abbreviations than ESPN for some teams.
TEAM_ALIASES = {
    "GBP": "GB", "KCC": "KC", "LVR": "LV", "NEP": "NE", "NOS": "NO",
    "SFO": "SF", "TBB": "TB", "JAC": "JAX", "WAS": "WSH",
}

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


def num(value):
    value = (value or "").replace(",", "").strip()
    if not value or value == "-":
        return 0.0
    return float(value)


def format_name(name):
    # "Allen, Josh" -> "Josh Allen"
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return name.strip()


def fetch_csv(pos, csv_file=None):
    if csv_file:
        with open(csv_file, encoding="utf-8") as f:
            text = f.read()
    else:
        import requests
        resp = requests.get(CSV_URL.format(pos=pos), headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = resp.text
    return list(csv.reader(io.StringIO(text)))


def build_record(pos, row):
    # Columns (by position, no usable header names — several are duplicated
    # across positions, e.g. "Yards"/"TDs" appear twice with different
    # meanings): Rank, ADP, ID, Name, Team, Bye, <position-specific...>
    name = format_name(row[3])
    team = TEAM_ALIASES.get(row[4].upper(), row[4].upper())
    bye = row[5]

    if pos == "QB":
        pass_comp, pass_yds, pass_td, pass_int = num(row[6]), num(row[7]), num(row[8]), num(row[9])
        rush_yds, rush_td, fum = num(row[10]), num(row[11]), num(row[12])
        s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
             "rush_yds": rush_yds, "rush_td": rush_td, "fum": fum}
        return scoring.qb_points(s), {
            "QB": name, "Team": team, "Bye": bye,
            "Pass Att": "", "Pass Comp": scoring.round2(pass_comp),
            "Pass Yds": scoring.round2(pass_yds), "Pass TD": scoring.round2(pass_td),
            "Pass Int": scoring.round2(pass_int), "Rush Att": "",
            "Rush Yds": scoring.round2(rush_yds), "Rush TD": scoring.round2(rush_td),
            "Fumbles": scoring.round2(fum),
        }
    elif pos == "RB":
        rush_att, rush_yds, rush_td, fum = num(row[6]), num(row[7]), num(row[8]), num(row[9])
        rec, rec_yds, rec_td = num(row[10]), num(row[11]), num(row[12])
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
        return scoring.ppr_points(s), {
            "RB": name, "Team": team, "Bye": bye,
            "Rush Att": scoring.round2(rush_att), "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td), "Targets": "",
            "Rec": scoring.round2(rec), "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td), "Fum": scoring.round2(fum),
        }
    elif pos == "WR":
        rec, rec_yds, rec_td = num(row[6]), num(row[7]), num(row[8])
        rush_att, rush_yds, rush_td, fum = num(row[9]), num(row[10]), num(row[11]), num(row[12])
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
        return scoring.ppr_points(s), {
            "WR": name, "Team": team, "Bye": bye,
            "Targets": "", "Rec": scoring.round2(rec), "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td), "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds), "Rush TD": scoring.round2(rush_td),
            "Fum": scoring.round2(fum),
        }
    elif pos == "TE":
        rec, rec_yds, rec_td = num(row[6]), num(row[7]), num(row[8])
        rush_att, rush_yds, rush_td = num(row[9]), num(row[10]), num(row[11])
        s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": num(row[12])}
        return scoring.ppr_points(s), {
            "TE": name, "Team": team, "Bye": bye,
            "Targets": "", "Rec": scoring.round2(rec), "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td), "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds), "Rush TD": scoring.round2(rush_td),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="fantasysharks")
    ap.add_argument("--csv-dir", help="dir with saved <pos>.csv files instead of fetching")
    args = ap.parse_args()

    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        csv_file = f"{args.csv_dir}/{pos.lower()}.csv" if args.csv_dir else None
        rows = fetch_csv(pos, csv_file)
        data_rows = rows[1:]
        recs = []
        for row in data_rows:
            if len(row) < 13 or not row[3].strip():
                continue
            recs.append(build_record(pos, row))
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
