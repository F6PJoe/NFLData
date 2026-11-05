#!/usr/bin/env python3
"""Read the weekly judgement sheet -- deliberately forgiving about spelling.

The decision column accepts, case-insensitively:

    OUT       won't play        -> share 0, removed from the pool entirely,
                                   so his touches redistribute to teammates
    LIMITED   plays reduced     -> 60% of normal usage, the other 40% goes
                                   back to the rest of the position group
    PLAY      plays normally    -> no change (same as leaving it blank)
    FULL      plays, full go    -> PLAY, and any game he LEFT injured (snaps
                                   under half his usual) is thrown out of his
                                   history -- Jefferson wk4 2026: hurt early
                                   in wk3, 2 targets, expected back at 100%.
                                   On a back returning from 2+ missed games
                                   it also forces the workhorse return: his
                                   backups' games without him barely count,
                                   even if the model thought they took the job
    SPLIT     back, job shared  -> PLAY, but NO workhorse return for this
                                   returning back: his backups keep the share
                                   they earned while he was out (2026-10-30,
                                   Joe: "override the 'backup took the job'")
    EVEN      even split        -> the players marked EVEN at one position
                                   on a team share their combined work
                                   equally (backs: carries + targets), each
                                   with his own efficiency; teammates
                                   untouched. Also SPLIT for a returning back
                                   (2026-11-03, Joe on Hall / Allen)
    START     QB starts         -> this quarterback is his team's starter;
                                   the others become backups. Nobody has to
                                   be marked OUT to make the switch.
    RUSH <n>  e.g. rush 6.5     -> QB only: his rushing attempts (add "ypc 6"
                                   for his yards per carry, or "ypc 6" alone
                                   -- Joe on Daniels 2026-11-04), at his own
                                   yards per carry and TD rate; the extra
                                   carries come out of his team's backs
                                   (passing untouched). 2026-11-03, Daniels.
                                   Since 2026-11-04 these have their own
                                   columns, `rush` and `ypc` (the workbook's
                                   QB carries / QB yds/carry), which win over the
                                   text here -- so the decision cell stays
                                   free for START / chance 50 / 85 only
    <number>  e.g. 40 or 40%    -> that percent of normal usage
    <n> ONLY  e.g. 85 only      -> HIS line x 85%, teammates untouched -- an
                                   eased-in player whose missing work does
                                   NOT go to the backups (Joe, 2026-10-22)

The role column (2026-10-31) takes RB1 / RB2 / WR3 / TE1 / QB1 ...: he gets
the work the model projects for that slot on his team, and the rest of the
position group shifts down a slot (project.role_multipliers). QB1 = START.
A player moved UP gets his own normal workload instead when it is more --
his share in healthy games with the players placed ahead of him playing
(project.ROLE_NORMAL; McConkey WR1 wk8: 6.4 targets, not the 4.4 the
Chargers' top receiver had while he was hurt). A player moved DOWN gets his
workload from games with the players now above him playing and ahead of him,
but never more than the model has him at now (ROLE_NORMAL_DOWN; Johnston WR2
under McConkey wk8 stays 3.9 -- his 2025 games beside McConkey said 7.0).
Both columns are usually filled from the team tabs of the review workbook
(review_book.py), which copies its edits into this sheet.

Blank always means PLAY, so an unfilled sheet is valid and changes nothing.
Anything it cannot parse is REPORTED rather than silently ignored -- a typo
that quietly does nothing is the worst outcome here.

Usage:
    python read_review.py --year 2026 --week 2          # show how it reads
"""

import argparse
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

