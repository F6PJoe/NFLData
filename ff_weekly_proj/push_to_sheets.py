#!/usr/bin/env python3
"""
Push consensus weekly projections to the live Google Sheet.

Reads consensus_<pos>.csv for QB/RB/WR/TE, sorts each by half-PPR fantasy
points (descending — QB uses its single "Fantasy Points" column), and writes
stat columns as raw values plus formula strings for fantasy points columns.

Scoring (standard ESPN/Yahoo):
  INT:    -2 pts    Fumbles:  -2 pts
  Pass:   0.04/yd, 4/TD
  Rush:   0.1/yd,  6/TD
  Rec:    0.1/yd,  6/TD  + PPR multiplier (0=STD, 0.5=Half, 1=PPR, 1.5=TE-Prem)

Column layout:
  QB  A=Name B=Team C=Opp D=PassAtt E=PassComp F=PassYds G=PassTD H=PassInt
      I=RushAtt J=RushYds K=RushTD L=Fumbles | M=FantasyPts
  RB  A=Name B=Team C=Opp D=RushAtt E=RushYds F=RushTD G=Targets H=Rec
      I=RecYds J=RecTD K=Fum | L=Half-PPR M=PPR N=STD
  WR  A=Name B=Team C=Opp D=Targets E=Rec F=RecYds G=RecTD H=RushAtt
      I=RushYds J=RushTD K=Fum | L=Half M=PPR N=STD
  TE  A=Name B=Team C=Opp D=Targets E=Rec F=RecYds G=RecTD H=RushAtt
      I=RushYds J=RushTD | K=Half-PPR L=PPR M=TEPremium

Usage:
    python push_to_sheets.py
"""

import csv
from pathlib import Path

