#!/usr/bin/env python3
"""Blowout garbage time -> data/garbage_<year>.csv (project.py GARBAGE).

Joe, 2026-11-19 (PIT wk10: Warren 7 carries, Nichols 6, starters pulled late in a blowout): "I would only consider
this a thing if the backup got significant work late in the game and he usually is not used that much or at all."

A team-game is FLAGGED when, after garbage time starts (first play in the 4th quarter with the score GARBAGE_MARGIN+
apart), a player who is usually not used -- under USUAL_MAX of his team's carries (backs) / targets (receivers) in his
earlier games this season, or no earlier games -- got BACKUP_MIN_RB carries + targets (RB) or BACKUP_MIN_REC targets
(WR/TE) in that window. For a flagged game the file lists every skill player's carries and targets BEFORE garbage time
and the team's totals before it, so the model can count the game as it stood when it was still a game.

    python build_garbage.py --year 2026
"""
import argparse
import collections
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
PBP = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse", "pbp_{}.csv")

GARBAGE_MARGIN = 17
USUAL_MAX = 0.10
BACKUP_MIN_RB = 4
BACKUP_MIN_REC = 3
SKILL = ("QB", "RB", "WR", "TE", "FB")


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def build(year):
    pos, usual = {}, collections.defaultdict(dict)    # pid -> {week: (car share, tgt share)}
    tt = collections.defaultdict(lambda: [0.0, 0.0])
    rows = [r for r in csv.DictReader(open(os.path.join(DATA, f"stats_player_week_{year}.csv"), encoding="utf-8"))
            if r["season_type"] == "REG" and r["position"] in SKILL]
    for r in rows:
        pos[r["player_id"]] = r["position"]
        t = tt[(r["team"], int(r["week"]))]
        t[0] += num(r["carries"]); t[1] += num(r["targets"])
    for r in rows:
        t = tt[(r["team"], int(r["week"]))]
        usual[r["player_id"]][int(r["week"])] = (num(r["carries"]) / t[0] if t[0] else 0.0,
                                                 num(r["targets"]) / t[1] if t[1] else 0.0)
    # no earlier games this season (week 1, or his first game): last season's average decides "usual"
    last = {}
    pp = os.path.join(DATA, f"stats_player_week_{year - 1}.csv")
    if os.path.exists(pp):
        ltt = collections.defaultdict(lambda: [0.0, 0.0])
        lrows = [r for r in csv.DictReader(open(pp, encoding="utf-8"))
                 if r["season_type"] == "REG" and r["position"] in SKILL]
        for r in lrows:
            t = ltt[(r["team"], int(r["week"]))]
            t[0] += num(r["carries"]); t[1] += num(r["targets"])
        acc = collections.defaultdict(list)
        for r in lrows:
            t = ltt[(r["team"], int(r["week"]))]
            acc[r["player_id"]].append((num(r["carries"]) / t[0] if t[0] else 0.0,
                                        num(r["targets"]) / t[1] if t[1] else 0.0))
        last = {pid: (sum(v[0] for v in a) / len(a), sum(v[1] for v in a) / len(a)) for pid, a in acc.items()}
    plays = collections.defaultdict(list)    # (team, week) -> [(garbage?, rusher, receiver)]
    with open(PBP.format(year), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["season_type"] != "REG" or not r["posteam"]:
                continue
            rush = r["rush_attempt"] == "1" and r["two_point_attempt"] != "1" and r["qb_kneel"] != "1"
            pas = r["pass_attempt"] == "1" and r["two_point_attempt"] != "1" and r["sack"] != "1"
            if not (rush or pas):
                continue
            late = num(r["qtr"]) >= 4 and abs(num(r["score_differential"])) >= GARBAGE_MARGIN
            plays[(r["posteam"], int(r["week"]))].append(
                (late, r["rusher_player_id"] if rush else "", r["receiver_player_id"] if pas else ""))
    out = []
    for (tm, wk), pl in sorted(plays.items()):
        start = next((i for i, p in enumerate(pl) if p[0]), None)
        if start is None:
            continue
        late = collections.Counter()
        for _, ru, rc in pl[start:]:
            if ru:
                late[(ru, "c")] += 1
            if rc:
                late[(rc, "t")] += 1
        who = []
        for pid in {k[0] for k in late}:
            po = pos.get(pid)
            if po not in ("RB", "WR", "TE", "FB"):
                continue
            prev = [v for w, v in usual.get(pid, {}).items() if w < wk]
            if not prev and pid in last:
                prev = [last[pid]]
            if po in ("RB", "FB"):
                n_ = late[(pid, "c")] + late[(pid, "t")]
                us = max((sum(v[0] for v in prev) / len(prev)) if prev else 0.0,
                         (sum(v[1] for v in prev) / len(prev)) if prev else 0.0)
                if n_ >= BACKUP_MIN_RB and us < USUAL_MAX:
                    who.append((pid, n_, us))
            else:
                n_ = late[(pid, "t")]
                us = (sum(v[1] for v in prev) / len(prev)) if prev else 0.0
                if n_ >= BACKUP_MIN_REC and us < USUAL_MAX:
                    who.append((pid, n_, us))
        if not who:
            continue
        pre = collections.Counter()
        for _, ru, rc in pl[:start]:
            if ru:
                pre[(ru, "c")] += 1
            if rc:
                pre[(rc, "t")] += 1
        tc = sum(v for k, v in pre.items() if k[1] == "c")
        tg = sum(v for k, v in pre.items() if k[1] == "t")
        flag = "; ".join(f"{pid} {n_} late (usual {us:.0%})" for pid, n_, us in who)
        ids = {k[0] for k in pre} | {k[0] for k in late}
        for pid in ids:
            out.append({"team": tm, "week": wk, "player_id": pid, "car_pre": pre[(pid, "c")],
                        "tgt_pre": pre[(pid, "t")], "team_car_pre": tc, "team_tgt_pre": tg,
                        "plays_pre": start, "plays": len(pl), "flagged_by": flag})
    dest = os.path.join(DATA, f"garbage_{year}.csv")
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0].keys()) if out else ["team", "week", "player_id"])
        w.writeheader()
        w.writerows(out)
    games = sorted({(r["team"], r["week"], r["flagged_by"]) for r in out}, key=lambda x: (x[1], x[0]))
    print(f"  {year}: {len(games)} flagged team-games -> {os.path.basename(dest)}")
    return games


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, nargs="+", default=[2026])
    ap.add_argument("--show", action="store_true")
    a = ap.parse_args()
    for y in a.year:
        g = build(y)
        if a.show:
            for tm, wk, f in g:
                print(f"    wk{wk:>2} {tm}: {f}")
