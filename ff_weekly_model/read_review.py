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
                                   in wk3, 2 targets, expected back at 100%
    START     QB starts         -> this quarterback is his team's starter;
                                   the others become backups. Nobody has to
                                   be marked OUT to make the switch.
    <number>  e.g. 40 or 40%    -> that percent of normal usage
    <n> ONLY  e.g. 85 only      -> HIS line x 85%, teammates untouched -- an
                                   eased-in player whose missing work does
                                   NOT go to the backups (Joe, 2026-10-22)

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
    if v in OUT_WORDS:
        return 0.0, "OUT", True
    if v in LIMITED_WORDS:
        return LIMITED_DEFAULT, f"LIMITED ({LIMITED_DEFAULT:.0%})", True
    ch = parse_chance(v)
    if ch is not None:
        return 1.0, f"{ch:.0%} CHANCE TO PLAY", True
    on = parse_only(v)
    if on is not None:
        return 1.0, f"{on:.0%} OF HIS LINE ONLY", True
    m = re.fullmatch(r"(\d{1,3})\s*%?", v)
    if m:
        pct = int(m.group(1))
        if 0 <= pct <= 200:          # above 100 = a BOOST, taken from teammates (2026-10-14)
            return pct / 100, f"{pct}% usage", True
    return 1.0, f"UNRECOGNISED {raw!r} -- treated as PLAY", False


def load_flags(year, week):
    """player_id -> "FULL" or "START" for the rows that say so."""
    path = os.path.join(DATA, f"review_{year}_wk{week:02d}.csv")
    out = {}
    if not os.path.exists(path):
        return out
    mult = load(year, week)[0]      # resolves blank ids by name the same way
    with open(path, newline="", encoding="utf-8-sig") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        v = (r.get("decision") or "").strip().lower().rstrip(".")
        flag = "FULL" if v in FULL_WORDS else "START" if v in START_WORDS else None
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
