#!/usr/bin/env python3
"""
Push subvertadown_defense.csv (from fetch_subvertadown_defense.py) into the
Stream-O-Matic sheet's "Live" tab: team name in column B, opponent (with an
"@" prefix when the team is away, e.g. "@WAS") in column E, and inverted
defense rank in column G, starting at row 2 -- per Joe's request, nothing
else on that tab is touched.

Row order is just the rank, best defense first (row 2 = highest rank). The
"Live" tab's other columns (Rost%/Start%/Opp/Imp/Def DAVE/Pressure/ECR) are
plain pasted values, not formulas keyed off column B, so they belong to
whatever team happened to be in that row before this run -- they will not
match the new B/G rows until Joe (or another script) refreshes them too.
That's expected per his ask, just flagging it since it's a shared sheet.

Usage:
    python push_subvertadown_to_sheet.py [--csv subvertadown_defense.csv]

Requires: google-api-python-client, google-auth
"""

import argparse
import csv
import os
from pathlib import Path

SHEET_ID = "1lTRoatl-YQHlv78YeisG7eFyz2xqaConGUoPo4medpQ"
SERVICE_ACCT = str(Path(__file__).parent.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
TAB = "Live"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="subvertadown_defense.csv")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        # fetch_subvertadown_defense.py is allowed to fail (e.g. a lapsed
        # subscription, login blocked from CI) without stopping the rest
        # of the pipeline -- see run_all.py. Leave B/E/G as whatever they
        # already were rather than crashing; every other push still runs
        # against that same, slightly-stale team list.
        print(f"[WARN] {args.csv} not found -- fetch_subvertadown_defense.py likely failed. "
              "Leaving columns B/E/G unchanged.")
        return

    with open(args.csv, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    rows.sort(key=lambda r: int(r["Rank"]), reverse=True)  # best defense first

    teams = [[r["Team"]] for r in rows]
    opps = [[r["Opp"]] for r in rows]
    ranks = [[int(r["Rank"])] for r in rows]
    n = len(rows)

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!B2", valueInputOption="RAW",
        body={"values": teams},
    ).execute()
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!E2", valueInputOption="RAW",
        body={"values": opps},
    ).execute()
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!G2", valueInputOption="RAW",
        body={"values": ranks},
    ).execute()

    print(f"Wrote {n} teams to '{TAB}'!B2:B{1 + n}, opponents to !E2:E{1 + n}, "
          f"and ranks to !G2:G{1 + n}.")


if __name__ == "__main__":
    main()