OUT_WORDS = {"out", "o", "sit", "no", "n", "inactive", "scratch"}
PLAY_WORDS = {"play", "p", "yes", "y", "active", "go", "in", ""}
FULL_WORDS = {"full", "full go", "fullgo", "100", "100%"}
START_WORDS = {"start", "starter", "starting", "qb1", "s"}
SPLIT_WORDS = {"split", "shared", "share", "committee", "rbbc"}
EVEN_WORDS = {"even", "50/50", "50-50", "even split"}
LIMITED_WORDS = {"limited", "ltd", "lim", "l", "reduced", "snap count", "pitch count"}
LIMITED_DEFAULT = 0.60
# CHANCE TO PLAY (2026-10-16): "chance 25", "25% chance", "c25" = a 25% chance
# he plays. His own projection stays what he scores IF he plays; every
# teammate is blended 25/75 between "he plays" and "he sits".
CHANCE_RE = re.compile(r"(?:chance|c)\s*(\d{1,3})\s*%?|(\d{1,3})\s*%?\s*chance")
# HIS LINE ONLY (2026-10-22, Joe on Jacobs / Charbonnet eased back in: "I don't
# want to give the extra carries to the backups"): "85 only" scales his own
# projection after the model runs; nobody else changes.
ONLY_RE = re.compile(r"(\d{1,3})\s*%?\s*only|only\s*(\d{1,3})\s*%?")


def parse_only(raw):
    m = ONLY_RE.fullmatch((raw or "").strip().lower().rstrip("."))
    if not m:
        return None
    p = int(m.group(1) or m.group(2))
    return p / 100 if 0 < p <= 100 else None


RUSH_RE = re.compile(r"(?:rush(?:es)?\s*(\d{1,2}(?:\.\d)?))?\s*(?:ypc\s*(\d{1,2}(?:\.\d{1,2})?))?")


def _rush_call(raw):
    m = RUSH_RE.fullmatch((raw or "").strip().lower().rstrip("."))
    return m if m and (m.group(1) or m.group(2)) else None


def parse_rush(raw):
    """"rush 6.5" / "rush 6.5 ypc 6" -> 6.5 (a QB's rushing attempts), else None."""
    m = _rush_call(raw)
    return float(m.group(1)) if m and m.group(1) else None


def parse_ypc(raw):
    """"ypc 6.5" / "rush 6 ypc 6.5" -> 6.5 (a QB's yards per carry), else None."""
    m = _rush_call(raw)
    return float(m.group(2)) if m and m.group(2) else None


def parse_chance(raw):
    m = CHANCE_RE.fullmatch((raw or "").strip().lower().rstrip("."))
    if not m:
        return None
    p = int(m.group(1) or m.group(2))
    return p / 100 if 0 <= p <= 100 else None


def parse_decision(raw):
    """-> (multiplier, label, ok). multiplier 0.0 means remove from the pool."""
    v = (raw or "").strip().lower().rstrip(".")
    if v in PLAY_WORDS:
        return 1.0, "PLAY", True
    if v in FULL_WORDS:
        return 1.0, "FULL (injury-shortened games ignored)", True
    if v in START_WORDS:
        return 1.0, "START (made his team's starter)", True
    if v in SPLIT_WORDS:
        return 1.0, "SPLIT (backups keep their share -- no workhorse return)", True
    if v in EVEN_WORDS:
        return 1.0, "EVEN (equal share with the others marked EVEN)", True
    if v in OUT_WORDS:
        return 0.0, "OUT", True
    if v in LIMITED_WORDS:
        return LIMITED_DEFAULT, f"LIMITED ({LIMITED_DEFAULT:.0%})", True
    ch = parse_chance(v)
    if ch is not None:
        return 1.0, f"{ch:.0%} CHANCE TO PLAY", True
    ru, yc = parse_rush(v), parse_ypc(v)
    if ru is not None or yc is not None:
        return 1.0, " ".join(x for x in (f"{ru:g} QB RUSHES" if ru is not None else "",
                                         f"{yc:g} YDS/CARRY" if yc is not None else "") if x)             + " (passing untouched)", True
    on = parse_only(v)
    if on is not None:
        return 1.0, f"{on:.0%} OF HIS LINE ONLY", True
    m = re.fullmatch(r"(\d{1,3})\s*%?", v)
    if m:
        pct = int(m.group(1))
        if 0 <= pct <= 200:          # above 100 = a BOOST, taken from teammates (2026-10-14)
            return pct / 100, f"{pct}% usage", True
    return 1.0, f"UNRECOGNISED {raw!r} -- treated as PLAY", False


