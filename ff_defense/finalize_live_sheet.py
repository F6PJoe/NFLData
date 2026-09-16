#!/usr/bin/env python3
"""
Weekly housekeeping on the Stream-O-Matic sheet's "Live" tab, run LAST
after all the fetch_*/push_* scripts for the week:

1. Bye weeks mean fewer than 32 teams. subvertadown_defense.csv (from the
   most recent fetch_subvertadown_defense.py run) is this week's
   authoritative team count -- it's the source that drives column B/G,
   so its row count IS however many teams have a game this week. Any
   leftover rows below that (from a previous week that had more teams,
   or just unused buffer rows) get deleted outright, not just cleared.
2. Column A's SCORE formula (=SUM(F{r}:K{r})+IF(ISNUMBER(SEARCH("@",
   D{r})), 0, 5)) is filled down from row 2 through the last real team
   row -- written explicitly per row rather than relying on a
   spreadsheet "fill handle," since this runs headless.
3. The team rows (A2:L<last>) are sorted descending by column A (SCORE)
   -- the header row is never touched.

Usage:
    python finalize_live_sheet.py [--csv subvertadown_defense.csv]

Requires: google-api-python-client, google-auth
"""

import argparse
import csv
from pathlib import Path

SHEET_ID = "1lTRoatl-YQHlv78YeisG7eFyz2xqaConGUoPo4medpQ"
SERVICE_ACCT = str(Path(__file__).parent.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
TAB = "Live"
TAB_GID = 0  # confirmed via spreadsheets.get -- Live is the first sheet

# Generous upper bound on rows ever in play (32 teams + header, plus margin).
MAX_ROW = 40

SCORE_FORMULA = '=SUM(F{r}:K{r})+IF(ISNUMBER(SEARCH("@", D{r})), 0, 5)'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="subvertadown_defense.csv")
    args = ap.parse_args()

    with open(args.csv, newline="", encoding="utf-8") as f:
        n_teams = sum(1 for _ in csv.DictReader(f))
    last_row = n_teams + 1  # +1 for the header

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    requests = []

    if last_row < MAX_ROW:
        # Delete rows (last_row+1)..MAX_ROW (1-indexed) -- 0-indexed
        # startIndex is last_row itself (row last_row+1 - 1), endIndex is
        # exclusive so MAX_ROW covers through 1-indexed row MAX_ROW.
        requests.append({
            "deleteDimension": {
                "range": {
                    "sheetId": TAB_GID, "dimension": "ROWS",
                    "startIndex": last_row, "endIndex": MAX_ROW,
                }
            }
        })

    formula_rows = [[SCORE_FORMULA.format(r=r)] for r in range(2, last_row + 1)]
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!A2", valueInputOption="USER_ENTERED",
        body={"values": formula_rows},
    ).execute()

    requests.append({
        "sortRange": {
            "range": {
                "sheetId": TAB_GID,
                "startRowIndex": 1, "endRowIndex": last_row,   # rows 2..last_row
                "startColumnIndex": 0, "endColumnIndex": 12,   # columns A..L
            },
            "sortSpecs": [{"dimensionIndex": 0, "sortOrder": "DESCENDING"}],
        }
    })

    sheet.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": requests}).execute()

    print(f"{n_teams} teams this week -> rows 2:{last_row}. "
          f"Deleted rows {last_row + 1}:{MAX_ROW}, filled SCORE formula, "
          f"sorted by SCORE descending.")


if __name__ == "__main__":
    main()
