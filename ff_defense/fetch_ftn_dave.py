#!/usr/bin/env python3
"""
Pull FTN's DAVE ratings (DVOA Adjusted for Variation Early) from
https://ftnfantasy.com/stats/nfl/dave for every team and write them to a CSV.

Unlike the tools.ftnfantasy.com rankings/projections API (ftn_auth.py
elsewhere in this repo), this page lives on the ftnfantasy.com WordPress
site and is gated by cookies, not a Bearer header: logging in via
api.ftnfantasy.com/users/login (same endpoint, same credentials) returns
access_token/refresh_token/user_id, and setting all THREE as cookies on
domain .ftnfantasy.com is what unlocks the page -- the access_token cookie
alone was not enough (verified: 0 rows with just access_token, 330 <td>s
once all three were set). The page is otherwise fully server-rendered
(a wpDataTables table, tableType "google_spreadsheet") -- no separate
XHR/API call to replicate, unlike the FTN rankings endpoints.

ftnfantasy.com also 403s a bare requests.get with no Referer/Accept
headers (a basic Cloudflare check, not real bot-fingerprinting) -- a
normal browser-like header set clears it.

Credentials: FTN_EMAIL / FTN_PASSWORD, read from a local .env if present,
else falling back to ../ff_rankings/.env (already has them for the
rankings/projections fetchers -- no need to duplicate).

Table columns (confirmed from the live page):
    TEAM, TOT DAVE, Total Rank, OFF DAVE, Off Rank, DEF DAVE, Def Rank,
    ST DAVE, ST Rank, Week
Off Rank and Def Rank are both "1 = best" (e.g. Baltimore's +9.4 OFF DAVE
-> Off Rank 4; Atlanta's -14.8 -> Off Rank 30).

Usage:
    python fetch_ftn_dave.py   # -> ftn_dave.csv

Requires: requests
"""

import argparse
import csv
import os
import re

import requests

LOGIN_URL = "https://api.ftnfantasy.com/users/login"
DAVE_URL = "https://ftnfantasy.com/stats/nfl/dave"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://ftnfantasy.com/",
}

# Pull one row's 10 <td> values in order: TEAM, TOT DAVE, Total Rank, OFF DAVE,
# Off Rank, DEF DAVE, Def Rank, ST DAVE, ST Rank, Week.
ROW_CELLS_RE = re.compile(r'<tr id="table_73_row_\d+"[^>]*>(.*?)</tr>', re.S)
CELL_RE = re.compile(r'<td[^>]*>([^<]*)</td>')

FIELDNAMES = ["Team", "OffDave", "OffRank", "DefDave", "DefRank", "Week"]


def _load_dotenv(path):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def login():
    """Log in and return a requests.Session with the cookies FTN's own site sets on success."""
    _load_dotenv(".env")
    _load_dotenv(os.path.join("..", "ff_rankings", ".env"))
    email = os.environ.get("FTN_EMAIL")
    password = os.environ.get("FTN_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "Set FTN_EMAIL and FTN_PASSWORD (a local .env, or ../ff_rankings/.env) to log in to FTN."
        )

    resp = requests.post(
        LOGIN_URL, json={"email": email, "password": password},
        headers={"Content-Type": "application/json", "User-Agent": HEADERS["User-Agent"]},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("status") != "success":
        raise RuntimeError(f"FTN login failed: {data.get('status')!r}")

    session = requests.Session()
    for name in ("access_token", "refresh_token", "user_id"):
        session.cookies.set(name, str(data[name]), domain=".ftnfantasy.com")
    return session


def fetch_rows(session):
    resp = session.get(DAVE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text

    rows = []
    for m in ROW_CELLS_RE.finditer(html):
        cells = CELL_RE.findall(m.group(1))
        if len(cells) != 10:
            continue
        team, _tot_dave, _tot_rank, off_dave, off_rank, def_dave, def_rank, _st_dave, _st_rank, week = cells
        rows.append({
            "Team": team,
            "OffDave": float(off_dave),
            "OffRank": int(off_rank),
            "DefDave": float(def_dave),
            "DefRank": int(def_rank),
            "Week": int(week),
        })
    return rows


def write_csv(rows, out_file):
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="ftn_dave.csv")
    args = ap.parse_args()

    session = login()
    rows = fetch_rows(session)
    if len(rows) < 32:
        raise SystemExit(
            f"Only found {len(rows)} team rows (expected 32) -- login likely failed "
            "or FTN's markup changed."
        )

    write_csv(rows, args.out)
    print(f"Week {rows[0]['Week']}: wrote {len(rows)} teams to {args.out}.")


if __name__ == "__main__":
    main()
