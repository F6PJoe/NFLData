#!/usr/bin/env python3
"""Build "IDP points allowed" tables (points against, by IDP scoring system
and defensive position) from nflverse.

Sibling to `ff_points_against` (offense QB/RB/WR/TE + team DST), but
deliberately a SEPARATE project/page, not folded into that one -- the whole
axis is different (3 IDP scoring systems instead of std/half/PPR, positions
are DL/LB/S instead of offensive skill positions) and the user asked for it
on its own page rather than mixed into the offense tables.

Same data source, no new sourcing question
--------------------------------------------
`stats_player_week_<year>.csv` (same file `ff_points_against` already reads)
carries individual defenders' own stat lines -- tackles (solo/assisted),
tackles for loss, QB hits, sacks (+ yards), interceptions (+ yards), passes
defended, forced fumbles, fumble recoveries (+ yards), safeties, blocked
kicks, defensive/special-teams TDs. Confirmed against nflverse's own
`dictionary_playerstats_def.csv` (not guessed) -- every stat all 3 scoring
systems below need is already in this file, no new source required.

Scoring
-------
Three systems, all per the user's own bullet lists:

  1-2-3 (idparmy.com/idp123):
    1pt  = assisted tackle, QB hit
    2pt  = solo tackle, tackle for loss
    3pt  = pass defended, forced fumble, fumble recovery, safety, blocked kick
    6pt  = interception, sack, touchdown

  Big 3 (theidpshow.com):
    .1pt  = sack yards, any return yards (INT + fumble-recovery return yards)
    .75pt = assisted tackle
    1.25pt = solo tackle
    2pt   = QB hit
    3pt   = fumble recovery, tackle for loss
    4pt   = pass defended, forced fumble
    5pt   = blocked kick, sack, safety
    6pt   = interception, touchdown

  FantasyPros (fantasypros.com/scoring-settings):
    solo tackle = 1.5, assisted tackle = 0.75, tackle for loss = 2.5,
    sack/forced-fumble/fumble-recovery = 4 each (3 separate event types,
    each independently worth 4 -- implemented literally per their bullet
    list, which lumps the three together rather than pricing them apart),
    interception = 5, defensive TD = 6, safety = 2, pass defended = 1.5.

Assisted-tackle column pick: nflverse has two similarly-named columns,
`def_tackles_with_assist` and `def_tackle_assists`. Checked real 2025 data
directly (not guessed) -- `def_tackles_with_assist` is almost always 0 even
for players who clearly picked up special-teams tackle assists (backups,
long snappers), while `def_tackle_assists` matches real box-score "AST"
behavior. Used `def_tackle_assists` throughout.

Position buckets: DL / LB / S only (per user's explicit ask), not a 4th
CB/DB bucket. nflverse's own `position` field is granular (DE/DT/NT/DL,
LB/OLB/MLB/ILB, S/SS/FS/SAF, plus CB/DB) -- checked the real distribution
of position spellings on defensive-stat rows in 2025 before writing
`POS_BUCKET` below, same diligence `ff_utilization` used for offensive
position spellings. CB/DB rows are simply excluded, not folded into S --
"DB" is genuinely ambiguous (could be a corner or a safety) and the user
asked for S specifically, not a merged secondary bucket.

No points-allowed tier (unlike ff_points_against's DST table) -- that's a
team-defense-level bonus stat, not part of individual IDP scoring in any of
these 3 systems. Pure per-player stat-line scoring, summed by team+week,
attributed to the OPPONENT (same "points against" direction as everywhere
else in this repo: a stat counts against whoever gave it up).

Usage:
    python fetch_nflverse_idp_points_against.py --year 2026
    python fetch_nflverse_idp_points_against.py --year 2025 --refresh
"""

import argparse
import csv
import json
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cached" / "nflverse"
OUTDIR = HERE / "data"

REL = "https://github.com/nflverse/nflverse-data/releases/download"
UA = {"User-Agent": "Mozilla/5.0 (ff_idp_points_against; personal use)"}

POSITIONS = ("DL", "LB", "S")
FORMATS = ("one_two_three", "big3", "fantasypros")

TEAM_FIX = {"LA": "LAR"}

POS_BUCKET = {
    "DE": "DL", "DT": "DL", "NT": "DL", "DL": "DL",
    "LB": "LB", "OLB": "LB", "MLB": "LB", "ILB": "LB",
    "S": "S", "SS": "S", "FS": "S", "SAF": "S",
}


