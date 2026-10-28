#!/usr/bin/env python3
"""Audit our projections against every source in ff_weekly_proj, one by one.

Those sources are a BENCHMARK, never an input (see the project notes). Three
questions, in order of how much they matter:

  out of range  -- players where our number sits outside what EVERY source
                   says. Disagreeing with an average is an opinion; sitting
                   outside all ten is usually a bug, and this is the view
                   worth reading first.
  per source    -- how closely we track each one, and whether we run high or
                   low against it. A bias against all ten is ours; a bias
                   against a single source is probably theirs.
  scoreboard    -- once the week is played, who was actually closer.

Sources carry stat lines, not points, so each is scored with the same
ff_weekly_proj/scoring.py the consensus builder uses -- otherwise we would be
comparing our half-PPR against somebody else's idea of half-PPR.

WEEK SAFETY: the files in ff_weekly_proj/ are a live scrape with no week
column, so they describe whatever week was last fetched. This reads an
archived weekly/<year>-wk<NN>/ when one exists, and otherwise says loudly
which files it fell back to and how old they are. The previous audit silently
compared week 3 against week 2 and made us look wrong about three QBs.

Usage:
    python audit_vs_sources.py --year 2026 --week 2
    python audit_vs_sources.py --year 2026 --week 2 --source espn
"""

import argparse
import csv
import datetime
import math
import os
import re
import statistics as st
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
WEEKLY_PROJ = os.path.join(os.path.dirname(HERE), "ff_weekly_proj")
sys.path.insert(0, WEEKLY_PROJ)
import scoring  # noqa: E402

SOURCES = ["espn", "cbs", "ftn", "yahoo", "fantasysharks", "draftsharks",
           "fantasydata", "4for4", "fantasylife", "fftoday"]
SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)
TEAM_FIX = {"JAC": "JAX", "LAR": "LA", "WSH": "WAS", "ARZ": "ARI"}

# CSV header -> the stat key scoring.py expects
COLMAP = {"Pass Att": "pass_att", "Pass Comp": "pass_cmp", "Pass Yds": "pass_yds",
          "Pass TD": "pass_td", "Pass Int": "pass_int", "Rush Att": "rush_att",
          "Rush Yds": "rush_yds", "Rush TD": "rush_td", "Targets": "targets",
          "Rec": "rec", "Rec Yds": "rec_yds", "Rec TD": "rec_td",
          "Fum": "fum", "Fumbles": "fum"}


def norm(name):
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    n = SUFFIX.sub("", n.lower())
    return re.sub(r"[^a-z]", "", n)


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def resolve_dir(year, week):
    """-> (directory, label). Prefers an archived week over the live scrape."""
    archived = os.path.join(WEEKLY_PROJ, "weekly", f"{year}-wk{week:02d}")
    if os.path.isdir(archived):
        return archived, f"weekly/{year}-wk{week:02d} (archived)"
    return WEEKLY_PROJ, "ff_weekly_proj/ (LIVE SCRAPE -- week not guaranteed)"


