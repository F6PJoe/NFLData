#!/usr/bin/env python3
"""
Load Nathan Jahnke's full weekly rankings export into his cached board.

The export is one CSV with every position -- "weekly_fantasy_rankings_<year>_
week_<N>.csv" (Chrome adds " (1)" etc. for repeat downloads):

    "Ovr. RankRk.","Pos RankPRk","Pos.Pos.","Name","Team","Opponent",...
    "1","1","RB","Jahmyr Gibbs","Lions","@Panthers",...
    "","1","DEF","Vikings DST","Vikings","Dolphins",...

It becomes his half-PPR board for every slot: QB/RB/WR/TE/K/DST in position-
rank order, and FLX as his RB/WR/TE in overall-rank order (the overall rank
interleaves QBs too, so they're dropped). Teams arrive as nicknames
("Lions") and are mapped to codes; DEF becomes DST under its full name.

run_weekly.py picks the file up automatically from Downloads or the
ff_rankings folder (newest matching file for the live week). The cached board
then competes with his FP board like any cached source -- freshest wins. The
export carries no "updated" time, so the board's time is the file's save
time, i.e. when it was downloaded.

    python import_full_board.py "<path to export>"     # manual import
"""

import argparse
import csv
import datetime
import glob
import os
import sys

import cached_source
import name_match
import weekly_freshness as wf

PREFIX, SOURCE, ORIGIN = "jahnke", "Nathan Jahnke", "PFF"
FILE_PATTERN = "weekly_fantasy_rankings_{year}_week_{week}*.csv"
SEARCH_DIRS = [os.path.join(os.path.expanduser("~"), "Downloads"),
               os.path.dirname(os.path.abspath(__file__))]

# "Lions" -> "DET", built from the canonical full names (last word is unique).
NICKNAMES = {full.split()[-1].lower(): code
             for code, full in name_match.DST_NAMES.items()}


def find_export(year, week, dirs=SEARCH_DIRS):
    """Newest export file for this year/week across `dirs`, or None."""
    pattern = FILE_PATTERN.format(year=year, week=int(week))
    hits = [p for d in dirs for p in glob.glob(os.path.join(d, pattern))]
    return max(hits, key=os.path.getmtime) if hits else None


def _team_code(team):
    team = (team or "").strip()
    code = NICKNAMES.get(team.lower())
    return code or name_match.clean_team(team)


def _col(header, *starts):
    """Index of the first header cell starting with any of `starts`."""
    for i, cell in enumerate(header):
        if any(cell.strip().lower().startswith(s) for s in starts):
            return i
    raise ValueError(f"export has no column starting with {starts}: {header}")


def parse_export(path):
    """{scoring_key: {slot: [{"Player","Team","Position"}]}} for cached_source."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f))
    header, body = rows[0], [r for r in rows[1:] if any(c.strip() for c in r)]
    i_ovr = _col(header, "ovr")
    i_pos_rank = _col(header, "pos rank")
    i_pos = _col(header, "pos.")
    i_name, i_team = _col(header, "name"), _col(header, "team")

    by_pos, overall = {}, []
    for r in body:
        pos = r[i_pos].strip().upper()
        pos = "DST" if pos in ("DEF", "D/ST") else pos
        team = _team_code(r[i_team])
        name = (name_match.dst_name(team) or r[i_name].strip()) if pos == "DST" \
            else r[i_name].strip()
        entry = {"Player": name, "Team": team, "Position": pos}
        by_pos.setdefault(pos, []).append((int(r[i_pos_rank]), entry))
        if r[i_ovr].strip() and pos in ("RB", "WR", "TE"):
            overall.append((int(r[i_ovr]), entry))

    def ordered(pairs):
        return [e for _rank, e in sorted(pairs, key=lambda t: t[0])]

    return {
        "HALF": {"FLX": ordered(overall),
                 **{s: ordered(by_pos.get(s, [])) for s in ("RB", "WR", "TE")}},
        "ANY": {s: ordered(by_pos.get(s, [])) for s in ("QB", "K", "DST")},
    }


def import_export(path, week_dir, when=None):
    """Merge the export into week_dir's cached jahnke.json. Returns
    (path written, {slot: player count}, board time).

    `when` (an aware datetime) overrides the file's save time -- for when Joe
    knows the real download time and the file was copied/moved since.
    """
    new_boards = parse_export(path)
    when = when or datetime.datetime.fromtimestamp(os.path.getmtime(path), wf.ET)
    stamp = when.isoformat(timespec="seconds")

    existing = cached_source.load_all(week_dir).get(PREFIX, {})
    boards = {sc: dict(slots) for sc, slots in (existing.get("boards") or {}).items()}
    timestamps = {sc: dict(ts) for sc, ts in (existing.get("timestamps") or {}).items()}
    for key, slots in new_boards.items():
        boards.setdefault(key, {}).update(slots)
        # published_at cleared: an older PFF capture's publish time must not
        # vouch for this file's content.
        timestamps[key] = {"captured_at": stamp, "published_at": None}

    written = cached_source.write(week_dir, PREFIX, SOURCE, ORIGIN, boards, timestamps)
    counts = {slot: len(rows) for slots in new_boards.values()
              for slot, rows in slots.items()}
    return written, counts, stamp


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", help="the weekly_fantasy_rankings_*.csv export")
    ap.add_argument("--week-dir", help="defaults to the newest weekly/<year>-wk<NN>")
    ap.add_argument("--out-root", default="weekly")
    args = ap.parse_args()

    week_dir = args.week_dir
    if not week_dir:
        dirs = sorted(d for d in glob.glob(os.path.join(args.out_root, "*-wk*"))
                      if os.path.isdir(d))
        if not dirs:
            sys.exit(f"No week directory under {args.out_root}/ -- pass --week-dir.")
        week_dir = dirs[-1]

    written, counts, stamp = import_export(args.path, week_dir)
    print(f"Imported {os.path.basename(args.path)} (saved {stamp}) -> {written}")
    print("  " + ", ".join(f"{s} {n}" for s, n in counts.items()))


if __name__ == "__main__":
    main()
