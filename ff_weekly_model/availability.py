#!/usr/bin/env python3
"""Who is playing this week, and how much -- applied BEFORE share normalisation.

This is the layer that decides which players compete for a team's touches. It
is a filter on the pool, not a projection: the model never predicts whether
someone will play. Official designations, roster transactions and Joe's own
call decide that, in this order of authority:

  1. roster status      RES / EXE / CUT / DEV / INA / RET  -> removed
                        (catches IR, the commissioner's exempt list, practice
                         squad and cuts -- none of which are "injuries" and
                         none of which any injury feed reports)
  2. injury report      Out / Doubtful                     -> removed
  3. rotation check     no snaps last week AND listed 3rd or deeper -> removed
                        (a healthy scratch nobody designates; kept conservative
                         so a returning starter listed 1st or 2nd is never cut)
  4. Joe's review sheet the Questionable calls, which OVERRIDE the above

Returns a multiplier per player: 0.0 removes him and hands his share to his
teammates, 1.0 is untouched, and values between scale him down and give the
remainder back to the position group.

Every exclusion carries a reason, so a surprising projection can always be
traced to the file that caused it.
"""

import collections
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UTIL = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")

PLAYABLE_STATUS = {"ACT"}
BLOCKING_REPORT = {"Out", "Doubtful"}
STATUS_MEANING = {"RES": "injured reserve", "EXE": "exempt list", "CUT": "released",
                  "DEV": "practice squad", "INA": "inactive", "RET": "retired",
                  "TRD": "traded"}


def _roster_status(year, week=None):
    """Latest status AT OR BEFORE `week`. Using the newest row regardless of
    week leaks the future into a backfilled projection -- a player placed on IR
    after week 1 would be scrubbed from the week 1 slate."""
    path = os.path.join(DATA, f"roster_{year}.csv")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            pid, wk = r.get("gsis_id"), int(r.get("week") or 0)
            if not pid or (week is not None and wk > week):
                continue
            prev = out.get(pid)
            if prev is None or wk >= prev[1]:
                out[pid] = (r.get("status", ""), wk)
    return {p: s for p, (s, _) in out.items()}


def _injury_report(year, week):
    path = os.path.join(DATA, f"injuries_{year}.csv")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["week"] == str(week) and r.get("gsis_id"):
                out[r["gsis_id"]] = r.get("report_status", "")
    return out


def _last_week_snaps(year, week):
    """player -> offense snaps in the most recent completed week before `week`."""
    path = os.path.join(UTIL, f"snaps_{year}.csv")
    xwalk = {}
    px = os.path.join(UTIL, "players.csv")
    if os.path.exists(px):
        with open(px, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("pfr_id") and r.get("gsis_id"):
                    xwalk[r["pfr_id"]] = r["gsis_id"]
    if not os.path.exists(path):
        return {}, None
    byweek = collections.defaultdict(dict)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            g = xwalk.get(r.get("pfr_player_id"))
            if g and r.get("game_type") == "REG":
                byweek[int(r["week"])][g] = float(r.get("offense_snaps") or 0)
    prior = [w for w in byweek if w < week]
    if not prior:
        return {}, None
    last = max(prior)
    return byweek[last], last


def _ord(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1:'st', 2:'nd', 3:'rd'}.get(n % 10, 'th')}"


def build(year, week, *, candidates, depth_rank=None, review=None):
    """candidates: {player_id: team}. -> ({pid: multiplier}, {pid: reason})."""
    status = _roster_status(year, week)
    report = _injury_report(year, week)
    snaps, snap_week = _last_week_snaps(year, week)
    depth_rank = depth_rank or {}
    review = review or {}

    mult, reason = {}, {}
    for pid in candidates:
        st = status.get(pid)
        if st and st not in PLAYABLE_STATUS:
            mult[pid] = 0.0
            reason[pid] = f"roster: {STATUS_MEANING.get(st, st)}"
            continue
        rep = report.get(pid, "")
        if rep in BLOCKING_REPORT:
            mult[pid] = 0.0
            reason[pid] = f"injury report: {rep}"
            continue
        # rotation check -- conservative on purpose
        if snap_week is not None and depth_rank.get(pid, 1) >= 3:
            if snaps.get(pid, 0) == 0:
                mult[pid] = 0.0
                reason[pid] = f"rotation: no snaps in wk{snap_week} (listed {_ord(depth_rank[pid])})"
                continue
        mult[pid] = 1.0

    # Joe's calls win over everything above
    for pid, m in review.items():
        if pid in candidates:
            mult[pid] = m
            reason[pid] = ("review sheet: OUT" if m == 0.0
                           else f"review sheet: {m:.0%} usage")
    return mult, reason


def summarise(mult, reason, names=None):
    names = names or {}
    removed = [(p, reason[p]) for p, m in mult.items() if m == 0.0]
    reduced = [(p, reason[p]) for p, m in mult.items() if 0 < m < 1]
    by = collections.Counter(r.split(":")[0] for _, r in removed)
    return removed, reduced, by
