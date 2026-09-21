#!/usr/bin/env python3
"""
Pull RTSports (RealTime Fantasy Sports) ADP from their adp-aav-provider
endpoint on rtsports.com. No login required.

Previously pointed at the same endpoint on freedraftguide.com, which went
behind a site-wide Cloudflare JS challenge in Aug 2026 (403 "Just a moment..."
to any scripted request, including the homepage). RTSports confirmed the
rtsports.com host as the one to use — same JSON, no challenge.

Usage:
    python fetch_rts_adp.py                 # live fetch -> rts_adp.csv
    python fetch_rts_adp.py --json-file saved.json   # offline parse

Requires: requests
"""

import argparse
import csv
import json
import sys

import requests

# Canonical host, given to us by RTSports directly. The equivalent
# freedraftguide.com endpoint sits behind a site-wide Cloudflare JS challenge
# (added ~Aug 2026 to keep AI scrapers out) and returns 403 to any plain HTTP
# request; rtsports.com serves the same JSON with no challenge.
URL = "https://www.rtsports.com/football/adp-aav-provider.php"

PARAMS = {
    "NUM": "500",
    "AAV": "0",
    "STYLE": "0",
    "CHANGE": "7",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal ADP consensus tool)",
    "Referer": "https://www.rtsports.com/",
}


def fetch_json(json_file=None):
    if json_file:
        with open(json_file, encoding="utf-8") as f:
            return json.load(f)
    resp = requests.get(URL, params=PARAMS, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.json()


def parse(data):
    rows = []
    for p in data.get("player_list", []):
        try:
            adp = round(float(p["avg"]), 2)
        except (KeyError, ValueError):
            continue
        if adp <= 0:
            continue
        rows.append({
            "Player":      p.get("name", ""),
            "Position(s)": p.get("position", ""),
            "Team":        p.get("team", ""),
            "RTSports":    adp,
        })
    rows.sort(key=lambda r: r["RTSports"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--output", default="rts_adp.csv")
    ap.add_argument("--json-file", help="Parse a saved JSON response instead of fetching")
    args = ap.parse_args()

    data = fetch_json(json_file=args.json_file)
    rows = parse(data)

    if not rows:
        sys.exit("No players found — check the JSON response.")

    fieldnames = ["Player", "Position(s)", "Team", "RTSports"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} players to {args.output}.")


if __name__ == "__main__":
    main()
