#!/usr/bin/env python3
"""
Push consensus draft projections to the live Google Sheet.

Reads consensus_<pos>.csv for QB/RB/WR/TE, sorts each by half-PPR fantasy
points (descending — QB has no half-PPR column, so its single "Fantasy
Points" column is used instead), and writes the data rows to the matching
"LIVE PROJECTIONS <POS>" tab starting at A2. Row 1 (headers) is never
touched. Also stamps 'Update Date'!B2 with the current Eastern date/time,
e.g. "May 18, 1:47 PM".

Usage:
    python push_to_sheets.py
"""

import csv
from pathlib import Path

SHEET_ID = "1HoxQZOsM0LFzHxEqCGv5yQJKa_ifdzasZoEHkMGVItQ"
SERVICE_ACCT = str(Path(__file__).parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")

SORT_COL = {
    "qb": "Fantasy Points",
    "rb": "Fantasy Points (Half-PPR)",
    "wr": "Fantasy Points (Half)",
    "te": "Fantasy Points (Half-PPR)",
}

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
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    for pos, tab in TABS.items():
        fn = f"consensus_{pos}.csv"
        with open(fn, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)

        sort_idx = header.index(SORT_COL[pos])
        rows.sort(key=lambda r: float(r[sort_idx]) if r[sort_idx] else 0, reverse=True)

        print(f"Clearing data rows in '{tab}' (row 1 header preserved)...")
        sheet.values().clear(spreadsheetId=SHEET_ID, range=f"{tab}!A2:Z").execute()

        print(f"Writing {len(rows)} rows to '{tab}'...")
        sheet.values().update(
            spreadsheetId=SHEET_ID,
            range=f"{tab}!A2",
            valueInputOption="RAW",
            body={"values": rows},
        ).execute()

    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    ts = f"{now.strftime('%B')} {now.day}, {now.strftime('%I').lstrip('0')}:{now.strftime('%M')} {now.strftime('%p')}"
    sheet.values().update(
        spreadsheetId=SHEET_ID,
        range="Update Date!B2",
        valueInputOption="RAW",
        body={"values": [[ts]]},
    ).execute()
    print(f"Timestamp written -> 'Update Date'!B2 = {ts}")

    print("Done.")


if __name__ == "__main__":
    main()
