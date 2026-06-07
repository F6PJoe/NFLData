#!/usr/bin/env python3
"""
Pull FFPC ADP from myffpc.com/FFPCADPReport.ashx.

The endpoint returns XML with <player> elements, each carrying:
  name, nflTeam, position, adp (decimal), min, max, leaguesDraftedIn

Date window defaults to the past 7 days (rolling), matching what the
FFPC ADP page uses.  Pass --days N to widen/narrow the window.

Usage:
    python fetch_ffpc_adp.py               # live fetch -> ffpc_adp.csv
    python fetch_ffpc_adp.py --days 14
    python fetch_ffpc_adp.py --xml-file saved.xml   # offline parse

Requires: requests
"""

import argparse
import csv
import datetime
import sys
import xml.etree.ElementTree as ET

import requests

BASE_URL = "https://myffpc.com/FFPCADPReport.ashx"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (personal ADP consensus tool)",
    "Referer": "https://myffpc.com/cms/public/ffpc-league-and-tournament-adp",
}

DATE_FMT = "%d%b%Y"   # e.g. 28May2026


def date_params(days=7):
    today = datetime.date.today()
    start = today - datetime.timedelta(days=days)
    return {
        "draftStartDateFrom": start.strftime(DATE_FMT),
        "draftStartDateTo":   today.strftime(DATE_FMT),
    }


def fetch_xml(days=7, xml_file=None):
    if xml_file:
        with open(xml_file, encoding="utf-8") as f:
            return f.read()
    params = {
        "leagueTypeID":    "1",
        "superflexFilter": "0",
        "slimRostersFilter": "0",
        **date_params(days),
    }
    resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse(xml_text):
    root = ET.fromstring(xml_text)
    rows = []
    for p in root.iter("player"):
        adp_raw = p.get("adp", "")
        try:
            adp = round(float(adp_raw), 2)
        except ValueError:
            continue
        if adp <= 0:
            continue
        rows.append({
            "Player":      p.get("name", ""),
            "Position(s)": p.get("position", ""),
            "Team":        p.get("nflTeam", ""),
            "FFPC":        adp,
        })
    rows.sort(key=lambda r: r["FFPC"])
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7,
                    help="Rolling window of drafts (default 7 days)")
    ap.add_argument("-o", "--output", default="ffpc_adp.csv")
    ap.add_argument("--xml-file", help="Parse a saved XML response instead of fetching")
    args = ap.parse_args()

    xml_text = fetch_xml(days=args.days, xml_file=args.xml_file)
    rows = parse(xml_text)

    if not rows:
        sys.exit("No players found — check the XML or widen --days.")

    fieldnames = ["Player", "Position(s)", "Team", "FFPC"]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} players to {args.output}.")


if __name__ == "__main__":
    main()
