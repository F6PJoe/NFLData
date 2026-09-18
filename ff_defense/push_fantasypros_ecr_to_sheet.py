#!/usr/bin/env python3
"""
Push FantasyPros' D/ST ECR (from fetch_fantasypros_dst_ecr.py) into the
Stream-O-Matic sheet's "Live" tab, column K: the row's OWN team's
inverted consensus rank (already inverted by the fetcher -- highest =
best defense, matching every other column on this sheet).

Reads the existing Team column (B) rather than assuming row order, same
as the other pushes in this project.

Usage:
    python push_fantasypros_ecr_to_sheet.py [--csv fantasypros_dst_ecr.csv]

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
    ap.add_argument("--csv", default="fantasypros_dst_ecr.csv")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"[WARN] {args.csv} not found -- fetch_fantasypros_dst_ecr.py likely failed. "
              "Leaving column K unchanged.")
        return

    with open(args.csv, newline="", encoding="utf-8") as f:
        ecr_rows = list(csv.DictReader(f))

    rank_by_team = {normalize(r["Team"]): int(r["Rank"]) for r in ecr_rows}

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    existing = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!B2:B").execute()
    live_teams = [row[0] if row else None for row in existing.get("values", [])]

    k_col = []
    missing = []
    for team in live_teams:
        abbr = normalize(team) if team else None
        rank = rank_by_team.get(abbr) if abbr else None
        k_col.append([rank if rank is not None else ""])
        if abbr and rank is None:
            missing.append(abbr)

    n = len(live_teams)
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!K2", valueInputOption="RAW",
        body={"values": k_col},
    ).execute()

    print(f"Wrote {n} rows to '{TAB}'!K2:K{1 + n} (ECR, inverted).")
    if missing:
        print("Unmatched (left blank):", ", ".join(missing))


if __name__ == "__main__":
    main()
