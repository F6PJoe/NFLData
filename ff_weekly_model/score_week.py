#!/usr/bin/env python3
"""Score a PLAYED week: us vs the consensus vs every source vs Establish the Run.

The audit (audit_vs_sources.py) compares us to the market BEFORE the games.
This is the other half: once the week is played, who was actually closer.

Reads
  data/projections_<year>_wk<NN>_final.csv   our projections frozen before
                                             kickoff (see --freeze); falls
                                             back to the live file with a
                                             warning, because that file is
                                             overwritten on every run
  ff_weekly_proj/weekly/<year>-wk<NN>/        the outside sources, and etr.csv
                                             when Establish the Run was saved
  data/stats_player_week_<year>.csv          what actually happened

Every test version (project.py --version NAME, files
projections_<year>_wk<NN>_<NAME>.csv) is frozen and scored beside the current
model, with a per-position split and a head-to-head on the players where the
versions actually disagree.

Only fantasy-relevant players are scored (consensus 5+ points, 4+ sources),
since RMSE over hundreds of 0-point backups says nothing useful.

Usage:
    python score_week.py --year 2026 --week 3 --freeze   # before kickoff
    python score_week.py --year 2026 --week 3            # after the games
"""

import argparse
import csv
import datetime
import math
import os
import statistics as st
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import audit_vs_sources as A  # noqa: E402
import project as P  # noqa: E402

MIN_CONS, MIN_SOURCES = 5.0, 4


def load_etr(directory):
    path = os.path.join(directory, "etr.csv")
    if not os.path.exists(path):
        return {}
    out = {}
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for r in csv.DictReader(fh):
            if r.get("Pos") in ("QB", "RB", "WR", "TE"):
                v = P.num(r.get("Half PPR Proj"), None)
                if v is not None:
                    out[A.norm(r["Player"])] = v
    return out


