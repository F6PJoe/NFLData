#!/usr/bin/env python3
"""
Pull Joe Bond's overall draft rankings (PPR / Half-PPR / Standard CSVs from a
shared Google Drive folder) and write them into the "Joe Bond Ranks" tab of
the live Cheat Sheet workbook.

Each Drive CSV has an "Overall" block in columns A-D (Name, Team, Position,
Player ID); only Name/Team are used here. The Joe Bond Ranks tab layout is:

    A:C = Half-PPR (Player, Team, Rank)
    E:G = PPR      (Player Name, Team, Rank)
    I:K = STD      (Player Name, Team, Rank)

Rank is just the row's position in the CSV's Overall list (1-based). Rows
beyond the new data's length are cleared if the previous run had more rows.

Usage:
    python update_joe_bond_ranks.py
"""

import csv
import io
import re
import unicodedata

from pathlib import Path

import win32com.client as win32
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

BASE = Path(__file__).resolve().parent.parent
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm"
SERVICE_ACCT = BASE / "triple-baton-456523-e4-b9ec3cbd6e3d.json"

# Drive file IDs (folder: https://drive.google.com/drive/u/0/folders/1mPmJprvfUfWMG0sPbqE_mBsItv2foM7n)
FILES = {
    "half_ppr": "1Hcve5KKV3BHzg2zbbk7jq90TvHxivoFI",
    "ppr": "1M4ybR_UtAsiOv-HfXk1xqGMDyfwAO-xq",
    "standard": "1yfBiu27-328aEG5Bri6t33gQXQBbwlNG",
}

# label -> first column (Player) of its block on the Joe Bond Ranks tab
START_COL = {
    "half_ppr": "A",
    "ppr": "E",
    "standard": "I",
}

xlUp = -4162

# JB CSV name → Cheat Sheet canonical name (when norm() alone can't resolve)
JB_RENAMES = {
    'Cam Ward': 'Cameron Ward',
    'Chig Okonkwo': 'Chigoziem Okonkwo',
    'Tank Dell': 'Nathaniel Dell',
    'Hollywood Brown': 'Marquise Brown',
    'Chris Brooks': 'Christopher Brooks',
}


def normalise_name(name):
    name = unicodedata.normalize("NFD", str(name)).encode("ascii", "ignore").decode()
    name = re.sub(r"['.]", "", name.lower())
    name = name.replace("-", " ")
    name = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\s*$", "", name)
    return name.strip()


def fetch_overall(drive_svc, file_id):
    """Download a Drive CSV and return its Overall [Name, Team] rows."""
    req = drive_svc.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    dl = MediaIoBaseDownload(buf, req)
    done = False
    while not done:
        _, done = dl.next_chunk()

    text = buf.getvalue().decode("utf-8")
    rows = list(csv.reader(io.StringIO(text)))
    return [(r[0], r[1]) for r in rows[2:] if r[0].strip()]


def main():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    drive_svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    ranks = {label: fetch_overall(drive_svc, fid) for label, fid in FILES.items()}
    for label, rows in ranks.items():
        print(f"  {label}: {len(rows)} players")

    excel = win32.gencache.EnsureDispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        wb = excel.Workbooks.Open(str(WORKBOOK))
        try:
            # Build name map from the Cheat Sheet tab (normalised -> canonical spelling)
            cs = wb.Sheets("Cheat Sheet")
            cs_last = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
            cheat_names = {}
            for r in range(2, cs_last + 1):
                v = cs.Cells(r, 1).Value
                if v:
                    cheat_names[normalise_name(v)] = v

            def align(name):
                # Check explicit rename map first, then norm-based Cheat Sheet lookup
                canonical = JB_RENAMES.get(name) or JB_RENAMES.get(name.strip())
                if canonical:
                    return canonical
                return cheat_names.get(normalise_name(name), name)

            sh = wb.Sheets("Joe Bond Ranks")
            for label, rows in ranks.items():
                col = START_COL[label]
                col2 = chr(ord(col) + 1)
                col3 = chr(ord(col) + 2)

                old_last_row = sh.Cells(sh.Rows.Count, col).End(xlUp).Row
                new_last_row = 1 + len(rows)

                values = [[align(name), team, i + 1] for i, (name, team) in enumerate(rows)]
                sh.Range(f"{col}2:{col3}{new_last_row}").Value = values

                if new_last_row < old_last_row:
                    sh.Range(f"{col}{new_last_row + 1}:{col3}{old_last_row}").ClearContents()

                print(f"  {label}: wrote {len(rows)} rows to {col}:{col3} (was {old_last_row - 1})")

            wb.Save()
            print("Saved.")
        finally:
            wb.Close(SaveChanges=False)
    finally:
        excel.Quit()


if __name__ == "__main__":
    main()
