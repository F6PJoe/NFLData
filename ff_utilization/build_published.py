#!/usr/bin/env python3
"""
Merge the official-basis build with FL's routes into the file the site reads.

    nflverse_weekly_<yr>_wk<a>-<b>.csv    official: snaps, rush, targets,
                                          ez_tgts, inside5_rush, adot
    utilization_weekly_<yr>_wk<a>-<b>.csv FL: routes + routes_pct ONLY
        ->  data/utilization_weekly.json  (what the posts fetch)

Why this mix is safe, when mixing generally isn't
-------------------------------------------------
Official and PFF counts differ by ~4-5% one-directionally (PFF doesn't credit
a target on a throwaway to the nearest receiver; the official feed does). The
rule that keeps a mixed table honest is: **no ratio may cross sources.**

    snaps_pct, rush_att_pct, targets_pct,
    ez_tgts_pct, inside5_rush_pct, adot      -> official numerator AND denominator
    routes, routes_pct                       -> FL numerator AND denominator

TPRR was the one column that broke the rule -- targets / routes, one from each
basis -- and it is deliberately NOT published. It stays in the FL spreadsheet.

Residual, accepted: a reader dividing the published targets by the published
routes gets a TPRR that is ~4% off FL's own. Unavoidable without dropping one
source, and small.

Not published at all (no official equivalent exists in-season):
    tprr, catchable_tgts, two_min/sdd/ldd snaps

Players with no FL route match are DROPPED, not published with routes=0 --
by decision, no player shows an incomplete row. Checked on 2026 wk1: of 43
unmatched, 32 had zero snaps/rush/targets (inactive/practice squad) and the
rest were fullbacks/emergency backs FL's own game-log excludes too, same
pattern as 2025 wk1-2. A player with real volume (3+ targets, or 6+ rushes)
and no match prints a WARNING instead of dropping silently, in case a future
week's miss is an actual name-matching bug rather than an FL exclusion.

Usage:
    python build_published.py --year 2026 --weeks 1-1
"""

import argparse
import csv
import json
import re
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"

# Order matters -- this is the column order on the site.
COLUMNS = [
    "player_id", "player", "team", "pos", "season", "week",
    "snaps", "snaps_pct",
    "rush_att", "rush_att_pct", "inside5_rush", "inside5_rush_pct",
    "routes", "routes_pct",
    "targets", "targets_pct", "rec", "ez_tgts", "ez_tgts_pct", "adot",
    "air_yards_total",
    # denominators, so any week range re-aggregates exactly in the browser
    "team_snaps", "team_rush_att", "team_inside5_rush", "team_targets",
    "team_ez_tgts", "team_routes",
]


def norm(name):
    name = unicodedata.normalize("NFKD", name or "")
    name = "".join(c for c in name if not unicodedata.combining(c))
    name = re.sub(r"\b(Jr|Sr|II|III|IV|V)\.?\b", "", name, flags=re.I)
    return re.sub(r"[^a-z]", "", name.lower())


