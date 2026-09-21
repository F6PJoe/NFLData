#!/usr/bin/env python3
"""Full skill-position roster per team, ordered by depth chart.

Source priority — each layer is used for what it's actually best at:

  1. Sleeper (fetch_sleeper.py)     WHO is on the team, and WHO IS HURT.
                                    Refreshed continuously; carries
                                    injury_status / body part / practice
                                    participation. This is the authority on
                                    team assignment and availability.
  2. nflverse depth charts          DEPTH ORDER. Sleeper's depth_chart_order
                                    is missing for ~25% of players; nflverse
                                    ranks everyone. Used to fill the gaps.
  3. nflverse rosters               The gsis_id bridge (Sleeper carries
                                    sportradar_id on ~98% of players but
                                    gsis_id on only ~16%, and gsis_id is what
                                    the historical stats are keyed on) plus
                                    draft capital.
  4. manual/overrides.csv           Anything all three still get wrong.

Writes rosters_<season>.csv — one row per skill player, sorted team, position,
depth. Players who can't play (IR / PUP / NFI / DNR / suspended / Out) are kept
but marked OUT and sorted last, so they hold no usage share.

Usage:
    python build_rosters.py
    python build_rosters.py --max-depth 8
"""

import argparse
import csv
import datetime
import os
import sys
from collections import Counter, defaultdict

import fetch_sleeper
import names
from teams import TEAMS, clean_team

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cached", "nflverse")
OVERRIDES = os.path.join(HERE, "manual", "overrides.csv")

SKILL = ("QB", "RB", "FB", "WR", "TE")
POS_ORDER = {pos: i for i, pos in enumerate(SKILL)}
OFFENSE_GROUP = "3WR 1TE"

# Designations that genuinely end a season — safe to auto-zero.
OUT_STATUSES = {"IR", "OUT", "SUS", "SUSP", "RET"}
OUT_ROSTER_STATUS = {"INACTIVE", "RETIRED"}

# Ambiguous in August and NOT safe to auto-zero. Preseason PUP/NFI is often
# precautionary — a player can come off it in camp and start Week 1 — so
# zeroing them out would silently delete a starter (George Kittle sat here in
# the 2026 preseason). These are surfaced for a human call instead, which is
# what manual/overrides.csv is for.
REVIEW_STATUSES = {"PUP", "NFI", "DNR", "COV", "DOUBTFUL"}

SEASON_START = (9, 1)


# ── source loaders ──────────────────────────────────────────────────────────

def load_sleeper():
    """Skill players with a team, keyed by normalized name + team."""
    blob, path = fetch_sleeper.load()
    players = {}
    for entry in blob.values():
        team = clean_team(entry.get("team", ""))
        pos = (entry.get("position") or "").upper()
        if team == "FA" or pos not in SKILL:
            continue
        # Sleeper keeps historical records with a stale last-team attached —
        # long-retired players, and a literal "Duplicate Player" placeholder.
        # `active` is the flag that separates those from the real roster.
        if not entry.get("active"):
            continue
        full = entry.get("full_name") or " ".join(
            filter(None, [entry.get("first_name"), entry.get("last_name")]))
        players[names.key(full, team)] = {"name": full, "team": team,
                                          "pos": pos, "raw": entry}
    return players, os.path.basename(path)


def load_nflverse_depth(season):
    """Depth order per team+position, keyed by normalized name + team."""
    path = os.path.join(CACHE, f"depth_charts_{season}.csv")
    if not os.path.exists(path):
        return {}, None
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    latest = max(r["dt"] for r in rows)
    depth = {}
    for row in rows:
        if row["dt"] != latest or row["pos_grp"] != OFFENSE_GROUP:
            continue
        if row["pos_abb"] not in SKILL or not row["player_name"].strip():
            continue
        team = clean_team(row["team"])
        rank = int(row["pos_rank"]) if row["pos_rank"].isdigit() else 99
        depth[names.key(row["player_name"], team)] = rank
    return depth, latest