def kickoffs(year, week):
    """team -> kickoff (local Eastern time, the machine's clock) for the week."""
    out = {}
    path = os.path.join(HERE, "data", "games.csv")
    with open(path, newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["season"] != str(year) or r["week"] != str(week) or not r.get("gameday"):
                continue
            t = r.get("gametime") or "13:00"
            k = datetime.datetime.strptime(f"{r['gameday']} {t}", "%Y-%m-%d %H:%M")
            out[r["home_team"]] = out[r["away_team"]] = k
    return out


def freeze(live, final, started):
    """Copy live -> final, except teams whose game has STARTED keep the rows
    already frozen for them. Thursday's (and Saturday's) games are locked
    before their own kickoff; re-freezing on Sunday must not overwrite them
    with numbers re-run after the game -- a post-game injury tag would quietly
    drop a player from the very week he was scored on."""
    with open(live, newline="", encoding="utf-8") as fh:
        rd = csv.DictReader(fh)
        cols, new = rd.fieldnames, list(rd)
    kept = []
    if os.path.exists(final) and started:
        with open(final, newline="", encoding="utf-8") as fh:
            kept = [r for r in csv.DictReader(fh) if r["team"] in started]
        new = [r for r in new if r["team"] not in started]
    with open(final, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(kept + new)
    return len(kept), len(new)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--freeze", action="store_true",
                    help="snapshot this week's projections before kickoff")
    args = ap.parse_args()

    base = os.path.join(HERE, "data", f"projections_{args.year}_wk{args.week:02d}")
    versions = {"current": base + ".csv"}
    for name in P.VARIANTS:
        if name != "current" and os.path.exists(f"{base}_{name}.csv"):
            versions[name] = f"{base}_{name}.csv"
    if args.freeze:
        now = datetime.datetime.now()
        started = {tm for tm, k in kickoffs(args.year, args.week).items() if k <= now}
        if started:
            print(f"  already kicked off (their frozen rows are kept): "
                  f"{', '.join(sorted(started))}")
        for name, live in versions.items():
            final = live.replace(".csv", "_final.csv")
            kept, new = freeze(live, final, started)
            print(f"  froze {os.path.basename(live)} -> {os.path.basename(final)}"
                  + (f"   ({kept} kept from earlier lock, {new} updated)" if kept else ""))
        return

    ours, pos_of, used = {}, {}, []
    for name, live in versions.items():
        final = live.replace(".csv", "_final.csv")
        src_file = final if os.path.exists(final) else live
        if src_file == live:
            print(f"  *** {name}: no frozen snapshot -- scoring the LIVE file, which "
                  f"may have been re-run after kickoff. ***")
        with open(src_file, newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        col = "dfs" if rows and "dfs" in rows[0] else "half_ppr"
        ours[name] = {A.norm(r["player"]): float(r[col]) for r in rows}
        for r in rows:
            pos_of.setdefault(A.norm(r["player"]), r["pos"])
        used.append(os.path.basename(src_file))
    vkeys = [f"OURS {n}" for n in ours]

    directory, label = A.resolve_dir(args.year, args.week)
    src = {n: A.load_source(directory, n) for n in A.SOURCES}
    src = {k: v for k, v in src.items() if v}
    etr = load_etr(directory)

    actual = {}
    for r in P.load_players(args.year):
        if int(r["week"]) == args.week and r["position"] in P.ALL_POSITIONS:
            actual[A.norm(r.get("player_display_name") or r.get("player_name", ""))] = \
                P.actual_points(r)
    if not actual:
        sys.exit(f"  no actual stats for week {args.week} yet -- refresh "
                 f"stats_player_week_{args.year}.csv after the games.")

    table = []
    for k in set().union(*[set(v) for v in src.values()]):
        vals = [v[k][0] for v in src.values() if k in v]
        if k not in actual or len(vals) < MIN_SOURCES:
            continue
        cons = sum(vals) / len(vals)
        if cons < MIN_CONS:
            continue
        row = {"a": actual[k], "consensus": cons, "ETR": etr.get(k),
               "pos": pos_of.get(k, ""), "name": k}
        row.update({f"OURS {n}": v.get(k) for n, v in ours.items()})
        row.update({s: v[k][0] for s, v in src.items() if k in v})
        table.append(row)

    print(f"\n  week {args.week} scoreboard -- {len(table)} fantasy-relevant players "
          f"(consensus {MIN_CONS:.0f}+, {MIN_SOURCES}+ sources)")
    print(f"  ours from {', '.join(used)}; sources from {label}\n")
    print(f"  {'projection':<26}{'n':>5}{'RMSE':>8}{'MAE':>7}{'bias':>8}")
    res = []
    for key in ["consensus"] + vkeys + ["ETR"] + list(src):
        v = [(r[key], r["a"]) for r in table if r.get(key) is not None]
        if len(v) < 0.6 * len(table):
            continue
        rmse = math.sqrt(sum((p - a) ** 2 for p, a in v) / len(v))
        mae = st.mean(abs(p - a) for p, a in v)
        res.append((rmse, key, len(v), mae, st.mean(p - a for p, a in v)))
    for rmse, key, n, mae, bias in sorted(res):
        print(f"  {key:<26}{n:>5}{rmse:>8.2f}{mae:>7.2f}{bias:>+8.2f}")
    print("\n  n differs where a source did not project a player; lower RMSE is better,")
    print("  bias above 0 means that projection ran high.\n")

    # by position, and the elite tiers the test versions were built for
    groups = [(p, lambda r, p=p: r["pos"] == p) for p in ("QB", "RB", "WR", "TE")]
    groups += [("QB cons 18+", lambda r: r["pos"] == "QB" and r["consensus"] >= 18),
               ("WR cons 12+", lambda r: r["pos"] == "WR" and r["consensus"] >= 12)]
    keys = ["consensus"] + vkeys + (["ETR"] if etr else [])
    print(f"  {'RMSE (bias)':<14}{'n':>4}" + "".join(f"{k:>18}" for k in keys))
    for glabel, f in groups:
        g = [r for r in table if f(r) and all(r.get(k) is not None for k in keys)]
        if not g:
            continue
        cells = []
        for k in keys:
            rm = math.sqrt(st.mean((r[k] - r["a"]) ** 2 for r in g))
            cells.append(f"{rm:.2f} ({st.mean(r[k] - r['a'] for r in g):+.2f})")
        print(f"  {glabel:<14}{len(g):>4}" + "".join(f"{c:>18}" for c in cells))

    # ranking order: did we put the players in the right ORDER, whatever the
    # point levels? (rank correlation, 1.0 = perfect order) and start/sit
    # pairs (two players at a position: how often the one ranked higher
    # actually scored more)
    def ranks(xs):
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        out = [0.0] * len(xs)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
                j += 1
            for m in range(i, j + 1):
                out[order[m]] = (i + j) / 2
            i = j + 1
        return out

    def corr(xs, ys):
        mx, my = st.mean(xs), st.mean(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den = math.sqrt(sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys))
        return num / den if den else 0.0

    print(f"\n  {'rank order':<14}{'n':>4}" + "".join(f"{k:>18}" for k in keys))
    for glabel, f in groups[:4]:
        g = [r for r in table if f(r) and all(r.get(k) is not None for k in keys)]
        if len(g) < 5:
            continue
        ra = ranks([r["a"] for r in g])
        cells = []
        for k in keys:
            rho = corr(ranks([r[k] for r in g]), ra)
            pairs = right = 0
            for i in range(len(g)):
                for j in range(i + 1, len(g)):
                    if g[i][k] == g[j][k] or g[i]["a"] == g[j]["a"]:
                        continue
                    pairs += 1
                    right += (g[i][k] > g[j][k]) == (g[i]["a"] > g[j]["a"])
            cells.append(f"{rho:.2f} / {right / pairs:.0%}" if pairs else f"{rho:.2f}")
        print(f"  {glabel:<14}{len(g):>4}" + "".join(f"{c:>18}" for c in cells))
    print("  rank correlation / start-sit pairs called right (higher is better)")

    # head-to-head, only where the versions differ by 0.3+ points
    cur = vkeys[0]
    for other in vkeys[1:]:
        d = [r for r in table if r.get(cur) is not None and r.get(other) is not None
             and abs(r[cur] - r[other]) >= 0.3]
        wins = sum(abs(r[other] - r["a"]) < abs(r[cur] - r["a"]) for r in d)
        print(f"\n  {other} vs {cur}: they differ on {len(d)} players; "
              f"{other[5:]} was closer on {wins}, {cur[5:]} on {len(d) - wins}")
        for r in sorted(d, key=lambda r: -abs(r[cur] - r[other]))[:12]:
            print(f"    {r['name']:<24}{r['pos']:<4}{cur[5:]} {r[cur]:5.1f}   "
                  f"{other[5:]} {r[other]:5.1f}   actual {r['a']:5.1f}")
    print()


if __name__ == "__main__":
    main()
