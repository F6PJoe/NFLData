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
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UTIL = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")

PLAYABLE_STATUS = {"ACT"}
BLOCKING_REPORT = {"Out", "Doubtful"}
# Sleeper statuses that mean "cannot play", beyond the two above. These are
# administrative facts rather than judgement calls, so they are applied and
# not put on the review sheet. nflverse roster status is supposed to catch
# them, but it lagged badly -- Jonathon Brooks sat on IR with an abdominal
# injury while nflverse still read ACT, and the model handed him 5.4 points
# and a slice of Carolina's backfield.
SLEEPER_BLOCKING = {"IR", "PUP", "Sus", "DNR", "COV", "NA"}
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


SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}


def norm_name(s):
    """Lowercase, strip punctuation and generational suffixes."""
    s = (s or "").lower()
    s = "".join(c for c in s if c.isalnum() or c.isspace())
    parts = [p for p in s.split() if p not in SUFFIXES]
    return " ".join(parts)


def _gsis_by_name(year):
    """(name, team) and name -> gsis_id, from the newest depth-chart snapshot.

    Sleeper leaves gsis_id null for most players -- 84% of tagged skill players
    when this was written, including starting quarterbacks -- so matching on it
    alone silently loses them. Name plus team is the fallback.
    """
    path = os.path.join(DATA, f"depth_charts_{year}.csv")
    if not os.path.exists(path):
        return {}, {}
    snaps = collections.defaultdict(list)
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("gsis_id") and r.get("player_name"):
                snaps[r["dt"]].append((r["player_name"], r["team"], r["gsis_id"]))
    if not snaps:
        return {}, {}
    pair, solo = {}, collections.defaultdict(set)
    for nm, tm, gid in snaps[max(snaps)]:
        pair[(norm_name(nm), tm)] = gid
        solo[norm_name(nm)].add(gid)
    # a bare name is only safe where it is unambiguous
    return pair, {n: next(iter(g)) for n, g in solo.items() if len(g) == 1}


SLEEPER = os.path.join(os.path.dirname(HERE), "ff_projections", "cached", "sleeper")


def sleeper_tags(year=None, before=None):
    """gsis_id -> (status, body part) from the newest cached Sleeper snapshot.

    A SECOND injury source, and on most days a faster one. The official report
    is a Wednesday-to-Friday artifact: on Tuesday it is empty, while Sleeper is
    already carrying what beat reporters filed over the weekend. It has no week
    column -- it describes right now -- so the cache's age is what matters, and
    the caller is expected to surface it.
    """
    blob, stamp = _sleeper_blob(before)
    if not blob:
        return {}, None
    pair, solo = _gsis_by_name(year) if year else ({}, {})
    out = {}
    for v in blob.values():
        if not isinstance(v, dict):
            continue
        st = v.get("injury_status")
        if not st:
            continue
        gid = v.get("gsis_id")
        if not gid:
            nm = norm_name(f"{v.get('first_name','')} {v.get('last_name','')}")
            gid = pair.get((nm, v.get("team"))) or solo.get(nm)
        if gid:
            out[gid] = (st, v.get("injury_body_part") or "")
    return out, stamp


def _sleeper_blob(before=None):
    """Newest snapshot -- or, with before="YYYY-MM-DD", the newest one dated
    strictly earlier (what Sleeper said before that day)."""
    if not os.path.isdir(SLEEPER):
        return None, None
    snaps = sorted(f for f in os.listdir(SLEEPER)
                   if f.startswith("players_nfl_") and f.endswith(".json")
                   and (before is None or f[len("players_nfl_"):-len(".json")] < before))
    if not snaps:
        return None, None
    with open(os.path.join(SLEEPER, snaps[-1]), encoding="utf-8") as fh:
        return json.load(fh), snaps[-1][len("players_nfl_"):-len(".json")]


def sleeper_meta(year=None):
    """gsis_id -> {player, pos, team} for anyone Sleeper knows about.

    Needed because a player Sleeper has already ruled out is filtered before
    the projections file is written, so his name has to come from somewhere
    else for the review sheet to be able to list him.
    """
    blob, _ = _sleeper_blob()
    if not blob:
        return {}
    pair, solo = _gsis_by_name(year) if year else ({}, {})
    out = {}
    for v in blob.values():
        if not isinstance(v, dict):
            continue
        nm = f"{v.get('first_name','')} {v.get('last_name','')}".strip()
        gid = v.get("gsis_id") or pair.get((norm_name(nm), v.get("team")))             or solo.get(norm_name(nm))
        if gid:
            out[gid] = {"player": nm, "pos": v.get("position") or "-",
                        "team": v.get("team") or "-"}
    return out


