#!/usr/bin/env python3
"""
Pull Draft Sharks' weekly stat-line projections for QB/RB/WR/TE.

Draft Sharks' weekly rankings page:
  https://www.draftsharks.com/weekly-rankings/<WEEK>/<pos>/half-ppr

The page uses an htmx load-table endpoint for projections data:
  GET /weekly-rankings/load-table
    ?week=<WEEK>&pprSuperflexSlug=half-ppr&fantasyPosition=<QB|RB|WR|TE>
    &researchDepth=projections&playerGroup=all

Requires login: Yii2 form login at /login (no reCAPTCHA).
Uses DRAFTSHARKS_EMAIL/DRAFTSHARKS_PASSWORD from a local .env.

Draft Sharks doesn't expose Rush Attempts, Targets, or Fumbles — left blank.

Usage:
    python fetch_draftsharks_projections.py
    python fetch_draftsharks_projections.py --year 2026 --week 3

Requires: requests
"""

import argparse
import csv
import datetime
import os
import re
import sys

import schedule as nfl_schedule
import scoring

BASE = "https://www.draftsharks.com"
LOAD_TABLE_URL = f"{BASE}/weekly-rankings/load-table"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

ESPN_TEAM = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}
TEAM_ALIASES = {"LVR": "LV", "WAS": "WSH", "JAC": "JAX"}

OUT_COLUMNS = {
    "QB": ["QB", "Team", "Opp", "Pass Att", "Pass Comp", "Pass Yds", "Pass TD",
           "Pass Int", "Rush Att", "Rush Yds", "Rush TD", "Fumbles"],
    "RB": ["RB", "Team", "Opp", "Rush Att", "Rush Yds", "Rush TD", "Targets", "Rec",
           "Rec Yds", "Rec TD", "Fum"],
    "WR": ["WR", "Team", "Opp", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
           "Rush Yds", "Rush TD", "Fum"],
    "TE": ["TE", "Team", "Opp", "Targets", "Rec", "Rec Yds", "Rec TD", "Rush Att",
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


def get_html(session, pos, week, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    params = {
        "week": week,
        "pprSuperflexSlug": "half-ppr",
        "fantasyPosition": pos,
        "researchDepth": "projections",
        "playerGroup": "all",
        "sort": "",
        "selectedTeam": "",
        "playerSearchTerm": "",
    }
    resp = session.get(LOAD_TABLE_URL, params=params,
                        headers={**HEADERS,
                                 "Referer": f"{BASE}/weekly-rankings/{week}/{pos.lower()}/half-ppr",
                                 "X-Requested-With": "XMLHttpRequest"}, timeout=60)
    resp.raise_for_status()
    return resp.text


def val(chunk, attribute, default=0.0):
    m = re.search(r'data-value="([^"]*)"[^>]*data-attribute="%s"' % re.escape(attribute), chunk)
    if not m or not m.group(1):
        return default
    return float(m.group(1).replace(",", ""))


def parse_position(pos, html, opponents):
    out = []
    for m in re.finditer(
        r'<tbody\s+data-player-row.*?data-fantasy-position="([^"]+)".*?data-player-name="([^"]+)".*?data-team-id="(\d+)"',
        html, re.S,
    ):
        row_pos, name, team_id = m.group(1), m.group(2), m.group(3)
        if row_pos != pos:
            continue
        end = html.find("</tbody>", m.end())
        chunk = html[m.start():end]

        team_m = re.search(r'team-logo team-logo-([a-z]+)', chunk)
        team = TEAM_ALIASES.get(team_m.group(1).upper(), team_m.group(1).upper()) if team_m else ""
        opp = opponents.get(team, "")

        pass_yds = val(chunk, "pass_yds")
        pass_tds = val(chunk, "pass_tds")
        pass_int = val(chunk, "pass_int")
        rush_yds = val(chunk, "rush_yds")
        rush_tds = val(chunk, "rush_tds")
        rec_catch = val(chunk, "rec_catch")
        rec_yds = val(chunk, "rec_yds")
        rec_tds = val(chunk, "rec_tds")

        if pos == "QB":
            s = {"pass_yds": pass_yds, "pass_td": pass_tds, "pass_int": pass_int,
                 "rush_yds": rush_yds, "rush_td": rush_tds, "fum": 0}
            out.append((scoring.qb_points(s), {
                "QB": name, "Team": team, "Opp": opp,
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
                "RB": name, "Team": team, "Opp": opp,
                "Rush Att": "", "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_tds), "Targets": "",
                "Rec": scoring.round2(rec_catch),
                "Rec Yds": scoring.round2(rec_yds), "Rec TD": scoring.round2(rec_tds),
                "Fum": "",
            }))
        elif pos == "WR":
            s = {"rush_yds": rush_yds, "rush_td": rush_tds, "rec": rec_catch,
                 "rec_yds": rec_yds, "rec_td": rec_tds, "fum": 0}
            out.append((scoring.ppr_points(s), {
                "WR": name, "Team": team, "Opp": opp,
                "Targets": "", "Rec": scoring.round2(rec_catch),
                "Rec Yds": scoring.round2(rec_yds), "Rec TD": scoring.round2(rec_tds),
                "Rush Att": "", "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_tds), "Fum": "",
            }))
        elif pos == "TE":
            s = {"rec": rec_catch, "rec_yds": rec_yds, "rec_td": rec_tds, "fum": 0}
            out.append((scoring.ppr_points(s), {
                "TE": name, "Team": team, "Opp": opp,
                "Targets": "", "Rec": scoring.round2(rec_catch),
                "Rec Yds": scoring.round2(rec_yds), "Rec TD": scoring.round2(rec_tds),
                "Rush Att": "", "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_tds),
            }))

    out.sort(key=lambda r: r[0], reverse=True)
    return [r for _, r in out]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--prefix", default="draftsharks")
    ap.add_argument("--html-dir")
    args = ap.parse_args()

    _load_dotenv()
    week, opponents = nfl_schedule.get_schedule(args.year, args.week)
    print(f"DraftSharks: week {week}")

    session = None
    if not args.html_dir:
        session = login()

    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        html_file = f"{args.html_dir}/ds_load_table_{pos.lower()}.html" if args.html_dir else None
        html = get_html(session, pos, week, html_file)
        recs = parse_position(pos, html, opponents)
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
