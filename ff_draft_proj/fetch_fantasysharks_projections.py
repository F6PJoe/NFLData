#!/usr/bin/env python3
"""
Pull Fantasy Sharks' season-long (preseason/draft) projections for QB/RB/WR/TE
directly from their public CSV export, no login needed.

  https://www.fantasysharks.com/apps/Projections/SeasonProjections.php?pos=<POS>&format=csv

This is the simple/legacy CSV export. The site's other projections export
(bert/forecasts/projections.php, used previously) started returning
403 Forbidden when called from non-residential IPs (e.g. GitHub Actions
runners) — confirmed it's IP-based blocking, not a User-Agent issue, since a
realistic browser UA didn't help. This endpoint includes bye week directly
(no separate ESPN schedule lookup needed) but does not report Pass Att (QB)
or Targets (RB/WR/TE) — left blank for those fields, same treatment as other
sources missing a stat.

Usage:
    python fetch_fantasysharks_projections.py

Requires: requests
"""

import argparse
import csv
import io
import os
import shutil
import sys
import time

import scoring

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cached")

# How long a cached snapshot may stand in for a live fetch. Past this, the
# source is DROPPED rather than used: preseason projections move enough
# (injuries, depth charts, holdouts) that month-old numbers would quietly
# drag the consensus while looking current. Better to lose one of ten
# sources than to average in stale data.
MAX_CACHE_AGE_DAYS = 14

CSV_URL = "https://www.fantasysharks.com/apps/Projections/SeasonProjections.php?pos={pos}&format=csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}

# Fantasy Sharks uses different team abbreviations than ESPN for some teams.
TEAM_ALIASES = {
    "GBP": "GB", "KCC": "KC", "LVR": "LV", "NEP": "NE", "NOS": "NO",
    "SFO": "SF", "TBB": "TB", "JAC": "JAX", "WAS": "WSH",
}

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


def num(value):
    value = (value or "").replace(",", "").strip()
    if not value or value == "-":
        return 0.0
    return float(value)


def format_name(name):
    # "Allen, Josh" -> "Josh Allen"
    if "," in name:
        last, first = name.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return name.strip()


class Blocked(Exception):
    """Site refused the request (403) — almost always the IP block, not us."""


def fetch_csv(pos, csv_file=None):
    if csv_file:
        with open(csv_file, encoding="utf-8") as f:
            text = f.read()
    else:
        import time

        import requests
        last = None
        # A couple of quick retries in case it's transient rate limiting; a
        # real IP block fails all of them and we fall back to cached CSVs.
        for attempt in range(3):
            try:
                resp = requests.get(CSV_URL.format(pos=pos), headers=HEADERS, timeout=30)
                if resp.status_code == 403:
                    last = Blocked(f"403 Forbidden for {pos}")
                    time.sleep(2 * (attempt + 1))
                    continue
                resp.raise_for_status()
                return list(csv.reader(io.StringIO(resp.text)))
            except requests.RequestException as e:
                last = e
                time.sleep(2 * (attempt + 1))
        raise last
    return list(csv.reader(io.StringIO(text)))


