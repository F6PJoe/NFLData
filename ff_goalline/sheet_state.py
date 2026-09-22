"""Shared helper: which week tab is "current" right now, read from the
sheet itself rather than a calendar anchor (unlike ff_defense/current_week.py).
This pipeline is inherently stateful -- each week's tab only exists once
advance_week.py creates it -- so the sheet's own tab list is a more direct
source of truth than a date computation, and needs no yearly maintenance.
"""

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SERVICE_ACCT = str(HERE.parent / "triple-baton-456523-e4-b9ec3cbd6e3d.json")
SHEET_ID = "1q-aklbeGgJ5gC0rdLbSpK7sdemIKEoao37LbooROfkI"

WEEK_TAB_RE = re.compile(r"^W(\d+)$")


def sheets_service():
    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_service_account_file(
        SERVICE_ACCT, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


def latest_week_tab(service):
    """-> highest N among existing "W<N>" tabs."""
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    weeks = [int(m.group(1)) for s in meta["sheets"]
             if (m := WEEK_TAB_RE.match(s["properties"]["title"]))]
    if not weeks:
        raise RuntimeError("No 'W<N>' tabs found on the sheet.")
    return max(weeks)
