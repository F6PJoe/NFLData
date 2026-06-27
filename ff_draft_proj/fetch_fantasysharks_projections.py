#!/usr/bin/env python3
"""
Pull Fantasy Sharks' season-long (preseason/draft) "High-Precision" projections
for QB/RB/WR/TE directly from their own bert/forecasts CSV export. No login
needed.

Page (for finding the season's "Segment" id and column layout):
  https://www.fantasysharks.com/apps/bert/forecasts/projections.php?Position=<POS>
CSV export:
  https://www.fantasysharks.com/apps/bert/forecasts/projections.php?csv=1&Sort=&Segment=<SEGMENT>&Position=<POS>&scoring=2&League=&uid=4&uid2=&printable=

Position ids: QB=1, RB=2, WR=4, TE=5. "Segment" is a season id that changes
every year (e.g. 874 = "2026 NFL Season") — found by scraping the <select>
options on the projections page for "<year> NFL Season".

Fantasy Sharks doesn't report Pass Att... actually it does on this
high-precision page ("Att" for QB). It does NOT report rush attempts for
WR/TE, so those are left blank (same treatment as CBS leaving TE rush stats
blank).

Bye weeks come from ESPN's public proTeamSchedules endpoint (same one used by
fetch_espn_projections.py) since this page doesn't include bye week.

Usage:
    python fetch_fantasysharks_projections.py
    python fetch_fantasysharks_projections.py --year 2026

Requires: requests
"""

import argparse
import csv
import datetime
import io
import json
import re
import sys

import scoring

PROJECTIONS_PAGE = "https://www.fantasysharks.com/apps/bert/forecasts/projections.php?Position=1"
CSV_URL = ("https://www.fantasysharks.com/apps/bert/forecasts/projections.php"
           "?csv=1&Sort=&Segment={segment}&Position={pos}&scoring=2&League=&uid=4&uid2=&printable=")
SCHEDULE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}?view=proTeamSchedules"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

POSITION_IDS = {"QB": 1, "RB": 2, "WR": 4, "TE": 5}

ESPN_TEAM = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
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


def num(text):
    text = (text or "").replace(",", "").strip()
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


