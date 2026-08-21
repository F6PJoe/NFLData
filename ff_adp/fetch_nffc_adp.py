#!/usr/bin/env python3
"""
Pull NFFC (and BB10s) ADP from nfc.shgn.com/adp.data.php.

The endpoint returns an HTML fragment of <tr> rows.  Each row carries:
  - player name  : <a class="PlayerLinkV"> text (strip inner tags)
  - team         : 3rd <td> text
  - position     : 4th <td> text  (primary position)
  - ADP          : 5th <td> sort-value attribute  (true decimal)

Usage:
    python fetch_nffc_adp.py               # NFFC -> nffc_adp.csv
    python fetch_nffc_adp.py --contest bb10s  -> bb10s_adp.csv
    python fetch_nffc_adp.py --html-file saved.html  # offline parse

Requires: requests, beautifulsoup4, lxml
"""

import argparse
import csv
import sys
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://nfc.shgn.com/adp.data.php"
DATE_FMT = "%m/%d/%Y"
ROLLING_DAYS = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal ADP consensus tool)",
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Referer": "https://nfc.shgn.com/adp/football",
}

# Base POST body observed from browser DevTools (football, no filters)
BASE_PAYLOAD = {
    "team_id":      "0",
    "from_date":    "",
    "to_date":      "",
    "num_teams":    "0",
    "draft_type":   "0",
    "sport":        "football",
    "position":     "",
    "league_teams": "0",
}

# Map contest slug -> output column name, filename, and any payload overrides
# BB10s overrides will be filled in once we capture that payload
CONTEST_MAP = {
    "nffc":    ("NFFC",         "nffc_adp.csv",         {}),
    "bb10s":   ("BB10s",        "bb10s_adp.csv",        {"draft_type": "969"}),
    "cutline": ("NFFC Cutline", "nffc_cutline_adp.csv", {"draft_type": "942"}),
}


def fetch_html(payload_overrides=None, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    today = datetime.now()
    from_date = (today - timedelta(days=ROLLING_DAYS)).strftime(DATE_FMT)
    to_date   = today.strftime(DATE_FMT)
    payload = dict(BASE_PAYLOAD)
    payload["from_date"] = from_date
    payload["to_date"]   = to_date
    if payload_overrides:
        payload.update(payload_overrides)
    print(f"  Date range: {from_date} – {to_date}")
    resp = requests.post(BASE_URL, data=payload, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse(html, col_name):
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 5:
            continue
        # Player name: anchor text minus any nested tag text
        anchor = tds[1].find("a", class_="PlayerLinkV")
        if not anchor:
            continue
        # Strip inner elements (sharplink-player etc.) and get remaining text
        for inner in anchor.find_all(True):
            inner.decompose()
        player = anchor.get_text(strip=True)
        if not player:
            continue

        team = tds[2].get_text(strip=True)
        pos  = tds[3].get_text(strip=True)

        adp_td = tds[4]
        adp_raw = adp_td.get("sort-value", "").strip()
        try:
            adp = round(float(adp_raw), 2)
        except ValueError:
            continue
        if adp <= 0:
            continue

        rows.append({
            "Player":     player,
            "Position(s)": pos,
            "Team":       team,
            col_name:     adp,
        })

    rows.sort(key=lambda r: r[col_name])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--contest",
        default="nffc",
        choices=list(CONTEST_MAP.keys()),
        help="nffc (default), bb10s, or cutline",
    )
    ap.add_argument("-o", "--output", default=None, help="Override output filename")
    ap.add_argument("--html-file", help="Parse a saved HTML response instead of fetching")
    args = ap.parse_args()

    col_name, default_out, overrides = CONTEST_MAP[args.contest]
    out_file = args.output or default_out

    html = fetch_html(payload_overrides=overrides, html_file=args.html_file)
    rows = parse(html, col_name)

    if not rows:
        sys.exit("No players found — check the HTML or contest param.")

    fieldnames = ["Player", "Position(s)", "Team", col_name]
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} players to {out_file}.")


if __name__ == "__main__":
    main()