def build_record(pos, row):
    # Columns (by position, no usable header names — several are duplicated
    # across positions, e.g. "Yards"/"TDs" appear twice with different
    # meanings): Rank, ADP, ID, Name, Team, Bye, <position-specific...>
    name = format_name(row[3])
    team = TEAM_ALIASES.get(row[4].upper(), row[4].upper())
    bye = row[5]

    if pos == "QB":
        pass_comp, pass_yds, pass_td, pass_int = num(row[6]), num(row[7]), num(row[8]), num(row[9])
        rush_yds, rush_td, fum = num(row[10]), num(row[11]), num(row[12])
        s = {"pass_yds": pass_yds, "pass_td": pass_td, "pass_int": pass_int,
             "rush_yds": rush_yds, "rush_td": rush_td, "fum": fum}
        return scoring.qb_points(s), {
            "QB": name, "Team": team, "Bye": bye,
            "Pass Att": "", "Pass Comp": scoring.round2(pass_comp),
            "Pass Yds": scoring.round2(pass_yds), "Pass TD": scoring.round2(pass_td),
            "Pass Int": scoring.round2(pass_int), "Rush Att": "",
            "Rush Yds": scoring.round2(rush_yds), "Rush TD": scoring.round2(rush_td),
            "Fumbles": scoring.round2(fum),
        }
    elif pos == "RB":
        rush_att, rush_yds, rush_td, fum = num(row[6]), num(row[7]), num(row[8]), num(row[9])
        rec, rec_yds, rec_td = num(row[10]), num(row[11]), num(row[12])
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
        return scoring.ppr_points(s), {
            "RB": name, "Team": team, "Bye": bye,
            "Rush Att": scoring.round2(rush_att), "Rush Yds": scoring.round2(rush_yds),
            "Rush TD": scoring.round2(rush_td), "Targets": "",
            "Rec": scoring.round2(rec), "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td), "Fum": scoring.round2(fum),
        }
    elif pos == "WR":
        rec, rec_yds, rec_td = num(row[6]), num(row[7]), num(row[8])
        rush_att, rush_yds, rush_td, fum = num(row[9]), num(row[10]), num(row[11]), num(row[12])
        s = {"rush_yds": rush_yds, "rush_td": rush_td, "rec": rec,
             "rec_yds": rec_yds, "rec_td": rec_td, "fum": fum}
        return scoring.ppr_points(s), {
            "WR": name, "Team": team, "Bye": bye,
            "Targets": "", "Rec": scoring.round2(rec), "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td), "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds), "Rush TD": scoring.round2(rush_td),
            "Fum": scoring.round2(fum),
        }
    elif pos == "TE":
        rec, rec_yds, rec_td = num(row[6]), num(row[7]), num(row[8])
        rush_att, rush_yds, rush_td = num(row[9]), num(row[10]), num(row[11])
        s = {"rec": rec, "rec_yds": rec_yds, "rec_td": rec_td, "fum": num(row[12])}
        return scoring.ppr_points(s), {
            "TE": name, "Team": team, "Bye": bye,
            "Targets": "", "Rec": scoring.round2(rec), "Rec Yds": scoring.round2(rec_yds),
            "Rec TD": scoring.round2(rec_td), "Rush Att": scoring.round2(rush_att),
            "Rush Yds": scoring.round2(rush_yds), "Rush TD": scoring.round2(rush_td),
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="fantasysharks")
    ap.add_argument("--csv-dir", help="dir with saved <pos>.csv files instead of fetching")
    ap.add_argument("--save-cache", action="store_true",
                    help="also copy fetched CSVs into cached/ (run from a residential IP, then commit)")
    args = ap.parse_args()

    wrote_any = False
    blocked = []
    for pos in ("QB", "RB", "WR", "TE"):
        csv_file = f"{args.csv_dir}/{pos.lower()}.csv" if args.csv_dir else None
        out_path = f"{args.prefix}_{pos.lower()}.csv"
        snapshot = os.path.join(CACHE_DIR, f"{args.prefix}_{pos.lower()}.csv")
        try:
            rows = fetch_csv(pos, csv_file)
        except Exception as e:
            # Fantasy Sharks blocks non-residential IPs (GitHub Actions
            # runners), so this fetch succeeds locally and 403s in CI. Rather
            # than kill the run and silently drop a source from the consensus,
            # fall back to the committed snapshot in cached/ and shout about
            # its age. Refresh that snapshot by running this script with
            # --save-cache from a residential connection and committing it.
            src = out_path if os.path.exists(out_path) else (
                snapshot if os.path.exists(snapshot) else None)
            if src:
                age_d = (time.time() - os.path.getmtime(src)) / 86400
                if age_d > MAX_CACHE_AGE_DAYS:
                    print(f"[WARN] fantasysharks {pos}: {type(e).__name__}: {e} — "
                          f"cached snapshot is {age_d:.0f} days old (limit "
                          f"{MAX_CACHE_AGE_DAYS}), DROPPING source rather than "
                          f"averaging in stale projections. Refresh with: "
                          f"python fetch_fantasysharks_projections.py --save-cache")
                    blocked.append(pos)
                    continue
                if src != out_path:
                    shutil.copyfile(src, out_path)
                print(f"[WARN] fantasysharks {pos}: {type(e).__name__}: {e} — "
                      f"using cached {src} ({age_d:.1f} days old)")
                blocked.append(pos)
                wrote_any = True
                continue
            print(f"[WARN] fantasysharks {pos}: {type(e).__name__}: {e} — "
                  f"no cached snapshot at {snapshot}, source dropped from consensus")
            blocked.append(pos)
            continue
        data_rows = rows[1:]
        recs = []
        for row in data_rows:
            if len(row) < 13 or not row[3].strip():
                continue
            recs.append(build_record(pos, row))
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
        if args.save_cache:
            os.makedirs(CACHE_DIR, exist_ok=True)
            shutil.copyfile(out, os.path.join(CACHE_DIR, out))
            print(f"  cached -> cached/{out}")
        wrote_any = True

    if blocked:
        print(f"[WARN] fantasysharks: {len(blocked)}/4 positions unavailable "
              f"({', '.join(blocked)}) — consensus is using cached/partial data for this source")

    if not wrote_any:
        sys.exit("No data parsed for any position.")


if __name__ == "__main__":
    main()
