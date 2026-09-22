#!/usr/bin/env python3
"""
Add one week's goal-line (inside-the-5) run/pass attempts and TDs to the
running season totals in the "Goal-Line Guide" Google Sheet.

Sheet: https://docs.google.com/spreadsheets/d/1q-aklbeGgJ5gC0rdLbSpK7sdemIKEoao37LbooROfkI
"Off" tab tracks each team's own offense; "Def" tab tracks what each team's
defense has allowed. Both have the same layout, one row per team (grouped
by division with a blank spacer row every 4 teams):

    A: Team | B: GL Run Att | C: TD | D: % (formula, untouched)
    (E blank) | F: GL Pass Att | G: TD | H: % (formula, untouched)

This is additive, not a recompute: it reads whatever is already in B/C/F/G,
adds new plays on top, and writes the new season-to-date total back.

Safe to run MORE THAN ONCE for the same week -- de-duped per GAME (nflverse
`game_id`, e.g. "2026_02_NYG_LAR"), tracked in data/counted_games.json
(committed to the repo so it persists across CI runs). This is what makes
the Monday/Tuesday split possible: a Monday-afternoon run picks up
whichever of that week's games are done by then (everything except Monday
Night Football, typically), marks those game_ids counted, and a Tuesday
run of the exact same command only finds the newly-available MNF game as
new -- no weekday-specific logic needed, no double-counting risk from
running it twice.

Goal-line definition, reverse-engineered from the sheet's own existing
numbers (nflverse play-by-play, weeks 1-2 of 2026): a play with
`yardline_100` between 0 and 5 inclusive (line of scrimmage inside the
opponent's 5), excluding two-point conversion attempts. That matched 30 of
32 teams exactly on both tabs; the handful of misses traced to a single
ambiguous aborted-snap play that nflverse flags as a rush attempt but the
sheet's own hand-tracking apparently didn't count that way -- not a
methodology error, just an edge case not worth chasing.

Usage:
    python update_weekly.py --week 2                    # 2026, writes
    python update_weekly.py --week 2 --dry-run           # preview only
    python update_weekly.py --week 2 --year 2025

Requires: google-api-python-client, google-auth
"""