ROLE_RE = re.compile(r"(qb|rb|wr|te)\s*-?\s*(\d)")


def parse_role(raw):
    """'RB2' -> ('RB', 2); blank or unreadable -> None."""
    m = ROLE_RE.fullmatch((raw or "").strip().lower())
    return (m.group(1).upper(), int(m.group(2))) if m and int(m.group(2)) >= 1 else None


def load_roles(year, week):
    """player_id -> (group, slot) for rows with a role, e.g. ('RB', 2)."""
    path = os.path.join(DATA, f"review_{year}_wk{week:02d}.csv")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        ro = parse_role(r.get("role"))
        if ro is None:
            if (r.get("role") or "").strip():
                print(f"  !! review sheet: could not read role {r.get('role')!r} for {r.get('player')}")
            continue
        pid = (r.get("player_id") or "").strip()
        if not pid:
            pid = _ids_by_name(year).get(((r.get("player") or "").strip().lower(), (r.get("team") or "").strip()))
        if pid:
            out[pid] = ro
    return out


def load_flags(year, week):
    """player_id -> "FULL", "START", "SPLIT" or "EVEN" for the rows that say so."""
    path = os.path.join(DATA, f"review_{year}_wk{week:02d}.csv")
    out = {}
    if not os.path.exists(path):
        return out
    mult = load(year, week)[0]      # resolves blank ids by name the same way
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        v = (r.get("decision") or "").strip().lower().rstrip(".")
        flag = ("FULL" if v in FULL_WORDS else "START" if v in START_WORDS
                else "SPLIT" if v in SPLIT_WORDS else "EVEN" if v in EVEN_WORDS else None)
        if not flag:
            continue
        pid = (r.get("player_id") or "").strip()
        if not pid:
            nm = (r.get("player") or "").strip()
            pid = _ids_by_name(year).get((nm.lower(), (r.get("team") or "").strip()))
        if pid:
            out[pid] = flag
    return out


def load_only(year, week):
    """player_id -> fraction of his own line, for rows like "85 only"."""
    path = os.path.join(DATA, f"review_{year}_wk{week:02d}.csv")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        f = parse_only(r.get("decision"))
        if f is None:
            continue
        pid = (r.get("player_id") or "").strip()
        if not pid:
            pid = _ids_by_name(year).get(((r.get("player") or "").strip().lower(), (r.get("team") or "").strip()))
        if pid:
            out[pid] = f
    return out


def rush_number(raw):
    """A number typed in the sheet's rush / ypc column ("7", "6.5", "rush 7")
    -> float, or None if blank / not a positive number."""
    m = re.search(r"\d+(?:\.\d+)?", str(raw or ""))
    return float(m.group(0)) if m and float(m.group(0)) > 0 else None


def load_rush(year, week, parse=None):
    """player_id -> rushing attempts (parse_ypc: his yards per carry), from
    the sheet's own `rush` / `ypc` columns -- the review workbook's QB carries
    / QB yds/carry cells (2026-11-04, Joe: separate fields, so a QB can carry START
    or "chance 50" AND a rushing call). A blank column falls back to the old
    one-cell call in decision: "rush 6.5" / "ypc 6.5" / "rush 6 ypc 6.5"."""
    parse = parse or parse_rush
    col = "ypc" if parse is parse_ypc else "rush"
    path = os.path.join(DATA, f"review_{year}_wk{week:02d}.csv")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        n = rush_number(r.get(col))
        if n is None:
            n = parse(r.get("decision"))
        if n is None:
            continue
        pid = (r.get("player_id") or "").strip()
        if not pid:
            pid = _ids_by_name(year).get(((r.get("player") or "").strip().lower(), (r.get("team") or "").strip()))
        if pid:
            out[pid] = n
    return out


