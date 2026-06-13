#!/usr/bin/env python3
"""
Pull FTN's season-long (preseason/draft) projections for QB/RB/WR/TE directly
from FTN's own API (ls.ftnfantasy.com), which requires a logged-in FTN
account.

Auth: ftn_auth.get_access_token() logs in via
  POST https://api.ftnfantasy.com/users/login  {"email":..., "password":...}
using FTN_EMAIL / FTN_PASSWORD from a local .env file (see .env.example).

Data: GET https://ls.ftnfantasy.com/api/ftn/players/projections/preseason
  Authorization: Bearer <access_token>
Returns a list of players, each with a "projections" list of {"stat": ..., "value": ...}
pairs. Relevant stat keys: cmp, att, pass_yd, td_pass, int, rsh, rsh_yd,
td_rsh, tar, rec, rec_yd, td_rec, points.

FTN doesn't report fumbles, so the Fumbles/Fum columns are left blank for
this source.

Fantasy points are computed locally with scoring.py from the stat line, same
as every other source, so all sources are comparable under one scoring set.

Bye weeks come from ESPN's public proTeamSchedules endpoint (same one used by
fetch_espn_projections.py).

Usage:
    python fetch_ftn_projections.py
    python fetch_ftn_projections.py --year 2026

Requires: requests
"""

import argparse
import csv
import datetime
import json
import sys

import ftn_auth
import scoring

DATA_URL = "https://ls.ftnfantasy.com/api/ftn/players/projections/preseason"
SCHEDULE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}?view=proTeamSchedules"

HEADERS = {"User-Agent": "Mozilla/5.0 (personal projections tool)"}

ESPN_TEAM = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}
# FTN uses a couple of different team abbreviations than ESPN.
TEAM_ALIASES = {"WAS": "WSH", "JAC": "JAX", "ARZ": "ARI", "LA": "LAR"}

STAT_MAP = {
    "pass_att": "att", "pass_cmp": "cmp", "pass_yds": "pass_yd", "pass_td": "td_pass",
    "pass_int": "int", "rush_att": "rsh", "rush_yds": "rsh_yd", "rush_td": "td_rsh",
    "targets": "tar", "rec": "rec", "rec_yds": "rec_yd", "rec_td": "td_rec",
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


def get_players(json_file=None):
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
    raw = {p["stat"]: p.get("value", 0) for p in projections}
    return {key: raw.get(stat_key, 0) for key, stat_key in STAT_MAP.items()}


def parse(players, byes):
    rows = {"QB": [], "RB": [], "WR": [], "TE": []}
    for p in players:
        pos = p.get("position")
        if pos not in rows:
            continue
        s = build_stat_line(p.get("projections") or [])
        name = p.get("name", "")
        team = TEAM_ALIASES.get(p.get("team", ""), p.get("team", ""))
        bye = byes.get(team, "")

        if pos == "QB":
            rows["QB"].append((scoring.qb_points(s), {
                "QB": name, "Team": team, "Bye": bye,
                "Pass Att": s["pass_att"], "Pass Comp": s["pass_cmp"],
                "Pass Yds": s["pass_yds"], "Pass TD": s["pass_td"], "Pass Int": s["pass_int"],
                "Rush Att": s["rush_att"], "Rush Yds": s["rush_yds"], "Rush TD": s["rush_td"],
                "Fumbles": "",
            }))
        elif pos == "RB":
            rows["RB"].append((scoring.ppr_points(s), {
                "RB": name, "Team": team, "Bye": bye,
                "Rush Att": s["rush_att"], "Rush Yds": s["rush_yds"], "Rush TD": s["rush_td"],
                "Targets": s["targets"], "Rec": s["rec"], "Rec Yds": s["rec_yds"],
                "Rec TD": s["rec_td"], "Fum": "",
            }))
        elif pos == "WR":
            rows["WR"].append((scoring.ppr_points(s), {
                "WR": name, "Team": team, "Bye": bye,
                "Targets": s["targets"], "Rec": s["rec"], "Rec Yds": s["rec_yds"],
                "Rec TD": s["rec_td"], "Rush Att": s["rush_att"], "Rush Yds": s["rush_yds"],
                "Rush TD": s["rush_td"], "Fum": "",
            }))
        elif pos == "TE":
            rows["TE"].append((scoring.ppr_points(s), {
                "TE": name, "Team": team, "Bye": bye,
                "Targets": s["targets"], "Rec": s["rec"], "Rec Yds": s["rec_yds"],
                "Rec TD": s["rec_td"], "Rush Att": s["rush_att"], "Rush Yds": s["rush_yds"],
                "Rush TD": s["rush_td"],
            }))

    for pos in rows:
        rows[pos].sort(key=lambda r: r[0], reverse=True)
        rows[pos] = [r for _, r in rows[pos]]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--prefix", default="ftn")
    ap.add_argument("--players-json-file", help="offline FTN preseason projections JSON")
    ap.add_argument("--byes-json-file", help="offline ESPN proTeamSchedules JSON")
    args = ap.parse_args()

    byes = load_byes(args.year, args.byes_json_file)
    players = get_players(args.players_json_file)
    rows = parse(players, byes)

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
