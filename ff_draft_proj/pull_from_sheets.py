#!/usr/bin/env python3
"""
Pull the live consensus projections from the Google Sheet (the inverse of
push_to_sheets.py), saving each "LIVE PROJECTIONS <POS>" tab to
consensus_<pos>.csv locally.

Usage:
    python pull_from_sheets.py
"""

import csv
from pathlib import Path

SHEET_ID = "1HoxQZOsM0LFzHxEqCGv5yQJKa_ifdzasZoEHkMGVItQ"
SERVICE_ACCT = str(Path(__file__).parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")

TABS = {
    "qb": "LIVE PROJECTIONS QB",
    "rb": "LIVE PROJECTIONS RB",
    "wr": "LIVE PROJECTIONS WR",
    "te": "LIVE PROJECTIONS TE",
}


def main():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets.readonly"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    for pos, tab in TABS.items():
        result = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{tab}!A1:Z").execute()
        rows = result.get("values", [])
        if not rows:
            print(f"[WARN] no data in '{tab}'")
            continue
        width = len(rows[0])
        rows = [r + [""] * (width - len(r)) for r in rows]
        fn = f"consensus_{pos}.csv"
        with open(fn, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerows(rows)
        print(f"Wrote {len(rows) - 1} rows to {fn}")


if __name__ == "__main__":
    main()
