#!/usr/bin/env python3
"""Per-player, per-season raw stat lines -> player_history.csv

The share files carry percentages; this carries the actual counts a human
wants while typing a projection: games, carries, yards, touchdowns, targets,
receptions, and the yards-per rates that come out of them.

Crucially this is keyed to the PLAYER, not the team, so a guy who changed
teams still shows what he did wherever he was. That is the whole point - his
production travels even though his usage share does not.

Usage:
    python build_history.py
"""

import argparse
import csv
import json
import os
import sys

import names
from teams import clean_team

HERE = os.path.dirname(os.path.abspath(__file__))
SR = os.path.join(HERE, "cached", "sr")
NFLVERSE = os.path.join(HERE, "cached", "nflverse")


def load_snaps(season):
    """{normalized name: mean offensive snap share} for one season.

    nflverse's offense_pct is already the fraction of his team's offensive
    snaps a player took in that game, so the season figure is just the mean
    across games he appeared in - i.e. his snap share WHEN ACTIVE. Games he
    missed are absent from the file rather than counted as zero, which is the
    behaviour we want: this is a role measure, not an availability measure.
    Availability is the Games input.
    """
    path = os.path.join(NFLVERSE, f"snap_counts_{season}.csv")
    if not os.path.exists(path):
        return {}
    totals = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            if row.get("game_type") != "REG":
                continue
            try:
                pct = float(row.get("offense_pct") or 0)
            except ValueError:
                continue
            if pct <= 0:
                continue
            key = names.normalize(row.get("player", ""))
            if not key:
                continue
            acc = totals.setdefault(key, [0.0, 0])
            acc[0] += pct
            acc[1] += 1
    return {k: v[0] / v[1] for k, v in totals.items() if v[1]}


