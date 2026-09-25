#!/usr/bin/env python3
"""
Pull ESPN's weekly projected stat lines from ESPN's public fantasy API.

Endpoints:
  Players + projected stats:
    https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/<YEAR>/
      segments/0/leaguedefaults/3?view=kona_player_info&scoringPeriodId=<WEEK>
  Schedule (opponents):
    schedule.get_schedule(year, week)

Projected weekly stats are statSourceId == 1, statSplitTypeId == 1 (weekly),
scoringPeriodId == <week>. Stat IDs are the same as the season version.

Usage:
    python fetch_espn_projections.py
    python fetch_espn_projections.py --year 2026 --week 3
    python fetch_espn_projections.py --json-file saved.json --week 3

Requires: requests
"""

import argparse
import csv
import datetime
import json
import sys

import schedule as nfl_schedule
import scoring

PLAYERS_URL = ("https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}"
               "/segments/0/leaguedefaults/3?view=kona_player_info&scoringPeriodId={week}")

POS = {1: "QB", 2: "RB", 3: "WR", 4: "TE"}
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
    "QB": ["QB", "Team", "Opp", "Pass Att", "Pass Comp", "Pass Yds", "Pass TD",
           "Pass Int", "Rush Att", "Rush Yds", "Rush TD", "Fumbles"],
    "RB": ["RB", "Team", "Opp", "Rush Att", "Rush Yds", "Rush TD", "Targets", "Rec",
           "Rec Yds", "Rec TD", "Fum"],
    "WR": ["WR", "Team", "Opp", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD", "Fum"],
    "TE": ["TE", "Team", "Opp", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD"],
}


def get_json(url, json_file, week):
    if json_file:
        with open(json_file, encoding="utf-8") as f:
            return json.load(f)
    import requests
    FILTER = {
        "players": {
            "limit": 2000,
            "sortAppliedStatTotalForScoringPeriodId": {
                "sortAsc": False, "sortPriority": 1, "value": week,
            },
        }
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (personal projections tool)",
        "X-Fantasy-Filter": json.dumps(FILTER),
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def iter_players(data):
    items = data.get("players", data) if isinstance(data, dict) else data
    for item in items:
        yield item.get("player", item) if isinstance(item, dict) else {}


def projected_stats(p, year, week):
    # seasonId MUST match. ESPN returns projections for the current AND the
    # previous season in the same list, in no fixed order; without this check
    # the first "week N" entry won, and for 571 of 700 players in week 3 of
    # 2026 that was LAST season's week-N projection -- empty for anyone who was
    # hurt that week (Brock Purdy: 0 across the board instead of 21/30, 260).
    for stat in p.get("stats") or []:
        if (
            stat.get("seasonId") == year
            and stat.get("statSourceId") == 1
            and stat.get("statSplitTypeId") == 1
            and stat.get("scoringPeriodId") == week
        ):
            return stat.get("stats") or {}
    return None


def build_stat_line(raw):
    return {key: raw.get(stat_id, 0) for key, stat_id in STAT_MAP.items()}


def parse(data, year, week, opponents):
    rows = {"QB": [], "RB": [], "WR": [], "TE": []}
    for p in iter_players(data):
        if not p:
            continue
        pos = POS.get(p.get("defaultPositionId"))
        if pos not in rows:
            continue
        raw = projected_stats(p, year, week)
        if raw is None:
            continue
        s = build_stat_line(raw)
        name = p.get("fullName", "")
        team = TEAM.get(p.get("proTeamId"), "")
        opp = opponents.get(team, "")

        if pos == "QB":
            rows["QB"].append((scoring.qb_points(s), {
                "QB": name, "Team": team, "Opp": opp,
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
                "RB": name, "Team": team, "Opp": opp,
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
                "WR": name, "Team": team, "Opp": opp,
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
                "TE": name, "Team": team, "Opp": opp,
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
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--prefix", default="espn")
    ap.add_argument("--json-file", dest="players_json_file")
    args = ap.parse_args()

    week, opponents = nfl_schedule.get_schedule(args.year, args.week)
    print(f"ESPN: week {week}, {len(opponents)} teams have opponents")

    url = PLAYERS_URL.format(year=args.year, week=week)
    data = get_json(url, args.players_json_file, week)
    rows = parse(data, args.year, week, opponents)

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
