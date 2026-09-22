#!/usr/bin/env python3
"""
Move the Goal-Line Guide sheet forward to a new week's tab.

Two things happen, in this order (order matters):

  1. Duplicate the FROM week's tab (e.g. "W2") and name the copy after the
     TO week (e.g. "W3"). The copy still has the FROM tab's live formulas
     in the GL R Grade / GL P Grade columns (VLOOKUPs into Off!/Def!), so
     once Off/Def gets updated for the week that just played, the new
     tab's grades automatically reflect the fresh season totals -- exactly
     what you want entering a new week. Away/Home/O/U/implied-total values
     get carried over too, but they're stale (still last week's matchups)
     until fill_week_odds.py --week <TO> overwrites them.

  2. Freeze the FROM tab in place: paste-special "values only" over its
     own GL R Grade / GL P Grade columns. Those cells are VLOOKUP formulas
     against Off!/Def! (see update_weekly.py's CLAUDE.md) -- if left as
     formulas, they'd silently recompute once Off/Def moves on to the next
     week's season totals, corrupting the historical record of what each
     team's grade actually was going into that past week. Freezing must
     happen AFTER step 1 -- freezing first would mean the duplicate starts
     out already stale instead of live.

Run this BEFORE update_weekly.py adds the just-played week's numbers to
Off/Def -- that's the ordering the freeze is protecting.

Usage:
    python advance_week.py --from 2 --to 3
    python advance_week.py --from 2 --to 3 --dry-run
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE_ACCT = str(HERE.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
SHEET_ID = "1q-aklbeGgJ5gC0rdLbSpK7sdemIKEoao37LbooROfkI"


def sheets_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def find_sheet(meta, title):
    for s in meta["sheets"]:
        if s["properties"]["title"] == title:
            return s["properties"]
    return None


def last_data_row(service, tab):
    """Last 1-indexed row with a non-empty column A, starting from row 2."""
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
    ap.add_argument("--from", dest="from_week", type=int, required=True)
    ap.add_argument("--to", dest="to_week", type=int, default=None)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    to_week = args.to_week or args.from_week + 1

    from_tab = f"W{args.from_week}"
    to_tab = f"W{to_week}"

    service = sheets_service()
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()

    from_props = find_sheet(meta, from_tab)
    if not from_props:
        print(f"No tab named '{from_tab}' found.", file=sys.stderr)
        return 1
    if find_sheet(meta, to_tab):
        print(f"'{to_tab}' already exists -- not overwriting. Delete it first if you "
              f"really want to redo this.", file=sys.stderr)
        return 1

    last_row = last_data_row(service, from_tab)
    n_rows = last_row - 1
    print(f"{from_tab} -> {to_tab}: duplicating ({n_rows} data rows), "
          f"then freezing {from_tab}'s GL Grade formulas (rows 2-{last_row}).")

    if args.dry_run:
        print("(dry run -- nothing written)")
        return 0

    from_id = from_props["sheetId"]
    requests_ = [
        {
            "duplicateSheet": {
                "sourceSheetId": from_id,
                "insertSheetIndex": from_props["index"] + 1,
                "newSheetName": to_tab,
            }
        },
        # Freeze the FROM tab's live formulas (C:D and J:K -- GL R/P Grade,
        # away and home) to their current computed values. Whole A:L row
        # range is fine to paste-over even though most columns are already
        # plain values -- pasting a value over itself is a no-op.
        {
            "copyPaste": {
                "source": {
                    "sheetId": from_id,
                    "startRowIndex": 1,
                    "endRowIndex": last_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": 12,
                },
                "destination": {
                    "sheetId": from_id,
                    "startRowIndex": 1,
                    "endRowIndex": last_row,
                    "startColumnIndex": 0,
                    "endColumnIndex": 12,
                },
                "pasteType": "PASTE_VALUES",
            }
        },
    ]
    service.spreadsheets().batchUpdate(spreadsheetId=SHEET_ID, body={"requests": requests_}).execute()
    print(f"Done. '{to_tab}' created (still has last week's matchups/odds -- "
          f"run fill_week_odds.py --week {to_week} to refresh those). "
          f"'{from_tab}' frozen to static values.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
