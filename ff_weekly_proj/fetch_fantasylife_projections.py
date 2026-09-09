#!/usr/bin/env python3
"""
Pull Fantasy Life's weekly projected stat lines for QB/RB/WR/TE.

  GET https://www.fantasylife.com/api/datatables/projections
    ?limit=65&offset=<N>&orderBy=-projectedFantasyPoints
    &seasonId=911c9071-892d-470e-aca8-457144b823cb
    &scoringSystemId=1c56287f-23de-42ca-b077-6b5f09a8f5f1
    &rosterPositions=<QB|RB|WR|TE>&projectedProvider=aggregate
    &projectionPeriod=weekly&weekNumber=<WEEK>&projectionType=avg&perGame=false

Auth: Firebase ID token via Google Identity Toolkit REST API.
Uses FANTASYLIFE_EMAIL/FANTASYLIFE_PASSWORD/FANTASYLIFE_FIREBASE_API_KEY from .env.

Opponent lookup comes from ESPN schedule utility.

Usage:
    python fetch_fantasylife_projections.py
    python fetch_fantasylife_projections.py --year 2026 --week 3

Requires: requests
"""

import argparse
import csv
import datetime
import json
import os
import sys

import schedule as nfl_schedule
import scoring

BASE = "https://www.fantasylife.com"
PROJECTIONS_URL = (
    f"{BASE}/api/datatables/projections?limit=65&offset={{offset}}"
    "&orderBy=-projectedFantasyPoints&seasonId=911c9071-892d-470e-aca8-457144b823cb"
    "&scoringSystemId=1c56287f-23de-42ca-b077-6b5f09a8f5f1&rosterPositions={pos}"
    "&projectedProvider=aggregate&projectionPeriod=weekly&weekNumber={week}"
    "&projectionType=avg&perGame=false"
)

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

TEAM_ALIASES = {"WAS": "WSH", "LVR": "LV", "JAC": "JAX"}

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


def get_token():
    import requests
    resp = requests.post(
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword"
        f"?key={os.environ['FANTASYLIFE_FIREBASE_API_KEY']}",
        json={
            "email": os.environ["FANTASYLIFE_EMAIL"],
            "password": os.environ["FANTASYLIFE_PASSWORD"],
            "returnSecureToken": True,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["idToken"]


def num(value):
    if value is None or value == "":
        return 0.0
    return float(value)


def fetch_position(token, pos, week, json_dir=None):
    import requests
    headers = {**HEADERS, "bearer-token": token}
    all_rows = []
    offset = 0
    while True:
        if json_dir:
            fn = f"{json_dir}/fl_{pos.lower()}_offset{offset}.json"
            with open(fn, encoding="utf-8") as f:
                data = json.load(f)
        else:
            resp = requests.get(
                PROJECTIONS_URL.format(pos=pos, week=week, offset=offset),
                headers=headers, timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        rows = data["data"]["playerProjections"]
        if not rows:
            break
        all_rows.extend(rows)
        if json_dir:
            break
        offset += 65
    return all_rows


def build_record(pos, row, opponents):
    athlete = row["athlete"]
    name = f"{athlete['firstName']} {athlete['lastName']}"
    alias = (athlete.get("team") or {}).get("alias", "")
    team = TEAM_ALIASES.get(alias, alias)
    opp = opponents.get(team, "")

    pass_yds = num(row["passingYards"])
    pass_td = num(row["passingTouchdowns"])
    pass_int = num(row["passingInterceptions"])
    rush_att = num(row["rushingAttempts"])
    rush_yds = num(row["rushingYards"])
    rush_td = num(row["rushingTouchdowns"])
    targets = num(row["receivingTargets"])
    rec = num(row["receivingReceptions"])
    rec_yds = num(row["receivingYards"])
    rec_td = num(row["receivingTouchdowns"])
    fum = num(row["fumblesLost"])

    if pos == "QB":
        s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
             "rush_yds": rush_yds, "rush_td": rush_td, "fum": fum}
        return scoring.qb_points(s), {
            "QB": name, "Team": team, "Opp": opp,
            "Pass Att": scoring.round2(num(row["passingAttempts"])),
            "Pass Comp": scoring.round2(num(row["passingCompletions"])),
            "Pass Yds": scoring.round2(pass_yds),
            "Pass TD": scoring.round2(pass_td),
            "Pass Int": scoring.round2(pass_int),
            "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
            "Fumbles": scoring.round2(fum),
        }
    elif pos == "RB":
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
        return scoring.ppr_points(s), {
            "RB": name, "Team": team, "Opp": opp,
            "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
            "Targets": scoring.round2(targets),
            "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td),
            "Fum": scoring.round2(fum),
        }
    elif pos == "WR":
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
        return scoring.ppr_points(s), {
            "WR": name, "Team": team, "Opp": opp,
            "Targets": scoring.round2(targets),
            "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td),
            "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
            "Fum": scoring.round2(fum),
        }
    elif pos == "TE":
        s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
        return scoring.ppr_points(s), {
            "TE": name, "Team": team, "Opp": opp,
            "Targets": scoring.round2(targets),
            "Rec": scoring.round2(rec),
            "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td),
            "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=datetime.date.today().year)
    ap.add_argument("--week", type=int, default=None)
    ap.add_argument("--prefix", default="fantasylife")
    ap.add_argument("--json-dir")
    args = ap.parse_args()

    _load_dotenv()
    week, opponents = nfl_schedule.get_schedule(args.year, args.week)
    print(f"FantasyLife: week {week}")

    token = None
    if not args.json_dir:
        token = get_token()

    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        rows = fetch_position(token, pos, week, args.json_dir)
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