def find_segment(year, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            html = f.read()
    else:
        import requests
        resp = requests.get(PROJECTIONS_PAGE, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        html = resp.text
    for segment, label in re.findall(r'<option value="(\d+)"[^>]*>(\d{4}) NFL Season</option>', html):
        if int(label) == year:
            return segment
    sys.exit(f"Could not find a '{year} NFL Season' segment on the projections page.")


def get_csv(segment, pos_id, csv_file=None):
    if csv_file:
        with open(csv_file, encoding="utf-8") as f:
            text = f.read()
    else:
        import requests
        resp = requests.get(CSV_URL.format(segment=segment, pos=pos_id), headers=HEADERS, timeout=30)
        resp.raise_for_status()
        text = resp.text
    return list(csv.DictReader(io.StringIO(text)))


def format_name(name):
    # "Allen, Josh" -> "Josh Allen"
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return name


def parse_position(pos, rows, byes):
    out = []
    for row in rows:
        name = format_name(row["Player Name"])
        team = TEAM_ALIASES.get(row["Team"], row["Team"])
        bye = byes.get(team, "")

        if pos == "QB":
            s = {"pass_yds": num(row["Pass Yds"]), "pass_td": num(row["Pass TDs"]),
                 "pass_int": num(row["Int"]), "rush_yds": num(row["Rush Yds"]),
                 "rush_td": num(row["Rush TDs"]), "fum": num(row["Fum Lost"])}
            out.append((scoring.qb_points(s), {
                "QB": name, "Team": team, "Bye": bye,
                "Pass Att": scoring.round2(num(row["Att"])),
                "Pass Comp": scoring.round2(num(row["Comp"])),
                "Pass Yds": scoring.round2(num(row["Pass Yds"])),
                "Pass TD": scoring.round2(num(row["Pass TDs"])),
                "Pass Int": scoring.round2(num(row["Int"])),
                "Rush Att": scoring.round2(num(row["Rush"])),
                "Rush Yds": scoring.round2(num(row["Rush Yds"])),
                "Rush TD": scoring.round2(num(row["Rush TDs"])),
                "Fumbles": scoring.round2(num(row["Fum Lost"])),
            }))
        elif pos == "RB":
            s = {"rush_yds": num(row["Rush Yds"]), "rush_td": num(row["Rush TDs"]),
                 "rec": num(row["Rec"]), "rec_yds": num(row["Rec Yds"]),
                 "rec_td": num(row["Rec TDs"]), "fum": num(row["Fum Lost"])}
            out.append((scoring.ppr_points(s), {
                "RB": name, "Team": team, "Bye": bye,
                "Rush Att": scoring.round2(num(row["Rush"])),
                "Rush Yds": scoring.round2(num(row["Rush Yds"])),
                "Rush TD": scoring.round2(num(row["Rush TDs"])),
                "Targets": scoring.round2(num(row["Tgt"])),
                "Rec": scoring.round2(num(row["Rec"])),
                "Rec Yds": scoring.round2(num(row["Rec Yds"])),
                "Rec TD": scoring.round2(num(row["Rec TDs"])),
                "Fum": scoring.round2(num(row["Fum Lost"])),
            }))
        elif pos == "WR":
            s = {"rush_yds": num(row["Rush Yds"]), "rush_td": num(row["Rush TDs"]),
                 "rec": num(row["Rec"]), "rec_yds": num(row["Rec Yds"]),
                 "rec_td": num(row["Rec TDs"]), "fum": num(row["Fum Lost"])}
            out.append((scoring.ppr_points(s), {
                "WR": name, "Team": team, "Bye": bye,
                "Targets": scoring.round2(num(row["Tgt"])),
                "Rec": scoring.round2(num(row["Rec"])),
                "Rec Yds": scoring.round2(num(row["Rec Yds"])),
                "Rec TD": scoring.round2(num(row["Rec TDs"])),
                "Rush Att": "",
                "Rush Yds": scoring.round2(num(row["Rush Yds"])),
                "Rush TD": scoring.round2(num(row["Rush TDs"])),
                "Fum": scoring.round2(num(row["Fum Lost"])),
            }))
        elif pos == "TE":
            s = {"rec": num(row["Rec"]), "rec_yds": num(row["Rec Yds"]),
                 "rec_td": num(row["Rec TDs"]), "fum": num(row["Fum Lost"])}
            out.append((scoring.ppr_points(s), {
                "TE": name, "Team": team, "Bye": bye,
                "Targets": scoring.round2(num(row["Tgt"])),
                "Rec": scoring.round2(num(row["Rec"])),
                "Rec Yds": scoring.round2(num(row["Rec Yds"])),
                "Rec TD": scoring.round2(num(row["Rec TDs"])),
                "Rush Att": "",
                "Rush Yds": scoring.round2(num(row["Rush Yds"])),
                "Rush TD": scoring.round2(num(row["Rush TDs"])),
            }))

    out.sort(key=lambda r: r[0], reverse=True)
    return [r for _, r in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--prefix", default="fantasysharks")
    ap.add_argument("--byes-json-file", help="offline ESPN proTeamSchedules JSON")
    ap.add_argument("--segment-html-file", help="offline saved projections page HTML")
    ap.add_argument("--csv-dir", help="dir with saved <pos>.csv files instead of fetching")
    args = ap.parse_args()

    byes = load_byes(args.year, args.byes_json_file)
    segment = find_segment(args.year, args.segment_html_file)

    wrote_any = False
    for pos, pos_id in POSITION_IDS.items():
        csv_file = f"{args.csv_dir}/{pos.lower()}.csv" if args.csv_dir else None
        rows = get_csv(segment, pos_id, csv_file)
        recs = parse_position(pos, rows, byes)
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
