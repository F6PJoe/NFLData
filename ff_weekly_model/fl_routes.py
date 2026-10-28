"""Fantasy Life (PFF-charted) route data, joined to gsis ids.

Pulled by ff_utilization/fetch_fantasylife_utilization.py into
data/fl_util/ (NOT the usage tool's own data folder, whose
utilization_weekly.json is the file the site uploads). FL has its own player
ids, so players are matched by name: season-wide (name, team) first, then
name alone when it is unique, then nflverse's player list -- a game with
routes but no catch has no stats row to match by week.
"""

import collections
import csv
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audit_vs_sources as A  # noqa: E402

USAGE_TOOL = os.path.join(os.path.dirname(HERE), "ff_utilization", "data")
PLAYERS = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse", "players.csv")


def _ids(year):
    by_nt, by_n = {}, collections.defaultdict(set)
    for y in (year - 1, year, year + 1):
        p = os.path.join(HERE, "data", f"stats_player_week_{y}.csv")
        if not os.path.exists(p):
            continue
        with open(p, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r["position"] in ("RB", "WR", "TE", "FB"):
                    n = A.norm(r["player_display_name"])
                    if y == year:
                        by_nt[(n, r["team"])] = r["player_id"]
                    by_n[n].add(r["player_id"])
    if os.path.exists(PLAYERS):
        with open(PLAYERS, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("gsis_id") and r.get("position") in ("RB", "WR", "TE", "FB"):
                    by_n[A.norm(r.get("display_name", ""))].add(r["gsis_id"])
    return by_nt, by_n


def load(year):
    """gsis_id -> {week: {"route_pct", "routes", "tprr", "ez_tgts", "i5", ...}}."""
    # This season's file comes from the usage tool's own weekly pull (read
    # only -- nothing here writes to its folder); past seasons were pulled once
    # into data/fl_util. Take whichever reaches the latest week.
    def last_week(f):
        try:
            return int(os.path.basename(f).rsplit("-", 1)[1].split(".")[0])
        except (IndexError, ValueError):
            return 0
    files = (glob.glob(os.path.join(HERE, "data", "fl_util", f"utilization_weekly_{year}_wk*.csv"))
             + glob.glob(os.path.join(USAGE_TOOL, f"utilization_weekly_{year}_wk1-*.csv")))
    files = sorted(files, key=lambda f: (last_week(f), os.path.getmtime(f)))
    out = collections.defaultdict(dict)
    if not files:
        return out
    by_nt, by_n = _ids(year)
    unmatched = 0
    with open(files[-1], newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            n = A.norm(r["player"])
            pid = by_nt.get((n, r["team"]))
            if not pid and len(by_n.get(n, ())) == 1:
                pid = next(iter(by_n[n]))
            if not pid:
                unmatched += 1
                continue
            f = lambda k: float(r.get(k) or 0)
            out[pid][int(r["week"])] = {
                "route_pct": f("routes_pct") / 100, "routes": f("routes"),
                "snap_pct": f("snaps_pct") / 100, "tgt": f("targets"),
                "tprr": f("tprr") / 100,
                "ez_tgts": f("ez_tgts"), "i5": f("inside5_rush"),
                "team_routes": f("team_routes"), "team_targets": f("team_targets")}
    load.unmatched = unmatched
    return out
