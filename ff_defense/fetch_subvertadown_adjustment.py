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

STALENESS IS THE REAL RISK HERE, not access. The sheet carries no week
marker anywhere in its contents, so a copy from three weeks ago looks
exactly like a fresh one -- there is no way to tell from the values alone.
What does tell us is Drive's own modifiedTime, which is why this script
asks for the drive.metadata.readonly scope on top of the usual Sheets one.

Two thresholds, deliberately:
  * Modified before THIS week's Tuesday 00:00 ET -> warn, but still write.
    On a Tuesday-morning run he may simply not have posted yet, and last
    week's situational read is better than nothing. Joe's call: he said
    he isn't worried about staleness.
  * Modified before LAST week's Tuesday -> refuse to write the CSV. That
    isn't "hasn't got to it yet," that's the sheet going quiet, and
    silently adding month-old adjustments to every projection for the rest
    of the season is the one failure mode nobody would notice. The push
    then falls back to raw Yahoo.

Usage:
    python fetch_subvertadown_adjustment.py          # -> subvertadown_adjustment.csv
    python fetch_subvertadown_adjustment.py --week 3

Requires: google-api-python-client, google-auth
"""

import argparse
import csv
import datetime
from pathlib import Path

from current_week import current_week, week_window_utc
from team_names import normalize

# Subvertadown's own sheet, shared with the service account read-only.
SOURCE_SHEET_ID = "1xGTyPr2LrPBME5G_-jHChjFoWvACg2P-RiQxfoyjV8E"
SOURCE_TAB = "Sheet1"
SERVICE_ACCT = str(Path(__file__).parent.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly",
          "https://www.googleapis.com/auth/drive.metadata.readonly"]

FIELDNAMES = ["Team", "Adjustment", "Rank", "SourceModified"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--out", default="subvertadown_adjustment.csv")
    ap.add_argument("--ignore-staleness", action="store_true",
                    help="write the CSV even if the sheet has gone quiet for weeks")
    args = ap.parse_args()

    week = args.week or current_week()

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(SERVICE_ACCT, scopes=SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False).spreadsheets()
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)

    meta = drive.files().get(fileId=SOURCE_SHEET_ID, fields="modifiedTime").execute()
    modified = datetime.datetime.fromisoformat(
        meta["modifiedTime"].replace("Z", "+00:00"))

    this_week_start, _ = week_window_utc(week)
    last_week_start, _ = week_window_utc(max(1, week - 1))
    age_days = (datetime.datetime.now(datetime.timezone.utc) - modified).days

    print(f"Source last modified {modified:%Y-%m-%d %H:%M} UTC ({age_days}d ago); "
          f"week {week} started {this_week_start:%Y-%m-%d}.")

    if modified < last_week_start and not args.ignore_staleness:
        raise SystemExit(
            f"[SKIP] Sheet hasn't been touched since before week {max(1, week - 1)} "
            f"started -- these adjustments are at least a full week out of date. "
            f"Not writing {args.out}; the Proj column will fall back to raw Yahoo. "
            f"Pass --ignore-staleness to override.")

    if modified < this_week_start:
        print(f"[WARN] Not yet updated for week {week} -- using last week's "
              f"adjustments. They'll be picked up on the next run once he posts.")

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
                    "Rank": r[3] if len(r) > 3 else "",
                    "SourceModified": modified.isoformat()})

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
