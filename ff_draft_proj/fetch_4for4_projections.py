#!/usr/bin/env python3
"""
Pull 4for4's season-long (preseason/draft) projections for QB/RB/WR/TE from
their projections CSV download.

  https://www.4for4.com/projections_csv/<set_id>

Requires a 4for4 subscription login: simple Drupal form login at
/user/login (form_id=user_login, name, pass — no CSRF token, no reCAPTCHA),
using FOR4FOR4_EMAIL/FOR4FOR4_PASSWORD from a local .env (see .env.example).

The CSV is a single file covering all positions (QB/RB/WR/TE/K) with columns:
  PID, Player, Pos, Team, FF Pts, ADP, Pass Comp, Pass Att, Pass Yds, Pass TD,
  INT, Rush Att, Rush Yds, Rush TD, Rec, Rec Yds, Rec TD, BYE, Pa1D, Ru1D,
  Rec1D, Fum, XP, FG, Health, C

Includes bye week directly — no separate ESPN lookup needed. 4for4 doesn't
report Targets — left blank.

The "60444" id in the URL is the default/current draft projections set
(matches the id used on 4for4's rankings-tabs pages, e.g.
/rankings-tabs/QB/60444/nojs); pass --set-id to override if it changes.

Usage:
    python fetch_4for4_projections.py
    python fetch_4for4_projections.py --set-id 60444

Requires: requests
"""

import argparse
import csv as csv_module
import io
import os
import sys

import scoring

BASE = "https://www.4for4.com"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                         "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"}

TEAM_ALIASES = {"WAS": "WSH"}

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


def get_csv_text(session, set_id, csv_file=None):
    if csv_file:
        with open(csv_file, encoding="utf-8") as f:
            return f.read()
    resp = session.get(f"{BASE}/projections_csv/{set_id}", headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp.text


def num(text):
    text = (text or "").replace(",", "").strip()
    if not text or text == "-":
        return 0.0
    return float(text)


def parse_rows(text):
    by_pos = {"QB": [], "RB": [], "WR": [], "TE": []}
    for row in csv_module.DictReader(io.StringIO(text)):
        pos = row["Pos"]
        if pos not in by_pos:
            continue

        name = row["Player"]
        team = TEAM_ALIASES.get(row["Team"], row["Team"])
        bye = row["BYE"]
        pass_yds, pass_td, pass_int = num(row["Pass Yds"]), num(row["Pass TD"]), num(row["INT"])
        rush_att, rush_yds, rush_td = num(row["Rush Att"]), num(row["Rush Yds"]), num(row["Rush TD"])
        rec, rec_yds, rec_td = num(row["Rec"]), num(row["Rec Yds"]), num(row["Rec TD"])
        fum = num(row["Fum"])

        if pos == "QB":
            s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
                 "rush_yds": rush_yds, "rush_td": rush_td, "fum": fum}
            by_pos[pos].append((scoring.qb_points(s), {
                "QB": name, "Team": team, "Bye": bye,
                "Pass Att": scoring.round2(num(row["Pass Att"])),
                "Pass Comp": scoring.round2(num(row["Pass Comp"])),
                "Pass Yds": scoring.round2(pass_yds),
                "Pass TD": scoring.round2(pass_td),
                "Pass Int": scoring.round2(pass_int),
                "Rush Att": scoring.round2(rush_att),
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_td),
                "Fumbles": scoring.round2(fum),
            }))
        elif pos == "RB":
            s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
                 "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
            by_pos[pos].append((scoring.ppr_points(s), {
                "RB": name, "Team": team, "Bye": bye,
                "Rush Att": scoring.round2(rush_att),
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_td),
                "Targets": "",
                "Rec": scoring.round2(rec),
                "Rec Yds": scoring.round2(rec_yds),
                "Rec TD": scoring.round2(rec_td),
                "Fum": scoring.round2(fum),
            }))
        elif pos == "WR":
            s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
                 "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
            by_pos[pos].append((scoring.ppr_points(s), {
                "WR": name, "Team": team, "Bye": bye,
                "Targets": "",
                "Rec": scoring.round2(rec),
                "Rec Yds": scoring.round2(rec_yds),
                "Rec TD": scoring.round2(rec_td),
                "Rush Att": scoring.round2(rush_att),
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_td),
                "Fum": scoring.round2(fum),
            }))
        elif pos == "TE":
            s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
            by_pos[pos].append((scoring.ppr_points(s), {
                "TE": name, "Team": team, "Bye": bye,
                "Targets": "",
                "Rec": scoring.round2(rec),
                "Rec Yds": scoring.round2(rec_yds),
                "Rec TD": scoring.round2(rec_td),
                "Rush Att": scoring.round2(rush_att),
                "Rush Yds": scoring.round2(rush_yds),
                "Rush TD": scoring.round2(rush_td),
            }))

    for pos in by_pos:
        by_pos[pos].sort(key=lambda r: r[0], reverse=True)
        by_pos[pos] = [r for _, r in by_pos[pos]]
    return by_pos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set-id", default="60444")
    ap.add_argument("--prefix", default="4for4")
    ap.add_argument("--csv-file", help="offline saved projections_csv response")
    args = ap.parse_args()

    _load_dotenv()
    session = None
    if not args.csv_file:
        session = login()

    text = get_csv_text(session, args.set_id, args.csv_file)
    by_pos = parse_rows(text)

    wrote_any = False
    for pos in ("QB", "RB", "WR", "TE"):
        recs = by_pos[pos]
        if not recs:
            print(f"No rows parsed for {pos}.")
            continue
        out = f"{args.prefix}_{pos.lower()}.csv"
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv_module.DictWriter(f, fieldnames=OUT_COLUMNS[pos])
            w.writeheader()
            w.writerows(recs)
        print(f"Wrote {len(recs)} {pos}s to {out}.")
        wrote_any = True

    if not wrote_any:
        sys.exit("No data parsed for any position.")


if __name__ == "__main__":
    main()