def load_chances(year, week):
    """player_id -> chance he plays, for rows like "chance 25"."""
    path = os.path.join(DATA, f"review_{year}_wk{week:02d}.csv")
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        ch = parse_chance(r.get("decision"))
        if ch is None:
            continue
        pid = (r.get("player_id") or "").strip()
        if not pid:
            pid = _ids_by_name(year).get(((r.get("player") or "").strip().lower(), (r.get("team") or "").strip()))
        if pid:
            out[pid] = ch
    return out


def _ids_by_name(year):
    out = {}
    for y in (year, year - 1):
        p = os.path.join(DATA, f"stats_player_week_{y}.csv")
        if os.path.exists(p):
            with open(p, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    out.setdefault((r["player_display_name"].lower(), r["team"]), r["player_id"])
    return out


def load(year, week):
    """player_id -> multiplier. Missing file or blank rows are fine.

    To add someone yourself, type his name and team into a new row and leave
    player_id blank -- the id is looked up for you. Nobody should have to go
    hunting for a gsis id to sit a running back.
    """
    path = os.path.join(DATA, f"review_{year}_wk{week:02d}.csv")
    out, problems = {}, []
    if not os.path.exists(path):
        return out, problems
    sys.path.insert(0, HERE)
    import availability
    pair, solo = availability._gsis_by_name(year)
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            raw = (r.get("decision") or "").strip()
            mult, label, ok = parse_decision(raw)
            if not ok:
                problems.append((r.get("player", "?"), r.get("decision")))
            # A BLANK cell is a non-answer and must stay one, so it never
            # overrides an Out designation upstream. An explicit PLAY is an
            # answer -- it has to travel, or you could never countermand a
            # third-party injury tag you believe is wrong.
            pid = (r.get("player_id") or "").strip()
            if not pid:                       # you typed a name, we find the id
                nm = availability.norm_name(r.get("player"))
                pid = pair.get((nm, (r.get("team") or "").strip())) or solo.get(nm)
                if not pid:
                    problems.append((r.get("player", "?"),
                                     "no player_id and the name did not match"))
                    continue
            if mult != 1.0 or raw:
                out[pid] = mult
    return out, problems


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    args = ap.parse_args()
    path = os.path.join(DATA, f"review_{args.year}_wk{args.week:02d}.csv")
    if not os.path.exists(path):
        print(f"  no sheet at {path} -- every Questionable player treated as PLAY")
        return
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    print(f"\n  reading {os.path.basename(path)}\n")
    print(f"  {'player':<24}{'you wrote':<14}{'read as':<24}{'effect'}")
    bad = 0
    for r in rows:
        mult, label, ok = parse_decision(r.get("decision"))
        bad += not ok
        ch = parse_chance(r.get("decision"))
        on = parse_only(r.get("decision"))
        eff = (f"{ch:.0%} chance he plays: teammates blended, his own number = if he plays"
               if ch is not None else
               f"his own line x{on:.2f}, teammates unchanged" if on is not None else
               "no change" if mult == 1.0 else
               "removed, share goes to teammates" if mult == 0.0 else
               f"QB: {mult:.0%} chance he STARTS, blended with his backup"
               if (r.get("pos") or "").strip().upper() == "QB" and mult < 1 else
               f"usage x{mult:.2f}, " + ("extra taken from teammates" if mult > 1 else "rest to teammates"))
        print(f"  {r['player']:<24}{(r.get('decision') or '(blank)'):<14}{label:<24}{eff}")
    print(f"\n  {len(rows)} rows, {bad} unrecognised\n")


if __name__ == "__main__":
    main()
