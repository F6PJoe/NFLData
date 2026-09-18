#!/usr/bin/env python3
"""
Push this week's implied totals (from fetch_implied_totals.py) into the
Stream-O-Matic sheet's "Live" tab, column F ("Imp"): the OPPONENT's
implied-total rank (1 = highest implied total i.e. toughest offense to
face, 32 = lowest), looked up via the row's own Opp column (E) -- same
pattern as column I's Opp Off Rank.

Reads the existing Team/Opp columns rather than assuming row order, same
as push_ftn_dave_to_sheet.py.

Usage:
    python push_implied_totals_to_sheet.py [--csv implied_totals.csv]

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
    ap.add_argument("--csv", default="implied_totals.csv")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"[WARN] {args.csv} not found -- fetch_implied_totals.py likely failed. "
              "Leaving column F unchanged.")
        return

    with open(args.csv, newline="", encoding="utf-8") as f:
        implied_rows = list(csv.DictReader(f))

    rank_by_team = {normalize(r["Team"]): int(r["Rank"]) for r in implied_rows}

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    existing = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!B2:E").execute()
    live_rows = existing.get("values", [])

    f_col = []
    missing = []
    for row in live_rows:
        opp = normalize(row[3]) if len(row) > 3 and row[3] else None
        rank = rank_by_team.get(opp) if opp else None
        f_col.append([rank if rank is not None else ""])
        if opp and rank is None:
            missing.append(opp)

    n = len(live_rows)
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!F2", valueInputOption="RAW",
        body={"values": f_col},
    ).execute()

    print(f"Wrote {n} rows to '{TAB}'!F2:F{1 + n} (Opp implied-total rank).")
    if missing:
        print("Unmatched opponents (left blank):", ", ".join(missing))


if __name__ == "__main__":
    main()
