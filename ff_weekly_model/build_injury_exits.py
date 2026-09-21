#!/usr/bin/env python3
"""Detect in-game injury exits straight from play-by-play descriptions.

Answers the question a news feed would otherwise be needed for: was this
player's quiet week a ROLE change, or did he get hurt in the first quarter and
never come back? Those look identical in a box score and mean opposite things
for next week.

nflverse play descriptions carry the events explicitly:

    "ARI-50-C.Simon was injured during the play."
    "** Injury Update: NO-12-C.Olave has returned to the game."

~954 injury events a season, ~630 returns -- so ~320 players get knocked out
and stay out. Players are named as TEAM-JERSEY-F.Lastname, joined back to
gsis_id through that week's own stat lines.

Writes data/injury_exits_<year>.csv with one row per player-game exit,
including how much game time was left when it happened.

Usage:
    python build_injury_exits.py --year 2025
"""

import argparse
import collections
import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
UTIL = os.path.join(os.path.dirname(HERE), "ff_utilization", "cached", "nflverse")

INJURED = re.compile(r'\b([A-Z]{2,3})-(\d{1,2})-([A-Z]\.[A-Za-z\'\-\.]+?)\s+was injured during the play')
RETURNED = re.compile(r'Injury Update:\s*([A-Z]{2,3})-(\d{1,2})-([A-Z]\.[A-Za-z\'\-\.]+?)\s+has returned')


def abbrev(display_name):
    """'Chris Olave' -> 'C.Olave' -- the form play descriptions use."""
    parts = display_name.split()
    if len(parts) < 2:
        return display_name
    return f"{parts[0][0]}.{' '.join(parts[1:])}".replace(" ", "")


def name_index(year):
    """(team, week, abbreviated name) -> gsis_id, from that week's stat lines."""
    idx = {}
    path = os.path.join(DATA, f"stats_player_week_{year}.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r.get("season_type") != "REG":
                continue
            key = (r["team"], int(r["week"]), abbrev(r["player_display_name"]))
            idx[key] = r["player_id"]
    return idx


def scan(year):
    """Injury and return events per game, from the play descriptions."""
    hurt = collections.defaultdict(dict)   # (game,team,jersey,name) -> secs left
    back = set()
    path = os.path.join(UTIL, f"pbp_{year}.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            d = r.get("desc") or ""
            if "njur" not in d:
                continue
            gid, wk = r["game_id"], int(r["week"])
            try:
                secs = float(r.get("game_seconds_remaining") or 0)
            except ValueError:
                secs = 0.0
            for tm, num, nm in INJURED.findall(d):
                k = (gid, wk, tm, num, nm)
                hurt.setdefault(k, secs)      # keep the FIRST occurrence
            for tm, num, nm in RETURNED.findall(d):
                back.add((gid, wk, tm, num, nm))
    return hurt, back


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    args = ap.parse_args()

    hurt, back = scan(args.year)
    idx = name_index(args.year)

    rows, unmatched = [], 0
    for (gid, wk, tm, num, nm), secs in sorted(hurt.items()):
        returned = (gid, wk, tm, num, nm) in back
        pid = idx.get((tm, wk, nm))
        if not pid:
            unmatched += 1
            continue
        rows.append({"player_id": pid, "team": tm, "week": wk, "game_id": gid,
                     "jersey": num, "name_in_pbp": nm,
                     "secs_remaining": int(secs), "returned": int(returned),
                     "exited": int(not returned)})

    dest = os.path.join(DATA, f"injury_exits_{args.year}.csv")
    with open(dest, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader(); w.writerows(rows)

    exits = [r for r in rows if r["exited"]]
    early = [r for r in exits if r["secs_remaining"] > 1800]   # left before halftime
    print(f"\n  {args.year}: {len(hurt):,} injury events, {len(back):,} returns")
    print(f"  matched to a player: {len(rows):,}  (unmatched {unmatched:,})")
    print(f"  did NOT return: {len(exits):,}   of which left before halftime: {len(early):,}")
    print(f"  -> {os.path.basename(dest)}\n")


if __name__ == "__main__":
    main()
