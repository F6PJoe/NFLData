#!/usr/bin/env python3
"""
Pull Yahoo Fantasy's Roster %, Start %, and weekly projected points for
every D/ST from a league's public "Players" page (no login needed -- same
public-page trick fetch_yahoo_projections.py in ff_draft_proj already
relies on for season projections).

Two different stat1 views are needed -- confirmed live neither one alone
has all three fields:
  - stat1=R_O   -> has "% Ros" and "% Start" (under a "Trends" column
    group), but no per-week projection at all.
  - stat1=S_PW_<week> -> has that week's "Fan Pts" (confirmed this is the
    projection, not an actual, since the games haven't been played yet),
    but only "% Ros", no "% Start".

Page (25 rows per request, paginated via &count=0,25,...):
    https://football.fantasysports.yahoo.com/f1/{league_id}/players
        ?status=ALL&eteam=ALL&fteam=NONE&pos=DEF&sort=PTS&sdir=1
        &stat1={R_O | S_PW_<week>}&count={offset}

S_PW_<week> needs bumping each week (Joe's own note: S_PW_2 -> S_PW_3 in
week 3, etc.), hence --week here rather than a silent default.

Yahoo's official OAuth API would give both in one call (percent_owned /
percent_started), but the registered app for this project's Yahoo OAuth
credentials returns "This application is not authorized to perform this
action" on every call, even the most basic one, despite Fantasy Sports -
Read showing enabled in the app's settings -- looks like a Yahoo-side
approval issue on the app itself, and the account owner can't edit
Client Type/API Permissions after creation to work around it. Scraping
these two public pages sidesteps needing that API at all.

Usage:
    python fetch_yahoo_def.py --week 2   # -> yahoo_def.csv

Requires: requests, beautifulsoup4
"""

import argparse
import csv
import re

import requests
from bs4 import BeautifulSoup

from team_names import normalize

RO_URL = ("https://football.fantasysports.yahoo.com/f1/{league_id}/players"
          "?status=ALL&eteam=ALL&fteam=NONE&pos=DEF&cut_type=9&stat1=R_O"
          "&myteam=0&sort=PTS&sdir=1&count={offset}")

PROJ_URL = ("https://football.fantasysports.yahoo.com/f1/{league_id}/players"
            "?pos=DEF&sort=PTS&sdir=1&status=ALL&eteam=ALL&fteam=NONE"
            "&stat1=S_PW_{week}&jsenabled=1&count={offset}")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

# Week is stamped so the pushes can refuse a leftover file from last week
# -- see current_week.stale_week().
FIELDNAMES = ["Week", "Team", "RosterPct", "StartPct", "Projection"]

PCT_RE = re.compile(r"([\-0-9.]+)%?")


def pct(text):
    text = (text or "").strip()
    m = PCT_RE.match(text)
    if not m or m.group(1) in ("", "-"):
        return None
    return float(m.group(1))


def num(text):
    text = (text or "").replace(",", "").replace("%", "").strip()
    if not text or text == "-":
        return None
    return float(text)


def team_from_player_cell(td):
    teampos_span = td.find("span", class_="Fz-xxs")
    if teampos_span is None:
        return None
    return normalize(teampos_span.get_text(strip=True).split(" - ")[0])


# Which S_PW_<week> the returned page says is actually selected. Yahoo's
# dropdown only offers the CURRENT and FUTURE weeks -- ask for a past one
# and it silently serves a different view with nothing selected rather than
# erroring, so the only way to know the request was honoured is to read
# this back off the page.
SELECTED_WEEK_RE = re.compile(
    r'<option[^>]*\bselected\b[^>]*value="S_PW_(\d+)"'
    r'|<option[^>]*value="S_PW_(\d+)"[^>]*\bselected\b')


def selected_week(html):
    m = SELECTED_WEEK_RE.search(html)
    return int(m.group(1) or m.group(2)) if m else None


def fetch_paginated(url_template, seen_html=None, **fmt):
    rows = []
    offset = 0
    while True:
        url = url_template.format(offset=offset, **fmt)
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        if seen_html is not None:
            seen_html.append(resp.text)
        soup = BeautifulSoup(resp.text, "html.parser")
        table = soup.find("table")
        tbody = table.find("tbody") if table else None
        trs = tbody.find_all("tr") if tbody else []
        if not trs:
            break
        rows.append(trs)
        if len(trs) < 25:
            break
        offset += 25
    return [tr for page in rows for tr in page]


def fetch_ownership(league_id):
    trs = fetch_paginated(RO_URL, league_id=league_id)
    out = {}
    for tr in trs:
        tds = tr.find_all("td")
        if len(tds) < 7:
            continue
        team = team_from_player_cell(tds[2])
        if not team:
            continue
        out[team] = {"RosterPct": pct(tds[5].get_text()), "StartPct": pct(tds[6].get_text())}
    return out


def fetch_projections(league_id, week):
    html = []
    trs = fetch_paginated(PROJ_URL, seen_html=html, league_id=league_id, week=week)

    # Verify Yahoo actually served the week we asked for. Without this, a
    # wrong --week produces perfectly plausible numbers for some other view
    # and nothing downstream can tell -- which is exactly how week-2
    # projections once got blended with week-3 adjustments and put the
    # Chargers at 8.51 points in the worst matchup on the board.
    got = selected_week(html[0]) if html else None
    if got != week:
        raise SystemExit(
            f"Yahoo did not serve week {week}: the page reports "
            f"{'week ' + str(got) if got else 'no week'} selected. Yahoo only "
            f"offers the current and future weeks, so a past --week is "
            f"silently ignored. Refusing to write projections that aren't "
            f"week {week}.")
    out = {}
    for tr in trs:
        tds = tr.find_all("td")
        if len(tds) < 10:
            continue
        team = team_from_player_cell(tds[2])
        if not team:
            continue
        out[team] = num(tds[6].get_text())
    return out


def write_csv(rows, out_file, week):
    rows = [dict(r, Week=week) for r in rows]
    with open(out_file, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--week", type=int, required=True, help="NFL week, e.g. 2 for S_PW_2")
    ap.add_argument("--league-id", default="84385")
    ap.add_argument("--out", default="yahoo_def.csv")
    args = ap.parse_args()

    ownership = fetch_ownership(args.league_id)
    projections = fetch_projections(args.league_id, args.week)

    teams = sorted(set(ownership) | set(projections))
    if len(teams) < 28:
        raise SystemExit(
            f"Only found {len(teams)} D/ST teams (expected ~32) -- "
            "Yahoo's markup may have changed."
        )

    rows = [{
        "Team": team,
        "RosterPct": ownership.get(team, {}).get("RosterPct"),
        "StartPct": ownership.get(team, {}).get("StartPct"),
        "Projection": projections.get(team),
    } for team in teams]

    write_csv(rows, args.out, args.week)
    print(f"Week {args.week}: wrote {len(rows)} teams to {args.out}.")


if __name__ == "__main__":
    main()
