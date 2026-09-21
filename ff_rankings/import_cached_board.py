#!/usr/bin/env python3
"""
Turn a copied-and-pasted rankings table into a cached source.

For boards with no fetchable API -- Jahnke on PFF+, Thorman later. Copy the
table out of the page, feed it in, and it becomes a first-class source that
`run_weekly.py` blends and freshness-gates like any other.

    python import_cached_board.py --prefix jahnke --source "Nathan Jahnke" \
        --origin PFF --slot FLX --scoring PPR board.txt

    # or pipe it
    type board.txt | python import_cached_board.py --prefix jahnke ... -

Repeat per slot; each run merges into that source's existing file for the week
rather than replacing it, so FLX/QB/RB/WR/TE can be imported one at a time.

Parsing is deliberately forgiving, because a table copied out of a browser
arrives in whatever shape that site happens to use. It accepts tab-separated,
comma-separated, or run-together whitespace text, with or without a leading
rank column, and pulls team/position out of the row wherever they sit. It then
prints what it understood -- always read that back before trusting it, since a
misparsed board is worse than no board.
"""

import argparse
import csv
import datetime
import io
import os
import re
import sys

import cached_source
import weekly_freshness as wf

POSITIONS = {"QB", "RB", "WR", "TE", "K", "DST", "D/ST", "DEF", "FB"}
TEAMS = {
    "ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE", "DAL", "DEN",
    "DET", "GB", "HOU", "IND", "JAC", "JAX", "KC", "LAC", "LAR", "LV",
    "MIA", "MIN", "NE", "NO", "NYG", "NYJ", "PHI", "PIT", "SEA", "SF",
    "TB", "TEN", "WAS", "WSH", "ARZ", "BLT", "HST", "INA", "CLV", "LA",
}
NOISE = {"BYE", "Q", "D", "O", "IR", "DNP", "LP", "FP", "SUS", "PUP"}


HEADER_WORDS = {"rank", "rk", "player", "name", "team", "tm", "pos", "position",
                "opp", "opponent", "proj", "projection", "tier", "bye", "notes",
                "status", "#"}


def split_row(line):
    """Tab/comma first, then runs of 2+ spaces, and only then single spaces.

    The ordering matters: a table copied as aligned text separates columns with
    runs of spaces, but names contain single ones. Splitting on any whitespace
    turns "Ja'Marr Chase" into two cells.
    """
    if "\t" in line:
        return [c.strip() for c in line.split("\t")]
    if line.count(",") >= 2:
        return [c.strip() for c in line.split(",")]
    if re.search(r"\s{2,}", line.strip()):
        return [c.strip() for c in re.split(r"\s{2,}", line.strip()) if c.strip()]
    return [c for c in line.strip().split() if c]


