#!/usr/bin/env python3
"""
Compare the math-only team-count estimate (build_teamcount_estimate.py)
against real market data pulled at that same team count, to test whether
proportionally-scaled REPLACEMENT_RANK (with POSITION_BUDGET_SHARE/
VORP_EXPONENT held constant) is close enough to skip full real-market
recalibration for every team count — see CLAUDE.md, "Team count: testing
math-only scaling."

Reuses compare_to_market.py's Draft Sharks/4for4 loaders (same export
format regardless of team count) but needs a NEW FantasyPros loader — the
10-team file is a raw site export (wide block format, "PlayerName - TEAM"
names, "$NN" values), not the manually-transcribed Position/Rank/Player/
Team/Value format used for the original 12-team reference file.

Usage:
    python compare_teamcount.py 10
"""

import csv
import sys
from pathlib import Path

import compare_to_market as mkt

HERE = Path(__file__).resolve().parent
POSITIONS = mkt.POSITIONS


def load_fp_raw_export(path):
    """FantasyPros raw site export: wide column-blocks per position, one
    title row ("10 team") before the real header row, Name cells formatted
    "Player - TEAM" within position blocks (Overall block uses "Player
    (POS - TEAM)" instead, but we don't read that block)."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    header_row_idx = next(i for i, row in enumerate(rows) if "QB" in row)
    block_labels = rows[header_row_idx]
    data_rows = rows[header_row_idx + 1:]
    out = {}
    for pos in POSITIONS:
        col = block_labels.index(pos)
        name_col, value_col = col, col + 2
        for row in data_rows:
            if value_col >= len(row):
                continue
            raw_name = row[name_col].strip()
            val = row[value_col].strip().lstrip("$")
            if not raw_name or not val:
                continue
            name = raw_name.split(" - ")[0].strip()
            try:
                fval = float(val)
            except ValueError:
                continue
            out[mkt.normalize_name(name)] = {"name": name, "pos": pos, "value": fval}
    return out


def load_ours(path):
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            out[mkt.normalize_name(row["Player"])] = {
                "name": row["Player"], "pos": row["Position"],
                "value": float(row["Auction Value ($)"]),
            }
    return out


def main():
    teams = sys.argv[1] if len(sys.argv) > 1 else "10"

    ours = load_ours(HERE / f"auction_values_{teams}team_half_ppr.csv")
    fp = load_fp_raw_export(HERE / f"reference_fantasypros_{teams}team.csv")
    for4 = mkt.load_4for4(HERE / f"reference_4for4_{teams}team.csv")
    ds_market = mkt.load_draftsharks(HERE / f"reference_draftsharks_{teams}team.csv", "Market $")
    ds_auction = mkt.load_draftsharks(HERE / f"reference_draftsharks_{teams}team.csv", "Auction $")

    sources = {"FantasyPros": fp, "4for4": for4, "DS Market": ds_market, "DS Auction": ds_auction}
    names = list(sources)

    print(f"=== Position budget share ({teams}-team) ===")
    header = f"{'Pos':4} {'Ours':>8}" + "".join(f" {n:>12}" for n in names)
    print(header)
    totals = {"Ours": 0.0, **{n: 0.0 for n in names}}
    for pos in POSITIONS:
        mk = mkt.matched_keys_for(pos, ours, *sources.values())
        o = sum(ours[k]["value"] for k in mk if ours[k]["pos"] == pos)
        vals = {n: sum(sources[n][k]["value"] for k in mk if k in sources[n] and sources[n][k]["pos"] == pos)
                for n in names}
        print(f"{pos:4} {o:>8.0f}" + "".join(f" {vals[n]:>12.0f}" for n in names))
        totals["Ours"] += o
        for n in names:
            totals[n] += vals[n]
    print(f"{'ALL':4} {totals['Ours']:>8.0f}" + "".join(f" {totals[n]:>12.0f}" for n in names))

    print(f"\n{'Pos':4} {'Ours %':>8}" + "".join(f" {n+' %':>12}" for n in names))
    for pos in POSITIONS:
        mk = mkt.matched_keys_for(pos, ours, *sources.values())
        o = sum(ours[k]["value"] for k in mk if ours[k]["pos"] == pos)
        vals = {n: sum(sources[n][k]["value"] for k in mk if k in sources[n] and sources[n][k]["pos"] == pos)
                for n in names}
        row = f"{pos:4} {100*o/totals['Ours']:>7.1f}%"
        for n in names:
            row += f" {100*vals[n]/totals[n]:>11.1f}%" if totals[n] else f" {'n/a':>12}"
        print(row)

    print(f"\n=== Top 15 per position: ours vs all references ({teams}-team) ===")
    for pos in POSITIONS:
        print(f"\n--- {pos} ---")
        print(f"{'Player':24} {'Ours':>6}" + "".join(f" {n:>11}" for n in names))
        pos_players = sorted([k for k, v in fp.items() if v["pos"] == pos],
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
