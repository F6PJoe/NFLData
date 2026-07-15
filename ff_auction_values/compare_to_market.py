#!/usr/bin/env python3
"""
Compare this project's auction values against real market references:
  - FantasyPros $200 half-PPR export (manually captured, see
    reference_fantasypros_200_half_ppr.csv)
  - 4for4 $200 half-PPR export (CSV downloaded from the user's account)
  - Draft Sharks full export, 12-team/$200/half-PPR/1QB-2RB-3WR-1TE-1FLEX,
    in two configurations the user pulled: "starters over depth"
    (reference_draftsharks_export.csv) and "balanced roster"
    (reference_draftsharks_balanced_export.csv). Each has two value
    columns, "Market $" (their tracked real auction-price consensus) and
    "Auction $" (their own 3D-model value). The "starters" pull runs hot at
    the top vs. FantasyPros/4for4 (by the user's own description of that
    slider setting) — treat it as directional only. The "balanced" pull is
    much closer to FantasyPros/4for4 in absolute scale and is the more
    trustworthy DS reference for calibration.

Prints, per position: total $ summed across matched players (budget share)
for ours vs. each reference, plus a per-player diff table for the top of
each position — the fastest way to see whether we're systematically off in
overall position balance (budget share) vs. just noisy on individual players.

Usage:
    python compare_to_market.py [path/to/4for4_export.csv]
"""

import csv
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "ff_rankings"))
from name_match import normalize_name  # noqa: E402

HERE = Path(__file__).resolve().parent
OURS_FILE = HERE / "auction_values_half_ppr.csv"
FP_FILE = HERE / "reference_fantasypros_200_half_ppr.csv"
DS_STARTERS_FILE = HERE / "reference_draftsharks_export.csv"
DS_BALANCED_FILE = HERE / "reference_draftsharks_balanced_export.csv"
DEFAULT_4FOR4 = Path.home() / "Downloads" / "4for4_auction_values_070826.csv"

POSITIONS = ["QB", "RB", "WR", "TE"]


def load_ours():
    out = {}
    with open(OURS_FILE, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            out[normalize_name(row["Player"])] = {
                "name": row["Player"], "pos": row["Position"],
                "value": float(row["Auction Value ($)"]),
            }
    return out


def load_fp():
    out = {}
    with open(FP_FILE, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            out[normalize_name(row["Player"])] = {
                "name": row["Player"], "pos": row["Position"],
                "value": float(row["Value"]),
            }
    return out


def load_4for4(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    block_labels = rows[0]
    data_rows = rows[2:]
    out = {}
    for pos in POSITIONS:
        if pos not in block_labels:
            continue
        col = block_labels.index(pos)
        name_col, val_col = col + 1, col + 3
        for row in data_rows:
            if val_col >= len(row):
                continue
            name = row[name_col].strip()
            val = row[val_col].strip().lstrip("$")
            if not name or not val:
                continue
            out[normalize_name(name)] = {
                "name": name, "pos": pos, "value": float(val),
            }
    return out


def load_draftsharks(path, value_col):
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            pos = row.get("Pos", "").strip()
            if pos not in POSITIONS:
                continue
            name = row.get("Player", "").strip()
            val = row.get(value_col, "").strip().lstrip("$")
            if not name or not val:
                continue
            out[normalize_name(name)] = {
                "name": name, "pos": pos, "value": float(val),
            }
    return out


def matched_keys_for(pos, ours, *sources):
    keys = set()
    for src in sources:
        keys |= {k for k, v in src.items() if v["pos"] == pos}
    return {k for k in keys if k in ours}


def main():
    for4_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_4FOR4

    ours = load_ours()
    sources = {
        "FantasyPros": load_fp(),
        "4for4": load_4for4(for4_path),
        "DS-Start Mkt": load_draftsharks(DS_STARTERS_FILE, "Market $"),
        "DS-Start Auc": load_draftsharks(DS_STARTERS_FILE, "Auction $"),
        "DS-Bal Mkt": load_draftsharks(DS_BALANCED_FILE, "Market $"),
        "DS-Bal Auc": load_draftsharks(DS_BALANCED_FILE, "Auction $"),
    }
    names = list(sources)

    print("=== Position budget share (sum of $ across matched players) ===")
    header = f"{'Pos':4} {'Ours':>8}" + "".join(f" {n:>12}" for n in names)
    print(header)
    totals = {"Ours": 0.0, **{n: 0.0 for n in names}}
    for pos in POSITIONS:
        mk = matched_keys_for(pos, ours, *sources.values())
        o = sum(ours[k]["value"] for k in mk if ours[k]["pos"] == pos)
        vals = {}
        for n in names:
            src = sources[n]
            vals[n] = sum(src[k]["value"] for k in mk if k in src and src[k]["pos"] == pos)
        row = f"{pos:4} {o:>8.0f}" + "".join(f" {vals[n]:>12.0f}" for n in names)
        print(row)
        totals["Ours"] += o
        for n in names:
            totals[n] += vals[n]
    print(f"{'ALL':4} {totals['Ours']:>8.0f}" + "".join(f" {totals[n]:>12.0f}" for n in names))

    print(f"\n{'Pos':4} {'Ours %':>8}" + "".join(f" {n+' %':>12}" for n in names)
          + "  (share of matched total)")
    for pos in POSITIONS:
        mk = matched_keys_for(pos, ours, *sources.values())
        o = sum(ours[k]["value"] for k in mk if ours[k]["pos"] == pos)
        vals = {}
        for n in names:
            src = sources[n]
            vals[n] = sum(src[k]["value"] for k in mk if k in src and src[k]["pos"] == pos)
        row = f"{pos:4} {100*o/totals['Ours']:>7.1f}%"
        for n in names:
            row += f" {100*vals[n]/totals[n]:>11.1f}%"
        print(row)

    print("\n=== Top 15 per position: ours vs all references ===")
    fp = sources["FantasyPros"]
    for pos in POSITIONS:
        print(f"\n--- {pos} ---")
        print(f"{'Player':24} {'Ours':>6}" + "".join(f" {n:>11}" for n in names))
        pos_players = sorted(
            [k for k, v in fp.items() if v["pos"] == pos],
            key=lambda k: -fp[k]["value"])[:15]
        for k in pos_players:
            name = fp[k]["name"]
            o = ours.get(k, {}).get("value")
            o_str = f"{o:.0f}" if o is not None else "-"
            row = f"{name:24} {o_str:>6}"
            for n in names:
                v = sources[n].get(k, {}).get("value")
                row += f" {v:>11.0f}" if v is not None else f" {'-':>11}"
            print(row)


if __name__ == "__main__":
    main()
