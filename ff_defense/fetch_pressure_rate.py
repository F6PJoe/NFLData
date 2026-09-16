#!/usr/bin/env python3
"""
Pull each team's pressure rate ALLOWED (how often their own offensive line
lets the QB get pressured) from Sharp Football Analysis
(sharpfootballanalysis.com/stats-nfl/nfl-offensive-line-stats/), and rank
all 32 -- highest pressure rate allowed (worst pass protection) = 32,
lowest = 1, per Joe's spec.

Joe originally used pro-football-reference.com's Pressure tab, which now
sits behind a real Cloudflare "Verify you are human" challenge that isn't
reliably clickable by automation. FTN's Stats iQ tool (an earlier
alternative tried here) turned out too noisy to use: this early in the
season it only has 1 game logged per team, and Denver/Kansas City's game
against each other specifically wasn't fully charted yet (both showed a
suspicious flat 0% - confirmed by cross-checking PFR's own row for that
game, which had PktTime/Blitz/Hrry all exactly 0 too, the same anomaly).
Joe ruled FTN out for this lag.

Sharp doesn't show that gap and is a plain public, server-rendered page
(a wpDataTables table again, but NOT paywalled here -- no login, no
Cloudflare challenge, confirmed live with a plain `requests.get`).

Note for later: Sharp's own numbers don't closely match PFR's either
beyond the extremes (both agree Green Bay is worst, both have the 49ers
near the top) -- "pressure" is a subjectively-charted stat, not an
official boxscore number, so real disagreement between sources is
expected and won't resolve as the season goes on. This is simply the
source Joe picked given FTN's specific data-lag problem.

Usage:
    python fetch_pressure_rate.py   # -> pressure_rate.csv

Requires: requests
"""

import argparse
import csv
import re

import requests

from team_names import nickname_to_abbr

URL = "https://www.sharpfootballanalysis.com/stats-nfl/nfl-offensive-line-stats/"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

# <tr id="table_85_row_N" ...><td>Team</td><td>Pressure Rate Allowed</td>...</tr>
ROW_RE = re.compile(
    r'<tr id="table_85_row_\d+"[^>]*>\s*<td[^>]*>([^<]+)</td>\s*<td[^>]*>([\-0-9.]+)</td>',
)

FIELDNAMES = ["Rank", "Team", "PressureRate"]


def fetch_rows():
    resp = requests.get(URL, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    html = resp.text
    return [{"Team": nickname_to_abbr(team), "PressureRate": float(rate)}
             for team, rate in ROW_RE.findall(html)]


def rank_rows(rows):
    ranked = sorted(rows, key=lambda r: r["PressureRate"])  # ascending: lowest first
    out = []
    for i, r in enumerate(ranked, start=1):
        out.append({"Rank": i, "Team": r["Team"], "PressureRate": r["PressureRate"]})
    return out


def write_csv(rows, out_file):
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="pressure_rate.csv")
    args = ap.parse_args()

    rows = fetch_rows()
    if len(rows) < 28:
        raise SystemExit(
            f"Only found {len(rows)} teams (expected ~32) -- Sharp's markup may have changed."
        )

    out_rows = rank_rows(rows)
    write_csv(out_rows, args.out)
    print(f"Wrote {len(out_rows)} teams to {args.out} "
          f"(rank 1 = lowest pressure rate allowed, {len(out_rows)} = highest).")


if __name__ == "__main__":
    main()