import argparse
import csv
import json
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
CACHE = HERE / "cached"
MANIFEST_PATH = HERE / "data" / "counted_games.json"
SERVICE_ACCT = str(HERE.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
SHEET_ID = "1q-aklbeGgJ5gC0rdLbSpK7sdemIKEoao37LbooROfkI"

PBP_URL = "https://github.com/nflverse/nflverse-data/releases/download/pbp/play_by_play_{year}.csv"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# nflverse spells three teams differently than this sheet does.
TEAM_FIX = {"ARI": "ARZ", "WAS": "WSH", "LA": "LAR"}

csv.field_size_limit(10 ** 7)


def num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def fetch_pbp(year):
    """Always re-downloads -- this is a weekly-fresh stat, and a cached pbp
    file from earlier in the week would silently omit the games that just
    finished (the exact bug documented in ff_utilization/CLAUDE.md)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    dest = CACHE / f"pbp_{year}.csv"
    print(f"Downloading play-by-play for {year}...", end="", flush=True)
    req = urllib.request.Request(PBP_URL.format(year=year), headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=300) as r:
        data = r.read()
    dest.write_bytes(data)
    print(f" {len(data) / 1024 / 1024:.1f} MB")
    return dest


def load_counted():
    if not MANIFEST_PATH.exists():
        return set()
    return set(json.loads(MANIFEST_PATH.read_text(encoding="utf-8")))


def save_counted(game_ids):
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(sorted(game_ids), indent=2) + "\n", encoding="utf-8")


def compute_week(pbp_path, year, week, already_counted=frozenset(), force_all=False):
    """-> (stats, new_game_ids, skipped_game_ids)

    stats: {team: {off_run_att, off_run_td, off_pass_att, off_pass_td,
                   def_run_att, def_run_td, def_pass_att, def_pass_td}}
    Only plays from games NOT in `already_counted` are included, unless
    force_all=True (used by --replace, which recomputes the whole week
    regardless of what's already been counted).
    """
    stats = {}
    week_game_ids = set()
    new_game_ids = set()
    skipped_game_ids = set()

    def bump(team, key):
        stats.setdefault(team, {}).setdefault(key, 0)
        stats[team][key] += 1

    n_plays = 0
    with open(pbp_path, encoding="utf-8") as fh:
        for p in csv.DictReader(fh):
            if p.get("season_type") != "REG":
                continue
            if int(num(p.get("week"))) != week:
                continue
            gid = p.get("game_id")
            week_game_ids.add(gid)
            if not force_all and gid in already_counted:
                skipped_game_ids.add(gid)
                continue
            new_game_ids.add(gid)

            if p.get("two_point_attempt") == "1":
                continue
            y100 = num(p.get("yardline_100"), -1)
            if not (0 <= y100 <= 5):
                continue

            oteam = TEAM_FIX.get(p.get("posteam") or "", p.get("posteam") or "")
            dteam = TEAM_FIX.get(p.get("defteam") or "", p.get("defteam") or "")

            if p.get("rush_attempt") == "1":
                n_plays += 1
                if oteam:
                    bump(oteam, "off_run_att")
                    if p.get("rush_touchdown") == "1":
                        bump(oteam, "off_run_td")
                if dteam:
                    bump(dteam, "def_run_att")
                    if p.get("rush_touchdown") == "1":
                        bump(dteam, "def_run_td")

            if p.get("pass_attempt") == "1":
                n_plays += 1
                if oteam:
                    bump(oteam, "off_pass_att")
                    if p.get("pass_touchdown") == "1":
                        bump(oteam, "off_pass_td")
                if dteam:
                    bump(dteam, "def_pass_att")
                    if p.get("pass_touchdown") == "1":
                        bump(dteam, "def_pass_td")

    print(f"  week {week}: {len(week_game_ids)} games in pbp so far "
          f"({len(skipped_game_ids)} already counted, {len(new_game_ids)} new); "
          f"{n_plays} goal-line plays in the new games")
    return stats, new_game_ids, skipped_game_ids


def sheets_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def cell_int(v):
    """Sheet stores a zero count as a blank cell, not '0' -- match that
    convention so a fresh row looks the same as one that's always been 0."""
    try:
        return int(num(v))
    except (TypeError, ValueError):
        return 0


def update_tab(service, tab, stats, off_or_def, dry_run, replace=False):
    """off_or_def: 'off' reads/writes stats[team]['off_*']; 'def' reads/writes
    stats[team]['def_*'], but BOTH write to the same B/C/F/G columns --
    'Off' and 'Def' are separate sheet tabs, each keyed off its own half of
    `stats`.

    replace=True overwrites the season total with this run's numbers
    instead of adding to what's already there -- for backfilling/resetting
    a tab to a known-correct baseline (e.g. "set this to week 1 only"),
    as opposed to the normal weekly add-on-top usage.
    """
    prefix = off_or_def
    existing = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"{tab}!A1:H41"
    ).execute().get("values", [])

    data = []
    print(f"\n{tab} tab:")
    for i, row in enumerate(existing[1:], start=2):  # skip header row
        if not row or not row[0].strip():
            continue
        team = row[0].strip()
        s = stats.get(team, {})
        d_run_att = s.get(f"{prefix}_run_att", 0)
        d_run_td = s.get(f"{prefix}_run_td", 0)
        d_pass_att = s.get(f"{prefix}_pass_att", 0)
        d_pass_td = s.get(f"{prefix}_pass_td", 0)

        old_run_att = cell_int(row[1]) if len(row) > 1 else 0
        old_run_td = cell_int(row[2]) if len(row) > 2 else 0
        old_pass_att = cell_int(row[5]) if len(row) > 5 else 0
        old_pass_td = cell_int(row[6]) if len(row) > 6 else 0

        if replace:
            new_run_att, new_run_td = d_run_att, d_run_td
            new_pass_att, new_pass_td = d_pass_att, d_pass_td
        else:
            new_run_att = old_run_att + d_run_att
            new_run_td = old_run_td + d_run_td
            new_pass_att = old_pass_att + d_pass_att
            new_pass_td = old_pass_td + d_pass_td

        if replace or d_run_att or d_run_td or d_pass_att or d_pass_td:
            arrow = "=" if replace else "+"
            print(f"  {team:<4} run {old_run_att:>2}/{old_run_td:>2} "
                  f"{arrow}{d_run_att}/{d_run_td} -> {new_run_att}/{new_run_td}   "
                  f"pass {old_pass_att:>2}/{old_pass_td:>2} "
                  f"{arrow}{d_pass_att}/{d_pass_td} -> {new_pass_att}/{new_pass_td}")

        data.append({
            "range": f"{tab}!B{i}:C{i}",
            "values": [[new_run_att or "", new_run_td or ""]],
        })
        data.append({
            "range": f"{tab}!F{i}:G{i}",
            "values": [[new_pass_att or "", new_pass_td or ""]],
        })

    if dry_run:
        print(f"  (dry run -- {tab} tab not written)")
        return

    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID,
        body={"valueInputOption": "RAW", "data": data},
    ).execute()
    print(f"  wrote {tab} tab.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--week", type=int, required=True, help="the week to add/catch up")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--dry-run", action="store_true", help="preview the additions, don't write to the sheet")
    ap.add_argument("--replace", action="store_true",
                     help="set the season total to exactly this week's numbers instead of "
                          "adding to what's already there -- for backfilling/resetting a tab "
                          "to a known baseline (e.g. 'make this week 1 only'), not normal weekly use")
    args = ap.parse_args()

    pbp_path = fetch_pbp(args.year)
    counted = load_counted()
    stats, new_game_ids, skipped = compute_week(
        pbp_path, args.year, args.week, already_counted=counted, force_all=args.replace
    )

    if not new_game_ids:
        print(f"No new games for {args.year} week {args.week} -- nothing to add "
              f"(already counted, or that week hasn't started yet).", file=sys.stderr)
        return 0 if skipped else 1

    service = sheets_service()
    update_tab(service, "Off", stats, "off", args.dry_run, args.replace)
    update_tab(service, "Def", stats, "def", args.dry_run, args.replace)

    if not args.dry_run:
        save_counted(counted | new_game_ids)
        print(f"\nManifest updated: {len(new_game_ids)} game(s) newly marked counted "
              f"({', '.join(sorted(new_game_ids))}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
