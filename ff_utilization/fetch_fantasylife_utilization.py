#!/usr/bin/env python3
"""
Pull Fantasy Life's Utilization Report (PFF-charted usage data) for RB/WR/TE,
both season totals and per-week game logs, into CSV + compact JSON.

Why this exists
---------------
The Utilization Report is the fastest public source for route-participation
data -- routes run, route %, TPRR -- because PFF charts it directly. Nothing
free gets you routes in-season at all (nflverse's participation data is
post-season only; PFR's advanced receiving CSV in nflverse has no route
columns), and Sportradar's play-by-play can't produce it either (its
per-play `statistics` array only lists players who TOUCHED the ball, never
who else was on the field). See CLAUDE.md for the full source comparison.

The website's own Game Log page forces you to pick one team at a time from a
dropdown, with oversized player cards. Both endpoints below return the same
data as plain JSON, so this pulls the whole league at once instead.

Endpoints (both need the Firebase `bearer-token` header, same auth as
ff_draft_proj/fetch_fantasylife_projections.py):

  season totals -- ALL players in ONE call, no pagination, no team filter:
    GET /api/datatables/season-stats
        ?year=<yr>&weeksMin=<n>&weeksMax=<n>&scoringSystem=<uuid>

  weekly game log -- ONE TEAM PER CALL (no team= and team=ALL both fail to
  return rows), each player carrying a nested `log_items` array with one
  entry per week actually played:
    GET /api/datatables/game-logs
        ?year=<yr>&team=<ALIAS>&weeksMin=<n>&weeksMax=<n>&scoringSystem=<uuid>

A note on "raw" values, verified against the live payload
--------------------------------------------------------
Only `player_snaps_raw` and `routes_raw` come back as true raw counts.
Every other counting stat is delivered as `<stat>_per_game` + `<stat>_percent`
only. So:

  * weekly rows  -- `_per_game` IS that week's raw count (one game), used as-is
  * season rows  -- raw total = `_per_game` * `games_played`, rounded

`--verify` checks that reconstruction against the raw fields that DO exist.

Deliberately NOT collected (per site plan): utilization_score, ppr_fantasy,
ppr_fantasy_rank, ppg, ppg_rank (FL/PFF proprietary or scoring-dependent);
adot, air_yards_*, play_action_targets_*, third_fourth_targets_*; and the
QB-shaped fields that are always 0 for RB/WR/TE (drop_backs_*, pass_plays_*,
pass_completions_percent, sacks_*, scrambles_*, qb_adot, ypa).

Setup: FANTASYLIFE_EMAIL / FANTASYLIFE_PASSWORD / FANTASYLIFE_FIREBASE_API_KEY
in ff_draft_proj/.env (already there for the projections fetcher), or this
project's own .env, or the environment.

Usage:
    python fetch_fantasylife_utilization.py --year 2025 --weeks 1-2
    python fetch_fantasylife_utilization.py --year 2025          # full season
    python fetch_fantasylife_utilization.py --year 2025 --weeks 1-2 --verify
    python fetch_fantasylife_utilization.py --year 2025 --season-only

Requires: requests
"""

import argparse
import collections
import csv
import json
import os
import statistics
import sys
import time
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
ENV_PATHS = [HERE / ".env", HERE.parent / "ff_draft_proj" / ".env"]

BASE = "https://www.fantasylife.com"
SEASON_URL = f"{BASE}/api/datatables/season-stats"
GAMELOG_URL = f"{BASE}/api/datatables/game-logs"

# FL's own default scoring system id (from the site's own request). Only
# affects the fantasy-points fields, which this script drops entirely --
# kept because the endpoints require the parameter.
SCORING_SYSTEM = "bdc25c88-4be3-49bf-989c-b6af3e6071ec"

POSITIONS = ("RB", "WR", "TE")

TEAMS = [
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAX", "KC", "LA", "LAC", "LV", "MIA",
    "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF", "TB",
    "TEN", "WAS",
]

THROTTLE = 0.4  # polite pause between the 32 per-team game-log calls

