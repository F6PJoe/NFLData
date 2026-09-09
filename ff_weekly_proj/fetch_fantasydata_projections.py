#!/usr/bin/env python3
"""
Pull FantasyData's weekly projections for QB/RB/WR/TE.

  https://fantasydata.com/nfl/fantasy-football-weekly-projections
    ?scope=game&spw=<YEAR>_REG_<WEEK>&position=<qb|rb|wr|te>
    &scoring=fpts_ppr&order_by=fpts_ppr&sort_dir=desc&page=<N>

Requires login: simple form login at /user/login (csrf_token, email, password).
Uses FANTASYDATA_EMAIL/FANTASYDATA_PASSWORD from a local .env.

Usage:
    python fetch_fantasydata_projections.py
    python fetch_fantasydata_projections.py --year 2026 --week 3

Requires: requests
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys

import schedule as nfl_schedule
import scoring

BASE = "https://fantasydata.com"
PROJECTIONS_URL = (f"{BASE}/nfl/fantasy-football-weekly-projections"
                   "?scope=game&spw={year}_REG_{week}&position={pos}"
                   "&scoring=fpts_ppr&order_by=fpts_ppr&sort_dir=desc&page={page}")
SCHEDULE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}?view=proTeamSchedules"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

TEAM_ALIASES = {"WAS": "WSH"}

# Weekly page inserts an "opp" column at index 5 (after rank/player/team/pos/gp).
# RB has 17 columns (no fpts_per_gp); QB and WR/TE have 19-20.
COLUMNS = {
    "QB": ["rank", "player", "team", "pos", "gp", "opp", "pass_cmp", "pass_att", "pass_cmp_pct",
           "pass_yds", "pass_yds_per_att", "pass_td", "pass_int", "pass_rating",
           "rush_att", "rush_yds", "rush_yds_per_att", "rush_td", "fpts_ppr"],
    "RB": ["rank", "player", "team", "pos", "gp", "opp", "rush_att", "rush_yds", "rush_yds_per_att",
           "rush_td", "rec_tgt", "rec", "rec_yds", "rec_td", "fum", "fum_lost", "fpts_ppr"],
    "WR": ["rank", "player", "team", "pos", "gp", "opp", "rec_tgt", "rec", "catch_rate", "rec_yds",
           "rec_td", "rec_yds_per_tgt", "rec_yds_per_rec", "rush_att", "rush_yds",
           "rush_yds_per_att", "rush_td", "fum", "fum_lost", "fpts_ppr"],
}
COLUMNS["TE"] = COLUMNS["WR"]

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

TAG_RE = re.compile(r"<[^>]+>")


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
    resp = session.get(f"{BASE}/user/login", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"', resp.text)
    data = {
        "csrf_token": m.group(1) if m else "",
        "email": os.environ["FANTASYDATA_EMAIL"],
        "password": os.environ["FANTASYDATA_PASSWORD"],
        "submit": "Continue",
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


def get_html(session, pos, year, week, page, html_file=None):
    if html_file:
        with open(html_file, encoding="utf-8") as f:
            return f.read()
    resp = session.get(
        PROJECTIONS_URL.format(year=year, week=week, pos=pos.lower(), page=page),
        headers=HEADERS, timeout=30,
    )
    resp.raise_for_status()
    return resp.text


def parse_rows(pos, html):
    cols = COLUMNS[pos]
    rows = []
    for m in re.finditer(r"<tr class='[^']*'>(.*?)</tr>", html, re.S):
        body = m.group(1)
        if "unauthorized" in body:
            continue
        cells = re.findall(r"<td[^>]*>(.*?)</td>", body, re.S)
        if len(cells) != len(cols):
            continue
        values = [TAG_RE.sub("", c).strip() for c in cells]
        rows.append(dict(zip(cols, values)))
    return rows


def fetch_position(session, pos, year, week, html_dir=None):
    all_rows = []
    page = 1
    while True:
        html_file = f"{html_dir}/fd_{pos.lower()}_page{page}.html" if html_dir else None
        html = get_html(session, pos, year, week, page, html_file)
        rows = parse_rows(pos, html)
        if not rows:
            break
        all_rows.extend(rows)
        if html_dir:
            break
        page += 1
    return all_rows


def build_record(pos, row, opponents):
    team = TEAM_ALIASES.get(row["team"], row["team"])
    opp = opponents.get(team, "")
    name = row["player"].replace("\xa0", " ").replace("&nbsp;", " ").split("  ")[0].strip()

    if pos == "QB":
        pass_yds, pass_td, pass_int = num(row["pass_yds"]), num(row["pass_td"]), num(row["pass_int"])
        rush_yds, rush_td = num(row["rush_yds"]), num(row["rush_td"])
        s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
             "rush_yds": rush_yds, "rush_td": rush_td, "fum": 0}
        return scoring.qb_points(s), {
            "QB": name, "Team": team, "Opp": opp,
            "Pass Att": scoring.round2(num(row["pass_att"])),
            "Pass Comp": scoring.round2(num(row["pass_cmp"])),
            "Pass Yds": scoring.round2(pass_yds),
            "Pass TD": scoring.round2(pass_td),
            "Pass Int": scoring.round2(pass_int),
            "Rush Att": scoring.round2(num(row["rush_att"])),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
            "Fumbles": "",
        }
    elif pos == "RB":
        rush_yds, rush_td = num(row["rush_yds"]), num(row["rush_td"])
        rec, rec_yds, rec_td = num(row["rec"]), num(row["rec_yds"]), num(row["rec_td"])
        fum_lost = num(row["fum_lost"])
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum_lost}
        return scoring.ppr_points(s), {
            "RB": name, "Team": team, "Opp": opp,
            "Rush Att": scoring.round2(num(row["rush_att"])),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
            "Targets": scoring.round2(num(row["rec_tgt"])),
            "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td),
            "Fum": scoring.round2(fum_lost),
        }
    elif pos == "WR":
        rush_yds, rush_td = num(row["rush_yds"]), num(row["rush_td"])
        rec, rec_yds, rec_td = num(row["rec"]), num(row["rec_yds"]), num(row["rec_td"])
        fum_lost = num(row["fum_lost"])
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum_lost}
        return scoring.ppr_points(s), {
            "WR": name, "Team": team, "Opp": opp,
            "Targets": scoring.round2(num(row["rec_tgt"])),
            "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td),
            "Rush Att": scoring.round2(num(row["rush_att"])),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
            "Fum": scoring.round2(fum_lost),
        }
    elif pos == "TE":
        rush_yds, rush_td = num(row["rush_yds"]), num(row["rush_td"])
        rec, rec_yds, rec_td = num(row["rec"]), num(row["rec_yds"]), num(row["rec_td"])
        s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": num(row["fum_lost"])}
        return scoring.ppr_points(s), {
            "TE": name, "Team": team, "Opp": opp,
            "Targets": scoring.round2(num(row["rec_tgt"])),
            "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td),
            "Rush Att": scoring.round2(num(row["rush_att"])),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--prefix", default="fantasydata")
    ap.add_argument("--html-dir")
    args = ap.parse_args()

    _load_dotenv()
    week, opponents = nfl_schedule.get_schedule(args.year, args.week)
    print(f"FantasyData: week {week}")

    session = None
    if not args.html_dir:
        session = login()

    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        rows = fetch_position(session, pos, args.year, week, args.html_dir)
        recs = [build_record(pos, row, opponents) for row in rows]
        recs.sort(key=lambda r: r[0], reverse=True)
        recs = [r for _, r in recs]
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
