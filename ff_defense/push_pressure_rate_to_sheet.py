#!/usr/bin/env python3
"""
Push pressure-rate-allowed ranks (from fetch_pressure_rate.py) into the
Stream-O-Matic sheet's "Live" tab, column J ("Pressure"): the OPPONENT's
rank (1 = allows the least pressure / best pass protection, 32 = allows
the most), looked up via the row's own Opp column (E) -- same pattern as
columns F and I.

Reads the existing Team/Opp columns rather than assuming row order, same
as the other pushes in this project.

Usage:
    python push_pressure_rate_to_sheet.py [--csv pressure_rate.csv]

Requires: google-api-python-client, google-auth
"""

import argparse
import csv
from pathlib import Path

from team_names import normalize

SHEET_ID = "1lTRoatl-YQHlv78YeisG7eFyz2xqaConGUoPo4medpQ"
SERVICE_ACCT = str(Path(__file__).parent.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
TAB = "Live"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="pressure_rate.csv")
    args = ap.parse_args()

    with open(args.csv, newline="", encoding="utf-8") as f:
        pressure_rows = list(csv.DictReader(f))

    rank_by_team = {normalize(r["Team"]): int(r["Rank"]) for r in pressure_rows}

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    existing = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!B2:E").execute()
    live_rows = existing.get("values", [])

    j_col = []
    missing = []
    for row in live_rows:
        opp = normalize(row[3]) if len(row) > 3 and row[3] else None
        rank = rank_by_team.get(opp) if opp else None
        j_col.append([rank if rank is not None else ""])
        if opp and rank is None:
            missing.append(opp)

    n = len(live_rows)
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!J2", valueInputOption="RAW",
        body={"values": j_col},
    ).execute()

    print(f"Wrote {n} rows to '{TAB}'!J2:J{1 + n} (Opp pressure-rate rank).")
    if missing:
        print("Unmatched opponents (left blank):", ", ".join(missing))


if __name__ == "__main__":
    main()