# (output_name, per_game_or_raw_key, percent_key)
# `raw_key` ending in `_raw` is a true raw count; anything else is per-game
# and gets multiplied by games_played for season rows.
STATS = [
    ("snaps",          "player_snaps_raw",                "snaps_percent"),
    ("routes",         "routes_raw",                      "routes_percent"),
    ("rush_att",       "designed_rush_attempts_per_game", "designed_rush_attempts_percent"),
    ("targets",        "targets_per_game",                "targets_percent"),
    ("catchable_tgts", "catchable_targets_per_game",      "catchable_targets_percent"),
    ("ez_tgts",        "endzone_targets_per_game",        "endzone_targets_percent"),
    ("inside5_rush",   "inside_five_rush_per_game",       "inside_five_rush_percent"),
    ("sdd_snaps",      "player_sdd_snaps_per_game",       "player_sdd_snaps_percent"),
    ("ldd_snaps",      "player_ldd_snaps_per_game",       "player_ldd_snaps_percent"),
    ("two_min_snaps",  "two_min_player_snaps_per_game",   "two_min_player_snaps_percent"),
]

# Team-level denominators -- pulled and stored (cheap, and they let any
# custom week range be re-aggregated correctly later), may not be displayed.
TEAM_FIELDS = [
    ("team_sdd_snaps",        "team_sdd_snaps"),
    ("team_ldd_snaps",        "team_ldd_snaps"),
    ("team_ez_tgts",          "team_endzone_targets"),
    ("team_third_fourth_pass", "team_third_fourth_pass"),
    ("team_inside5_rush",     "inside_five_rush_team"),
]


def load_env():
    for path in ENV_PATHS:
        if not path.exists():
            continue
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())


