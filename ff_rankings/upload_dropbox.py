#!/usr/bin/env python3
"""
Upload the half-PPR rankings workbook to Dropbox, for the phone.

Built for the GitHub "Weekly rankings (half PPR)" workflow: Joe triggers it
from his phone, opens the workbook in Excel mobile and copies each tab into
the FantasyPros portal. It lands in the Dropbox app's own folder as

    Week 5/Week 5 Half PPR.xlsx

overwritten on every run. It's run_weekly.py's rankings_half.xlsx: one tab per
list in paste order, a header row naming each ranker (with update time), then
Rank/Player/Team/Position in A-D -- what Joe copies, skipping the header --
and each ranker's own rank to the right, so he can see who's included.

Needs DROPBOX_APP_KEY, DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN (GitHub
secrets; .env locally). The refresh token never expires; each run trades it
for a short-lived access token.

    python upload_dropbox.py                 # newest weekly/<year>-wk<NN>
    python upload_dropbox.py --week-dir weekly/2026-wk05
"""

import argparse
import glob
import json
import os
import re
import sys

import requests

import weekly_freshness as wf

TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
UPLOAD_URL = "https://content.dropboxapi.com/2/files/upload"
ENV_KEYS = ("DROPBOX_APP_KEY", "DROPBOX_APP_SECRET", "DROPBOX_REFRESH_TOKEN")


def access_token(session):
    wf._load_dotenv()
    # Pasted secrets often carry a stray space, newline or the JSON's quotes.
    env = {k: os.environ.get(k, "").strip().strip('"').strip() for k in ENV_KEYS}
    missing = [k for k, v in env.items() if not v]
    if missing:
        sys.exit(f"Missing {', '.join(missing)} -- add them as GitHub secrets (or to .env).")
    if env["DROPBOX_REFRESH_TOKEN"].startswith("sl."):
        sys.exit("DROPBOX_REFRESH_TOKEN starts with 'sl.' -- that's the 4-hour "
                 "access_token. Save the refresh_token value instead.")
    resp = session.post(TOKEN_URL, timeout=30, data={
        "grant_type": "refresh_token",
        "refresh_token": env["DROPBOX_REFRESH_TOKEN"],
        "client_id": env["DROPBOX_APP_KEY"],
        "client_secret": env["DROPBOX_APP_SECRET"],
    })
    if not resp.ok:
        # Dropbox's error body names the bad piece (invalid_client = key or
        # secret, invalid_grant = refresh token) and never echoes a secret.
        sys.exit(f"Dropbox refused the token exchange ({resp.status_code}): {resp.text}")
    return resp.json()["access_token"]


def upload(session, token, dropbox_path, data):
    resp = session.post(UPLOAD_URL, data=data, timeout=60, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/octet-stream",
        "Dropbox-API-Arg": json.dumps({"path": dropbox_path, "mode": "overwrite",
                                       "mute": True}),
    })
    resp.raise_for_status()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--week-dir", help="defaults to the newest weekly/<year>-wk<NN>")
    ap.add_argument("--out-root", default="weekly")
    args = ap.parse_args()

    week_dir = args.week_dir or max(
        (d for d in glob.glob(os.path.join(args.out_root, "*-wk*")) if os.path.isdir(d)),
        default=None)
    if not week_dir:
        sys.exit(f"No week directory under {args.out_root}/")
    week = int(re.search(r"wk(\d+)", os.path.basename(os.path.normpath(week_dir))).group(1))

    book = os.path.join(week_dir, "rankings_half.xlsx")
    if not os.path.exists(book):
        sys.exit(f"No rankings_half.xlsx in {week_dir} -- is openpyxl installed?")

    session = requests.Session()
    token = access_token(session)
    dest = f"/Week {week}/Week {week} Half PPR.xlsx"
    with open(book, "rb") as f:
        upload(session, token, dest, f.read())
    print(f"  {dest}")


if __name__ == "__main__":
    main()
