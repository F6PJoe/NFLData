#!/usr/bin/env python3
"""
Collapse the per-slot consensus files into a single combined file per
scoring format — one half-PPR file, one PPR file, one STD file — for
uploading elsewhere (e.g. a FantasyPros contributor submission).

Uses consensus_ovr*.csv as the source, since OVR already has every player
(QB/RB/WR/TE/K/DST) in one ranked list — that's the "single file with
everyone" shape an upload typically wants. Strips down to just
Rank/Player/Team/Position (drops Sources and the 4 per-source columns,
which are useful for QA here but not meaningful to an external upload).

Usage:
    python export_for_upload.py
"""

import csv

SLOT_FILES = {
    "HALF": "consensus_ovr.csv",
    "PPR": "consensus_ovr_ppr.csv",
    "STD": "consensus_ovr_std.csv",
}

OUT_FILES = {
    "HALF": "upload_half.csv",
    "PPR": "upload_ppr.csv",
    "STD": "upload_std.csv",
}

FIELDNAMES = ["Rank", "Player", "Team", "Position"]


def main():
    for scoring, in_file in SLOT_FILES.items():
        try:
            with open(in_file, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
        except FileNotFoundError:
            print(f"Skipping {scoring} — {in_file} not found (run build_consensus.py first).")
            continue

        out_file = OUT_FILES[scoring]
        with open(out_file, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=FIELDNAMES)
            w.writeheader()
            for row in rows:
                w.writerow({col: row[col] for col in FIELDNAMES})
        print(f"Wrote {len(rows)} players to {out_file}.")


if __name__ == "__main__":
    main()
