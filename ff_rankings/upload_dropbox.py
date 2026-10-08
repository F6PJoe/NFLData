#!/usr/bin/env python3
"""
Upload the half-PPR paste lists to Dropbox, one CSV per list, for the phone.

Built for the GitHub "Weekly rankings (half PPR)" workflow: Joe triggers it
from his phone, then opens the CSVs in Excel mobile and copies each into the
FantasyPros portal. Files land in the Dropbox app's own folder as

    Week 5/1 FLX.csv, 2 QB.csv, ... 7 DST.csv

numbered in paste order, overwritten on every run. There's no header row, so
select-all/copy gives exactly the copy page's rows (rank, name, team, pos).

Needs DROPBOX_APP_KEY, DROPBOX_APP_SECRET and DROPBOX_REFRESH_TOKEN (GitHub
secrets; .env locally). The refresh token never expires; each run trades it
for a short-lived access token.

    python upload_dropbox.py                 # newest weekly/<year>-wk<NN>
    python upload_dropbox.py --week-dir weekly/2026-wk05
"""

import argparse
import csv
import glob
import io
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
    missing = [k for k in ENV_KEYS if not os.environ.get(k)]
    if missing:
        sys.exit(f"Missing {', '.join(missing)} -- add them as GitHub secrets (or to .env).")
    resp = session.post(TOKEN_URL, timeout=30, data={
        "grant_type": "refresh_token",
        "refresh_token": os.environ["DROPBOX_REFRESH_TOKEN"],
        "client_id": os.environ["DROPBOX_APP_KEY"],
        "client_secret": os.environ["DROPBOX_APP_SECRET"],
    })
    resp.raise_for_status()
    return resp.json()["access_token"]


def headerless_csv(path):
    """The paste CSV's rows without its header line, as bytes."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))[1:]
    out = io.StringIO()
    csv.writer(out, lineterminator="\r\n").writerows(rows)
    return out.getvalue().encode("utf-8")


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

    session = requests.Session()
    token = access_token(session)
    for n, (slot, _scoring) in enumerate(wf.paste_order("HALF"), start=1):
        src = os.path.join(week_dir, f"paste_{slot.lower()}.csv")
        if not os.path.exists(src):
            print(f"  {slot}: no paste file in {week_dir} -- skipped")
            continue
        dest = f"/Week {week}/{n} {slot}.csv"
        upload(session, token, dest, headerless_csv(src))
        print(f"  {dest}")


if __name__ == "__main__":
    main()
