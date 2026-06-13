#!/usr/bin/env python3
"""
Pull Fantasy Life's season-long (preseason/draft) stat-line projections for
QB/RB/WR/TE.

  GET https://www.fantasylife.com/api/datatables/projections
    ?limit=65&offset=<N>&orderBy=-projectedFantasyPoints
    &seasonId=911c9071-892d-470e-aca8-457144b823cb
    &scoringSystemId=1c56287f-23de-42ca-b077-6b5f09a8f5f1
    &rosterPositions=<QB|RB|WR|TE>&projectedProvider=aggregate
    &projectionPeriod=seasonal&projectionType=avg&perGame=false

This API requires a `bearer-token` header containing a Firebase ID token
(Fantasy Life's auth is Firebase Authentication, project "fantasy-life-1b94f").
Rather than scripting their Next.js login form (which uses server actions with
no visible REST endpoint), we sign in directly against Google's Identity
Toolkit REST API using the app's public Firebase Web API key:

  POST https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword
    ?key=AIzaSyAtYDLhL3ya9gIMYMKHE-9l4--GM6giL0I
    {"email": ..., "password": ..., "returnSecureToken": true}

This returns an idToken usable as the `bearer-token` header. Requires
FANTASYLIFE_EMAIL/FANTASYLIFE_PASSWORD from a local .env (see .env.example).

Bye weeks come from ESPN's public proTeamSchedules endpoint, keyed off each
player's team alias.

Usage:
    python fetch_fantasylife_projections.py
    python fetch_fantasylife_projections.py --year 2026

Requires: requests
"""

import argparse
import csv
import datetime
import json
import os
import sys

import scoring

BASE = "https://www.fantasylife.com"
PROJECTIONS_URL = (f"{BASE}/api/datatables/projections?limit=65&offset={{offset}}"
                   "&orderBy=-projectedFantasyPoints&seasonId=911c9071-892d-470e-aca8-457144b823cb"
                   "&scoringSystemId=1c56287f-23de-42ca-b077-6b5f09a8f5f1&rosterPositions={pos}"
                   "&projectedProvider=aggregate&projectionPeriod=seasonal&projectionType=avg&perGame=false")
SCHEDULE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/{year}?view=proTeamSchedules"
FIREBASE_API_KEY = "AIzaSyAtYDLhL3ya9gIMYMKHE-9l4--GM6giL0I"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

ESPN_TEAM = {
    0: "FA", 1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WSH",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}
TEAM_ALIASES = {"WAS": "WSH", "LVR": "LV", "JAC": "JAX"}

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


def get_token():
    import requests
    resp = requests.post(
        f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={FIREBASE_API_KEY}",
        json={
            "email": os.environ["FANTASYLIFE_EMAIL"],
            "password": os.environ["FANTASYLIFE_PASSWORD"],
            "returnSecureToken": True,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["idToken"]


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


def num(value):
    if value is None or value == "":
        return 0.0
    return float(value)


def fetch_position(token, pos, json_dir=None):
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
            resp = requests.get(PROJECTIONS_URL.format(pos=pos, offset=offset), headers=headers, timeout=30)
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


def build_record(pos, row, byes):
    athlete = row["athlete"]
    name = f"{athlete['firstName']} {athlete['lastName']}"
    alias = (athlete.get("team") or {}).get("alias", "")
    team = TEAM_ALIASES.get(alias, alias)
    bye = byes.get(team, "")

    pass_yds, pass_td, pass_int = num(row["passingYards"]), num(row["passingTouchdowns"]), num(row["passingInterceptions"])
    rush_att, rush_yds, rush_td = num(row["rushingAttempts"]), num(row["rushingYards"]), num(row["rushingTouchdowns"])
    targets, rec, rec_yds, rec_td = num(row["receivingTargets"]), num(row["receivingReceptions"]), num(row["receivingYards"]), num(row["receivingTouchdowns"])
    fum = num(row["fumblesLost"])

    if pos == "QB":
        s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
             "rush_yds": rush_yds, "rush_td": rush_td, "fum": fum}
        return scoring.qb_points(s), {
            "QB": name, "Team": team, "Bye": bye,
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
            "RB": name, "Team": team, "Bye": bye,
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
            "WR": name, "Team": team, "Bye": bye,
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
            "TE": name, "Team": team, "Bye": bye,
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
    ap.add_argument("--prefix", default="fantasylife")
    ap.add_argument("--byes-json-file", help="offline ESPN proTeamSchedules JSON")
    ap.add_argument("--json-dir", help="dir with saved fl_<pos>_offset0.json files instead of fetching (single page only)")
    args = ap.parse_args()

    _load_dotenv()
    byes = load_byes(args.year, args.byes_json_file)

    token = None
    if not args.json_dir:
        token = get_token()

    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        rows = fetch_position(token, pos, args.json_dir)
        recs = [build_record(pos, row, byes) for row in rows]
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
