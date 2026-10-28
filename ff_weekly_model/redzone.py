"""Red-zone roles: each player's share of his team's plays inside the 10.

Touchdowns were split by OVERALL share -- a back with half the carries got
half the rushing TDs. But touchdowns come from inside the 10, and teams hand
those plays out differently: a goal-line back scores well beyond his carry
share, a third-down or between-the-20s back well short of it, and tight ends
draw end-zone targets out of proportion to their volume.

From play-by-play, per player and week: carries and targets inside the 10,
and his team's totals in the same game (only games he played count for him).
Week 0 holds last season, so a role carries over until this season says
otherwise.
"""

import collections
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PBP = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")
LINE = 10


def _season(year):
    """(week, team) team totals, (week, pid, team) player counts -- cached.
    Each is [rz carries, rz targets, all carries, all targets]."""
    cache = os.path.join(HERE, "data", f"redzone2_{year}.csv")
    src = os.path.join(PBP, f"pbp_{year}.csv")
    team = collections.defaultdict(lambda: [0, 0, 0, 0])
    ply = collections.defaultdict(lambda: [0, 0, 0, 0])
    if os.path.exists(cache) and (not os.path.exists(src) or
                                  os.path.getmtime(cache) >= os.path.getmtime(src)):
        with open(cache, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                k = (int(r["week"]), r["team"])
                v = [int(r["car"]), int(r["tgt"]), int(r["car_all"]), int(r["tgt_all"])]
                if r["player_id"] == "TEAM":
                    team[k] = v
                else:
                    ply[(k[0], r["player_id"], r["team"])] = v
        return team, ply
    if not os.path.exists(src):
        return team, ply
    with open(src, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("season_type") != "REG" or r.get("two_point_attempt") == "1":
                continue
            try:
                yl = float(r.get("yardline_100") or "nan")
            except ValueError:
                yl = float("nan")
            rz = yl <= LINE
            wk, tm = int(r["week"]), r["posteam"]
            if r.get("rush") == "1" and r.get("qb_kneel") != "1":
                pid, i = r.get("rusher_player_id"), 0
            elif r.get("pass") == "1":
                pid, i = r.get("receiver_player_id"), 1
            else:
                continue
            if pid in (None, "", "NA"):
                continue
            team[(wk, tm)][i + 2] += 1
            ply[(wk, pid, tm)][i + 2] += 1
            if rz:
                team[(wk, tm)][i] += 1
                ply[(wk, pid, tm)][i] += 1
    with open(cache, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["week", "team", "player_id", "car", "tgt", "car_all", "tgt_all"])
        for (wk, tm), v in team.items():
            w.writerow([wk, tm, "TEAM", *v])
        for (wk, pid, tm), v in ply.items():
            w.writerow([wk, tm, pid, *v])
    return team, ply


def usage(year, played):
    """pid -> {week: [rz car, team rz car, rz tgt, team rz tgt, car, team car,
    tgt, team tgt]}; week 0 = last
    season. `played[year]` = {pid: {week: team}} -- the games each player was
    on the field, so a team's red-zone plays only count against a player in
    games he actually played."""
    out = collections.defaultdict(lambda: collections.defaultdict(lambda: [0.0] * 8))
    for yr, wk_key in ((year - 1, lambda w: 0), (year, lambda w: w)):
        team, ply = _season(yr)
        for pid, games in played.get(yr, {}).items():
            for wk, tm in games.items():
                tv = team.get((wk, tm), (0, 0, 0, 0))
                pv = ply.get((wk, pid, tm), (0, 0, 0, 0))
                c = out[pid][wk_key(wk)]
                c[0] += pv[0]; c[1] += tv[0]; c[2] += pv[1]; c[3] += tv[1]
                c[4] += pv[2]; c[5] += tv[2]; c[6] += pv[3]; c[7] += tv[3]
    return out
