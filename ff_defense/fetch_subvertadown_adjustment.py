#!/usr/bin/env python3
"""
Pull Subvertadown's situational D/ST adjustment from the Google Sheet he
shares with Joe, for blending into the Proj column.

The sheet is a plain 32-row grid with no header:
    A = nickname ("Cardinals")   B = abbreviation ("ARI")
    C = adjustment in fantasy points, signed (+1.2 ... -1.5)
    D = rank (32 = biggest positive adjustment, 1 = most negative)

Only column C is used. It's an adjustment, not a projection -- it gets
ADDED to Yahoo's number in push_proj_to_sheet.py, which is what Joe wants
in that column: Yahoo's baseline with Subvertadown's situational read on
top, as one value rather than two competing columns.

NO STALENESS CHECK, DELIBERATELY. An earlier version read Drive's
modifiedTime and refused anything that predated this week's Tuesday. That
was wrong: the sheet is built from VLOOKUPs and FILTERs pulling from
Subvertadown's other sheets, and Drive only bumps modifiedTime when the
file ITSELF is edited -- formula recalculation against an external source
doesn't touch it. So the timestamp sat frozen at 2026-09-22 while the
values underneath kept updating, and the check started throwing away good
adjustments every run.

There is no signal in this sheet that reveals its freshness: no week
marker in the contents, and a modification date that doesn't move. Joe's
call is to assume it's current, which is the only option actually
available. If it ever does go stale it will show up as adjustments that
don't match the week's matchups, not as anything a script can detect.

Usage:
    python fetch_subvertadown_adjustment.py          # -> subvertadown_adjustment.csv

Requires: google-api-python-client, google-auth
"""

import argparse
import csv
from pathlib import Path

from team_names import normalize

# Subvertadown's own sheet, shared with the service account read-only.
SOURCE_SHEET_ID = "1xGTyPr2LrPBME5G_-jHChjFoWvACg2P-RiQxfoyjV8E"
SOURCE_TAB = "Sheet1"
SERVICE_ACCT = str(Path(__file__).parent.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")

# Sheets only -- the Drive scope was here purely for the modifiedTime check.
SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

FIELDNAMES = ["Team", "Adjustment", "Rank"]


def main():
    ap = argparse.ArgumentParser()
    # --week is accepted but unused: the sheet holds one current-week grid
    # with no week column to select on. It stays so run_all.py can pass
    # "--week N" uniformly to every fetcher in its step list.
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--out", default="subvertadown_adjustment.csv")
    args = ap.parse_args()

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(SERVICE_ACCT, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()

    rows = sheets.values().get(
        spreadsheetId=SOURCE_SHEET_ID, range=f"{SOURCE_TAB}!A1:D40"
    ).execute().get("values", [])

    out = []
    for r in rows:
        if len(r) < 3 or not r[1]:
            continue
        try:
            adj = float(r[2])
        except ValueError:
            continue          # header or stray row -- the sheet has none today
        out.append({"Team": normalize(r[1]), "Adjustment": adj,
                    "Rank": r[3] if len(r) > 3 else ""})

    if len(out) < 28:
        raise SystemExit(f"Only parsed {len(out)} teams -- expected 32. "
                         "Has the sheet's layout changed?")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(out)

    lo = min(out, key=lambda r: r["Adjustment"])
    hi = max(out, key=lambda r: r["Adjustment"])
    print(f"Wrote {len(out)} teams to {args.out} "
          f"(range {lo['Adjustment']:+.1f} {lo['Team']} to {hi['Adjustment']:+.1f} {hi['Team']}).")


if __name__ == "__main__":
    main()
