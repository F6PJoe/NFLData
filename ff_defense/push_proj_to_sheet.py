#!/usr/bin/env python3
"""
Write the Proj column (K) on the "Live" tab: Yahoo's projected D/ST points
plus Subvertadown's situational adjustment, as one number.

Joe wants a single projection column, not two competing ones -- Yahoo
supplies the baseline and Subvertadown supplies the situational read on
top. The displayed value stays a raw point total (7.24, not a rank);
finalize_live_sheet.py's SCORE formula does the ranking inline via
RANK.EQ, so the scale of whatever lands here never matters to the score.

If subvertadown_adjustment.csv is missing -- the fetch failed, or it
refused to write because the source sheet went stale -- this falls back to
raw Yahoo and says so, rather than leaving the column empty. A projection
without the adjustment is still a projection.

This used to live inside push_yahoo_def_to_sheet.py, which now writes only
Rost%/Start% (C/D). Splitting it out is what lets the column combine two
sources without that script pretending to own a number it no longer solely
produces.

Usage:
    python push_proj_to_sheet.py [--yahoo yahoo_def.csv]
                                 [--adjustment subvertadown_adjustment.csv]

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


def load(path, key, value, cast=float):
    with open(path, newline="", encoding="utf-8") as f:
        return {normalize(r[key]): cast(r[value]) for r in csv.DictReader(f) if r[value]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yahoo", default="yahoo_def.csv")
    ap.add_argument("--adjustment", default="subvertadown_adjustment.csv")
    args = ap.parse_args()

    if not os.path.exists(args.yahoo):
        print(f"[WARN] {args.yahoo} not found -- fetch_yahoo_def.py likely failed. "
              "Leaving column K unchanged.")
        return

    proj_by_team = load(args.yahoo, "Team", "Projection")

    if os.path.exists(args.adjustment):
        adj_by_team = load(args.adjustment, "Team", "Adjustment")
        source = "Yahoo + Subvertadown adjustment"
    else:
        adj_by_team = {}
        source = "Yahoo only (no Subvertadown adjustment available)"
        print(f"[WARN] {args.adjustment} not found -- writing raw Yahoo projections.")

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    existing = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!B2:B").execute()
    live_teams = [row[0] if row else None for row in existing.get("values", [])]

    k_col, missing_proj, missing_adj = [], [], []
    for team in live_teams:
        abbr = normalize(team) if team else None
        proj = proj_by_team.get(abbr) if abbr else None
        if proj is None:
            k_col.append([""])
            if abbr:
                missing_proj.append(abbr)
            continue
        adj = adj_by_team.get(abbr, 0.0)
        if abbr and adj_by_team and abbr not in adj_by_team:
            missing_adj.append(abbr)
        k_col.append([round(proj + adj, 2)])

    n = len(live_teams)
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!K2", valueInputOption="RAW",
        body={"values": k_col},
    ).execute()

    print(f"Wrote {n} rows to '{TAB}'!K2:K{1 + n} (Proj -- {source}).")
    if missing_proj:
        print("No Yahoo projection (left blank):", ", ".join(sorted(set(missing_proj))))
    if missing_adj:
        print("No adjustment (raw Yahoo used):", ", ".join(sorted(set(missing_adj))))


if __name__ == "__main__":
    main()
