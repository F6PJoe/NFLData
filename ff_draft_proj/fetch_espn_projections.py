#!/usr/bin/env python3
"""
Pull ESPN's season-long projected stat lines straight from ESPN's public
fantasy API and write one CSV per position (QB/RB/WR/TE), matching the
project's consensus schema.

Endpoints:
  Players + projected stats:
    https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/<YEAR>/segments/0/leaguedefaults/3?view=kona_player_info
  Pro team bye weeks:
    https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/<YEAR>?view=proTeamSchedules

Projected season totals are statSourceId == 1, statSplitTypeId == 0. The
"stats" dict keys are ESPN's numeric stat IDs:
  0  pass att        1  pass cmp        3  pass yds        4  pass td
  20 pass int        23 rush att        24 rush yds        25 rush td
  42 rec yds         43 rec td          53 receptions      58 targets
  72 fumbles (lost)

Fantasy points are computed locally with scoring.py so all sources share the
same scoring rules, rather than trusting each site's own point total.

Usage:
    python fetch_espn_projections.py                 # live fetch, current season
    python fetch_espn_projections.py --year 2026
    python fetch_espn_projections.py --json-file saved.json   # offline parse

Requires: requests
"""

import argparse
import csv
import datetime
import json
import sys

import scoring

PLAYERS_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/segments/0/leaguedefaults/3?view=kona_player_info"
SCHEDULE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}?view=proTeamSchedules"

FILTER = {
    "players": {
        "limit": 2000,
        "sortDraftRanks": {"sortPriority": 100, "sortAsc": True, "value": "STANDARD"},
    }
}

POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DST"}
TEAM = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}

STAT_MAP = {
    "pass_att": "0", "pass_cmp": "1", "pass_yds": "3", "pass_td": "4", "pass_int": "20",
    "rush_att": "23", "rush_yds": "24", "rush_td": "25",
    "targets": "58", "rec": "53", "rec_yds": "42", "rec_td": "43",
    "fum": "72",
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


def get_json(url, json_file):
    if json_file:
        with open(json_file, encoding="utf-8") as f:
            return json.load(f)
    import requests
    headers = {
        "User-Agent": "Mozilla/5.0 (personal projections tool)",
        "X-Fantasy-Filter": json.dumps(FILTER),
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def load_byes(args):
    if args.players_json_file:
        return {}
    data = get_json(SCHEDULE_URL.format(year=args.year), None)
    teams = data.get("settings", {}).get("proTeams", []) or data.get("proTeams", [])
    return {t["id"]: t.get("byeWeek", "") for t in teams}


def iter_players(data):
    items = data.get("players", data) if isinstance(data, dict) else data
    for item in items:
        yield item.get("player", item) if isinstance(item, dict) else {}


def projected_stats(p, year):
    for stat in p.get("stats") or []:
        if (
            stat.get("statSourceId") == 1
            and stat.get("statSplitTypeId") == 0
            and stat.get("seasonId") == year
        ):
            return stat.get("stats") or {}
    return None


def build_stat_line(raw):
    return {key: raw.get(stat_id, 0) for key, stat_id in STAT_MAP.items()}


def parse(data, year, byes):
    rows = {"QB": [], "RB": [], "WR": [], "TE": []}
    for p in iter_players(data):
        if not p:
            continue
        pos = POS.get(p.get("defaultPositionId"))
        if pos not in rows:
            continue
        raw = projected_stats(p, year)
        if raw is None:
            continue
        s = build_stat_line(raw)
        name = p.get("fullName", "")
        team = TEAM.get(p.get("proTeamId"), "")
        bye = byes.get(p.get("proTeamId"), "")

        if pos == "QB":
            rows["QB"].append((scoring.qb_points(s), {
                "QB": name, "Team": team, "Bye": bye,
                "Pass Att": scoring.round2(s["pass_att"]),
                "Pass Comp": scoring.round2(s["pass_cmp"]),
                "Pass Yds": scoring.round2(s["pass_yds"]),
                "Pass TD": scoring.round2(s["pass_td"]),
                "Pass Int": scoring.round2(s["pass_int"]),
                "Rush Att": scoring.round2(s["rush_att"]),
                "Rush Yds": scoring.round2(s["rush_yds"]),
                "Rush TD": scoring.round2(s["rush_td"]),
                "Fumbles": scoring.round2(s["fum"]),
            }))
        elif pos == "RB":
            rows["RB"].append((scoring.ppr_points(s), {
                "RB": name, "Team": team, "Bye": bye,
                "Rush Att": scoring.round2(s["rush_att"]),
                "Rush Yds": scoring.round2(s["rush_yds"]),
                "Rush TD": scoring.round2(s["rush_td"]),
                "Targets": scoring.round2(s["targets"]),
                "Rec": scoring.round2(s["rec"]),
                "Rec Yds": scoring.round2(s["rec_yds"]),
                "Rec TD": scoring.round2(s["rec_td"]),
                "Fum": scoring.round2(s["fum"]),
            }))
        elif pos == "WR":
            rows["WR"].append((scoring.ppr_points(s), {
                "WR": name, "Team": team, "Bye": bye,
                "Targets": scoring.round2(s["targets"]),
                "Rec": scoring.round2(s["rec"]),
                "Rec Yds": scoring.round2(s["rec_yds"]),
                "Rec TD": scoring.round2(s["rec_td"]),
                "Rush Att": scoring.round2(s["rush_att"]),
                "Rush Yds": scoring.round2(s["rush_yds"]),
                "Rush TD": scoring.round2(s["rush_td"]),
                "Fum": scoring.round2(s["fum"]),
            }))
        elif pos == "TE":
            rows["TE"].append((scoring.ppr_points(s), {
                "TE": name, "Team": team, "Bye": bye,
                "Targets": scoring.round2(s["targets"]),
                "Rec": scoring.round2(s["rec"]),
                "Rec Yds": scoring.round2(s["rec_yds"]),
                "Rec TD": scoring.round2(s["rec_td"]),
                "Rush Att": scoring.round2(s["rush_att"]),
                "Rush Yds": scoring.round2(s["rush_yds"]),
                "Rush TD": scoring.round2(s["rush_td"]),
            }))

    for pos in rows:
        rows[pos].sort(key=lambda r: r[0], reverse=True)
        rows[pos] = [r for _, r in rows[pos]]
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--prefix", default="espn", help="output filename prefix")
    ap.add_argument("--json-file", dest="players_json_file",
                    help="parse a saved players JSON response instead of fetching")
    args = ap.parse_args()

    byes = load_byes(args)
    data = get_json(PLAYERS_URL.format(year=args.year), args.players_json_file)
    rows = parse(data, args.year, byes)

    if not any(rows.values()):
        sys.exit("No projected players found (check the year or the saved file).")

    for pos, recs in rows.items():
        out = f"{args.prefix}_{pos.lower()}.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OUT_COLUMNS[pos])
            w.writeheader()
            w.writerows(recs)
        print(f"Wrote {len(recs)} {pos}s to {out}.")


if __name__ == "__main__":
    main()
