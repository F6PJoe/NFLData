#!/usr/bin/env python3
"""
Pull Draft Sharks' season-long (preseason/draft) stat-line projections for
QB/RB/WR/TE.

Draft Sharks' rankings page (https://www.draftsharks.com/rankings/half-ppr)
has a "Projections" view (toggled via the "Projections" button next to
"Rankings") that renders per-stat columns (Pass Att/Comp/Yds/TD/Int, Rush
Yds/TD, Rec/Rec Yds/Rec TD) for every player. That view is loaded via an htmx
endpoint:

  GET /rankings/load-table
    ?pprSuperflexSlug=half-ppr&fantasyPosition=<QB|RB|WR|TE>
    &researchDepth=projections&playerGroup=all&sort=&selectedTeam=
    &playerSearchTerm=

Requires a logged-in session (Yii2 form login at /login, no reCAPTOCHA) using
DRAFTSHARKS_EMAIL/DRAFTSHARKS_PASSWORD from a local .env (see .env.example).

Each fantasyPosition request returns a deep pool for that position (e.g.
~130 RBs, ~110 TEs, ~200 WRs, ~40 QBs) plus a shallow sampling of other
positions; rows are filtered to data-fantasy-position == the requested
position.

Draft Sharks' projections view does NOT expose Rush Attempts or Targets (only
Rush Yds/TD and Receptions/Rec Yds/Rec TD), and doesn't report fumbles for
offensive players — those columns are left blank.

Bye weeks come from ESPN's public proTeamSchedules endpoint (same one used by
fetch_fantasysharks_projections.py) since this view doesn't include bye week.

Usage:
    python fetch_draftsharks_projections.py
    python fetch_draftsharks_projections.py --year 2026

Requires: requests
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys

import scoring

BASE = "https://www.draftsharks.com"
LOAD_TABLE_URL = f"{BASE}/rankings/load-table"
SCHEDULE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}?view=proTeamSchedules"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

ESPN_TEAM = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}
# Draft Sharks' team-logo CSS class abbreviations differ from ESPN's for a few teams.
TEAM_ALIASES = {"LVR": "LV", "WAS": "WSH", "JAC": "JAX"}

OUT_COLUMNS = {
    "QB": ["QB", "Team", "Bye", "Pass Att", "Pass Comp", "Pass Yds", "Pass TD",
           "Pass Int", "Rush Att", "Rush Yds", "Rush TD", "Fumbles"],
    "RB": ["RB", "Team", "Bye", "Rush Att", "Rush Yds", "Rush TD", "Targets", "Rec",
           "Rec Yds", "Rec TD", "Fum"],
    "WR": ["WR", "Team", "Bye", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD", "Fum"],
    "TE": ["TE", "Team", "Bye", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD"],
}


def _load_dotenv():
    path = os.path.join(os.path.dirname(__file__), ".env")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def login():
    import requests
    session = requests.Session()
    resp = session.get(f"{BASE}/login", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    m = re.search(r'name="_frontendCSRF"[^>]*value="([^"]+)"', resp.text)
    data = {
        "_frontendCSRF": m.group(1) if m else None,
        "LoginForm[email]": os.environ["DRAFTSHARKS_EMAIL"],
        "LoginForm[password]": os.environ["DRAFTSHARKS_PASSWORD"],
        "LoginForm[rememberMe]": "1",
        "login-button": "",
    }
    resp = session.post(f"{BASE}/login", data=data,
                         headers={**HEADERS, "Referer": f"{BASE}/login"}, timeout=30)
    resp.raise_for_status()
    return session


def load_byes(year, json_file=None):
    if json_file:
        with open(json_file, encoding="utf-8") as f:
            data = json.load(f)
    else:
        import requests
        resp = requests.get(SCHEDULE_URL.format(year=year), headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    teams = data.get("settings", {}).get("proTeams", []) or data.get("proTeams", [])
    return {ESPN_TEAM.get(t["id"], ""): t.get("byeWeek", "") for t in teams if t["id"] in ESPN_TEAM}


def get_html(session, pos, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    params = {
        "pprSuperflexSlug": "half-ppr",
        "fantasyPosition": pos,
        "researchDepth": "projections",
        "playerGroup": "all",
        "sort": "",
        "selectedTeam": "",
        "playerSearchTerm": "",
    }
    resp = session.get(LOAD_TABLE_URL, params=params,
                        headers={**HEADERS, "Referer": f"{BASE}/rankings/half-ppr",
                                 "X-Requested-With": "XMLHttpRequest"}, timeout=60)
    resp.raise_for_status()
    return resp.text


def val(chunk, attribute, default=0.0):
    m = re.search(r'data-value="([^"]*)"[^>]*data-attribute="%s"' % re.escape(attribute), chunk)
    if not m or not m.group(1):
        return default
    return float(m.group(1).replace(",", ""))


def parse_position(pos, html, byes):
    out = []
    for m in re.finditer(r'<tbody\s+data-player-row.*?data-fantasy-position="([^"]+)".*?data-player-name="([^"]+)".*?data-team-id="(\d+)"',
                          html, re.S):
        row_pos, name, team_id = m.group(1), m.group(2), m.group(3)
        if row_pos != pos:
            continue
        end = html.find("</tbody>", m.end())
        chunk = html[m.start():end]

        team_m = re.search(r'team-logo team-logo-([a-z]+)', chunk)
        team = TEAM_ALIASES.get(team_m.group(1).upper(), team_m.group(1).upper()) if team_m else ""
        bye = byes.get(team, "")

        pass_yds, pass_tds, pass_int = val(chunk, "pass_yds"), val(chunk, "pass_tds"), val(chunk, "pass_int")
        rush_yds, rush_tds = val(chunk, "rush_yds"), val(chunk, "rush_tds")
        rec_catch, rec_yds, rec_tds = val(chunk, "rec_catch"), val(chunk, "rec_yds"), val(chunk, "rec_tds")

        if pos == "QB":
            s = {"pass_yds": pass_yds, "pass_td": pass_tds, "pass_int": pass_int,
                 "rush_yds": rush_yds, "rush_td": rush_tds, "fum": 0}
            out.append((scoring.qb_points(s), {
                "QB": name, "Team": team, "Bye": bye,
                "Pass Att": scoring.round2(val(chunk, "pass_att")),
                "Pass Comp": scoring.round2(val(chunk, "pass_cmp")),
                "Pass Yds": scoring.round2(pass_yds),
                "Pass TD": scoring.round2(pass_tds),
                "Pass Int": scoring.round2(pass_int),
                "Rush Att": "",
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_tds),
                "Fumbles": "",
            }))
        elif pos == "RB":
            s = {"rush_yds": rush_yds, "rush_td": rush_tds, "rec": rec_catch,
                 "rec_yds": rec_yds, "rec_td": rec_tds, "fum": 0}
            out.append((scoring.ppr_points(s), {
                "RB": name, "Team": team, "Bye": bye,
                "Rush Att": "",
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_tds),
                "Targets": "",
                "Rec": scoring.round2(rec_catch),
                "Rec Yds": scoring.round2(rec_yds),
                "Rec TD": scoring.round2(rec_tds),
                "Fum": "",
            }))
        elif pos == "WR":
            s = {"rush_yds": rush_yds, "rush_td": rush_tds, "rec": rec_catch,
                 "rec_yds": rec_yds, "rec_td": rec_tds, "fum": 0}
            out.append((scoring.ppr_points(s), {
                "WR": name, "Team": team, "Bye": bye,
                "Targets": "",
                "Rec": scoring.round2(rec_catch),
                "Rec Yds": scoring.round2(rec_yds),
                "Rec TD": scoring.round2(rec_tds),
                "Rush Att": "",
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_tds),
                "Fum": "",
            }))
        elif pos == "TE":
            s = {"rec": rec_catch, "rec_yds": rec_yds, "rec_td": rec_tds, "fum": 0}
            out.append((scoring.ppr_points(s), {
                "TE": name, "Team": team, "Bye": bye,
                "Targets": "",
                "Rec": scoring.round2(rec_catch),
                "Rec Yds": scoring.round2(rec_yds),
                "Rec TD": scoring.round2(rec_tds),
                "Rush Att": "",
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_tds),
            }))

    out.sort(key=lambda r: r[0], reverse=True)
    return [r for _, r in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--prefix", default="draftsharks")
    ap.add_argument("--byes-json-file", help="offline ESPN proTeamSchedules JSON")
    ap.add_argument("--html-dir", help="dir with saved ds_load_table_<pos>.html files instead of fetching")
    args = ap.parse_args()

    _load_dotenv()
    byes = load_byes(args.year, args.byes_json_file)

    session = None
    if not args.html_dir:
        session = login()

    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        html_file = f"{args.html_dir}/ds_load_table_{pos.lower()}.html" if args.html_dir else None
        html = get_html(session, pos, html_file)
        recs = parse_position(pos, html, byes)
        if not recs:
            print(f"No rows parsed for {pos}.")
            continue
        out = f"{args.prefix}_{pos.lower()}.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=OUT_COLUMNS[pos])
            w.writeheader()
            w.writerows(recs)
        print(f"Wrote {len(recs)} {pos}s to {out}.")
        wrote_any = True

    if not wrote_any:
        sys.exit("No data parsed for any position.")


if __name__ == "__main__":
    main()
