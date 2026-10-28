#!/usr/bin/env python3
"""Partial games: a game a player LEFT hurt counts over the plays he was there for.

Joe, 2026-10-28: "build the partial game so it gets counted, but not counted as
a he didn't play in 3 qtrs." The exit rules used to throw such a game out; the
box score would otherwise read it as a full game of tiny usage. Here it stays
in, measured honestly:

  his share     his targets / the team's targets BEFORE he left (same for
                carries) -- the share he was earning while on the field
  game weight   the fraction of the team's offensive plays run before he left,
                so a one-quarter game counts as a quarter of a game

When he left:
  * a play-by-play exit ("X was injured during the play", no return) gives the
    exact play;
  * otherwise (a snap collapse the injury report confirms) it is estimated from
    snaps: he played `pct` of the team's snaps against a usual `ref`, so he was
    there for the first pct / ref of the game.
Checked against 2024-25 participation data (who was on the field for every
play): `python partial_games.py --calibrate 2025`.

NOT ADOPTED (2026-10-28): 9 versions tested against dropping the game, none
passed Joe's rule (results in ../TESTED_SETTINGS.md, PARTIAL_GAME). The model
instead keeps the exit game as it happened at a weight (EXIT_KEEP_W). Kept
for the calibration: the play-by-play exit moment is exact; snap-only exits
were half in-and-out games.
"""

import argparse
import collections
import csv
import os
import statistics

import sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # research/ -> ff_weekly_model
sys.path.insert(0, HERE)
DATA = os.path.join(HERE, "data")
UTIL = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")
SKILL = ("RB", "WR", "TE")


def team_plays(year, positions):
    """(team, week) -> [(game_secs_left, play_id, skill_target, skill_carry)],
    the team's offensive snaps in order. Targets and carries count only for
    RB/WR/TE, the same denominators the model's shares use."""
    out = collections.defaultdict(list)
    path = os.path.join(UTIL, f"pbp_{year}.csv")
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("season_type") != "REG" or r.get("play_type") not in ("pass", "run"):
                continue
            if r.get("two_point_attempt") == "1" or not r.get("posteam"):
                continue
            rec, rus = r.get("receiver_player_id") or "", r.get("rusher_player_id") or ""
            t = 1 if rec and positions.get(rec) in SKILL else 0
            c = 1 if rus and positions.get(rus) in SKILL and r.get("play_type") == "run" else 0
            out[(r["posteam"], int(r["week"]))].append(
                (float(r.get("game_seconds_remaining") or 0), int(float(r["play_id"])), t, c))
    for v in out.values():
        v.sort(key=lambda x: (-x[0], x[1]))
    return out


def pbp_exit_secs(year, min_secs=0):
    """(gsis_id, week) -> game seconds left when he was knocked out (no return)."""
    path = os.path.join(DATA, f"injury_exits_{year}.csv")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("exited") == "1" and float(r.get("secs_remaining") or 0) >= min_secs:
                out[(r["player_id"], int(r["week"]))] = float(r["secs_remaining"])
    return out


def usual_pct(wks, w, prev_avg=None, exits=()):
    """His usual snap share before week w: median of earlier games that were not
    exits; last season's average when there are none."""
    before = [v for x, v in wks.items() if x < w and v > 0 and x not in exits]
    if before:
        return statistics.median(before)
    return prev_avg


def estimate(exits, team_of, plays, snap_pct, snap_prev=None, exit_secs=None, ordered=True):
    """(pid, week) -> (game_weight, target_ratio, carry_ratio) for each exit game.
    target_ratio = share of the team's skill targets that came before he left;
    his share over the part he played is his full-game share / target_ratio.
    A snap-only exit with ordered=False is spread evenly over the game (he was
    in and out) rather than placed at the start: every ratio = pct / usual."""
    exit_secs = exit_secs or {}
    out = {}
    ex_by_pid = collections.defaultdict(set)
    for pid, w in exits:
        ex_by_pid[pid].add(w)
    for pid, w in exits:
        pl = plays.get((team_of.get((pid, w)), w))
        if not pl:
            continue
        n_all = len(pl)
        if (pid, w) in exit_secs:
            s = exit_secs[(pid, w)]
            n = sum(1 for p in pl if p[0] >= s)
        else:
            wks = snap_pct.get(pid, {})
            pct = wks.get(w)
            prev = snap_prev.get(pid) if snap_prev else None
            prev_avg = sum(prev.values()) / len(prev) if prev else None
            ref = usual_pct(wks, w, prev_avg, ex_by_pid[pid])
            if pct is None or not ref:
                continue
            if not ordered:
                f = min(pct / ref, 1.0)
                out[(pid, w)] = (f, f, f)
                continue
            n = round(n_all * min(pct / ref, 1.0))
        n = max(0, min(n, n_all))
        tt = sum(p[2] for p in pl); tc = sum(p[3] for p in pl)
        bt = sum(p[2] for p in pl[:n]); bc = sum(p[3] for p in pl[:n])
        out[(pid, w)] = (n / n_all, bt / tt if tt else 0.0, bc / tc if tc else 0.0)
    return out