def is_header(cells):
    """A header row copied along with the table, not a player."""
    words = [c.strip().lower().strip("#.") for c in cells if c.strip()]
    if not words:
        return False
    return sum(1 for w in words if w in HEADER_WORDS) >= max(2, len(words) // 2)


def parse_row(line, default_position):
    """One table row -> {Player, Team, Position}, or None if it isn't one."""
    cells = split_row(line)
    if not cells or is_header(cells):
        return None

    # Drop a leading rank number if present.
    if re.fullmatch(r"\d{1,3}\.?", cells[0]):
        cells = cells[1:]
    if not cells:
        return None

    team = position = None
    kept = []
    for cell in cells:
        token = cell.strip().upper().strip(".")
        if token in POSITIONS and position is None:
            position = "DST" if token in ("D/ST", "DEF") else token
        elif token in TEAMS and team is None:
            team = cell.strip().upper()
        elif token in NOISE or re.fullmatch(r"[\d.%+-]+", token):
            continue                      # bye weeks, projections, statuses
        else:
            kept.append(cell.strip())

    # "Ja'Marr Chase CIN WR" collapses to one cell when copied from some tables.
    if not kept:
        return None
    name = kept[0]
    m = re.match(r"^(.*?)[,\s]+([A-Z]{2,3})\s*[-/]?\s*([A-Z]{1,3})$", name)
    if m and m.group(2) in TEAMS and m.group(3) in POSITIONS:
        name, team, position = m.group(1).strip(), m.group(2), m.group(3)

    name = re.sub(r"\s+", " ", name).strip(" -,")
    if not name or len(name) < 2 or name.upper() in POSITIONS | TEAMS:
        return None
    return {"Player": name, "Team": team or "FA",
            "Position": position or default_position}


# Column names seen in real exports, lowercased. PFF's weekly export uses
# "Full Name" / "Team Abbreviation" / "Position", after a title line and a
# blank line -- so the header is found by scanning, not assumed to be line 1.
NAME_COLS = ("full name", "player", "player name", "name")
TEAM_COLS = ("team abbreviation", "team", "tm")
POS_COLS = ("position", "pos")


def parse_csv(text, default_position):
    """Parse a real CSV export by column name, not by guessing at layout.

    Preferred over parse_board whenever the file has a proper header row: a
    known schema should never be fuzzy-matched.
    """
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    rows_in = [r for r in reader if any(c.strip() for c in r)]

    header_at = name_i = team_i = pos_i = None
    for i, row in enumerate(rows_in):
        lower = [c.strip().lower() for c in row]
        if any(c in NAME_COLS for c in lower):
            header_at = i
            name_i = next(j for j, c in enumerate(lower) if c in NAME_COLS)
            team_i = next((j for j, c in enumerate(lower) if c in TEAM_COLS), None)
            pos_i = next((j for j, c in enumerate(lower) if c in POS_COLS), None)
            break
    if header_at is None:
        return None, ["no header row with a recognisable name column"]

    out, skipped = [], []
    for row in rows_in[header_at + 1:]:
        if name_i >= len(row):
            skipped.append(",".join(row))
            continue
        name = row[name_i].strip().strip('"')
        if not name:
            skipped.append(",".join(row))
            continue
        out.append({
            "Player": name,
            "Team": (row[team_i].strip().strip('"').upper()
                     if team_i is not None and team_i < len(row) else "FA") or "FA",
            "Position": (row[pos_i].strip().strip('"').upper()
                         if pos_i is not None and pos_i < len(row)
                         else default_position) or default_position,
        })
    return out, skipped


def parse_board(text, default_position):
    rows, skipped = [], []
    for line in text.splitlines():
        if not line.strip():
            continue
        row = parse_row(line, default_position)
        (rows if row else skipped).append(row if row else line.strip())
    return rows, skipped


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("paste", help="file containing the pasted table, or - for stdin")
    ap.add_argument("--prefix", required=True,
                    help="source key, matching SOURCE_PRIORITY (e.g. jahnke)")
    ap.add_argument("--source", required=True, help='display name, e.g. "Nathan Jahnke"')
    ap.add_argument("--origin", default="manual", help="where it came from, e.g. PFF")
    ap.add_argument("--slot", required=True,
                    choices=["FLX", "QB", "RB", "WR", "TE", "K", "DST"])
    ap.add_argument("--scoring", default="HALF", choices=["HALF", "PPR", "STD"])
    ap.add_argument("--published-at",
                    help="ISO time the analyst published it (preferred for "
                         "freshness over the time you pasted it)")
    ap.add_argument("--week-dir", help="defaults to the newest weekly/<year>-wk<NN>")
    ap.add_argument("--out-root", default="weekly")
    args = ap.parse_args()

    text = sys.stdin.read() if args.paste == "-" else open(
        args.paste, encoding="utf-8").read()

    week_dir = args.week_dir
    if not week_dir:
        candidates = sorted(
            d for d in (os.path.join(args.out_root, n)
                        for n in os.listdir(args.out_root))
            if os.path.isdir(d)) if os.path.isdir(args.out_root) else []
        if not candidates:
            sys.exit(f"No week directory under {args.out_root}/ -- "
                     f"run run_weekly.py once first, or pass --week-dir.")
        week_dir = candidates[-1]

    rows, skipped = parse_csv(text, args.slot)
    if rows is None:
        rows, skipped = parse_board(text, args.slot)
    if not rows:
        sys.exit("Parsed no rows. Check the paste, or pass a cleaner table.")

    # Merge into whatever this source already has for the week. Format-invariant
    # slots go under "ANY" so they serve every format from one capture.
    existing = cached_source.load_all(week_dir).get(args.prefix, {})
    boards = {sc: dict(slots)
              for sc, slots in (existing.get("boards") or {}).items()}
    key = "ANY" if args.slot in wf.FORMAT_INVARIANT_SLOTS else args.scoring
    boards.setdefault(key, {})[args.slot] = rows

    # Timestamps are per-key too, and ONLY the key being imported changes --
    # merging one format's capture must never touch another format's stamp.
    # Verified broken before this: refreshing Jahnke's HALF boards alone was
    # making his untouched PPR/STD boards look freshly current.
    timestamps = {sc: dict(ts) for sc, ts in (existing.get("timestamps") or {}).items()}
    timestamps[key] = {
        "captured_at": datetime.datetime.now(wf.ET).isoformat(timespec="seconds"),
        "published_at": args.published_at or (timestamps.get(key) or {}).get("published_at"),
    }

    path = cached_source.write(
        week_dir, args.prefix, args.source, args.origin, boards, timestamps)

    print(f"Parsed {len(rows)} players into {args.slot}/{args.scoring}.")
    print(f"  1. {rows[0]['Player']} ({rows[0]['Team']} {rows[0]['Position']})")
    if len(rows) > 1:
        print(f"  2. {rows[1]['Player']} ({rows[1]['Team']} {rows[1]['Position']})")
    if len(rows) > 2:
        print(f"  {len(rows)}. {rows[-1]['Player']} "
              f"({rows[-1]['Team']} {rows[-1]['Position']})")
    unknown_team = sum(1 for r in rows if r["Team"] == "FA")
    if unknown_team:
        print(f"  NOTE: {unknown_team} rows had no recognisable team.")
    if skipped:
        print(f"  Skipped {len(skipped)} non-player line(s); first few:")
        for line in skipped[:3]:
            print(f"    {line[:70]}")
    print(f"\nWrote {path}")
    print(f"Slots now cached for {args.source}: {cached_source.slot_summary(cached_source.load_all(week_dir)[args.prefix])}")
    print("Read the sample above before trusting it -- a misparsed board is "
          "worse than no board.")


if __name__ == "__main__":
    main()
