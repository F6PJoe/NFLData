#!/usr/bin/env python3
"""
Pull CBS Sports fantasy ADP from their public draft averages page.

Data is server-rendered HTML — no XHR call, no login needed.

URL pattern:
  https://www.cbssports.com/fantasy/football/draft/averages/{scoring}/{pos}/{format}/all/
  scoring : ppr | standard | half
  pos     : both (all positions) | QB | RB | WR | TE | K | DST
  format  : h2h | roto

Usage:
    python fetch_cbs_adp.py                        # PPR, all -> cbs_adp.csv
    python fetch_cbs_adp.py --scoring standard
    python fetch_cbs_adp.py --html-file saved.html # offline parse

Requires: requests, beautifulsoup4, lxml
"""

import argparse
import csv
import sys

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.cbssports.com/fantasy/football/draft/averages/{scoring}/{pos}/{fmt}/all/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_html(scoring="ppr", pos="both", fmt="h2h", html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    url = BASE_URL.format(scoring=scoring, pos=pos, fmt=fmt)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse(html):
    """
    CBS table layout (6 tds per row):
      td[0] rank | td[1] player blob | td[2] trend icon
      td[3] ADP  | td[4] drafted     | td[5] %

    td[1] contains two <a> tags — the second one is the full-name link.
    Inside that link the text order is: FullName + Position + Team,
    all run together, so we pull name/pos/team from the <a> sub-elements.
    """
    soup = BeautifulSoup(html, "lxml")
    rows = []
    for tr in soup.select("tr"):
        tds = tr.find_all("td")
        if len(tds) < 4:
            continue

        # td[0] should be a rank integer
        try:
            int(tds[0].get_text(strip=True))
        except ValueError:
            continue

        # td[3] is ADP
        adp_raw = tds[3].get_text(strip=True)
        try:
            adp = round(float(adp_raw), 2)
        except ValueError:
            continue
        if adp <= 0:
            continue

        # td[1]: full name is inside span.CellPlayerName--long
        long_span = tds[1].select_one("span.CellPlayerName--long")
        if not long_span:
            continue
        player_a = long_span.find("a")
        if not player_a:
            continue
        player = player_a.get_text(strip=True)
        pos_text  = (long_span.select_one("span.CellPlayerName-position") or {}).get_text(strip=True) if hasattr(long_span.select_one("span.CellPlayerName-position"), "get_text") else ""
        team_text = (long_span.select_one("span.CellPlayerName-team") or {}).get_text(strip=True) if hasattr(long_span.select_one("span.CellPlayerName-team"), "get_text") else ""

        rows.append({
            "Player":      player,
            "Position(s)": pos_text,
            "Team":        team_text,
            "CBS":         adp,
        })

    rows.sort(key=lambda r: r["CBS"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scoring", default="ppr", choices=["ppr", "standard", "half"])
    ap.add_argument("--pos",     default="both")
    ap.add_argument("--fmt",     default="h2h")
    ap.add_argument("-o", "--output", default="cbs_adp.csv")
    ap.add_argument("--html-file")
    args = ap.parse_args()

    html = fetch_html(scoring=args.scoring, pos=args.pos, fmt=args.fmt,
                      html_file=args.html_file)
    rows = parse(html)

    if not rows:
        sys.exit("No players found — CBS page structure may have changed.")

    fieldnames = ["Player", "Position(s)", "Team", "CBS"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} players to {args.output}.")


if __name__ == "__main__":
    main()
