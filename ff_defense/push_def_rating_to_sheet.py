#!/usr/bin/env python3
"""
Push the self-owned defensive rating (from fetch_def_rating.py) into the
Stream-O-Matic sheet's "Live" tab, column G -- replacing FTN's Def DAVE.

Matched on the row's OWN team (column B), unlike column H which matches
on the opponent. Rank is written as-is because fetch_def_rating.py
already ranks in the sheet's direction: 32 = best defense, 1 = worst. No
33-minus-rank inversion here, which the DAVE version needed.

Usage:
    python push_def_rating_to_sheet.py [--csv def_rating.csv]

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="def_rating.csv")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"[WARN] {args.csv} not found -- fetch_def_rating.py likely failed. "
              "Leaving column G unchanged.")
        return

    with open(args.csv, newline="", encoding="utf-8") as f:
        rank_by_team = {normalize(r["Team"]): int(r["Rank"]) for r in csv.DictReader(f)}

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    existing = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!B2:B").execute()
    live_rows = existing.get("values", [])

    g_col, missing = [], []
    for row in live_rows:
        team = normalize(row[0]) if row and row[0] else None
        rank = rank_by_team.get(team) if team else None
        g_col.append([rank if rank is not None else ""])
        if team and rank is None:
            missing.append(team)

    n = len(live_rows)
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!G2", valueInputOption="RAW",
        body={"values": g_col},
    ).execute()

    print(f"Wrote {n} rows to '{TAB}'!G2:G{1 + n} (own defense rating rank, 32 = best).")
    if missing:
        print("Unmatched teams (left blank):", ", ".join(sorted(set(missing))))


if __name__ == "__main__":
    main()
