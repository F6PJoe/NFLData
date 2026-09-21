#!/usr/bin/env python3
"""
Combine all 6 per-slot consensus files (OVR/QB/RB/WR/TE/FLX) for one scoring
format into a single CSV, laid out as side-by-side column blocks (one block
per slot, separated by a blank spacer column) — same shape as a multi-tab
spreadsheet, just in one CSV instead of separate tabs.

Each block keeps every column from the per-slot consensus file (Rank,
Player, Team, Position, Sources, and the 4 per-source rank columns with
their timestamped headers), so you can still see each ranker's individual
rank, not just the blended one. The first column of each block is renamed
to "<Slot> Rank" (e.g. "Ovr Rank", "QB Rank") instead of the generic "Rank",
matching how this looked as separate tabs.

Writes one file per scoring format: rankings_half.csv, rankings_ppr.csv,
rankings_std.csv.

Usage:
    python export_combined.py
"""

import csv

SLOTS = [("ovr", "Ovr"), ("qb", "QB"), ("rb", "RB"), ("wr", "WR"),
         ("te", "TE"), ("flx", "FLX")]
SCORING_SUFFIX = {"HALF": "", "PPR": "_ppr", "STD": "_std"}
OUT_FILES = {"HALF": "rankings_half.csv", "PPR": "rankings_ppr.csv", "STD": "rankings_std.csv"}


def load_slot(slot, suffix):
    fn = f"consensus_{slot}{suffix}.csv"
    try:
        with open(fn, newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            header = next(reader)
            rows = list(reader)
    except FileNotFoundError:
        return None, []
    return header, rows


def build_combined(suffix):
    blocks = []  # list of (header, rows) per slot, in SLOTS order
    for slot, label in SLOTS:
        header, rows = load_slot(slot, suffix)
        if header is None:
            print(f"Skipping slot {slot} — consensus_{slot}{suffix}.csv not found.")
            continue
        header = list(header)
        header[0] = f"{label} Rank"
        blocks.append((header, rows))

    if not blocks:
        return None

    max_rows = max(len(rows) for _header, rows in blocks)
    n_cols = [len(header) for header, _rows in blocks]

    out_rows = []
    header_row = []
    for i, (header, _rows) in enumerate(blocks):
        header_row.extend(header)
        if i != len(blocks) - 1:
            header_row.append("")  # spacer column
    out_rows.append(header_row)

    for r in range(max_rows):
        row = []
        for i, (_header, rows) in enumerate(blocks):
            if r < len(rows):
                row.extend(rows[r])
            else:
                row.extend([""] * n_cols[i])
            if i != len(blocks) - 1:
                row.append("")
        out_rows.append(row)

    return out_rows


def main():
    for scoring, suffix in SCORING_SUFFIX.items():
        out_rows = build_combined(suffix)
        if out_rows is None:
            print(f"No data found for {scoring} — run build_consensus.py first.")
            continue
        out_file = OUT_FILES[scoring]
        with open(out_file, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerows(out_rows)
        print(f"Wrote {out_file} ({len(out_rows) - 1} rows).")


if __name__ == "__main__":
    main()
