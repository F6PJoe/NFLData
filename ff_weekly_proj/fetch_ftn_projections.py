#!/usr/bin/env python3
"""
Pull FTN's weekly projected stat lines for QB/RB/WR/TE.

Auth: ftn_auth.get_access_token() logs in via FTN_EMAIL/FTN_PASSWORD from .env.

Data: GET https://fantasydata.ftnfantasy.com/api/projections/weekly
  Authorization: Bearer <access_token>

The endpoint always returns the current week and takes no week parameter, so
--week only affects the Opp lookup, not which slate is fetched.

Opponent lookup comes from ESPN schedule utility (the payload's own "opp"
field wins when present).

Usage:
    python fetch_ftn_projections.py
    python fetch_ftn_projections.py --year 2026 --week 3

Requires: requests
"""

import argparse
import csv
import datetime
import json
import sys

import ftn_auth
import schedule as nfl_schedule
import scoring

DATA_URL = "https://fantasydata.ftnfantasy.com/api/projections/weekly"

HEADERS = {"User-Agent": "Mozilla/5.0 (personal projections tool)"}

TEAM_ALIASES = {"WAS": "WSH", "JAC": "JAX", "ARZ": "ARI", "LA": "LAR"}

STAT_MAP = {
    "pass_att": "att", "pass_cmp": "cmp", "pass_yds": "pass_yd", "pass_td": "td_pass",
    "pass_int": "int", "rush_att": "rsh", "rush_yds": "rsh_yd", "rush_td": "td_rsh",
    "targets": "tar", "rec": "rec", "rec_yds": "rec_yd", "rec_td": "td_rec",
    "fum": "fum",
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


def get_players(week, json_file=None):
    if json_file:
        with open(json_file, encoding="utf-8") as f:
            return json.load(f)
    import requests
    token = ftn_auth.get_access_token()
    headers = dict(HEADERS, Authorization=f"Bearer {token}")
    resp = requests.get(DATA_URL, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def build_stat_line(projections):
    """Flatten FTN's [{stat, value}] list into a scoring.py stat dict.

    Stats the payload omits stay None. FTN sends only the stats relevant to a
    player's position, and build_consensus averages each column across the
    sources that supply it -- so a blank abstains where a 0 would drag every
    player's average toward zero.
    """
    raw = {p["stat"]: p.get("value") for p in projections}
    return {key: raw.get(stat_key) for key, stat_key in STAT_MAP.items()}


def cell(value):
    """Format a stat for the CSV -- blank when FTN doesn't report it."""
    return "" if value is None else value


def parse(players, opponents):
    rows = {"QB": [], "RB": [], "WR": [], "TE": []}
    for p in players:
        pos = p.get("position")
        if pos not in rows:
            continue
        s = build_stat_line(p.get("projections") or [])
        name = p.get("name", "")
        team = TEAM_ALIASES.get(p.get("team", ""), p.get("team", ""))
        # FTN provides opp directly; fall back to schedule lookup
        opp = p.get("opp") or opponents.get(team, "")

        if pos == "QB":
            rows["QB"].append((scoring.qb_points(s), {
                "QB": name, "Team": team, "Opp": opp,
                "Pass Att": cell(s["pass_att"]), "Pass Comp": cell(s["pass_cmp"]),
                "Pass Yds": cell(s["pass_yds"]), "Pass TD": cell(s["pass_td"]), "Pass Int": cell(s["pass_int"]),
                "Rush Att": cell(s["rush_att"]), "Rush Yds": cell(s["rush_yds"]), "Rush TD": cell(s["rush_td"]),
                "Fumbles": cell(s["fum"]),
            }))
        elif pos == "RB":
            rows["RB"].append((scoring.ppr_points(s), {
                "RB": name, "Team": team, "Opp": opp,
                "Rush Att": cell(s["rush_att"]), "Rush Yds": cell(s["rush_yds"]), "Rush TD": cell(s["rush_td"]),
                "Targets": cell(s["targets"]), "Rec": cell(s["rec"]), "Rec Yds": cell(s["rec_yds"]),
                "Rec TD": cell(s["rec_td"]), "Fum": cell(s["fum"]),
            }))
        elif pos == "WR":
            rows["WR"].append((scoring.ppr_points(s), {
                "WR": name, "Team": team, "Opp": opp,
                "Targets": cell(s["targets"]), "Rec": cell(s["rec"]), "Rec Yds": cell(s["rec_yds"]),
                "Rec TD": cell(s["rec_td"]), "Rush Att": cell(s["rush_att"]), "Rush Yds": cell(s["rush_yds"]),
                "Rush TD": cell(s["rush_td"]), "Fum": cell(s["fum"]),
            }))
        elif pos == "TE":
            rows["TE"].append((scoring.ppr_points(s), {
                "TE": name, "Team": team, "Opp": opp,
                "Targets": cell(s["targets"]), "Rec": cell(s["rec"]), "Rec Yds": cell(s["rec_yds"]),
                "Rec TD": cell(s["rec_td"]), "Rush Att": cell(s["rush_att"]), "Rush Yds": cell(s["rush_yds"]),
                "Rush TD": cell(s["rush_td"]),
            }))

    for pos in rows:
        rows[pos].sort(key=lambda r: r[0], reverse=True)
        rows[pos] = [r for _, r in rows[pos]]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--prefix", default="ftn")
    ap.add_argument("--players-json-file")
    args = ap.parse_args()

    week, opponents = nfl_schedule.get_schedule(args.year, args.week)
    print(f"FTN: week {week}")

    players = get_players(week, args.players_json_file)
    rows = parse(players, opponents)

    if not any(rows.values()):
        sys.exit("No projected players found.")

    for pos, recs in rows.items():
        out = f"{args.prefix}_{pos.lower()}.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OUT_COLUMNS[pos])
            w.writeheader()
            w.writerows(recs)
        print(f"Wrote {len(recs)} {pos}s to {out}.")


if __name__ == "__main__":
    main()