def _last_week_snaps(year, week):
    """-> ({team: {player: offense snaps}} in EACH TEAM's most recent game
    before `week`, {team: that week}). Per team, not one league week: a team
    coming off a bye has no snaps "last week", and the rotation check was
    removing every player listed 3rd or lower on it (Miami wk7 2026, off its
    wk6 bye: Kevin Coleman Jr., 17% of the targets, "no snaps in wk6")."""
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
    byteam = collections.defaultdict(lambda: collections.defaultdict(dict))
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            g = xwalk.get(r.get("pfr_player_id"))
            if g and r.get("game_type") == "REG" and int(r["week"]) < week:
                byteam[r.get("team")][int(r["week"])][g] = float(r.get("offense_snaps") or 0)
    snaps, last = {}, {}
    for tm, wks in byteam.items():
        lw = max(wks)
        last[tm] = lw
        snaps[tm] = wks[lw]
    return snaps, last


def _ord(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1:'st', 2:'nd', 3:'rd'}.get(n % 10, 'th')}"


def build(year, week, *, candidates, depth_rank=None, review=None, positions=None):
    """candidates: {player_id: team}. -> ({pid: multiplier}, {pid: reason}).

    positions ({pid: pos}) lets the rotation check use a player's rank among
    the players still AVAILABLE, not his printed depth-chart slot. Without it,
    a team's RB3 was cut for being "listed 3rd" even when the RB2 ahead of him
    was out -- which in week 3 2026 handed Jaylen Warren 100% of Pittsburgh's
    carries once Rico Dowdle was ruled out.
    """
    status = _roster_status(year, week)
    report = _injury_report(year, week)
    tags, _tag_date = sleeper_tags(year)
    snaps, snap_week = _last_week_snaps(year, week)
    depth_rank = depth_rank or {}
    review = review or {}

    # who is gone for a reason that has nothing to do with the rotation check,
    # so that everyone behind them moves up a slot before it runs
    gone = set()
    for pid in candidates:
        st = status.get(pid)
        rep = report.get(pid, "")
        tag = "" if rep else tags.get(pid, ("", ""))[0]
        if st and st not in PLAYABLE_STATUS and rep == "Questionable":
            st = None
        if ((st and st not in PLAYABLE_STATUS) or rep in BLOCKING_REPORT
                or tag in BLOCKING_REPORT or tag in SLEEPER_BLOCKING
                or review.get(pid) == 0.0):
            gone.add(pid)

    def live_rank(pid):
        r = depth_rank.get(pid, 1)
        if not positions or pid not in positions:
            return r
        tm, po = candidates[pid], positions[pid]
        ahead = sum(1 for q, t in candidates.items()
                    if q != pid and t == tm and positions.get(q) == po
                    and depth_rank.get(q, 99) < r and q not in gone)
        return ahead + 1

    # a player whose empty last week was an INJURY, not the bench: officially
    # Questionable now (designated to return), or ruled out / on reserve last
    # week. Only these skip the rotation check -- a practice-report listing
    # alone does not (Hollywood Brown, Sills: healthy depth, rightly removed).
    prev_report = _injury_report(year, week - 1) if week and week > 1 else {}
    prev_status = _roster_status(year, week - 1) if week and week > 1 else {}

    def returning(pid):
        return (report.get(pid) == "Questionable"
                or prev_report.get(pid) in BLOCKING_REPORT
                or prev_status.get(pid) in ("RES", "PUP", "EXE"))

    mult, reason = {}, {}
    for pid in candidates:
        st = status.get(pid)
        # THIS WEEK'S official game designation outranks a roster status: a
        # player listed Questionable has been designated to return / activated
        # (Jordan Mason MIN wk7 2026: Questionable, roster still "RES").
        # Out / Doubtful are handled just below either way.
        if st and st not in PLAYABLE_STATUS and report.get(pid) == "Questionable":
            st = None
        if st and st not in PLAYABLE_STATUS:
            mult[pid] = 0.0
            reason[pid] = f"roster: {STATUS_MEANING.get(st, st)}"
            continue
        rep = report.get(pid, "")
        if rep in BLOCKING_REPORT:
            mult[pid] = 0.0
            reason[pid] = f"injury report: {rep}"
            continue
        # Sleeper only gets a say where the official report is silent -- an
        # official designation always outranks an aggregated one.
        if not rep:
            tag, part = tags.get(pid, ("", ""))
            if tag in BLOCKING_REPORT or tag in SLEEPER_BLOCKING:
                mult[pid] = 0.0
                reason[pid] = f"sleeper: {tag}" + (f" ({part})" if part else "")
                continue
        # rotation check -- conservative on purpose. Not for a player on THIS
        # week's injury report: his empty last week was the injury, not the
        # bench (Jordan Mason MIN wk7 2026: off IR, Questionable, listed 4th
        # on the chart while on reserve, so "no snaps in wk6, 4th" removed him)
        tm_ = candidates[pid]
        if tm_ in snap_week and live_rank(pid) >= 3 and not returning(pid):
            if snaps.get(tm_, {}).get(pid, 0) == 0:
                mult[pid] = 0.0
                reason[pid] = (f"rotation: no snaps in {tm_}'s last game (wk{snap_week[tm_]}) "
                               f"(effectively {_ord(live_rank(pid))})")
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
