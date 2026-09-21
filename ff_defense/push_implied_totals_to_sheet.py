#!/usr/bin/env python3
"""
Rank this week's implied team totals and push them to the Stream-O-Matic
sheet's "Live" tab, column F ("Imp"): the OPPONENT's implied-total rank
(1 = highest implied total i.e. toughest offense to face, 32 = lowest),
looked up via the row's own Opp column (E) -- same pattern as column I.

THE IMP TAB IS THE BACKUP STORE. The Odds API only returns games that
haven't kicked off yet, so from Thursday night onward fetch_implied_
totals.py sees only a partial slate. Ranking a partial slate would be
wrong, not merely stale: it produces 1..k instead of 1..<teams playing>,
a different scale from the rows already in column F.

So every fetched value gets banked on the "IMP" tab, and each run merges:

    stored (IMP tab, if its week stamp matches) + live (this run's fetch)
    -> live wins for any team in both
    -> rank the merged set 1..N
    -> write the merge back to IMP, and the ranks to column F

A team whose game has kicked off keeps the last number seen before
kickoff, which is the final correct one for that week. Result: a genuine
full-slate ranking on every run, including Sunday night.

The week stamp (IMP!I1) is what makes this safe. Without it, the first
run of a new week would merge last week's leftovers for teams whose new
lines aren't posted yet and quietly produce a wrong ranking. If the
stored week doesn't match, the stored rows are ignored entirely.

Bye weeks need no special handling: teams on bye appear in neither the
fetch nor (after the first run of the week) the tab, so the ranking just
covers however many teams are actually playing.

Usage:
    python push_implied_totals_to_sheet.py [--csv implied_totals.csv]

Requires: google-api-python-client, google-auth
"""

import argparse
import csv
import datetime
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from current_week import current_week
from team_names import normalize

SHEET_ID = "1lTRoatl-YQHlv78YeisG7eFyz2xqaConGUoPo4medpQ"
SERVICE_ACCT = str(Path(__file__).parent.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
TAB = "Live"
BACKUP_TAB = "IMP"
ET = ZoneInfo("America/New_York")

BACKUP_HEADERS = ["Rank", "Team", "Implied Total", "Spread", "O/U", "Opponent"]


def read_backup(sheet, week):
    """Rows banked on the IMP tab for THIS week, keyed by team. Empty if the
    tab's week stamp doesn't match (start of a new week, or first ever run)."""
    try:
        stamp = sheet.values().get(
            spreadsheetId=SHEET_ID, range=f"{BACKUP_TAB}!I1"
        ).execute().get("values", [])
    except Exception as exc:
        print(f"[WARN] couldn't read {BACKUP_TAB} week stamp ({exc}) -- treating as empty.")
        return {}

    stored_week = stamp[0][0] if stamp and stamp[0] else None
    if str(stored_week) != str(week):
        print(f"{BACKUP_TAB} holds week {stored_week!r}, not {week} -- ignoring banked "
              "values and starting this week fresh.")
        return {}

    rows = sheet.values().get(
        spreadsheetId=SHEET_ID, range=f"{BACKUP_TAB}!A2:F"
    ).execute().get("values", [])

    out = {}
    for r in rows:
        if len(r) < 6 or not r[1]:
            continue
        try:
            out[normalize(r[1])] = {
                "Team": normalize(r[1]), "ImpliedTotal": float(r[2]),
                "Spread": r[3], "OU": r[4], "Opponent": normalize(r[5]),
            }
        except ValueError:
            continue
    return out


def write_backup(sheet, merged, week):
    values = [[m["Rank"], m["Team"], m["ImpliedTotal"], m["Spread"], m["OU"], m["Opponent"]]
              for m in merged]
    sheet.values().clear(spreadsheetId=SHEET_ID, range=f"{BACKUP_TAB}!A2:F").execute()
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{BACKUP_TAB}!A1", valueInputOption="RAW",
        body={"values": [BACKUP_HEADERS] + values},
    ).execute()
    now = datetime.datetime.now(ET).strftime("%a %m/%d %I:%M %p ET")
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{BACKUP_TAB}!H1", valueInputOption="RAW",
        body={"values": [["Week", week], ["Updated", now]]},
    ).execute()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="implied_totals.csv")
    ap.add_argument("--week", type=int, default=None)
    args = ap.parse_args()

    if not os.path.exists(args.csv):
        print(f"[WARN] {args.csv} not found -- fetch_implied_totals.py likely failed. "
              "Leaving column F unchanged.")
        return

    with open(args.csv, newline="", encoding="utf-8") as f:
        live_rows = list(csv.DictReader(f))

    week = args.week or (int(live_rows[0]["Week"]) if live_rows else current_week())

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    merged = read_backup(sheet, week)
    banked = len(merged)
    for r in live_rows:
        merged[normalize(r["Team"])] = {
            "Team": normalize(r["Team"]), "ImpliedTotal": float(r["ImpliedTotal"]),
            "Spread": r["Spread"], "OU": r["OU"], "Opponent": normalize(r["Opponent"]),
        }

    if not merged:
        print("[SKIP] no live lines and nothing banked for this week -- "
              "leaving column F unchanged.")
        return

    ordered = sorted(merged.values(), key=lambda m: -m["ImpliedTotal"])
    for i, m in enumerate(ordered, start=1):
        m["Rank"] = i
    rank_by_team = {m["Team"]: m["Rank"] for m in ordered}

    print(f"Ranked {len(ordered)} teams for week {week} "
          f"({len(live_rows)} live, {max(len(ordered) - len(live_rows), 0)} from {BACKUP_TAB} backup).")

    # Bank the merge FIRST, and unconditionally. Even if the ranking can't
    # be published yet (below), every value banked now is one that won't
    # need to come from a live line again this week.
    write_backup(sheet, ordered, week)

    existing = sheet.values().get(spreadsheetId=SHEET_ID, range=f"{TAB}!B2:F").execute()
    sheet_rows = existing.get("values", [])

    f_col, missing = [], []
    for row in sheet_rows:
        row = row + [""] * (5 - len(row))
        opp = normalize(row[3]) if row[3] else None
        rank = rank_by_team.get(opp) if opp else None
        f_col.append([rank if rank is not None else ""])
        if opp and rank is None:
            missing.append(opp)

    # If any opponent is missing, the merged set doesn't cover the full
    # slate, so its ranks run 1..k rather than 1..<teams playing> -- a
    # different scale from what's already in column F. Bank it (done
    # above) but don't publish it. This only happens before the backup has
    # seen a full slate; once it has, every team is always covered.
    if missing:
        print(f"[SKIP] {len(missing)} opponent(s) in neither the live fetch nor the "
              f"{BACKUP_TAB} backup: {', '.join(sorted(set(missing)))}. "
              f"Ranking would be 1..{len(ordered)}, not full-slate, so column F is "
              "left as-is. Values banked for next run.")
        return

    n = len(sheet_rows)
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!F2", valueInputOption="RAW",
        body={"values": f_col},
    ).execute()
    print(f"Wrote {n} rows to '{TAB}'!F2:F{1 + n} (Opp implied-total rank).")


if __name__ == "__main__":
    main()
