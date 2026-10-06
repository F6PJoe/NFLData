#!/usr/bin/env python3
"""
Weekly housekeeping on the Stream-O-Matic sheet's "Live" tab, run LAST
after all the fetch_*/push_* scripts for the week:

1. Bye weeks mean fewer than 32 teams. Rows with no team in column B are
   deleted BY POSITION -- the actual blank rows, found by reading column B,
   wherever they sit. This is deliberate and was learned the hard way: it
   used to delete by COUNT, trimming everything below schedule.csv's row
   total, which assumed the spare rows were at the bottom.
   push_schedule_to_sheet.py blanks a bye team's row in place, so on the
   first bye week of 2026 the blanks were mid-sheet and the bottom-trim
   deleted Denver instead. schedule.csv is now only a cross-check that
   warns on a mismatch.
   Trailing leftover rows (from a week that had more teams) are still
   removed by range, up to MAX_ROW.
2. Column A's SCORE formula is filled down from row 2 through the last
   real team row -- written explicitly per row rather than relying on a
   spreadsheet "fill handle," since this runs headless. RANK.EQ is wrapped
   in IFERROR: on an empty Proj cell it returns #N/A, which propagates
   through the whole SUM and -- because errors sort ABOVE numbers in a
   descending sort -- lands that row at the top of the chart. A missing
   projection now contributes 0, the same as a blank in SUM.
3. The team rows (A2:K<last>) are sorted descending by column A (SCORE)
   -- the header row is never touched.

Usage:
    python finalize_live_sheet.py [--csv schedule.csv]

Requires: google-api-python-client, google-auth
"""

import argparse
import csv
import os
from pathlib import Path