def load_nflverse_roster(season):
    """Bio + id bridge, indexed by sportradar_id and by normalized name."""
    path = os.path.join(CACHE, f"roster_{season}.csv")
    if not os.path.exists(path):
        return {}, {}
    by_sr, by_name = {}, {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("sportradar_id"):
                by_sr[row["sportradar_id"]] = row
            by_name.setdefault(names.normalize(row.get("full_name", "")), row)
    return by_sr, by_name


def load_overrides():
    """Hand corrections applied last, on top of every source."""
    if not os.path.exists(OVERRIDES):
        return []
    rows = []
    with open(OVERRIDES, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if not row.get("player", "").strip():
                continue
            row["team"] = clean_team(row.get("team", ""))
            row["pos"] = (row.get("pos") or "").strip().upper()
            row["status"] = (row.get("status") or "").strip().upper()
            rows.append(row)
    return rows


# ── assembly ────────────────────────────────────────────────────────────────

def age_at(birth_date, season):
    if not birth_date:
        return ""
    try:
        born = datetime.date.fromisoformat(str(birth_date)[:10])
    except ValueError:
        return ""
    ref = datetime.date(season, *SEASON_START)
    return ref.year - born.year - ((ref.month, ref.day) < (born.month, born.day))


def availability(entry):
    """Map Sleeper status/injury_status onto our status flag.

    Returns (status_label, injury_detail) where status_label is one of
    OUT (auto-zeroed), the raw designation for anything needing review, or
    ACT. Only season-ending designations auto-zero — see REVIEW_STATUSES.
    """
    injury = (entry.get("injury_status") or "").strip()
    status = (entry.get("status") or "").strip()

    detail = " / ".join(filter(None, [
        injury or None,
        entry.get("injury_body_part"),
        entry.get("injury_notes"),
    ]))

    if injury.upper() in OUT_STATUSES or status.upper() in OUT_ROSTER_STATUS:
        return "OUT", detail
    return (injury.upper() or "ACT"), detail


def needs_review(player):
    return player["status"] in REVIEW_STATUSES


COLUMNS = [
    "team", "pos", "depth", "player", "age", "exp", "status", "injury",
    "jersey", "height", "weight", "college", "draft_year", "draft_pick",
    "sleeper_id", "sportradar_id", "gsis_id", "espn_id",
]


def build(season):
    sleeper, sleeper_file = load_sleeper()
    nfl_depth, snapshot = load_nflverse_depth(season)
    by_sr, by_name = load_nflverse_roster(season)

    players, no_depth = [], 0
    for key, rec in sleeper.items():
        entry = rec["raw"]
        status, injury = availability(entry)

        # Depth: Sleeper first, nflverse to fill its gaps.
        order = entry.get("depth_chart_order")
        if order is None:
            order = nfl_depth.get(key)
            if order is None:
                no_depth += 1
        depth = int(order) if order else 99

        # Bridge to gsis_id (what historical stats are keyed on) via
        # sportradar_id, falling back to name.
        bio = by_sr.get(entry.get("sportradar_id") or "") or \
            by_name.get(names.normalize(rec["name"])) or {}

        players.append({
            "team": rec["team"],
            "pos": rec["pos"],
            "depth": depth,
            "player": rec["name"],
            "age": entry.get("age") or age_at(entry.get("birth_date"), season),
            "exp": entry.get("years_exp"),
            "status": status,
            "injury": injury,
            "jersey": entry.get("number") or "",
            "height": entry.get("height") or "",
            "weight": entry.get("weight") or "",
            "college": entry.get("college") or "",
            "draft_year": bio.get("entry_year", ""),
            "draft_pick": bio.get("draft_number", ""),
            "sleeper_id": entry.get("player_id") or "",
            "sportradar_id": entry.get("sportradar_id") or "",
            "gsis_id": entry.get("gsis_id") or bio.get("gsis_id", ""),
            "espn_id": entry.get("espn_id") or "",
        })

    log = apply_overrides(players, load_overrides(), season)
    renumber(players)
    players.sort(key=lambda p: (p["team"], POS_ORDER.get(p["pos"], 9), p["depth"]))
    return players, sleeper_file, snapshot, no_depth, log


def apply_overrides(players, overrides, season):
    log = []
    index = {names.key(p["player"], p["team"]): p for p in players}
    anywhere = defaultdict(list)
    for p in players:
        anywhere[names.normalize(p["player"])].append(p)

    for ov in overrides:
        norm = names.normalize(ov["player"])
        target = index.get(names.key(ov["player"], ov["team"]))
        if target is None and anywhere[norm]:
            target = anywhere[norm][0]

        if target is None:
            target = {c: "" for c in COLUMNS}
            target.update({"team": ov["team"], "pos": ov["pos"],
                           "depth": 99, "player": ov["player"].strip(),
                           "status": ov["status"] or "ACT"})
            players.append(target)
            log.append(f"ADDED   {target['team']:<4} {target['pos']:<3} "
                       f"{target['player']}")
        else:
            changes = []
            if ov["team"] != "FA" and ov["team"] != target["team"]:
                changes.append(f"team {target['team']}->{ov['team']}")
                target["team"] = ov["team"]
            if ov["pos"] and ov["pos"] != target["pos"]:
                changes.append(f"pos {target['pos']}->{ov['pos']}")
                target["pos"] = ov["pos"]
            if changes:
                log.append(f"MOVED   {target['team']:<4} {target['pos']:<3} "
                           f"{target['player']}  ({', '.join(changes)})")

        if ov.get("depth", "").strip().isdigit():
            target["depth"] = int(ov["depth"])
            target["_forced"] = True   # beat the incumbent on a depth tie
        if ov["status"]:
            was = target.get("status")
            target["status"] = ov["status"]
            if ov["status"] != was:
                log.append(f"STATUS  {target['team']:<4} {target['pos']:<3} "
                           f"{target['player']}  ({was} -> {ov['status']})")
    return log


# A fullback is listed as FB1 on his own depth chart, which made him collide
# with the RB1 when the two groups were merged downstream - Carolina showed
# Mason Stokke slotted above Jonathon Brooks. Fullbacks are never the RB2, so
# they get pushed to the bottom of the running back room.
FB_DEPTH_OFFSET = 10


def renumber(players):
    """Re-rank depth within team+position; OUT players sort last.

    FB is merged into the RB room here rather than downstream, so the whole
    backfield is numbered once and consistently everywhere it's read.
    """
    groups = defaultdict(list)
    for p in players:
        groups[(p["team"], "RB" if p["pos"] == "FB" else p["pos"])].append(p)
    for group in groups.values():
        active = [p for p in group if p.get("status") != "OUT"]
        active.sort(key=lambda p: (p["depth"] + (FB_DEPTH_OFFSET
                                                 if p["pos"] == "FB" else 0),
                                   not p.get("_forced", False)))
        for rank, p in enumerate(active, start=1):
            p["depth"] = rank
        for p in group:
            if p.get("status") == "OUT":
                p["depth"] = 99
            p.pop("_forced", None)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2026)
    ap.add_argument("--max-depth", type=int, default=0,
                    help="cap depth per position (0 = keep everyone)")
    args = ap.parse_args()

    players, sleeper_file, snapshot, no_depth, log = build(args.season)

    if args.max_depth:
        players = [p for p in players
                   if p["depth"] <= args.max_depth or p["status"] == "OUT"]

    out = os.path.join(HERE, f"rosters_{args.season}.csv")
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(players)

    print(f"Sleeper roster/injury : {sleeper_file}")
    print(f"nflverse depth chart  : {snapshot or 'not cached'}")
    print(f"Wrote {os.path.basename(out)} - {len(players)} skill players")
    if no_depth:
        print(f"  {no_depth} had no depth order in either source (placed last)")

    if log:
        print(f"\nManual overrides ({os.path.relpath(OVERRIDES, HERE)}):")
        for line in log:
            print(f"  {line}")

    sidelined = [p for p in players if p["status"] == "OUT"]
    injured = [p for p in sidelined if p["injury"]]
    inactive = [p for p in sidelined if not p["injury"]]
    if injured:
        print(f"\nOut with an injury - no usage share ({len(injured)}):")
        for p in sorted(injured, key=lambda p: (p["team"], p["pos"])):
            print(f"  {p['team']:<4} {p['pos']:<3} {p['player']:<26}{p['injury']}")
    if inactive:
        # Roster-status only (Sleeper "Inactive"): out of the league, camp
        # cuts, unsigned. No injury attached, nothing to check.
        print(f"\n  plus {len(inactive)} inactive/unsigned with no injury listed")

    review = [p for p in players if needs_review(p)]
    if review:
        print(f"\n{'=' * 70}")
        print(f"NEEDS YOUR CALL ({len(review)}) - still projected at full share")
        print(f"{'=' * 70}")
        print("PUP/NFI/DNR in August is ambiguous: a player can come off it in")
        print("camp and start Week 1, or miss the year. Not auto-zeroed - if")
        print("you know they're done, add a row to manual/overrides.csv:")
        print("    <player>,<team>,<pos>,,OUT,<why>\n")
        for p in sorted(review, key=lambda p: (p["depth"], p["team"])):
            mark = "  <-- STARTER" if p["depth"] == 1 else ""
            print(f"  {p['team']:<4} {p['pos']:<3} depth {p['depth']:<3} "
                  f"{p['player']:<24} {p['injury']}{mark}")

    banged = [p for p in players
              if p["status"] == "QUESTIONABLE" and p["depth"] <= 3]
    if banged:
        print(f"\nQuestionable, depth 1-3 (week-to-week, not season-long):")
        for p in sorted(banged, key=lambda p: (p["team"], p["pos"])):
            print(f"  {p['team']:<4} {p['pos']:<3} depth {p['depth']} "
                  f"{p['player']:<24} {p['injury']}")

    by_team = defaultdict(Counter)
    for p in players:
        by_team[p["team"]][p["pos"]] += 1
    print(f"\nSkill players per team:\n")
    print(f"  {'TM':<5} {'QB':>3} {'RB':>3} {'FB':>3} {'WR':>3} {'TE':>3}  {'TOT':>4}")
    print(f"  {'-' * 5} {'-' * 3} {'-' * 3} {'-' * 3} {'-' * 3} {'-' * 3}  {'-' * 4}")
    for team in TEAMS:
        counts = by_team[team]
        print(f"  {team:<5} " + " ".join(f"{counts[p]:>3}" for p in SKILL)
              + f"  {sum(counts.values()):>4}")


if __name__ == "__main__":
    sys.exit(main())
