#!/usr/bin/env python3
"""
Push Yahoo D/ST Roster %, Start %, and weekly projection (from
fetch_yahoo_def.py) into the Stream-O-Matic sheet's "Live" tab: columns C
(Rost%), D (Start%), and L (Proj), matched to the row's OWN team in column
B (not the opponent, unlike the DAVE/implied-total pushes).

Roster%/Start% are written as real fractions (7 -> 0.07) with a "0%"
number format applied, so the sheet actually renders "7%" instead of the
plain number 7 -- Joe's data never has fractional percentage points, so
no decimals are shown.

Usage:
    python push_yahoo_def_to_sheet.py [--csv yahoo_def.csv]

Requires: google-api-python-client, google-auth
"""

import argparse
import csv
import os
from pathlib import Path

from team_names import normalize

SHEET_ID = "1lTRoatl-YQHlv78YeisG7eFyz2xqaConGUoPo4medpQ"
SERVICE_ACCT = str(Path(__file__).parent.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
TAB = "Live"
TAB_GID = 0  # confirmed via spreadsheets.get -- Live is the first sheet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="yahoo_def.csv")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"[WARN] {args.csv} not found -- fetch_yahoo_def.py likely failed. "
              "Leaving columns C/D/L unchanged.")
        return

    with open(args.csv, newline="", encoding="utf-8") as f:
        yahoo_rows = list(csv.DictReader(f))

    def to_float(v):
        return float(v) if v not in (None, "") else None

    roster_by_team = {normalize(r["Team"]): to_float(r["RosterPct"]) for r in yahoo_rows}
    start_by_team = {normalize(r["Team"]): to_float(r["StartPct"]) for r in yahoo_rows}
    proj_by_team = {normalize(r["Team"]): to_float(r["Projection"]) for r in yahoo_rows}

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    existing = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!B2:B").execute()
    live_teams = [row[0] if row else None for row in existing.get("values", [])]

    c_col, d_col, l_col = [], [], []
    missing = []
    for team in live_teams:
        abbr = normalize(team) if team else None
        roster = roster_by_team.get(abbr) if abbr else None
        start = start_by_team.get(abbr) if abbr else None
        proj = proj_by_team.get(abbr) if abbr else None
        c_col.append([roster / 100 if roster is not None else ""])
        d_col.append([start / 100 if start is not None else ""])
        l_col.append([proj if proj is not None else ""])
        if abbr and roster is None:
            missing.append(abbr)

    n = len(live_teams)
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!C2", valueInputOption="RAW",
        body={"values": c_col},
    ).execute()
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!D2", valueInputOption="RAW",
        body={"values": d_col},
    ).execute()
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!L2", valueInputOption="RAW",
        body={"values": l_col},
    ).execute()

    # Whole-percent display ("7%", no decimals) for the Rost%/Start% columns.
    def percent_format_request(col_index):
        return {
            "repeatCell": {
                "range": {
                    "sheetId": TAB_GID, "startRowIndex": 1, "endRowIndex": 1 + n,
                    "startColumnIndex": col_index, "endColumnIndex": col_index + 1,
                },
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "PERCENT", "pattern": "0%"}}},
                "fields": "userEnteredFormat.numberFormat",
            }
        }

    sheet.batchUpdate(spreadsheetId=SHEET_ID, body={
        "requests": [percent_format_request(2), percent_format_request(3)],  # C, D
    }).execute()

    print(f"Wrote {n} rows to '{TAB}'!C2:C{1 + n} (Rost%), !D2:D{1 + n} (Start%), "
          f"and !L2:L{1 + n} (Proj).")
    if missing:
        print("Unmatched (left blank):", ", ".join(missing))


if __name__ == "__main__":
    main()