SHEET_ID = "1R7HBUls8QdlS0HQ_Xu4WBmZFHgt2DYdhR4JSeNjW0yM"
SERVICE_ACCT = str(Path(__file__).parent.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")

SORT_COL = {
    "qb": "Fantasy Points",
    "rb": "Fantasy Points (Half-PPR)",
    "wr": "Fantasy Points (Half)",
    "te": "Fantasy Points (Half-PPR)",
}

TABS = {
    "qb": "LIVE PROJECTIONS QB",
    "rb": "LIVE PROJECTIONS RB",
    "wr": "LIVE PROJECTIONS WR",
    "te": "LIVE PROJECTIONS TE",
}

# Stat columns only (written as RAW values).
STAT_HEADERS = {
    "qb": ["QB", "Team", "Opp", "Pass Att", "Pass Comp", "Pass Yds", "Pass TD",
           "Pass Int", "Rush Att", "Rush Yds", "Rush TD", "Fumbles"],
    "rb": ["RB", "Team", "Opp", "Rush Att", "Rush Yds", "Rush TD", "Targets", "Rec",
           "Rec Yds", "Rec TD", "Fum"],
    "wr": ["WR", "Team", "Opp", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD", "Fum"],
    "te": ["TE", "Team", "Opp", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD"],
}

# Clear range covers stat columns + formula columns so the sheet is fully reset each run.
CLEAR_RANGE = {
    "qb": "A2:M",
    "rb": "A2:N",
    "wr": "A2:N",
    "te": "A2:M",
}

# Starting column letter for formula columns (one past last stat col).
FORMULA_START_COL = {"qb": "M", "rb": "L", "wr": "L", "te": "K"}


def make_formulas(pos, row_num):
    """Return a list of Sheets formula strings for the points columns at sheet row row_num."""
    r = row_num
    if pos == "qb":
        # F=PassYds G=PassTD H=PassInt J=RushYds K=RushTD L=Fumbles
        return [f"=F{r}*0.04+G{r}*4-H{r}*2+J{r}*0.1+K{r}*6-L{r}*2"]
    elif pos == "rb":
        # E=RushYds F=RushTD H=Rec I=RecYds J=RecTD K=Fum
        half = f"=E{r}*0.1+F{r}*6+H{r}*0.5+I{r}*0.1+J{r}*6-K{r}*2"
        ppr  = f"=E{r}*0.1+F{r}*6+H{r}*1+I{r}*0.1+J{r}*6-K{r}*2"
        std  = f"=E{r}*0.1+F{r}*6+I{r}*0.1+J{r}*6-K{r}*2"
        return [half, ppr, std]
    elif pos == "wr":
        # E=Rec F=RecYds G=RecTD I=RushYds J=RushTD K=Fum
        half = f"=F{r}*0.1+G{r}*6+E{r}*0.5+I{r}*0.1+J{r}*6-K{r}*2"
        ppr  = f"=F{r}*0.1+G{r}*6+E{r}*1+I{r}*0.1+J{r}*6-K{r}*2"
        std  = f"=F{r}*0.1+G{r}*6+I{r}*0.1+J{r}*6-K{r}*2"
        return [half, ppr, std]
    elif pos == "te":
        # E=Rec F=RecYds G=RecTD I=RushYds J=RushTD (no fum col)
        half   = f"=F{r}*0.1+G{r}*6+E{r}*0.5+I{r}*0.1+J{r}*6"
        ppr    = f"=F{r}*0.1+G{r}*6+E{r}*1+I{r}*0.1+J{r}*6"
        teprem = f"=F{r}*0.1+G{r}*6+E{r}*1.5+I{r}*0.1+J{r}*6"
        return [half, ppr, teprem]


def main():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    service = build("sheets", "v4", credentials=creds, cache_discovery=False)
    sheet = service.spreadsheets()

    for pos, tab in TABS.items():
        fn = f"consensus_{pos}.csv"
        with open(fn, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            all_rows = list(reader)

        sort_col = SORT_COL[pos]
        all_rows.sort(
            key=lambda r: float(r[sort_col]) if r.get(sort_col) else 0,
            reverse=True,
        )

        def coerce(v):
            if v == "" or v is None:
                return ""
            try:
                f = float(v)
                return int(f) if f == int(f) else f
            except (ValueError, TypeError):
                return v

        stat_cols = STAT_HEADERS[pos]
        stat_rows = [[coerce(r.get(col, "")) for col in stat_cols] for r in all_rows]
        n = len(stat_rows)

        # Clear the full range (stat + formula cols) so stale rows are gone.
        clear_range = f"{tab}!{CLEAR_RANGE[pos]}"
        print(f"Clearing '{tab}' ({CLEAR_RANGE[pos]})...")
        sheet.values().clear(spreadsheetId=SHEET_ID, range=clear_range).execute()

        if not stat_rows:
            print(f"No rows for {pos}, skipping write.")
            continue

        # Write stat columns as raw values.
        print(f"Writing {n} rows of stat data to '{tab}'...")
        sheet.values().update(
            spreadsheetId=SHEET_ID,
            range=f"{tab}!A2",
            valueInputOption="RAW",
            body={"values": stat_rows},
        ).execute()

        # Write formula strings for points columns (USER_ENTERED so Sheets evaluates them).
        formula_rows = [make_formulas(pos, row_num) for row_num in range(2, 2 + n)]
        start_col = FORMULA_START_COL[pos]
        print(f"Writing formulas to '{tab}'!{start_col}2:{start_col}{1 + n}...")
        sheet.values().update(
            spreadsheetId=SHEET_ID,
            range=f"{tab}!{start_col}2",
            valueInputOption="USER_ENTERED",
            body={"values": formula_rows},
        ).execute()

    from datetime import datetime
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("America/New_York"))
    ts = (f"{now.strftime('%B')} {now.day}, "
          f"{now.strftime('%I').lstrip('0')}:{now.strftime('%M')} {now.strftime('%p')}")
    sheet.values().update(
        spreadsheetId=SHEET_ID,
        range="Update Date!B2",
        valueInputOption="RAW",
        body={"values": [[ts]]},
    ).execute()
    print(f"Timestamp written -> 'Update Date'!B2 = {ts}")

    print("Done.")


if __name__ == "__main__":
    main()
