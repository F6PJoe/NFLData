#!/usr/bin/env python3
"""
Pull ESPN's own ADP straight from ESPN's public fantasy API.

This is an example of "going to the source": instead of reading an aggregator,
you call the same JSON endpoint ESPN's own draft pages use. No login needed for
public player data. ESPN reports a true decimal ADP (e.g. 1.56), not a rounded rank.

Endpoint:
  https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/<YEAR>/players?view=kona_player_info
  with an X-Fantasy-Filter header to lift the 50-row cap and sort by draft rank.

Usage:
    python fetch_espn_adp.py                 # live fetch, current season -> espn_adp.csv
    python fetch_espn_adp.py --year 2026
    python fetch_espn_adp.py --json-file saved.json   # parse a saved response (offline)

Requires: requests
"""

import argparse
import csv
import datetime
import json
import sys

# Live draft results endpoint — same data structure, but returns real live ADP
# (the old /players endpoint returned stale/placeholder values for some players)
BASE = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}/segments/0/leaguedefaults/3?view=kona_player_info"

# X-Fantasy-Filter: raise the default 50-row limit and sort by standard draft rank
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

OUT_COLUMNS = ["Player", "Position(s)", "Team", "ESPN", "ESPN_Rank", "ESPN_ID"]


def get_json(args):
    if args.json_file:
        with open(args.json_file, encoding="utf-8") as f:
            return json.load(f)
    import requests
    url = BASE.format(year=args.year)
    headers = {
        "User-Agent": "Mozilla/5.0 (personal ADP consensus tool)",
        "X-Fantasy-Filter": json.dumps(FILTER),
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def iter_players(data):
    """ESPN returns either a flat list of player objects or {'players': [{'player': {...}}]}."""
    items = data.get("players", data) if isinstance(data, dict) else data
    for item in items:
        yield item.get("player", item) if isinstance(item, dict) else {}


def parse(data):
    rows = []
    for p in iter_players(data):
        if not p:
            continue
        adp = (p.get("ownership") or {}).get("averageDraftPosition")
        rank = ((p.get("draftRanksByRankType") or {}).get("STANDARD") or {}).get("rank")
        # skip players ESPN isn't drafting (ADP 0 / missing)
        if not adp or adp <= 0:
            continue
        rows.append({
            "Player": p.get("fullName", ""),
            "Position(s)": POS.get(p.get("defaultPositionId"), ""),
            "Team": TEAM.get(p.get("proTeamId"), ""),
            "ESPN": round(adp, 2),
            "ESPN_Rank": rank if rank is not None else "",
            "ESPN_ID": p.get("id", ""),
        })
    rows.sort(key=lambda r: r["ESPN"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("-o", "--output", default="espn_adp.csv")
    ap.add_argument("--json-file", help="parse a saved JSON response instead of fetching")
    args = ap.parse_args()

    rows = parse(get_json(args))
    if not rows:
        sys.exit("No players with an ADP found (check the year or the saved file).")

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=OUT_COLUMNS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} players to {args.output}.")


if __name__ == "__main__":
    main()
