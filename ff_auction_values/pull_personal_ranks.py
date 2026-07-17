#!/usr/bin/env python3
"""
Download Joe Bond's personal rankings CSVs from the shared Google Drive
folder and save them as ff_cheatsheet/joe_bond_<fmt>.csv -- the exact files
build_auction_values.py's load_personal_ranks() reads.

This is the same Drive source ff_cheatsheet/update_joe_bond_ranks.py pulls
from, using the same Google service account credentials (already a GitHub
Secret, GOOGLE_SERVICE_ACCOUNT) -- but unlike that script, this one does
NOT touch the local Excel workbook (win32com isn't available on GitHub
Actions' Linux runners, and isn't needed here anyway). It saves the raw
downloaded CSV bytes as-is: the Drive file's wide multi-block format
(Overall/QB/RB/WR/TE/... columns side by side) is already exactly what
load_personal_ranks() parses, so no reformatting is needed.

Lets the daily automated workflow pick up Joe's current rankings on every
run instead of relying on a manually-pushed snapshot.

Usage:
    python pull_personal_ranks.py
"""

import io
from pathlib import Path

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

BASE = Path(__file__).resolve().parent.parent
SERVICE_ACCT = BASE / "ff_draft_proj" / "triple-baton-456523-e4-b9ec3cbd6e3d.json"
OUT_DIR = BASE / "ff_cheatsheet"

# Same Drive file IDs as ff_cheatsheet/update_joe_bond_ranks.py
# (folder: https://drive.google.com/drive/u/0/folders/1mPmJprvfUfWMG0sPbqE_mBsItv2foM7n)
FILES = {
    "half_ppr": "1Hcve5KKV3BHzg2zbbk7jq90TvHxivoFI",
    "ppr": "1M4ybR_UtAsiOv-HfXk1xqGMDyfwAO-xq",
    "standard": "1yfBiu27-328aEG5Bri6t33gQXQBbwlNG",
}


def main():
    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    drive_svc = build("drive", "v3", credentials=creds, cache_discovery=False)

    OUT_DIR.mkdir(exist_ok=True)
    for fmt, file_id in FILES.items():
        req = drive_svc.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        dl = MediaIoBaseDownload(buf, req)
        done = False
        while not done:
            _, done = dl.next_chunk()

        out_path = OUT_DIR / f"joe_bond_{fmt}.csv"
        out_path.write_bytes(buf.getvalue())
        print(f"  {fmt}: wrote {out_path} ({len(buf.getvalue()) / 1024:.0f} KB)")


if __name__ == "__main__":
    main()
