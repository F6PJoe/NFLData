#!/usr/bin/env python3
"""
Push opponent offensive EPA ranks (from fetch_nflverse_epa.py) into the
Stream-O-Matic sheet's "Live" tab, column H -- replacing FTN's DAVE as
the source for "how good is the offense this defense is facing."

Rank is used AS-IS, no inversion: 1 = best offense, 32 = worst, so a high
number means a weak opposing offense (a good matchup). That's the same
convention the FTN Off Rank used, so nothing downstream changes.

Reads the sheet's existing Team/Opp columns rather than assuming row
order, same as every other push here.

NOTE: this writes ONLY column H. Column G (the defense's own quality) is
deliberately NOT the defensive half of this same file -- backtesting
showed defensive EPA alone is a poor standalone rating (corr 0.118 at 100
plays vs offense's 0.402). It's built separately in fetch_def_rating.py,
which blends EPA allowed with success rate allowed and shrinks toward
Joe's preseason ranks.

Usage:
    python push_nflverse_epa_to_sheet.py [--csv nflverse_epa.csv]

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
    ap.add_argument("--csv", default="nflverse_epa.csv")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"[WARN] {args.csv} not found -- fetch_nflverse_epa.py likely failed. "
              "Leaving column H unchanged.")
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

    existing = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!B2:E").execute()
    live_rows = existing.get("values", [])

    h_col, missing = [], []
    for row in live_rows:
        opp = normalize(row[3]) if len(row) > 3 and row[3] else None
        rank = rank_by_team.get(opp) if opp else None
        h_col.append([rank if rank is not None else ""])
        if opp and rank is None:
            missing.append(opp)

    n = len(live_rows)
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!H2", valueInputOption="RAW",
        body={"values": h_col},
    ).execute()

    print(f"Wrote {n} rows to '{TAB}'!H2:H{1 + n} (Opp offensive EPA rank).")
    if missing:
        print("Unmatched opponents (left blank):", ", ".join(sorted(set(missing))))


if __name__ == "__main__":
    main()