def apply(tgt, car, exits, info, cap=1.0, min_f=0.0, exact=None):
    """Rescale each exit game's share to the part he played. -> {(pid, week): weight}.
    An exit with no estimate (no play-by-play for the game, no usual snap
    share), or with no team targets AND no carries before he left, carries no
    information: it is dropped, as before. So is a stint under `min_f` of the
    game, and -- with `exact` (the play-by-play exits) -- any exit whose moment
    is only estimated from snaps."""
    weights = {}
    for pid, w in exits:
        f, rt, rc = info.get((pid, w), (0.0, 0.0, 0.0))
        if exact is not None and (pid, w) not in exact:
            f = 0.0
        if f <= 0 or f < min_f or (rt <= 0 and rc <= 0):
            for d in (tgt, car):
                d.get(pid, {}).pop(w, None)
            continue
        for d, r_ in ((tgt, rt), (car, rc)):
            if pid in d and w in d[pid]:
                d[pid][w] = min(d[pid][w] / r_, cap) if r_ > 0 else d[pid][w]
        weights[(pid, w)] = f
    return weights


# ------------------------------------------------------------------ calibration

def on_field(year):
    """(game_id, play_id) -> set of offensive gsis_ids (participation data)."""
    path = os.path.join(DATA, "participation", f"pbp_participation_{year}.csv")
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            ids = r.get("offense_players") or ""
            out[(r["nflverse_game_id"], int(float(r["play_id"])))] = set(ids.split(";")) if ids else set()
    return out


def calibrate(year):
    """How close is the snap-based exit point to the real one? Uses every
    confirmed exit game in `year` that the model's exit rules would flag."""
    import project as P
    rows = P.load_players(year)
    tgt, car, pos, _ = P.shares_by_week(rows)
    team_of = {(r["player_id"], int(r["week"])): r["team"] for r in rows}
    snaps, snaps_prev = P.load_snap_pct(year), P.load_snap_pct(year - 1)
    found = set()
    P.drop_exit_weeks(tgt, car, snaps, snaps_prev, positions=pos,
                      confirmed=P.injury_confirmed(year), returning=P.first_games_back(year),
                      pregame=P.listed_pregame(year), collect=found)
    secs = pbp_exit_secs(year, P.PBP_EXIT_MIN_SECS)
    plays = team_plays(year, pos)
    est_snap = estimate(found, team_of, plays, snaps, snaps_prev)            # snaps only
    est_pbp = estimate(set(secs), team_of, plays, snaps, snaps_prev, secs)   # pbp moment
    gid = {}
    with open(os.path.join(UTIL, f"pbp_{year}.csv"), newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("posteam"):
                gid[(r["posteam"], int(r["week"]), int(float(r["play_id"])))] = r["game_id"]
    field = on_field(year)

    def actual(pid, w):
        tm = team_of.get((pid, w))
        pl = plays.get((tm, w))
        if not pl:
            return None
        last = -1
        for i, p in enumerate(pl):
            if pid in field.get((gid.get((tm, w, p[1])), p[1]), ()):
                last = i
        if last < 0:
            return None
        n = last + 1
        tt = sum(p[2] for p in pl); bt = sum(p[2] for p in pl[:n])
        return n / len(pl), (bt / tt if tt else 0.0)

    for label, est in (("snap-collapse exits, estimated from snaps", est_snap),
                       ("play-by-play exits, from the injury play", est_pbp)):
        err_f, err_r, n = [], [], 0
        for k, (f, rt, _) in est.items():
            a = actual(*k)
            if a is None:
                continue
            n += 1
            err_f.append(f - a[0]); err_r.append(rt - a[1])
        if not n:
            print(f"  {label}: none")
            continue
        mae = lambda v: sum(abs(x) for x in v) / len(v)
        print(f"  {label}: {n} games")
        print(f"     share of the game he was there for: off by {mae(err_f):.0%} on average "
              f"(bias {statistics.mean(err_f):+.0%})")
        print(f"     share of team targets before he left: off by {mae(err_r):.0%} "
              f"(bias {statistics.mean(err_r):+.0%})")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calibrate", type=int, metavar="YEAR", required=True)
    calibrate(ap.parse_args().calibrate)