def load(path):
    with open(path, encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


# csv.DictReader yields STRINGS. Written into the JSON untouched, the grid's
# season view does "0" + "46" = "046" instead of 46, and every rate derived
# from it comes out NaN. Coerce before writing -- the FL pipeline never hit
# this because it builds rows from numbers directly.
INT_COLS = {"season", "week", "snaps", "rush_att", "inside5_rush", "routes",
            "targets", "rec", "ez_tgts", "team_snaps", "team_rush_att",
            "team_inside5_rush", "team_targets", "team_ez_tgts", "team_routes"}
FLOAT_COLS = {"snaps_pct", "rush_att_pct", "inside5_rush_pct", "routes_pct",
              "targets_pct", "ez_tgts_pct", "adot", "air_yards_total"}


def coerce(row):
    out = {}
    for k, v in row.items():
        if k in INT_COLS:
            try:
                out[k] = int(float(v))
            except (TypeError, ValueError):
                out[k] = 0
        elif k in FLOAT_COLS:
            try:
                out[k] = round(float(v), 1)
            except (TypeError, ValueError):
                out[k] = 0.0
        else:
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--weeks", default="1-1")
    args = ap.parse_args()

    suffix = f"{args.year}_wk{args.weeks}"
    off = load(DATA / f"nflverse_weekly_{suffix}.csv")
    fl = load(DATA / f"utilization_weekly_{suffix}.csv")

    # FL routes keyed by normalised name + week. Names are full on both sides
    # here (the official build resolves display names via nflverse players),
    # so a plain normalised match is enough -- no initial/prefix juggling.
    routes, by_surname = {}, {}
    for r in fl:
        val = (
            int(float(r["routes"])),
            float(r["routes_pct"]),
            # FL's own team route denominator, so routes_pct stays FL-internal
            int(float(r.get("team_routes") or 0)),
        )
        routes[(norm(r["player"]), r["week"])] = val
        # Fallback index. The two feeds disagree on given names -- FL says
        # "Chigoziem Okonkwo", the official feed "Chig Okonkwo" -- so a full
        # name match misses real players. Surname + team + week + position is
        # specific enough; anything ambiguous is dropped below rather than
        # guessed at.
        sk = (norm(r["player"].split()[-1]), r["team"], r["week"], r["pos"])
        by_surname.setdefault(sk, []).append(val)

    rows, matched, via_surname, dropped = [], 0, 0, []
    for r in off:
        hit = routes.get((norm(r["player"]), r["week"]))
        if hit is None:
            sk = (norm(r["player"].split()[-1]), r["team"], r["week"], r["pos"])
            cands = by_surname.get(sk) or []
            if len(cands) == 1:          # unambiguous only
                hit = cands[0]
                via_surname += 1
        if hit is None:
            # No FL route data -- by decision, drop rather than publish a
            # player with an incomplete row. Checked directly (2026 wk1): of
            # 43 such players, 32 recorded zero snaps/rush/targets entirely,
            # and the rest are fullbacks/emergency backs FL's own game-log
            # excludes too (same pattern independently confirmed on 2025
            # wk1-2 -- see the CLAUDE.md section on FL's game-log filtering).
            # Not a matching bug; these players just aren't in FL's pool.
            dropped.append(r)
            continue
        matched += 1
        n, pct, team_n = hit
        out = {c: r.get(c, "") for c in COLUMNS if c in r}
        out["routes"] = n
        out["routes_pct"] = pct
        out["team_routes"] = team_n
        rows.append({c: out.get(c, "") for c in COLUMNS})

    # The official build carries snap PERCENTAGE straight from the gamebook but
    # no team snap total -- and the season view needs the denominator, or
    # snap% over a custom week range computes to zero. Recover it as
    # snaps / pct, taking the median across a team-week so one rounded share
    # can't skew it.
    import statistics
    implied = {}
    for r in rows:
        try:
            n, pct = int(r["snaps"] or 0), float(r["snaps_pct"] or 0)
        except (TypeError, ValueError):
            continue
        if n and pct:
            implied.setdefault((r["team"], r["week"]), []).append(n / (pct / 100))
    for r in rows:
        vals = implied.get((r["team"], r["week"]))
        r["team_snaps"] = int(round(statistics.median(vals))) if vals else 0

    rows = [coerce(r) for r in rows]
    rows.sort(key=lambda x: (x["week"], -x["snaps"]))

    csv_path = DATA / f"published_{suffix}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    json_path = DATA / "utilization_weekly.json"
    payload = {"cols": COLUMNS, "rows": [[r.get(c) for c in COLUMNS] for r in rows]}
    json_path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")

    print(f"official rows: {len(off)}   FL rows: {len(fl)}")
    print(f"published: {matched}/{len(off)} matched to FL routes "
          f"({100*matched/len(off):.0f}%)"
          + (f", {via_surname} via surname fallback" if via_surname else ""))
    print(f"dropped (no FL route match): {len(dropped)}")
    notable = [r for r in dropped if int(r["targets"]) > 2 or int(r["rush_att"]) > 5]
    if notable:
        print(f"  WARNING -- {len(notable)} dropped players had real volume, "
              f"check these aren't a real match miss:")
        for r in notable[:8]:
            print(f"    {r['player']} ({r['team']}) rush={r['rush_att']} tgt={r['targets']}")
    print(f"\n{csv_path.name}  ({csv_path.stat().st_size/1024:.0f} KB)")
    print(f"UPLOAD -> {json_path}  ({json_path.stat().st_size/1024:.0f} KB)")


if __name__ == "__main__":
    main()
