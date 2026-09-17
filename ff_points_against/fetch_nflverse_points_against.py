#!/usr/bin/env python3
"""Build "fantasy points allowed" tables (points against, by position and
scoring format) from nflverse -- replaces the old manual workflow of
downloading a weekly CSV per position/format from FantasyData and pasting it
into a Google Sheet of VLOOKUPs.

Why nflverse and not Sportradar / GSIS gamebooks
-------------------------------------------------
This table only needs player BOX SCORE stats grouped by opponent -- it is not
a participation/snap-count problem like `ff_utilization`, so the constraints
that pushed that project to FantasyLife/PFF don't apply here. nflverse's
`stats_player_week_<year>.csv` release already carries `opponent_team` and
every counting stat scoring needs (passing/rushing/receiving yards & TDs,
interceptions, receptions, fumbles lost, 2pt conversions, and every defensive/
special-teams stat DST scoring needs), for free, no login. No reason to pay
for Sportradar or parse GSIS gamebook PDFs for this.

Update timing: confirmed live for the current season -- `stats_player_week`
is rebuilt nightly during the season (and again at points during game days),
so Sunday's games are in by Monday morning. The NFL issues stat corrections
Monday-Wednesday, so a Thursday pull is the most "final" version, same
caveat as everywhere else in this repo that reads nflverse in-season.
See https://nflreadr.nflverse.com/articles/nflverse_data_schedule.html

Scoring (QB/RB/WR/TE): reuses ff_draft_proj/scoring.py's rushing/receiving/
fumble formulas, but ADDS 2pt conversions (2 pts each, passing or rushing/
receiving), which that module doesn't model -- fine for preseason projections
(2pt conversions aren't projected), but real games have them and skipping
them was the entire gap when this was checked against the legacy
FantasyData-sourced numbers on fantasysixpack.net (11/18 weeks matched
exactly for a spot-checked team/position; every remaining week matched once
its 2pt conversions were added back in, modulo the odd point from in-season
stat corrections the old page was never updated to reflect).

Scoring (DST): standard/ESPN-default team-defense scoring, same regardless
of std/half/PPR (matches QB, which also doesn't vary by format):
    sack = 1, interception = 2, fumble recovery = 2, safety = 2,
    defensive TD = 6, special-teams TD = 6, blocked kick = 2,
    plus a points-allowed tier (0=10, 1-6=7, 7-13=4, 14-20=1, 21-27=0,
    28-34=-1, 35+=-4).
Computed from `stats_player_week`'s individual defender stat columns
(def_sacks/def_interceptions/etc.), summed by team, PLUS the opponent's real
final score for that game (from nfldata's games.csv -- `stats_player_week`
has no score column). Attributed to the OPPONENT team, same "points against"
direction as every other position here: a QB's points count against the
defense that allowed them, so a defense's points count against the offense
that allowed THEM to happen.

Usage:
    python fetch_nflverse_points_against.py --year 2026
    python fetch_nflverse_points_against.py --year 2025 --refresh
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

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "ff_draft_proj"))
import scoring  # noqa: E402  (ff_draft_proj/scoring.py, shared formulas)

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cached" / "nflverse"
OUTDIR = HERE / "data"

REL = "https://github.com/nflverse/nflverse-data/releases/download"
GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
UA = {"User-Agent": "Mozilla/5.0 (ff_points_against; personal use)"}

SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
POSITIONS = SKILL_POSITIONS + ("DST",)

# nflverse spells these differently than the site's existing tables/sheet.
TEAM_FIX = {"LA": "LAR"}

FORMATS = ("std", "half_ppr", "ppr")

BLOCKED_KICK_COLS = ("def_punt_blocks", "def_pat_blocks", "def_fg_blocks")

# Standard/ESPN-default points-allowed tier -- see module docstring.
POINTS_ALLOWED_TIERS = (
    (0, 10), (6, 7), (13, 4), (20, 1), (27, 0), (34, -1),
)


def points_allowed_tier(pts_allowed):
    for cutoff, value in POINTS_ALLOWED_TIERS:
        if pts_allowed <= cutoff:
            return value
    return -4


def fetch(url, dest, refresh=False):
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
            raise SystemExit(f"no data yet ({url} -> 404)")
        raise
    dest.write_bytes(data)
    print(f"  fetched  {dest.name}  ({len(data)/1024:.0f} KB)")
    time.sleep(0.2)
    return dest


def fetch_stats(year, refresh=False):
    url = f"{REL}/stats_player/stats_player_week_{year}.csv"
    return fetch(url, CACHE / f"stats_player_week_{year}.csv", refresh)


def fetch_games(refresh=False):
    return fetch(GAMES_URL, CACHE / "games.csv", refresh)


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def two_pt_points(row):
    """Not in ff_draft_proj/scoring.py (irrelevant for preseason projections),
    but real games have them and the legacy site data was scored with them."""
    return 2 * (num(row.get("passing_2pt_conversions"))
                + num(row.get("rushing_2pt_conversions"))
                + num(row.get("receiving_2pt_conversions")))


def stat_line(row):
    """Map nflverse's column names to the keys scoring.py expects."""
    return {
        "pass_yds": num(row.get("passing_yards")),
        "pass_td": num(row.get("passing_tds")),
        "pass_int": num(row.get("passing_interceptions")),
        "rush_yds": num(row.get("rushing_yards")),
        "rush_td": num(row.get("rushing_tds")),
        "rec": num(row.get("receptions")),
        "rec_yds": num(row.get("receiving_yards")),
        "rec_td": num(row.get("receiving_tds")),
        "fum": num(row.get("fumbles_lost_total")),
    }