def get_token():
    """Sign in via Google Identity Toolkit -- FL's auth is Firebase, and the
    site's own login is a Next.js server action with no usable REST endpoint,
    so we authenticate against Firebase directly (same as the projections
    fetcher in ff_draft_proj)."""
    try:
        api_key = os.environ["FANTASYLIFE_FIREBASE_API_KEY"]
        email = os.environ["FANTASYLIFE_EMAIL"]
        password = os.environ["FANTASYLIFE_PASSWORD"]
    except KeyError as exc:
        sys.exit(
            f"Missing {exc.args[0]}. Add FANTASYLIFE_EMAIL / FANTASYLIFE_PASSWORD / "
            f"FANTASYLIFE_FIREBASE_API_KEY to one of: "
            + ", ".join(str(p) for p in ENV_PATHS)
        )
    resp = requests.post(
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
        f"?key={api_key}",
        json={"email": email, "password": password, "returnSecureToken": True},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["idToken"]


def session_for(token):
    sess = requests.Session()
    sess.headers.update({
        # A real UA matters here: fantasysixpack.net's own Cloudflare/SiteGround
        # layers block the default python-requests UA outright (see
        # ff_auction_values/CLAUDE.md rounds 9-10). Same courtesy here.
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "bearer-token": token,
    })
    return sess


def num(value):
    if value in (None, ""):
        return 0.0
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def pct(value):
    """FL sends shares as 0-1 floats; store as a 1-decimal percentage."""
    return round(num(value) * 100, 1)


def build_row(stat, name, team, position, week, games):
    """Flatten one FL stat blob into our column set.

    `games` is 1 for a weekly row (so `_per_game` == that week's raw count)
    and games_played for a season row.
    """
    row = {
        # FL's two endpoints spell the same player differently -- `season-stats`
        # sends a single `player_name` WITH suffixes and punctuation
        # ("Brian Thomas Jr.", "D.K. Metcalf") while `game-logs` sends
        # firstName/lastName WITHOUT them ("Brian Thomas", "DK Metcalf").
        # Joining on name loses ~10% of players, so carry the id and join on it.
        "player_id": stat.get("player_id") or "",
        "player": name,
        "team": team,
        "pos": position,
        "season": int(num(stat.get("season"))),
    }
    if week is None:
        row["games"] = games
    else:
        row["week"] = week

    for out_name, raw_key, pct_key in STATS:
        raw_val = num(stat.get(raw_key))
        if not raw_key.endswith("_raw"):
            raw_val *= games
        row[out_name] = int(round(raw_val))
        row[f"{out_name}_pct"] = pct(stat.get(pct_key))

    row["tprr"] = round(num(stat.get("tprr")) * 100, 1)

    for out_name, src_key in TEAM_FIELDS:
        row[out_name] = int(round(num(stat.get(src_key))))
    return row


def columns(weekly):
    cols = ["player_id", "player", "team", "pos", "season"]
    cols.append("week" if weekly else "games")
    for out_name, _, _ in STATS:
        cols.extend([out_name, f"{out_name}_pct"])
    cols.append("tprr")
    cols.extend(name for name, _ in TEAM_FIELDS)
    if weekly:
        cols.extend(name for name, _, _ in DERIVED_TEAM_TOTALS)
    return cols


def fetch_season(sess, year, wmin, wmax):
    params = {
        "year": year, "weeksMin": wmin, "weeksMax": wmax,
        "scoringSystem": SCORING_SYSTEM,
    }
    resp = sess.get(SEASON_URL, params=params, timeout=60)
    resp.raise_for_status()
    players = resp.json()["data"]["players"] or []

    rows = []
    for p in players:
        if p.get("position") not in POSITIONS:
            continue
        athlete = p.get("athlete") or {}
        team = ((athlete.get("team") or {}).get("alias")) or ""
        games = int(num(p.get("games_played")))
        if games <= 0:
            continue
        rows.append(build_row(p, p.get("player_name", ""), team,
                              p["position"], None, games))
    rows.sort(key=lambda r: -r["snaps"])
    return rows


FINGERPRINT_FIELDS = ("team_sdd_snaps", "team_ldd_snaps", "team_ez_tgts",
                      "team_third_fourth_pass")


def _fingerprint(row):
    """Identify the team a player ACTUALLY played for in a given week.

    The four team_* denominators are that week's real team totals, and
    snaps / snaps_pct recovers the team's total offensive snaps -- together
    unique enough to name the team (verified: the 4 team_* fields alone
    collided for one team in one week; adding implied snaps made all 32
    distinct in every week tested).
    """
    snaps, pct_ = row["snaps"], row["snaps_pct"]
    implied = round(snaps / (pct_ / 100)) if (pct_ and snaps) else -1
    return tuple(row[f] for f in FINGERPRINT_FIELDS) + (implied,)


def reattribute_teams(rows):
    """Fix the team label on mid-season movers.

    `game-logs` is scoped to a player's CURRENT roster and its `log_items`
    carry no team field of their own, so a traded player's earlier weeks come
    back under his NEW team -- e.g. Rashid Shaheed's pre-trade weeks appear
    under SEA though he played them for NO. FL's own UI has the same flaw.
    Roughly 3% of player-weeks in a full season are affected, and they're
    disproportionately the players worth writing about.

    Each row still carries its real team's weekly numbers, so the true team is
    recoverable: take the modal fingerprint of every team-week (the majority of
    players on a team are correctly labelled) and re-attribute anyone whose own
    fingerprint matches a different team. Skips any week where fingerprints
    aren't unique rather than guessing.
    """
    by_week = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in rows:
        by_week[row["week"]][row["team"]].append(_fingerprint(row))

    moved = 0
    for week in sorted(by_week):
        try:
            modes = {team: statistics.mode(fps)
                     for team, fps in by_week[week].items()}
        except statistics.StatisticsError:
            continue
        if len(set(modes.values())) != len(modes):
            print(f"  week {week}: fingerprint collision -- "
                  f"leaving team labels as-is")
            continue
        lookup = {fp: team for team, fp in modes.items()}
        for row in rows:
            if row["week"] != week:
                continue
            true_team = lookup.get(_fingerprint(row))
            if true_team and true_team != row["team"]:
                row["team"] = true_team
                moved += 1
    return moved


# (output_name, raw_field, percent_field) -- team totals FL never sends, but
# which are exactly recoverable as raw / pct.
DERIVED_TEAM_TOTALS = [
    ("team_snaps",         "snaps",         "snaps_pct"),
    ("team_routes",        "routes",        "routes_pct"),
    ("team_targets",       "targets",       "targets_pct"),
    ("team_rush_att",      "rush_att",      "rush_att_pct"),
    ("team_two_min_snaps", "two_min_snaps", "two_min_snaps_pct"),
]


def add_derived_team_totals(rows):
    """Store the team denominators for snaps/routes/targets/rush attempts.

    FL sends these four as a player share with no team total attached (unlike
    sdd/ldd/ez/inside5, which come with explicit `team_*` fields). But
    `raw / pct` recovers the total, and once teams are correctly attributed it
    agrees across every player on a team-week -- measured on 2025 wk1-2:
    routes 64/64, targets 64/64, rush att 45/45 team-weeks consistent within
    1.5, snaps 57/64 (worst spread 1.9, pure rounding).

    Storing them is what lets the SEASON view be recomputed client-side for any
    week range -- sum the raw, sum the team totals, divide -- instead of
    needing a separate pre-aggregated file per range. Median across players is
    used rather than one player's value so a single rounded share can't skew it.
    """
    groups = collections.defaultdict(lambda: collections.defaultdict(list))
    for row in rows:
        key = (row["team"], row["week"])
        for out_name, raw_field, pct_field in DERIVED_TEAM_TOTALS:
            raw, pct_ = row[raw_field], row[pct_field]
            if raw and pct_:
                groups[key][out_name].append(raw / (pct_ / 100))

    for row in rows:
        found = groups.get((row["team"], row["week"]), {})
        for out_name, _, _ in DERIVED_TEAM_TOTALS:
            vals = found.get(out_name)
            row[out_name] = int(round(statistics.median(vals))) if vals else 0


def fetch_weekly(sess, year, wmin, wmax, name_map=None):
    """`name_map` is {player_id: display_name} from the season feed, used to
    give weekly rows the fuller name spelling (suffixes and punctuation) that
    only `season-stats` returns."""
    name_map = name_map or {}
    rows = []
    for i, team in enumerate(TEAMS, 1):
        params = {
            "year": year, "team": team, "weeksMin": wmin, "weeksMax": wmax,
            "scoringSystem": SCORING_SYSTEM,
        }
        resp = sess.get(GAMELOG_URL, params=params, timeout=60)
        resp.raise_for_status()
        items = resp.json()["data"].get("items") or []

        for item in items:
            player = item.get("player") or {}
            position = player.get("position")
            if position not in POSITIONS:
                continue
            name = f"{player.get('firstName','')} {player.get('lastName','')}".strip()
            alias = ((player.get("team") or {}).get("alias")) or team
            for log in item.get("log_items") or []:
                week = int(num(log.get("week")))
                if not wmin <= week <= wmax:
                    continue
                row = build_row(log, name, alias, position, week, 1)
                row["player"] = name_map.get(row["player_id"], name)
                rows.append(row)

        print(f"  [{i:2}/32] {team:<3}  running total: {len(rows)} player-week rows")
        if i < len(TEAMS):
            time.sleep(THROTTLE)

    moved = reattribute_teams(rows)
    print(f"  re-attributed {moved} player-week rows to the team actually "
          f"played for (mid-season movers)")
    add_derived_team_totals(rows)

    rows.sort(key=lambda r: (r["week"], -r["snaps"]))
    return rows


def write_csv(path, rows, cols):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=cols)
        writer.writeheader()
        writer.writerows(rows)


