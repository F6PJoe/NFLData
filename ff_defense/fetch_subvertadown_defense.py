#!/usr/bin/env python3
"""
Pull Subvertadown's weekly D/ST projections from
https://subvertadown.com/weekly/defense and write each team's inverted
defense rank (worst projected defense = 1, best on a non-bye week = the
number of teams with a game that week) to a CSV.

The page is server-rendered (no separate XHR for the table), but logged
out it only renders 2 of the ~32 rows -- the rest require a Standard-tier
account. Login is a plain Laravel form POST (no Livewire involved in auth
itself): GET /login for a CSRF token, POST email/password/_token, then the
same session's GET /weekly/defense comes back with every team's row.

Credentials come from SUBVERTADOWN_EMAIL / SUBVERTADOWN_PASSWORD, loaded
from a local .env (never committed; see .env.example).

Each row looks like:
    <tr id="row-TB" class="sub-table-row">
      <td class="-sticky">
        <span class="font-bold">Buccaneers</span>
        <span class="font-normal">vs. Browns</span>
      </td>
      ...
      <span class="block dark:text-gray-100">9.6</span>   <- this week's projection
      ...

9.6 is the team's projected D/ST fantasy points for the week (ESPN
scoring, the page's default) -- higher is a better projected defense.
The inverted rank sorts ascending by that value: the lowest projection
gets rank 1 (worst), the highest gets rank N (best), where N is however
many teams have a game that week (bye teams simply have no row).

"vs." means the row's own team is home (opponent traveled to them); "@"
means the row's own team is away. The Opp column reproduces that same
convention with abbreviations instead of full names -- e.g. Buccaneers'
row (home vs. Browns) writes "CLE" with no "@", while Browns' own row
(away @ Buccaneers) writes "@TB" -- using each team's own row id (e.g.
"row-TB") as the abbreviation, so no separate name-to-code table is
needed.

Usage:
    python fetch_subvertadown_defense.py   # -> subvertadown_defense.csv

Requires: requests
"""

import argparse
import csv
import os
import re
import sys

import requests

BASE = "https://subvertadown.com"
LOGIN_URL = f"{BASE}/login"
DEFENSE_URL = f"{BASE}/weekly/defense"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

ROW_START_RE = re.compile(r'<tr id="row-([A-Z]+)" class="sub-table-row">')
NAME_RE = re.compile(r'font-bold">\s*([A-Za-z0-9. ]+?)\s*</span>')
OPP_RE = re.compile(r'font-normal">\s*(vs\.|@)\s*([A-Za-z0-9. ]+?)\s*</span>', re.S)
VALUE_RE = re.compile(r'class="block dark:text-gray-100">\s*([\-0-9.]+)\s*</span>')
WEEK_RE = re.compile(r'&quot;week&quot;:(\d+)')
CSRF_RE = re.compile(r'<meta name="csrf-token" content="([^"]+)"')

FIELDNAMES = ["Rank", "Team", "Value", "Opp", "Week"]


def _load_dotenv(path=".env"):
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


def login(session):
    _load_dotenv()
    email = os.environ.get("SUBVERTADOWN_EMAIL")
    password = os.environ.get("SUBVERTADOWN_PASSWORD")
    if not email or not password:
        raise RuntimeError(
            "Set SUBVERTADOWN_EMAIL and SUBVERTADOWN_PASSWORD (e.g. in a local "
            ".env file, see .env.example) to log in to Subvertadown."
        )

    resp = session.get(LOGIN_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    m = CSRF_RE.search(resp.text)
    if not m:
        raise RuntimeError("Couldn't find a csrf-token meta tag on the login page -- site markup may have changed.")
    token = m.group(1)

    resp = session.post(
        LOGIN_URL,
        data={"_token": token, "email": email, "password": password},
        headers={**HEADERS, "Referer": LOGIN_URL, "X-CSRF-TOKEN": token},
        timeout=30,
    )
    resp.raise_for_status()

    # A 200 here doesn't guarantee a real login -- Laravel re-renders the
    # login page (still 200) on bad credentials, and a Cloudflare challenge
    # page is also a 200. Surface enough to tell those apart without
    # printing anything sensitive.
    print(f"[login] POST {LOGIN_URL} -> {resp.status_code}, landed on {resp.url}")
    if "/login" in resp.url:
        print("[login] WARNING: redirected back to /login -- credentials were likely rejected.")
    if "Just a moment" in resp.text or "cf-chl" in resp.text or "challenges.cloudflare.com" in resp.text:
        print("[login] WARNING: response looks like a Cloudflare challenge page, not the real site.")
    if "These credentials do not match" in resp.text or "credentials do not match" in resp.text.lower():
        print("[login] WARNING: page shows a 'credentials do not match' validation error.")
    cookie_names = sorted(c.name for c in session.cookies)
    print(f"[login] session cookies set: {cookie_names}")


def fetch_rows(session):
    resp = session.get(DEFENSE_URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text

    starts = [m.start() for m in ROW_START_RE.finditer(html)]
    starts.append(len(html))

    rows = []
    week = None
    for i in range(len(starts) - 1):
        block = html[starts[i]:starts[i + 1]]
        header_m = ROW_START_RE.match(block)
        name_m = NAME_RE.search(block)
        opp_m = OPP_RE.search(block)
        val_m = VALUE_RE.search(block)
        if not (name_m and val_m):
            continue
        if week is None:
            week_m = WEEK_RE.search(block)
            if week_m:
                week = int(week_m.group(1))
        rows.append({
            "abbr": header_m.group(1),
            "team": name_m.group(1),
            "away": bool(opp_m) and opp_m.group(1) == "@",
            "opponent": opp_m.group(2) if opp_m else "",
            "value": float(val_m.group(1)),
        })

    # e.g. "Buccaneers" -> "TB", used to abbreviate the opponent column too.
    abbr_by_team = {r["team"]: r["abbr"] for r in rows}
    for r in rows:
        opp_abbr = abbr_by_team.get(r["opponent"], r["opponent"])
        r["opp"] = f"@{opp_abbr}" if r["away"] else opp_abbr

    return rows, week


def build_ranked_rows(rows, week):
    ranked = sorted(rows, key=lambda r: r["value"])  # ascending: worst first
    out = []
    for i, r in enumerate(ranked, start=1):
        out.append({
            "Rank": i,
            "Team": r["team"],
            "Value": r["value"],
            "Opp": r["opp"],
            "Week": week,
        })
    return out


def write_csv(out_rows, out_file):
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(out_rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="subvertadown_defense.csv")
    args = ap.parse_args()

    session = requests.Session()
    login(session)

    rows, week = fetch_rows(session)
    if len(rows) <= 2:
        sys.exit(
            f"Only found {len(rows)} team row(s) -- login likely failed (check "
            "SUBVERTADOWN_EMAIL/SUBVERTADOWN_PASSWORD) or Subvertadown's markup changed."
        )

    out_rows = build_ranked_rows(rows, week)
    write_csv(out_rows, args.out)
    print(f"Week {week}: wrote {len(out_rows)} teams to {args.out} "
          f"(rank 1 = worst projected D/ST, rank {len(out_rows)} = best).")


if __name__ == "__main__":
    main()