def player_points(row, pos):
    """-> {"std": x, "half_ppr": x, "ppr": x} for one player-week."""
    stats = stat_line(row)
    bonus = two_pt_points(row)
    if pos == "QB":
        base = scoring.qb_points(stats) + bonus
        return {f: base for f in FORMATS}
    return {
        "std": scoring.std_points(stats) + bonus,
        "half_ppr": scoring.half_ppr_points(stats) + bonus,
        "ppr": scoring.ppr_points(stats) + bonus,
    }


def dst_stat_points(row):
    """Turnover/scoring-play points only -- the points-allowed tier is added
    separately (it's a team-game fact, not a per-player stat, and must only
    be counted once per team per week, not once per defender row)."""
    blocked = sum(num(row.get(c)) for c in BLOCKED_KICK_COLS)
    return (
        num(row.get("def_sacks")) * 1
        + num(row.get("def_interceptions")) * 2
        + num(row.get("fumble_recovery_opp")) * 2
        + num(row.get("def_safeties")) * 2
        + num(row.get("def_tds")) * 6
        + num(row.get("special_teams_tds")) * 6
        + blocked * 2
    )


def load_schedule(year, refresh=False):
    """-> (points_allowed, opponent_of), both keyed (team, week).
    points_allowed[(team, wk)] = the REAL final score of that team's
    opponent that game (nflverse's stats_player_week has no score column).
    Only completed games are included -- a future/unplayed week is simply
    absent, same as a bye."""
    path = fetch_games(refresh)
    points_allowed, opponent_of = {}, {}
    with open(path, encoding="utf-8") as fh:
        for g in csv.DictReader(fh):
            if g.get("season") != str(year) or g.get("game_type") != "REG":
                continue
            hs, aws = g.get("home_score"), g.get("away_score")
            if hs in (None, "", "NA") or aws in (None, "", "NA"):
                continue  # not played yet
            wk = int(num(g.get("week")))
            home = TEAM_FIX.get(g.get("home_team") or "", g.get("home_team") or "")
            away = TEAM_FIX.get(g.get("away_team") or "", g.get("away_team") or "")
            points_allowed[(home, wk)] = num(aws)
            points_allowed[(away, wk)] = num(hs)
            opponent_of[(home, wk)] = away
            opponent_of[(away, wk)] = home
    return points_allowed, opponent_of


def build(year, refresh=False):
    path = fetch_stats(year, refresh)
    points_allowed, opponent_of = load_schedule(year, refresh)

    # points[format][pos][team][week] = points allowed that week
    points = {f: {p: defaultdict(lambda: defaultdict(float)) for p in POSITIONS}
              for f in FORMATS}
    # every (team, week) the team actually played a REG game -- lets a bye
    # week come out blank instead of a false zero.
    played = defaultdict(set)
    # raw defensive/special-teams stat points, keyed (team, week) -- summed
    # across every defender's own row before the points-allowed tier (a
    # team-game fact, not a per-player one) gets added on separately below.
    dst_raw = defaultdict(lambda: defaultdict(float))

    with open(path, encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("season_type") != "REG":
                continue
            wk = int(num(row.get("week")))
            team = TEAM_FIX.get(row.get("team") or "", row.get("team") or "")
            if team:
                dst_raw[team][wk] += dst_stat_points(row)

            pos = row.get("position")
            if pos not in SKILL_POSITIONS:
                continue
            opp = row.get("opponent_team") or ""
            opp = TEAM_FIX.get(opp, opp)
            if not opp:
                continue
            played[opp].add(wk)
            pts = player_points(row, pos)
            for fmt in FORMATS:
                points[fmt][pos][opp][wk] += pts[fmt]

    for team, weeks_ in dst_raw.items():
        for wk, raw in weeks_.items():
            pa = points_allowed.get((team, wk))
            opp = opponent_of.get((team, wk))
            if pa is None or not opp:
                continue
            total = raw + points_allowed_tier(pa)
            played[opp].add(wk)
            for fmt in FORMATS:
                points[fmt]["DST"][opp][wk] += total

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
    dest = OUTDIR / f"points_against_{year}.json"
    dest.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return dest


def write_csv(payload, teams, year):
    """Long-form reference CSV -- every (format, position, team, week) row,
    easy to spot-check by hand or diff against the old FantasyData exports."""
    dest = OUTDIR / f"points_against_{year}.csv"
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
                     help="re-download stats_player_week/games even if "
                          "cached -- the stats file is one-per-season and "
                          "overwritten in place, so pass this on every real "
                          "weekly run (same trap documented in "
                          "ff_utilization)")
    args = ap.parse_args()

    print(f"points against -- {args.year}\n")
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