def _i(d, key):
    try:
        return int(d.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def load(season):
    path = os.path.join(SR, str(season))
    if not os.path.isdir(path):
        return {}
    out = {}
    for fn in sorted(os.listdir(path)):
        with open(os.path.join(path, fn), encoding="utf-8") as fh:
            d = json.load(fh)
        team = clean_team(d["alias"])
        for p in d["players"]:
            pr = p.get("receiving") or {}
            pu = p.get("rushing") or {}
            pp = p.get("passing") or {}
            car = _i(pu, "attempts") - _i(pu, "kneel_downs")
            tgt, patt = _i(pr, "targets"), _i(pp, "attempts")
            if not (car or tgt or patt):
                continue
            key = p["id"] or names.normalize(p["name"])
            out[key] = {
                "name": p["name"], "name_key": names.normalize(p["name"]),
                "team": team, "games": _i(p, "games_played"),
                "car": car, "ruyd": _i(pu, "yards"), "rutd": _i(pu, "touchdowns"),
                "tgt": tgt, "rec": _i(pr, "receptions"),
                "reyd": _i(pr, "yards"), "retd": _i(pr, "touchdowns"),
                # gross_yards, not yards - Sportradar's `yards` is net of sacks
                "patt": patt, "pyds": _i(pp, "gross_yards"),
                "ptd": _i(pp, "touchdowns"), "pint": _i(pp, "interceptions"),
                "pcmp": _i(pp, "completions"),
            }
    return out


FIELDS = ["team", "games", "car", "ruyd", "rutd", "tgt", "rec", "reyd",
          "retd", "patt", "pcmp", "pyds", "ptd", "pint"]

# Same weighting build_shares.py uses for the seeded inputs, so the reference
# columns and the values they're compared against are computed the same way.
RECENCY = {0: 0.5, 1: 0.3, 2: 0.2}   # offset from most recent season
FULL_SEASON = 17


def weighted_rate(per_season, num_key, den_key, min_denom, places):
    """Recency- and games-weighted rate across seasons.

    Each season contributes its OWN rate, weighted by how recent it is and how
    much of it the player was available for. A season below `min_denom` is
    skipped entirely rather than down-weighted - a 4-carry sample isn't a weak
    signal, it's noise, and letting it in is how a rate ends up looking broken.
    """
    num = den = 0.0
    for offset, rec in per_season:
        if not rec:
            continue
        d = rec.get(den_key) or 0
        if d < min_denom:
            continue
        w = RECENCY.get(offset, 0.1) * min(rec.get("games") or 0,
                                           FULL_SEASON) / FULL_SEASON
        if w <= 0:
            continue
        num += ((rec.get(num_key) or 0) / d) * w
        den += w
    return round(num / den, places) if den else ""


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", type=int, default=2026)
    args = ap.parse_args()

    seasons = [args.season - 3, args.season - 2, args.season - 1]
    hist = {yr: load(yr) for yr in seasons}
    snaps = {yr: load_snaps(yr) for yr in seasons}
    have_snaps = sum(len(v) for v in snaps.values())
    if not any(hist.values()):
        sys.exit(f"No Sportradar cache in {SR}. Run fetch_sportradar.py first.")

    roster = list(csv.DictReader(
        open(os.path.join(HERE, f"rosters_{args.season}.csv"), encoding="utf-8")))

    by_id = hist
    by_name = {yr: {r["name_key"]: r for r in h.values()} for yr, h in hist.items()}

    cols = ["player", "team", "pos", "depth", "sportradar_id"]
    for yr in seasons:
        cols += [f"{yr}_{f}" for f in FIELDS]
    for yr in seasons:
        cols.append(f"{yr}_snap_pct")
    cols += ["car_3y", "ruyd_3y", "tgt_3y", "reyd_3y", "patt_3y", "pcmp_3y",
             "pyds_3y", "ypc_3y", "ypr_3y", "catch_3y", "comp_pct_3y",
             "ypa_3y", "int_pct_3y", "games_3y", "snap_pct_3y"]

    rows = []
    for r in roster:
        out = {"player": r["player"], "team": r["team"], "pos": r["pos"],
               "depth": r["depth"], "sportradar_id": r["sportradar_id"]}
        totals = {k: 0 for k in ("car", "ruyd", "tgt", "rec", "reyd",
                                 "patt", "pcmp", "pyds", "games")}
        # (offset from most recent season, that season's record) - offset 0 is
        # last year, which carries the most weight.
        per_season = []
        for idx, yr in enumerate(seasons):
            rec = (by_id[yr].get(r["sportradar_id"]) if r["sportradar_id"] else None)
            if rec is None:
                rec = by_name[yr].get(names.normalize(r["player"]))
            for f_ in FIELDS:
                out[f"{yr}_{f_}"] = rec[f_] if rec else ""
            if rec:
                for k in totals:
                    totals[k] += rec[k]
            per_season.append((len(seasons) - 1 - idx, rec))
            sp = snaps.get(yr, {}).get(names.normalize(r["player"]))
            out[f"{yr}_snap_pct"] = round(sp, 3) if sp else ""
        out["car_3y"], out["ruyd_3y"] = totals["car"], totals["ruyd"]
        out["tgt_3y"], out["reyd_3y"] = totals["tgt"], totals["reyd"]
        out["patt_3y"], out["pcmp_3y"] = totals["patt"], totals["pcmp"]
        out["pyds_3y"] = totals["pyds"]
        out["games_3y"] = totals["games"]
        # Rate columns are recency- and games-weighted, matching how
        # build_shares.py seeds the input cells. They used to be POOLED
        # (total yards / total carries across all 3 years), which silently
        # contradicted the seeds sitting beside them in the same row: pooling
        # gives the most weight to whichever season had the most volume, the
        # opposite of recency. Dameon Pierce read 3.80 Y/C pooled vs 5.28
        # weighted, because 145 of his carries were in 2023 and 4 in 2025.
        for col, num_key, den_key, min_n, places in (
                ("ypc_3y", "ruyd", "car", 20, 2),
                ("ypr_3y", "reyd", "rec", 12, 2),
                ("catch_3y", "rec", "tgt", 15, 3),
                ("comp_pct_3y", "pcmp", "patt", 20, 3),
                # Y/A is unbounded, so a thin sample doesn't just look
                # uncertain, it looks BROKEN - 1 attempt for 37 yards reads as
                # 37.0 Y/A. Comp% can't do that (bounded 0-100%), which is why
                # the floor matters most here.
                ("ypa_3y", "pyds", "patt", 20, 2),
                ("int_pct_3y", "pint", "patt", 20, 3)):
            out[col] = weighted_rate(per_season, num_key, den_key, min_n, places)

        # Snap share, recency-weighted the same way as everything else.
        num = den = 0.0
        for idx, yr in enumerate(seasons):
            sp = snaps.get(yr, {}).get(names.normalize(r["player"]))
            if not sp:
                continue
            w = RECENCY.get(len(seasons) - 1 - idx, 0.1)
            num += sp * w
            den += w
        out["snap_pct_3y"] = round(num / den, 3) if den else ""
        rows.append(out)

    path = os.path.join(HERE, f"player_history_{args.season}.csv")
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    have = sum(1 for r in rows if r["games_3y"])
    matched_snaps = sum(1 for r in rows if r.get("snap_pct_3y"))
    print(f"Wrote {os.path.basename(path)} - {len(rows)} players, "
          f"{have} with a stat line in {seasons[0]}-{seasons[-1]}")
    print(f"  snap share matched for {matched_snaps} players "
          f"({have_snaps:,} player-games read)")


if __name__ == "__main__":
    sys.exit(main())