def write_json(path, rows, cols):
    """Columnar array-of-arrays, not array-of-objects: the key names appear
    once in `cols` instead of being repeated on every row. Roughly a 3x size
    reduction on this dataset, which matters because the browser downloads
    this file."""
    payload = {"cols": cols, "rows": [[r.get(c) for c in cols] for r in rows]}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))


def verify(sess, year, wmin, wmax, season_rows):
    """Cross-check the per_game * games reconstruction against the two fields
    FL gives us raw, and against summed weekly rows."""
    print("\n=== verification ===")
    by_name = {r["player"]: r for r in season_rows}

    resp = sess.get(SEASON_URL, params={
        "year": year, "weeksMin": wmin, "weeksMax": wmax,
        "scoringSystem": SCORING_SYSTEM,
    }, timeout=60)
    resp.raise_for_status()
    raw_players = {p["player_name"]: p for p in resp.json()["data"]["players"] or []}

    checked = mismatch = 0
    for name, row in list(by_name.items()):
        src = raw_players.get(name)
        if not src:
            continue
        # snaps/routes came straight from *_raw -- confirm we didn't mangle them
        for out_name, raw_key in (("snaps", "player_snaps_raw"), ("routes", "routes_raw")):
            checked += 1
            if row[out_name] != int(round(num(src.get(raw_key)))):
                mismatch += 1
                print(f"  MISMATCH {name} {out_name}: {row[out_name]} != {src.get(raw_key)}")
    print(f"raw-field passthrough: {checked} checks, {mismatch} mismatches")

    # snaps has both a raw total and a per_game+games form -- if the
    # reconstruction is sound, they agree.
    recon_checked = recon_off = 0
    for name, src in raw_players.items():
        if src.get("position") not in POSITIONS:
            continue
        games = int(num(src.get("games_played")))
        if games <= 0:
            continue
        recon_checked += 1
        recon = round(num(src.get("snaps_per_game")) * games)
        actual = int(round(num(src.get("player_snaps_raw"))))
        if abs(recon - actual) > 1:  # allow 1 for FL's own rounding
            recon_off += 1
            if recon_off <= 5:
                print(f"  recon off: {name} snaps {recon} vs raw {actual}")
    print(f"per_game*games reconstruction: {recon_checked} players, "
          f"{recon_off} off by >1")


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--weeks", default="1-22",
                    help="week range, e.g. '1-2', '5', '1-22' (default 1-22)")
    ap.add_argument("--season-only", action="store_true")
    ap.add_argument("--weekly-only", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--outdir", default=str(HERE / "data"))
    args = ap.parse_args()

    if "-" in args.weeks:
        wmin, wmax = (int(x) for x in args.weeks.split("-", 1))
    else:
        wmin = wmax = int(args.weeks)

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    load_env()
    sess = session_for(get_token())
    print(f"Fantasy Life Utilization Report -- {args.year}, weeks {wmin}-{wmax}\n")

    suffix = f"{args.year}_wk{wmin}-{wmax}"

    # Always pull season totals, even with --weekly-only: it's a single call and
    # it's the only source of the fuller name spellings the weekly feed lacks.
    print("Season totals (1 call, all teams)...")
    season_rows = fetch_season(sess, args.year, wmin, wmax)
    name_map = {r["player_id"]: r["player"] for r in season_rows if r["player_id"]}

    if not args.weekly_only:
        rows = season_rows
        cols = columns(weekly=False)
        csv_path = outdir / f"utilization_season_{suffix}.csv"
        json_path = outdir / f"utilization_season_{suffix}.json"
        write_csv(csv_path, rows, cols)
        write_json(json_path, rows, cols)
        print(f"  {len(rows)} players -> {csv_path.name} "
              f"({csv_path.stat().st_size/1024:.0f} KB), "
              f"{json_path.name} ({json_path.stat().st_size/1024:.0f} KB)")
        if args.verify:
            verify(sess, args.year, wmin, wmax, rows)

    if not args.season_only:
        print("\nWeekly game logs (32 calls, one per team)...")
        rows = fetch_weekly(sess, args.year, wmin, wmax, name_map)
        cols = columns(weekly=True)
        csv_path = outdir / f"utilization_weekly_{suffix}.csv"
        json_path = outdir / f"utilization_weekly_{suffix}.json"
        write_csv(csv_path, rows, cols)
        write_json(json_path, rows, cols)
        print(f"  {len(rows)} player-week rows -> {csv_path.name} "
              f"({csv_path.stat().st_size/1024:.0f} KB), "
              f"{json_path.name} ({json_path.stat().st_size/1024:.0f} KB)")

        # The site fetches a fixed filename, so also write an undated copy.
        # THIS is the file to upload -- same name every week, so the embed URL
        # never changes and there's nothing to rename by hand.
        upload = outdir / "utilization_weekly.json"
        write_json(upload, rows, cols)
        print(f"\n  UPLOAD THIS -> {upload}")
        print(f"  to /wp-content/plugins/s2member-files/{upload.name}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001 - top-level CLI guard
        print(f"FAILED: {exc}", file=sys.stderr)
        sys.exit(1)