def fetch(year, refresh=False):
    url = f"{REL}/stats_player/stats_player_week_{year}.csv"
    dest = CACHE / f"stats_player_week_{year}.csv"
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and not refresh:
        print(f"  cached   {dest.name}")
        return dest
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            data = r.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise SystemExit(f"no data yet for {year} ({url} -> 404)")
        raise
    dest.write_bytes(data)
    print(f"  fetched  {dest.name}  ({len(data)/1024:.0f} KB)")
    time.sleep(0.2)
    return dest


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def stat_line(row):
    blocked = (num(row.get("def_punt_blocks")) + num(row.get("def_pat_blocks"))
               + num(row.get("def_fg_blocks")))
    tds = num(row.get("def_tds")) + num(row.get("special_teams_tds"))
    return_yards = num(row.get("def_interception_yards")) + num(row.get("fumble_recovery_yards_opp"))
    return {
        "solo": num(row.get("def_tackles_solo")),
        "ast": num(row.get("def_tackle_assists")),
        "tfl": num(row.get("def_tackles_for_loss")),
        "qb_hit": num(row.get("def_qb_hits")),
        "pd": num(row.get("def_pass_defended")),
        "ff": num(row.get("def_fumbles_forced")),
        "fr": num(row.get("fumble_recovery_opp")),
        "safety": num(row.get("def_safeties")),
        "blocked": blocked,
        "int": num(row.get("def_interceptions")),
        "sack": num(row.get("def_sacks")),
        "td": tds,
        "sack_yds": num(row.get("def_sack_yards")),
        "return_yds": return_yards,
    }


def points_123(s):
    return (1 * (s["ast"] + s["qb_hit"])
            + 2 * (s["solo"] + s["tfl"])
            + 3 * (s["pd"] + s["ff"] + s["fr"] + s["safety"] + s["blocked"])
            + 6 * (s["int"] + s["sack"] + s["td"]))


def points_big3(s):
    return (0.1 * (s["sack_yds"] + s["return_yds"])
            + 0.75 * s["ast"]
            + 1.25 * s["solo"]
            + 2 * s["qb_hit"]
            + 3 * (s["fr"] + s["tfl"])
            + 4 * (s["pd"] + s["ff"])
            + 5 * (s["blocked"] + s["sack"] + s["safety"])
            + 6 * (s["int"] + s["td"]))


def points_fantasypros(s):
    return (1.5 * s["solo"]
            + 0.75 * s["ast"]
            + 2.5 * s["tfl"]
            + 4 * (s["sack"] + s["ff"] + s["fr"])
            + 5 * s["int"]
            + 6 * s["td"]
            + 2 * s["safety"]
            + 1.5 * s["pd"])


SCORERS = {
    "one_two_three": points_123,
    "big3": points_big3,
    "fantasypros": points_fantasypros,
}


def build(year, refresh=False):
    path = fetch(year, refresh)

    # points[format][idp_pos][team][week] = points allowed that week
    points = {f: {p: defaultdict(lambda: defaultdict(float)) for p in POSITIONS}
              for f in FORMATS}
    played = defaultdict(set)

    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("season_type") != "REG":
                continue
            bucket = POS_BUCKET.get(row.get("position") or "")
            if not bucket:
                continue
            opp = row.get("opponent_team") or ""
            opp = TEAM_FIX.get(opp, opp)
            if not opp:
                continue
            wk = int(num(row.get("week")))
            s = stat_line(row)
            if not any(s.values()):
                continue
            played[opp].add(wk)
            for fmt, scorer in SCORERS.items():
                points[fmt][bucket][opp][wk] += scorer(s)

    weeks = sorted({wk for wks in played.values() for wk in wks})
    teams = sorted(played)

    out = {"season": year, "weeks": weeks, "formats": {}}
    for fmt in FORMATS:
        out["formats"][fmt] = {}
        for pos in POSITIONS:
            table = {}
            for team in teams:
                by_week = points[fmt][pos][team]
                row_weeks = {wk: round(by_week.get(wk, 0.0), 1)
                             for wk in played[team]}
                avg = round(sum(row_weeks.values()) / len(row_weeks), 1) \
                    if row_weeks else 0.0
                table[team] = {"weeks": row_weeks, "avg": avg}
            out["formats"][fmt][pos] = table
    return out, teams


def write_json(payload, year):
    OUTDIR.mkdir(parents=True, exist_ok=True)
    dest = OUTDIR / f"idp_points_against_{year}.json"
    dest.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return dest


def write_csv(payload, teams, year):
    dest = OUTDIR / f"idp_points_against_{year}.csv"
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["season", "format", "position", "team", "week", "points"])
        for fmt in FORMATS:
            for pos in POSITIONS:
                for team in teams:
                    row = payload["formats"][fmt][pos][team]
                    for wk, pts in sorted(row["weeks"].items()):
                        w.writerow([year, fmt, pos, team, wk, pts])
    return dest


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--refresh", action="store_true",
                     help="re-download stats_player_week even if cached -- "
                          "the file is one-per-season and overwritten in "
                          "place, so pass this on every real weekly run")
    args = ap.parse_args()

    print(f"IDP points against -- {args.year}\n")
    payload, teams = build(args.year, args.refresh)
    print(f"{len(teams)} teams, weeks present: {payload['weeks']}")

    jpath = write_json(payload, args.year)
    cpath = write_csv(payload, teams, args.year)
    print(f"  {jpath.name}  ({jpath.stat().st_size/1024:.0f} KB)")
    print(f"  {cpath.name}  ({cpath.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
