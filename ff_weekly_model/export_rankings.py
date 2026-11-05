#!/usr/bin/env python3
"""Our weekly projections as a FantasyPros-style rankings file.

    python export_rankings.py --year 2026 --week 6

Ranks the half-PPR projections (data/projections_<yr>_wk<NN>.csv) by position
and writes NFL_<year>_Week_<N>_Half_PPR_Weekly_Rankings.csv here, in exactly
the layout ff_rankings uploads (QB, RB, WR, TE, Flex, empty Superflex, DST,
K -- one 6-column block each). It reuses ff_rankings' writer, so FP's player
IDs, name spellings ("Patrick Mahomes II"), team codes (LAR, JAC), opponents
and kickoff times come from FP's own lists exactly as in Joe's export.

The model does not project kickers or defenses: the DST and K blocks are
copied from that week's ff_rankings consensus (weekly/<yr>-wkNN/consensus_
dst.csv / consensus_k.csv) when it exists, and left empty otherwise.
"""

import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
RANKINGS = os.path.join(os.path.dirname(HERE), "ff_rankings")
sys.path.insert(0, RANKINGS)

import name_match            # noqa: E402  (ff_rankings)
import site_exports          # noqa: E402
import weekly_consensus as wc  # noqa: E402

# our team codes -> FP's, for anyone FP's lists can't match
FP_TEAM = {"LA": "LAR", "JAX": "JAC"}
MIN_UNMATCHED = 3.0


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--version", default="current",
                    help="which projection version (current, noqbtd, epa)")
    args = ap.parse_args()

    tag = "" if args.version == "current" else f"_{args.version}"
    src = os.path.join(HERE, "data", f"projections_{args.year}_wk{args.week:02d}{tag}.csv")
    with open(src, newline="", encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if float(r["half_ppr"] or 0) > 0]

    def entry(r):
        rec = {"Player": r["player"], "Team": FP_TEAM.get(r["team"], r["team"]),
               "Position": r["pos"]}
        return name_match.normalize_name(r["player"]), rec

    by_pts = sorted(rows, key=lambda r: -float(r["half_ppr"]))
    blends = {pos: [entry(r) for r in by_pts if r["pos"] == pos]
              for pos in ("QB", "RB", "WR", "TE")}
    blends["FLX"] = [entry(r) for r in by_pts if r["pos"] in ("RB", "WR", "TE")]

    # DST / K: not modelled -- borrow that week's ff_rankings consensus
    week_dir = os.path.join(RANKINGS, "weekly", f"{args.year}-wk{args.week:02d}")
    borrowed = site_exports.load_blends(week_dir, "HALF") if os.path.isdir(week_dir) else {}
    for slot in ("DST", "K"):
        if borrowed.get(slot):
            blends[slot] = borrowed[slot]

    meta = site_exports.fetch_site_meta(str(args.year), str(args.week))
    # FP doesn't rank fullbacks and deep backups; with no FP row and no override
    # ID, a player projected under MIN_UNMATCHED is left off rather than
    # written with a blank ID (Joe's site import needs every ID).
    overrides = wc.load_id_overrides()
    pts = {name_match.normalize_name(r["player"]): float(r["half_ppr"]) for r in rows}
    for slot in ("QB", "RB", "WR", "TE", "FLX"):
        blends[slot] = [(k, rec) for k, rec in blends[slot]
                        if k in meta or k in overrides or pts.get(k, 0) >= MIN_UNMATCHED]
    out = os.path.join(HERE, f"NFL_{args.year}_Week_{args.week}_Half_PPR_Weekly_Rankings.csv")
    missing = wc.write_site_export(out, blends, meta, id_overrides=overrides)
    counts = {s: len(v) for s, v in blends.items()}
    print(f"  ranked from {os.path.basename(src)}: {counts}")
    print(f"  DST/K from {'ff_rankings consensus' if borrowed else 'nowhere (left empty)'}")
    print(f"  -> {out}")
    if missing:
        print(f"\n  {len(missing)} player(s) without a FantasyPros ID (written with the ID blank):")
        for m in missing:
            print(f"    {m['name']} ({m['team']} {m['position']}) -- {m['list']} #{m['rank']}")


if __name__ == "__main__":
    main()
