#!/usr/bin/env python3
"""
RETIRED -- NOT IN THE PIPELINE. DO NOT RUN.

The column letters below (H/I) are from BEFORE Subvertadown's
column was deleted from the Live tab; the tab is now A-K and
everything from Def Rating rightward shifted one column left.
Running this would write into the wrong columns. Kept only for the
source-access notes in CLAUDE.md. See push_schedule_to_sheet.py /
push_def_rating_to_sheet.py for the live equivalents.

Push FTN DAVE ratings (from fetch_ftn_dave.py) into the Stream-O-Matic
sheet's "Live" tab, per Joe's spec:

  - Column H (Def DAVE): the ROW'S OWN team's Def Rank, inverted (FTN's
    Def Rank is 1 = best defense; inverted = 33 - rank, so it matches this
    sheet's convention of higher = better/tougher defense, same as the
    Subvertadown rank in column G).
  - Column I (Opp Off DAVE): the OPPONENT's Off Rank, used AS-IS (FTN's
    Off Rank is already 1 = best offense, so a high number here already
    means "weak opposing offense" -- a good matchup -- consistent with
    higher-is-better everywhere else on this sheet; Joe only asked to
    invert the defense rank, not this one).

Reads the existing Team (B) and Opp (E) columns already on the sheet
(rather than assuming row order) so it lines up with whatever's there,
including "@"-prefixed away opponents from push_subvertadown_to_sheet.py.

FTN uses "JAX" for the Jaguars where the rest of this sheet uses "JAC" --
aliased via team_names.normalize().

Usage:
    python push_ftn_dave_to_sheet.py [--csv ftn_dave.csv]

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
    ap.add_argument("--csv", default="ftn_dave.csv")
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        # fetch_ftn_dave.py is allowed to fail without stopping the rest of
        # the pipeline (FTN's login is often blocked from CI/datacenter IPs
        # -- see run_all.py) -- on an ephemeral runner there's no leftover
        # CSV from a prior run to fall back on either, so just leave
        # columns H/I as whatever they already were and exit cleanly. DVOA
        # moves slowly week to week, so a stale value there is a much
        # smaller problem than crashing the whole weekly refresh over it.
        print(f"[WARN] {args.csv} not found -- fetch_ftn_dave.py likely failed. "
              "Leaving columns H/I unchanged.")
        return

    with open(args.csv, newline="", encoding="utf-8") as f:
        dave_rows = list(csv.DictReader(f))

    def_rank_by_team = {normalize(r["Team"]): int(r["DefRank"]) for r in dave_rows}
    off_rank_by_team = {normalize(r["Team"]): int(r["OffRank"]) for r in dave_rows}

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    existing = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!B2:E").execute()
    live_rows = existing.get("values", [])

    h_col, i_col = [], []
    missing = []
    for row in live_rows:
        team = normalize(row[0]) if len(row) > 0 and row[0] else None
        opp = normalize(row[3]) if len(row) > 3 and row[3] else None

        def_rank = def_rank_by_team.get(team) if team else None
        off_rank = off_rank_by_team.get(opp) if opp else None

        h_col.append([33 - def_rank if def_rank is not None else ""])
        i_col.append([off_rank if off_rank is not None else ""])

        if team and def_rank is None:
            missing.append(f"team {team!r} (row Def Rank)")
        if opp and off_rank is None:
            missing.append(f"opp {opp!r} (row Off Rank)")

    n = len(live_rows)
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!H2", valueInputOption="RAW",
        body={"values": h_col},
    ).execute()
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!I2", valueInputOption="RAW",
        body={"values": i_col},
    ).execute()

    print(f"Wrote {n} rows to '{TAB}'!H2:H{1 + n} (Def DAVE, inverted) "
          f"and !I2:I{1 + n} (Opp Off DAVE).")
    if missing:
        print("Unmatched (left blank):", "; ".join(missing))


if __name__ == "__main__":
    main()