def load_source(directory, name):
    """-> {normalised player: (half-PPR points, position, team)}."""
    out = {}
    for pos in ("qb", "rb", "wr", "te"):
        path = os.path.join(directory, f"{name}_{pos}.csv")
        if not os.path.exists(path):
            continue
        with open(path, newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                player = (r.get(pos.upper()) or r.get("Player") or "").strip()
                if not player:
                    continue
                stats = {COLMAP[c]: num(v) for c, v in r.items() if c in COLMAP}
                pts = (scoring.qb_points(stats) if pos == "qb"
                       else scoring.half_ppr_points(stats))
                # An exact 0 is a placeholder, not a projection. ESPN lists 298
                # of its 700 players at 0 -- starters included (Purdy, Shough,
                # Winston in wk3 2026) -- and FantasyData 348 of 774. Averaged
                # in, they dragged Purdy's consensus from 19.8 to 17.3. Skipping
                # them means "this source did not project him", which is true.
                if not any(stats.values()):
                    continue
                out[norm(player)] = (pts, pos.upper(),
                                     TEAM_FIX.get(r.get("Team", ""), r.get("Team", "")))
    return out


def load_ours(year, week):
    path = os.path.join(DATA, f"projections_{year}_wk{week:02d}.csv")
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["player"].strip():
                out[norm(r["player"])] = {"pts": float(r["half_ppr"]), "pos": r["pos"],
                                          "team": r["team"], "name": r["player"]}
    return out


def agreement(ours, theirs, keys):
    o = [ours[k]["pts"] for k in keys]
    t = [theirs[k][0] for k in keys]
    mo, mt = st.mean(o), st.mean(t)
    cov = sum((a - mo) * (b - mt) for a, b in zip(o, t))
    den = math.sqrt(sum((a - mo) ** 2 for a in o) * sum((b - mt) ** 2 for b in t))
    return {"n": len(keys), "corr": cov / den if den else float("nan"),
            "mad": st.mean([abs(a - b) for a, b in zip(o, t)]),
            "bias": mo - mt}


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--source", help="drill into one source's disagreements")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    directory, label = resolve_dir(args.year, args.week)
    ours = load_ours(args.year, args.week)
    loaded = {s: load_source(directory, s) for s in SOURCES}
    loaded = {s: v for s, v in loaded.items() if v}

    print(f"\n  auditing week {args.week} against {len(loaded)} sources")
    print(f"  reading: {label}")
    if directory == WEEKLY_PROJ:
        stamps = []
        for s in loaded:
            p = os.path.join(directory, f"{s}_rb.csv")
            if os.path.exists(p):
                stamps.append(os.path.getmtime(p))
        if stamps:
            new = datetime.datetime.fromtimestamp(max(stamps))
            old = datetime.datetime.fromtimestamp(min(stamps))
            print(f"  *** these files were fetched {old:%Y-%m-%d} to {new:%Y-%m-%d}."
                  f" Confirm that is week {args.week}. ***")
    print()

    print(f"  {'source':<16}{'n':>5}{'corr':>8}{'mean gap':>11}{'our bias':>11}")
    rows = []
    for s, t in sorted(loaded.items()):
        keys = [k for k in ours if k in t]
        if len(keys) < 20:
            continue
        a = agreement(ours, t, keys)
        rows.append((s, a))
        print(f"  {s:<16}{a['n']:>5}{a['corr']:>8.3f}{a['mad']:>10.2f}p"
              f"{a['bias']:>+10.2f}p")
    if rows:
        print("  " + "-" * 50)
        print(f"  {'median':<16}{'':>5}"
              f"{st.median([a['corr'] for _, a in rows]):>8.3f}"
              f"{st.median([a['mad'] for _, a in rows]):>10.2f}p"
              f"{st.median([a['bias'] for _, a in rows]):>+10.2f}p")

    print("\n\n  players where our number is outside EVERY source's range")
    print("  (the view that actually catches bugs)\n")
    flags = []
    for k, mine in ours.items():
        vals = [t[k][0] for t in loaded.values() if k in t]
        if len(vals) < 5:
            continue
        lo, hi = min(vals), max(vals)
        if mine["pts"] > hi:
            flags.append((mine["pts"] - hi, mine, lo, hi, len(vals), "HIGH"))
        elif mine["pts"] < lo:
            flags.append((lo - mine["pts"], mine, lo, hi, len(vals), "LOW"))
    flags.sort(reverse=True, key=lambda x: x[0])
    if not flags:
        print("  none -- every projection sits inside the range of the sources.")
    else:
        print(f"  {'player':<22}{'pos':<5}{'tm':<5}{'ours':>7}{'their range':>16}"
              f"{'off by':>9}  n")
        for gap, m, lo, hi, n, direction in flags[:args.top]:
            rng = f"{lo:.1f} - {hi:.1f}"
            print(f"  {m['name'][:21]:<22}{m['pos']:<5}{m['team']:<5}"
                  f"{m['pts']:>7.1f}{rng:>16}{gap:>+8.1f} {direction:<5}{n}")
        print(f"\n  {len(flags)} of {len(ours)} projections fall outside every source.")

    # ---- calibration: are we compressing the range?
    # A per-player gap is noise; a gap that grows monotonically with how much
    # the market likes a player is over-shrinkage, and that is a model setting
    # rather than an opinion.
    tiered = []
    for k, mine in ours.items():
        vals = [t[k][0] for t in loaded.values() if k in t]
        if len(vals) >= 8:
            med = st.median(vals)
            tiered.append((med, mine["pos"], mine["pts"] - med))
    if tiered:
        print("\n\n  calibration -- our bias against the market median\n")
        print(f"  {'market tier':<20}{'n':>5}{'mean bias':>12}{'median':>11}")
        for lbl, lo, hi in [("15+ pts (studs)", 15, 1e9), ("10-15", 10, 15),
                            ("5-10", 5, 10), ("2-5", 2, 5), ("under 2", 0, 2)]:
            sub = [b for m, _, b in tiered if lo <= m < hi]
            if len(sub) < 8:
                continue
            print(f"  {lbl:<20}{len(sub):>5}{st.mean(sub):>+11.2f}p"
                  f"{st.median(sub):>+10.2f}p")
        print(f"\n  {'starters (10+), by position':<27}{'n':>5}{'mean bias':>12}")
        for pos in ("QB", "RB", "WR", "TE"):
            sub = [b for m, p, b in tiered if m >= 10 and p == pos]
            if len(sub) < 5:
                continue
            print(f"  {pos:<27}{len(sub):>5}{st.mean(sub):>+11.2f}p")

    if args.source:
        t = loaded.get(args.source)
        if not t:
            print(f"\n  no data for source {args.source!r}")
            return
        keys = [k for k in ours if k in t]
        d = sorted(((ours[k]["pts"] - t[k][0], ours[k]) for k in keys),
                   key=lambda x: -abs(x[0]))
        print(f"\n\n  biggest disagreements with {args.source}\n")
        print(f"  {'player':<22}{'pos':<5}{'tm':<5}{'ours':>7}{'theirs':>8}{'diff':>8}")
        for diff, m in d[:args.top]:
            print(f"  {m['name'][:21]:<22}{m['pos']:<5}{m['team']:<5}"
                  f"{m['pts']:>7.1f}{m['pts'] - diff:>8.1f}{diff:>+8.1f}")
    print()


if __name__ == "__main__":
    main()
