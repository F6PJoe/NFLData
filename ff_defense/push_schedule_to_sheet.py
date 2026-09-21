#!/usr/bin/env python3
"""
Push schedule.csv (from fetch_schedule.py) into the Stream-O-Matic
sheet's "Live" tab: team nickname in column B, opponent in column E
("@ABBR" when away, plain "ABBR" at home).

This replaces push_subvertadown_to_sheet.py. Subvertadown used to define
the team list AND supply a projection column; access to it is gone, so
the roster of teams now comes from nflverse's free schedules release --
a source that can't be revoked. Its old column was deleted outright, so
the tab is now A-K (everything from Def Rating rightward shifted one
column left).

Teams are updated IN PLACE -- each team keeps whatever row it already
sits on. That matters because every other column on this tab is a plain
value bound to its row, not a formula keyed off column B. Rewriting
column B in a different order silently detaches all of them from their
teams, which was a real bug once: 29 of 32 rows ended up attached to the
wrong team because this step wrote its own order while the rows were in
finalize's SCORE-sorted order. Reordering rows is finalize_live_sheet.py's
job -- its sortRange moves whole rows, so it can do it safely. This
script must not.

Usage:
    python push_schedule_to_sheet.py [--csv schedule.csv]

Requires: google-api-python-client, google-auth
"""

import argparse
import csv
import os
from pathlib import Path

from team_names import abbr_to_nickname, normalize

SHEET_ID = "1lTRoatl-YQHlv78YeisG7eFyz2xqaConGUoPo4medpQ"
SERVICE_ACCT = str(Path(__file__).parent.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
TAB = "Live"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="schedule.csv")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        # fetch_schedule.py is allowed to fail without stopping the rest of
        # the pipeline (see run_all.py). Leave B/E as whatever they already
        # were -- every other push still runs against that team list, which
        # is at worst last week's.
        print(f"[WARN] {args.csv} not found -- fetch_schedule.py likely failed. "
              "Leaving columns B/E unchanged.")
        return

    with open(args.csv, newline="", encoding="utf-8") as f:
        by_team = {normalize(r["Team"]): r for r in csv.DictReader(f)}

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    existing = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!B2:B").execute()
    existing_teams = [row[0] if row else "" for row in existing.get("values", [])]

    out_b, out_e = [], []
    bye_rows, seen = [], set()
    for i, team in enumerate(existing_teams):
        key = normalize(team) if team else None
        rec = by_team.get(key) if key else None
        if rec:
            out_b.append([abbr_to_nickname(rec["Team"])])
            out_e.append([rec["Opp"]])
            seen.add(key)
        else:
            # On a bye this week (or an already-blank row): blank the whole
            # row so its stale values can't score, then finalize's sort +
            # row-delete drops it off the bottom.
            out_b.append([""])
            out_e.append([""])
            bye_rows.append(i + 2)

    # Teams playing this week that aren't on the sheet yet (coming off a
    # bye, or a first-ever run) get appended; their other columns fill in
    # when those pushes run.
    added = 0
    for key, rec in by_team.items():
        if key not in seen:
            out_b.append([abbr_to_nickname(rec["Team"])])
            out_e.append([rec["Opp"]])
            added += 1

    if bye_rows:
        sheet.values().batchClear(
            spreadsheetId=SHEET_ID,
            body={"ranges": [f"{TAB}!B{r}:K{r}" for r in bye_rows]},
        ).execute()

    for col, values in (("B", out_b), ("E", out_e)):
        sheet.values().update(
            spreadsheetId=SHEET_ID, range=f"{TAB}!{col}2", valueInputOption="RAW",
            body={"values": values},
        ).execute()

    n = len(out_b)
    print(f"Updated {len(seen)} teams in place across '{TAB}'!B2:B{1 + n} "
          f"(+{added} added, {len(bye_rows)} cleared as bye/blank).")


if __name__ == "__main__":
    main()