SHEET_ID = "1lTRoatl-YQHlv78YeisG7eFyz2xqaConGUoPo4medpQ"
SERVICE_ACCT = str(Path(__file__).parent.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
TAB = "Live"
TAB_GID = 0  # confirmed via spreadsheets.get -- Live is the first sheet

# Generous upper bound on rows ever in play (32 teams + header, plus margin).
MAX_ROW = 40

# F:J are the five ranked columns (Imp, Def Rating, Opp Off EPA, Pressure,
# ECR). Subvertadown's old column sat between Imp and Def Rating and was
# deleted outright once its source was gone, so the range is contiguous
# again -- there's no longer a gap to skip.
#
# RANK.EQ(K{r}, K:K, 1) scores the Yahoo projection in column K. Order 1 is
# ASCENDING, so the lowest projection ranks 1 and the highest ranks 32 --
# matching every other column here, where a bigger number is better. It's
# ranked rather than added raw so one column of fantasy points can't
# outweigh five columns of 1-32 ranks. The whole-column K:K reference is
# safe: RANK.EQ ignores the text header and blank rows.
#
# The "@" test reads column E (Opp). It used to read D (Start%), which never
# contains an "@" -- so every team got the +5 home bonus, including road
# teams. Harmless to the ORDER, since a constant shifts all 32 scores
# equally, but the home bonus was doing nothing at all.
SCORE_FORMULA = ('=SUM(F{r}:J{r})+IFERROR(RANK.EQ(K{r}, K:K, 1), 0)'
                 '+IF(ISNUMBER(SEARCH("@", E{r})), 0, 5)')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", default="schedule.csv")
    args = ap.parse_args()

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    # Which rows actually hold a team RIGHT NOW. This is what decides which
    # rows get deleted -- not a count.
    #
    # It used to be a count: schedule.csv's row total, with everything below
    # that deleted. That silently assumed the extra rows sat at the BOTTOM.
    # They don't. push_schedule_to_sheet.py blanks a bye team's row IN PLACE,
    # wherever that team happened to be sitting, so on the first bye week of
    # 2026 the blanks were mid-sheet and deleting the bottom rows removed
    # Denver instead. The surviving blank row then took the SCORE formula,
    # RANK.EQ on an empty cell returned #N/A, and #N/A sorts ABOVE numbers
    # descending -- so it landed at row 2 and crashed generate_reddit_post.py.
    #
    # Note values().get trims trailing empty rows, so `teams` covers the
    # interior only; trailing leftovers are handled by the range delete below.
    existing = sheet.values().get(
        spreadsheetId=SHEET_ID, range=f"{TAB}!B2:B{MAX_ROW}").execute()
    teams = [(row[0].strip() if row and row[0] else "")
             for row in existing.get("values", [])]
    blank_rows = [i + 2 for i, t in enumerate(teams) if not t]
    n_teams = sum(1 for t in teams if t)

    if os.path.exists(args.csv):
        with open(args.csv, newline="", encoding="utf-8") as f:
            expected = sum(1 for _ in csv.DictReader(f))
        if expected != n_teams:
            # Not fatal: push_schedule_to_sheet.py appends any team that's
            # missing on its next run, so this heals itself. Worth saying out
            # loud though -- it's how Denver's disappearance would have been
            # caught the same day instead of a week later.
            print(f"[WARN] {args.csv} lists {expected} teams but the sheet has "
                  f"{n_teams}. Going with the sheet. If the sheet is short, the "
                  f"next push_schedule_to_sheet.py run re-adds the missing team.")

    last_row = n_teams + 1  # +1 for the header
    print(f"{n_teams} teams on the sheet"
          + (f", {len(blank_rows)} blank row(s) to remove: {blank_rows}"
             if blank_rows else ", no blank rows")
          + ".")

    # STEP 1 -- delete rows in their OWN batchUpdate, before anything is
    # written. Sequencing matters here and getting it wrong is subtle: if the
    # formulas are written first and the deletes applied after, every row
    # below a deleted one shifts up by one and the last row ends up with no
    # formula at all. That happened on the first attempt at this fix -- the
    # Broncos landed at the bottom with an empty SCORE.
    delete_requests = []

    # Blank rows bottom-up, so an earlier deletion can't shift the index of
    # one still to come.
    for r in sorted(blank_rows, reverse=True):
        delete_requests.append({
            "deleteDimension": {
                "range": {"sheetId": TAB_GID, "dimension": "ROWS",
                          "startIndex": r - 1, "endIndex": r}
            }
        })

    # Then any trailing rows left over from a week with more teams. After the
    # blanks are gone the data is contiguous from row 2, so everything from
    # last_row+1 down is surplus. (0-indexed startIndex is last_row; endIndex
    # is exclusive, so MAX_ROW covers through 1-indexed row MAX_ROW.)
    if last_row < MAX_ROW:
        delete_requests.append({
            "deleteDimension": {
                "range": {"sheetId": TAB_GID, "dimension": "ROWS",
                          "startIndex": last_row, "endIndex": MAX_ROW}
            }
        })

    if delete_requests:
        sheet.batchUpdate(spreadsheetId=SHEET_ID,
                          body={"requests": delete_requests}).execute()

    # STEP 2 -- now that rows 2..last_row are exactly the real teams, fill the
    # SCORE formula. Written explicitly per row: there's no "fill handle"
    # headlessly.
    formula_rows = [[SCORE_FORMULA.format(r=r)] for r in range(2, last_row + 1)]
    sheet.values().update(
        spreadsheetId=SHEET_ID, range=f"{TAB}!A2", valueInputOption="USER_ENTERED",
        body={"values": formula_rows},
    ).execute()

    # STEP 3 -- sort. sortRange moves whole rows, so this is the one step
    # allowed to reorder them.
    sheet.batchUpdate(spreadsheetId=SHEET_ID, body={"requests": [{
        "sortRange": {
            "range": {
                "sheetId": TAB_GID,
                "startRowIndex": 1, "endRowIndex": last_row,   # rows 2..last_row
                "startColumnIndex": 0, "endColumnIndex": 11,   # columns A..K
            },
            "sortSpecs": [{"dimensionIndex": 0, "sortOrder": "DESCENDING"}],
        }
    }]}).execute()

    print(f"{n_teams} teams this week -> rows 2:{last_row}. "
          f"Removed {len(blank_rows)} blank row(s) and anything below row "
          f"{last_row}, filled SCORE formula, sorted by SCORE descending.")


if __name__ == "__main__":
    main()
