#!/usr/bin/env python3
"""
Write a week's matchups into its tab's Away (A) / Home (H) columns, sorted
by kickoff time -- the step that has to happen between duplicating a new
week tab (advance_week.py) and pulling odds for it (fill_week_odds.py),
since a freshly duplicated tab still shows the OLD week's teams in A/H and
fill_week_odds.py matches games by (away, home) pair, so it can't find
anything to update until the matchups themselves are current.

Uses nflverse's full-season schedule (already published for every week,
including ones that haven't happened yet), same source and same team-code
normalization (ARZ/WSH/JAX/LAR/LAC etc., matching this sheet's convention)
as fill_week_odds.py.

Row count handling: if this week has FEWER games than the tab currently has
template rows (a bye week), the extra rows are cleared entirely -- a
leftover matchup with no real game would otherwise sit there with stale
data and broken VLOOKUPs. If this week has MORE rows than the template
(shouldn't happen early season, but just in case), the last template row's
GL Grade formulas (C/D and J/K) get copied down to the new rows so the
VLOOKUPs exist there too, not just blank cells.

Usage:
    python set_week_matchups.py --week 3
    python set_week_matchups.py --week 3 --dry-run
"""

import argparse
import csv
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE_ACCT = str(HERE.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
SHEET_ID = "1q-aklbeGgJ5gC0rdLbSpK7sdemIKEoao37LbooROfkI"

GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

TEAM_FIX = {"ARI": "ARZ", "WAS": "WSH", "LA": "LAR"}


def fetch_games():
    req = urllib.request.Request(GAMES_URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        text = r.read().decode("utf-8")
    return list(csv.DictReader(text.splitlines()))


def week_schedule(games, year, week):
    """-> [(away, home)] sorted by kickoff (gameday, then gametime)."""
    rows = [g for g in games
            if g["season"] == str(year) and g["game_type"] == "REG" and int(g["week"]) == week]
    rows.sort(key=lambda g: (g["gameday"], g.get("gametime") or ""))
    return [(TEAM_FIX.get(g["away_team"], g["away_team"]),
              TEAM_FIX.get(g["home_team"], g["home_team"])) for g in rows]


def sheets_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def sheet_id_for(service, tab):
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    for s in meta["sheets"]:
        if s["properties"]["title"] == tab:
            return s["properties"]["sheetId"]
    return None


def last_data_row(service, tab):
    values = service.spreadsheets().values().get(
        spreadsheetId=SHEET_ID, range=f"{tab}!A2:A100"
    ).execute().get("values", [])
    last = 1
    for i, row in enumerate(values, start=2):
        if row and row[0].strip():
            last = i
    return last


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--tab", default=None, help="sheet tab name (default: 'W<week>')")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    tab = args.tab or f"W{args.week}"

    games = fetch_games()
    matchups = week_schedule(games, args.year, args.week)
    if not matchups:
        print(f"No {args.year} week {args.week} games in the nflverse schedule.", file=sys.stderr)
        return 1

    service = sheets_service()
    tab_id = sheet_id_for(service, tab)
    if tab_id is None:
        print(f"No tab named '{tab}' found -- run advance_week.py first.", file=sys.stderr)
        return 1

    template_last_row = last_data_row(service, tab)
    n_new = len(matchups)
    n_template = template_last_row - 1

    print(f"{tab}: {n_new} games this week, {n_template} template rows currently present.")
    for away, home in matchups:
        print(f"  {away} @ {home}")

    if args.dry_run:
        print("(dry run -- nothing written)")
        return 0

    requests_ = []
    data = [{"range": f"{tab}!A{i}", "values": [[away]]}
            for i, (away, home) in enumerate(matchups, start=2)]
    data += [{"range": f"{tab}!H{i}", "values": [[home]]}
             for i, (away, home) in enumerate(matchups, start=2)]

    if n_new > n_template and n_template >= 1:
        # Copy the last template row's GL Grade formulas down to the new rows.
        src_row = template_last_row
        requests_.append({
            "copyPaste": {
                "source": {"sheetId": tab_id, "startRowIndex": src_row - 1, "endRowIndex": src_row,
                           "startColumnIndex": 0, "endColumnIndex": 12},
                "destination": {"sheetId": tab_id, "startRowIndex": template_last_row,
                                "endRowIndex": 1 + n_new, "startColumnIndex": 0, "endColumnIndex": 12},
                "pasteType": "PASTE_FORMULA",
            }
        })
    elif n_new < n_template:
        # Bye-week-style trim: clear the now-unused rows entirely.
        requests_.append({
            "updateCells": {
                "range": {"sheetId": tab_id, "startRowIndex": 1 + n_new, "endRowIndex": template_last_row,
                          "startColumnIndex": 0, "endColumnIndex": 12},
                "fields": "userEnteredValue",
            }
        })

    if requests_:
        service.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": requests_}).execute()
    service.spreadsheets().values().batchUpdate(
        spreadsheetId=SHEET_ID, body={"valueInputOption": "RAW", "data": data}
    ).execute()

    print(f"Wrote {n_new} matchups to {tab}!A2:A{1 + n_new} / H2:H{1 + n_new}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
