#!/usr/bin/env python3
"""
RETIRED -- NOT IN THE PIPELINE. DO NOT RUN.

The column letters below (B/E/G) are from BEFORE Subvertadown's
column was deleted from the Live tab; the tab is now A-K and
everything from Def Rating rightward shifted one column left.
Running this would write into the wrong columns. Kept only for the
source-access notes in CLAUDE.md. See push_schedule_to_sheet.py /
push_def_rating_to_sheet.py for the live equivalents.

Push subvertadown_defense.csv (from fetch_subvertadown_defense.py) into the
Stream-O-Matic sheet's "Live" tab: team name in column B, opponent (with an
"@" prefix when the team is away, e.g. "@WAS") in column E, and inverted
defense rank in column G, starting at row 2 -- per Joe's request, nothing
else on that tab is touched.

Teams are updated IN PLACE -- each team keeps whatever row it already sits
on. That matters because every other column on this tab (Rost%/Start%/Imp/
Def DAVE/Opp Off DAVE/Pressure/ECR/Proj) is a plain value bound to its row,
not a formula keyed off column B. Rewriting column B in a different order
silently detaches all of them from their teams.

That was a real bug: this script used to write B/E/G sorted by rank while
the sheet's rows were in finalize_live_sheet.py's SCORE-sorted order. The
columns refreshed later in the same run (C/D/F/K/L) re-matched to the new
B and healed themselves, but the ones run_frequent.py deliberately skips
(H/I from FTN DAVE, J from pressure rate) stayed bound to the old rows --
29 of 32 were attached to the wrong team. Reordering rows is
finalize_live_sheet.py's job: its sortRange moves whole rows, so it can
reorder safely. This script must not.

Usage:
    python push_subvertadown_to_sheet.py [--csv subvertadown_defense.csv]

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
    by_team = {normalize(r["Team"]): r for r in rows}

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    existing = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!B2:B").execute()
    existing_teams = [row[0] if row else "" for row in existing.get("values", [])]

    # Update each team IN PLACE, preserving which row each team sits on --
    # every other column (C/D/F/H..L) is a plain value bound to its row, so
    # reordering column B here would silently detach all of them from their
    # teams. That is exactly what used to happen: this script wrote B/E/G in
    # its own rank order while the rows were in finalize's SCORE-sorted
    # order, and the columns run_frequent.py skips (H/I from DAVE, J from
    # pressure) stayed on the old rows and went wrong. Row ORDER is
    # finalize_live_sheet.py's job -- its sortRange moves whole rows, so it
    # can reorder safely; this script must not.
    out_b, out_e, out_g = [], [], []
    bye_rows = []
    seen = set()
    for i, team in enumerate(existing_teams):
        key = normalize(team) if team else None
        rec = by_team.get(key) if key else None
        if rec:
            out_b.append([rec["Team"]])
            out_e.append([rec["Opp"]])
            out_g.append([int(rec["Rank"])])
            seen.add(key)
        else:
            # On a bye this week (or an already-blank row): blank the whole
            # row so its stale values can't score, then finalize's sort +
            # row-delete drops it off the bottom.
            out_b.append([""])
            out_e.append([""])
            out_g.append([""])
            bye_rows.append(i + 2)

    # Teams playing this week that aren't on the sheet yet (coming off a
    # bye, or a first-ever run) get appended; their other columns fill in
    # when those pushes run.
    added = 0
    for key, rec in by_team.items():
        if key not in seen:
            out_b.append([rec["Team"]])
            out_e.append([rec["Opp"]])
            out_g.append([int(rec["Rank"])])
            added += 1

    if bye_rows:
        sheet.values().batchClear(
            spreadsheetId=SHEET_ID,
            body={"ranges": [f"{TAB}!B{r}:L{r}" for r in bye_rows]},
        ).execute()

    for col, values in (("B", out_b), ("E", out_e), ("G", out_g)):
        sheet.values().update(
            spreadsheetId=SHEET_ID, range=f"{TAB}!{col}2", valueInputOption="RAW",
            body={"values": values},
        ).execute()

    n = len(out_b)
    print(f"Updated {len(seen)} teams in place across '{TAB}'!B2:B{1 + n} "
          f"(+{added} added, {len(bye_rows)} cleared as bye/blank).")


if __name__ == "__main__":
    main()
