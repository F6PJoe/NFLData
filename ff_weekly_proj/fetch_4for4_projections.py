#!/usr/bin/env python3
"""
Pull 4for4's weekly projections for QB/RB/WR/TE.

  https://www.4for4.com/fantasy-football-projections/<pos>/<year>/week<N>

Requires a 4for4 subscription login (simple Drupal form login, no reCAPTCHA).
Uses FOR4FOR4_EMAIL/FOR4FOR4_PASSWORD from a local .env.

4for4 doesn't report Targets on the weekly page — left blank.

NOTE: 4for4 may also provide a weekly CSV download similar to the draft
projections CSV at /projections_csv/<set_id>. If they do, the set_id for
weekly would need to be found by inspecting the page. The HTML scraper below
works as a reliable fallback.

Usage:
    python fetch_4for4_projections.py
    python fetch_4for4_projections.py --year 2026 --week 3

Requires: requests, beautifulsoup4
"""

import argparse
import csv
import datetime
import os
import re
import sys

from bs4 import BeautifulSoup

import schedule as nfl_schedule
import scoring

BASE = "https://www.4for4.com"
PAGE_URL = f"{BASE}/fantasy-football-projections/{{pos}}/{{year}}/week{{week}}"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

TEAM_ALIASES = {"WAS": "WSH", "JAC": "JAX"}

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
    session.get(f"{BASE}/user/login", headers=HEADERS, timeout=30)
    data = {
        "form_id": "user_login",
        "name": os.environ["FOR4FOR4_EMAIL"],
        "pass": os.environ["FOR4FOR4_PASSWORD"],
        "remember_me": "1",
        "op": "Log in",
    }
    resp = session.post(f"{BASE}/user/login", data=data,
                         headers={**HEADERS, "Referer": f"{BASE}/user/login"}, timeout=30)
    resp.raise_for_status()
    return session


def num(text):
    text = (text or "").replace(",", "").strip()
    if not text or text == "-":
        return 0.0
    return float(text)


def get_html(session, pos, year, week, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    url = PAGE_URL.format(pos=pos.lower(), year=year, week=week)
    resp = session.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def parse_position(pos, html, opponents):
    """Parse 4for4's weekly projections table. Column order varies by position."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table")
    if table is None:
        return []

    # Find header row to map column names to indices
    header_row = table.find("thead")
    if header_row is None:
        return []
    headers = [th.get_text(strip=True).lower() for th in header_row.find_all("th")]

    def col(*names):
        for name in names:
            try:
                return headers.index(name)
            except ValueError:
                pass
        return None

    rows = []
    tbody = table.find("tbody")
    if tbody is None:
        return []

    # Locate the player-name column by looking for the 'player' header
    name_col = col("player")

    for tr in tbody.find_all("tr"):
        tds = tr.find_all("td")
        if not tds:
            continue

        def cell(*names, default=0.0):
            idx = col(*names)
            if idx is None or idx >= len(tds):
                return default
            return num(tds[idx].get_text(strip=True))

        # Player name: use 'player' column if found, else look for a link in any cell
        if name_col is not None and name_col < len(tds):
            a = tds[name_col].find("a")
            name = a.get_text(strip=True) if a else tds[name_col].get_text(strip=True)
        else:
            name = ""
            for td in tds:
                a = td.find("a")
                if a:
                    name = a.get_text(strip=True)
                    break
        if not name:
            continue

        team_idx = col("team")
        team = tds[team_idx].get_text(strip=True) if team_idx is not None else ""
        team = TEAM_ALIASES.get(team, team)
        opp_idx = col("opp")
        opp = tds[opp_idx].get_text(strip=True) if opp_idx is not None else opponents.get(team, "")
        opp = opp.lstrip("@")

        # 4for4 weekly headers: att/comp/payds/patdpassing/int/ruatt/ruydsrushing/rutd
        # 4for4 seasonal headers: pass att/cmp/pass yds/pass td/int/rush att/rush yds/rush td
        # recydsreceiving/rectd are used on weekly; rec yds/rec td on seasonal
        pass_att = cell("att", "pass att")
        pass_cmp = cell("comp", "cmp", "pass comp")
        pass_yds = cell("payds", "pass yds", "pass yd")
        pass_td = cell("patdpassing", "pass td", "td") if pos == "QB" else 0
        pass_int = cell("int")
        rush_att_val = cell("ruatt", "rush att", "car")
        rush_yds = cell("ruydsrushing", "rush yds", "rush yd")
        rush_td_val = cell("rutd", "rush td")
        rec = cell("rec")
        rec_yds = cell("recydsreceiving", "rec yds", "rec yd")
        rec_td = cell("rectd", "rec td")
        fum = cell("fum", "fl")

        if pos == "QB":
            s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
                 "rush_yds": rush_yds, "rush_td": rush_td_val, "fum": fum}
            rows.append((scoring.qb_points(s), {
                "QB": name, "Team": team, "Opp": opp,
                "Pass Att": scoring.round2(pass_att),
                "Pass Comp": scoring.round2(pass_cmp),
                "Pass Yds": scoring.round2(pass_yds),
                "Pass TD": scoring.round2(pass_td),
                "Pass Int": scoring.round2(pass_int),
                "Rush Att": scoring.round2(rush_att_val),
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_td_val),
                "Fumbles": scoring.round2(fum),
            }))
        elif pos == "RB":
            s = {"rush_yds": rush_yds, "rush_td": rush_td_val, "rec": rec,
                 "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
            rows.append((scoring.ppr_points(s), {
                "RB": name, "Team": team, "Opp": opp,
                "Rush Att": scoring.round2(rush_att_val),
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_td_val),
                "Targets": "",
                "Rec": scoring.round2(rec),
                "Rec Yds": scoring.round2(rec_yds),
                "Rec TD": scoring.round2(rec_td),
                "Fum": scoring.round2(fum),
            }))
        elif pos == "WR":
            s = {"rush_yds": rush_yds, "rush_td": rush_td_val, "rec": rec,
                 "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
            rows.append((scoring.ppr_points(s), {
                "WR": name, "Team": team, "Opp": opp,
                "Targets": "",
                "Rec": scoring.round2(rec),
                "Rec Yds": scoring.round2(rec_yds),
                "Rec TD": scoring.round2(rec_td),
                "Rush Att": scoring.round2(rush_att_val),
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_td_val),
                "Fum": scoring.round2(fum),
            }))
        elif pos == "TE":
            s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
            rows.append((scoring.ppr_points(s), {
                "TE": name, "Team": team, "Opp": opp,
                "Targets": "",
                "Rec": scoring.round2(rec),
                "Rec Yds": scoring.round2(rec_yds),
                "Rec TD": scoring.round2(rec_td),
                "Rush Att": scoring.round2(rush_att_val),
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_td_val),
            }))

    rows.sort(key=lambda r: r[0], reverse=True)
    return [r for _, r in rows]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--prefix", default="4for4")
    ap.add_argument("--html-dir")
    args = ap.parse_args()

    _load_dotenv()
    week, opponents = nfl_schedule.get_schedule(args.year, args.week)
    print(f"4for4: week {week}")

    session = None
    if not args.html_dir:
        session = login()

    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        html_file = f"{args.html_dir}/{pos.lower()}.html" if args.html_dir else None
        html = get_html(session, pos, args.year, week, html_file)
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
