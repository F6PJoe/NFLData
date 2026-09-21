#!/usr/bin/env python3
"""
Pull Draft Sharks' half-PPR rankings (overall + per position) from
https://www.draftsharks.com/rankings/half-ppr.

No login required — unlike Draft Sharks' *projections* view
(fetch_draftsharks_projections.py in ff_draft_proj, which does require a
session), the rankings view's htmx endpoint is publicly reachable logged
out:

  GET /rankings/load-table
    ?pprSuperflexSlug=half-ppr&fantasyPosition=<""|QB|RB|WR|TE|FLEX>
    &researchDepth=rankings&playerGroup=all&sort=&selectedTeam=
    &playerSearchTerm=

`fantasyPosition=""` (empty) gives the cross-positional overall ranking
(includes DST/K/IDP rows too — filtered out here, keeping QB/RB/WR/TE).
`fantasyPosition=FLEX` (not "FLX") gives a cross-positional RB/WR/TE-only
ranking. Confirmed both by reading the literal `handleFantasyPositionChange`
button values in the rankings page's own HTML/Alpine.js markup.

Each player is one `<tbody data-player-row ... data-fantasy-position="RB"
data-player-name="..." data-team-id="...">` block; rank is the first
`<span>N</span>` inside it, team is read from the `<img
src="/img/icons/teams/<ABBR>.svg">` badge.

The page itself reports an ISO last-updated timestamp
(`<time class="tool-page-header__last-updated-time" datetime="...">`),
printed here so staleness can be checked before trusting a pull.

Each run fetches all 3 real scoring formats — `pprSuperflexSlug=half-ppr`
(half), `=ppr` (PPR), and `=""` empty (Standard) — confirmed distinct (not
just half-PPR repeated) by checking real movement: Derrick Henry (low
targets) rises and Christian McCaffrey (heavy receiver) falls going from
half to the empty-slug "Standard" fetch, in the correct direction. Writes
`<prefix>_<slot>.csv` (half), `_ppr.csv`, `_std.csv`.

Usage:
    python fetch_draftsharks_rankings.py   # -> draftsharks_ovr.csv / _qb / _rb / _wr / _te / _flx.csv x3 formats

Requires: requests
"""

import argparse
import csv
import re
import sys

import requests

import source_timestamps

BASE = "https://www.draftsharks.com"
LOAD_TABLE_URL = f"{BASE}/rankings/load-table"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

TEAM_ALIASES = {"LVR": "LV", "WAS": "WSH", "JAC": "JAX"}

# our position label -> Draft Sharks' fantasyPosition query value
POSITION_PARAM = {"OVR": "", "QB": "QB", "RB": "RB", "WR": "WR", "TE": "TE", "FLX": "FLEX"}
OUT_NAME = {"OVR": "ovr", "QB": "qb", "RB": "rb", "WR": "wr", "TE": "te", "FLX": "flx"}
FIELDNAMES = ["Rank", "Player", "Team", "Position"]

# our scoring label -> Draft Sharks' pprSuperflexSlug query value
SCORING_SLUG = {"HALF": "half-ppr", "PPR": "ppr", "STD": ""}
SCORING_SUFFIX = {"HALF": "", "PPR": "_ppr", "STD": "_std"}

ROW_RE = re.compile(
    r'<tbody\s+data-player-row.*?data-fantasy-position="([^"]+)".*?'
    r'data-player-name="([^"]+)".*?data-team-id="(\d+)"',
    re.S,
)
RANK_RE = re.compile(r'rank-index">\s*<span>(\d+)</span>')
TEAM_IMG_RE = re.compile(r'team-badge"\s*\n?\s*src="/img/icons/teams/([A-Z]+)\.svg')
TIMESTAMP_RE = re.compile(r'tool-page-header__last-updated-time"\s+datetime="([^"]+)"')


def fetch_html(fantasy_position, ppr_slug, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    params = {
        "pprSuperflexSlug": ppr_slug,
        "fantasyPosition": fantasy_position,
        "researchDepth": "rankings",
        "playerGroup": "all",
        "sort": "",
        "selectedTeam": "",
        "playerSearchTerm": "",
    }
    resp = requests.get(LOAD_TABLE_URL, params=params,
                         headers={**HEADERS, "Referer": f"{BASE}/rankings/half-ppr",
                                  "X-Requested-With": "XMLHttpRequest"}, timeout=60)
    resp.raise_for_status()
    return resp.text


def parse(html, keep_positions):
    rows = []
    for m in ROW_RE.finditer(html):
        pos, name, _team_id = m.groups()
        if pos not in keep_positions:
            continue
        end = html.find("</tbody>", m.end())
        chunk = html[m.start():end]

        rank_m = RANK_RE.search(chunk)
        if not rank_m:
            continue
        team_m = TEAM_IMG_RE.search(chunk)
        team = TEAM_ALIASES.get(team_m.group(1), team_m.group(1)) if team_m else ""

        rows.append({
            "Rank": int(rank_m.group(1)),
            "Player": name,
            "Team": team,
            "Position": pos,
        })

    rows.sort(key=lambda r: r["Rank"])
    return rows


def extract_timestamp(html):
    m = TIMESTAMP_RE.search(html)
    return m.group(1) if m else None


def write_csv(rows, out_file):
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="draftsharks")
    ap.add_argument("--scoring", default=None, choices=["STD", "HALF", "PPR"],
                     help="Limit to one scoring format (default: fetch all 3)")
    ap.add_argument("--html-dir", help="dir with saved ds_rankings_<scoring>_<pos>.html files instead of fetching")
    args = ap.parse_args()

    scorings = [args.scoring] if args.scoring else ["HALF", "PPR", "STD"]

    last_updated = None
    for scoring in scorings:
        suffix = SCORING_SUFFIX[scoring]
        for label in ("OVR", "QB", "RB", "WR", "TE", "FLX"):
            html_file = (f"{args.html_dir}/ds_rankings_{scoring.lower()}_{label.lower()}.html"
                         if args.html_dir else None)
            html = fetch_html(POSITION_PARAM[label], SCORING_SLUG[scoring], html_file)
            keep = {"QB", "RB", "WR", "TE"} if label in ("OVR", "FLX") else {label}
            rows = parse(html, keep)
            if not rows:
                sys.exit(f"No players parsed for {scoring}/{label} — check the page markup hasn't changed.")
            out_file = f"{args.prefix}_{OUT_NAME[label]}{suffix}.csv"
            write_csv(rows, out_file)
            print(f"Wrote {len(rows)} players to {out_file}.")
            last_updated = last_updated or extract_timestamp(html)

    print(f"Draft Sharks last updated: {last_updated or 'unknown'}")
    source_timestamps.save_timestamp("DraftSharks", last_updated)


if __name__ == "__main__":
    main()
