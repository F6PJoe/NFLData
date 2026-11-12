#!/usr/bin/env python3
"""Our projections vs what the player-prop market implies (a benchmark -- never copied).

    python props_compare.py --year 2026 --week 9 [--snapshot data/props/<file>.csv]

Joe 2026-11-05: "pull this week's props to see what you can do with it". Each prop is turned
into an EXPECTED stat (what fantasy points use), not left as the 50/50 line:
  yards / catches  per book: no-vig chance of the over -> the 50/50 point (lognormal spread for
                   yards), median across books, then x the average-over-median ratio measured
                   on our own 2024-26 player-weeks at that size (yards outcomes are lopsided --
                   a 30-yard receiving line averages ~36)
  pass TDs         no-vig over/under at 0.5 / 1.5 / 2.5 -> the Poisson average that fits
  anytime TD       no-vig chance of a TD -> expected TDs (Poisson)
Missing pieces (a WR's rushing, a QB's INTs, a player with no TD prop) take our own number.
Writes "Week N Props vs Model.xlsx" next to the rankings files.
"""
import argparse, collections, csv, glob, math, os, statistics as st, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from audit_vs_sources import norm

# average / 50-50 point, by the 50/50 point's size (2024-26 player-weeks, our backtest)
RATIO = {"player_reception_yds": [(25, 1.35), (40, 1.20), (55, 1.15), (70, 1.07), (1e9, 1.06)],
         "player_rush_yds_RB": [(35, 1.30), (55, 1.16), (75, 1.06), (1e9, 1.08)],
         "player_rush_yds_QB": [(15, 1.50), (25, 1.22), (1e9, 1.15)],
         "player_pass_yds": [(1e9, 1.00)],
         "player_receptions": [(1e9, 1.03)]}
SIGMA = {"player_reception_yds": 0.7, "player_rush_yds": 0.6, "player_pass_yds": 0.25}


def imp(price):
    price = float(price)
    return 100 / (price + 100) if price > 0 else -price / (-price + 100)


def z(p):          # standard normal quantile (Acklam-free bisection; fine for this)
    lo, hi = -6.0, 6.0
    for _ in range(60):
        m = (lo + hi) / 2
        if 0.5 * math.erfc(-m / math.sqrt(2)) < p:
            lo = m
        else:
            hi = m
    return (lo + hi) / 2


def ratio(key, m):
    for cut, r in RATIO[key]:
        if m < cut:
            return r
    return 1.0


def poisson_mean(line, p_over):
    k = int(math.floor(line)) + 1                 # over = at least k
    lo, hi = 0.001, 8.0
    for _ in range(60):
        lam = (lo + hi) / 2
        p = 1 - sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k))
        lo, hi = (lam, hi) if p < p_over else (lo, lam)
    return (lo + hi) / 2


def week_rows(year, week, which="latest"):
    """Prop rows for the week: each game from its LATEST snapshot (or its FIRST, which="first"),
    so pregame pulls of one slot don't drop the other games. Returns (rows, files used)."""
    files = sorted(glob.glob(os.path.join(HERE, "data", "props", f"{year}_wk{week:02d}_*.csv")))
    if which == "first":
        files = files[::-1]
    per_game, used = {}, set()
    for p in files:                                   # later files overwrite earlier ones
        g = collections.defaultdict(list)
        for r in csv.DictReader(open(p, encoding="utf-8")):
            g[r["game"]].append(r)
        for name, rs in g.items():
            per_game[name] = (p, rs)
    rows = []
    for p, rs in per_game.values():
        rows += rs; used.add(os.path.basename(p))
    return rows, sorted(used)


def market_values(path_or_rows):
    """player -> {market: expected value}, and player -> game."""
    by = collections.defaultdict(lambda: collections.defaultdict(lambda: collections.defaultdict(dict)))
    game = {}
    src = csv.DictReader(open(path_or_rows, encoding="utf-8")) if isinstance(path_or_rows, str) else path_or_rows
    for r in src:
        p = r["player"]
        game[p] = r["game"]
        by[p][r["market"]][(r["book"], r["line"])][r["side"]] = r["price"]
    out = {}
    for p, mk in by.items():
        v = {}
        for m, books in mk.items():
            ests = []
            for (book, line), sides in books.items():
                if m == "player_anytime_td":
                    y = sides.get("Yes")
                    if y is None:
                        continue
                    n = sides.get("No")
                    pr = imp(y) / (imp(y) + imp(n)) if n else imp(y) / 1.08
                    pr = min(max(pr, 0.001), 0.95)
                    ests.append(-math.log(1 - pr))
                    continue
                if "Over" not in sides or "Under" not in sides or line == "":
                    continue
                L = float(line)
                po = imp(sides["Over"]) / (imp(sides["Over"]) + imp(sides["Under"]))
                if m == "player_pass_tds":
                    ests.append(poisson_mean(L, po))
                elif m == "player_receptions":
                    ests.append(L + z(po) * 1.2)
                else:
                    ests.append(L * math.exp(SIGMA.get(m, 0.6) * z(po)))
            if ests:
                v[m] = st.median(ests)
        out[p] = v
    return out, game


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--snapshot", help="one snapshot file (default: each game's latest pull)")
    ap.add_argument("--first", action="store_true", help="each game's earliest pull instead")
    a = ap.parse_args()
    rows, snap = build_rows(a.year, a.week, a.snapshot, a.first)
    write(rows, a, snap)


def build_rows(year, week, snapshot=None, first=False, proj_path=None):
    """[{pos, player, team, ours, props, cons, stats, cover, has_td}] for players with any prop, and
    the snapshot description. 'props' = half-PPR points with every piece that has a prop taken
    from the market and every piece without one taken from our projection."""
    a = argparse.Namespace(year=year, week=week, snapshot=snapshot, first=first)
    if a.snapshot:
        snap = a.snapshot
        mv, game = market_values(snap)
    else:
        rws, used = week_rows(a.year, a.week, "first" if a.first else "latest")
        snap = ", ".join(used)
        mv, game = market_values(rws)
    f = lambda r, k: float(r.get(k) or 0)
    ours = {}
    for r in csv.DictReader(open(proj_path or os.path.join(HERE, "data", f"projections_{a.year}_wk{a.week:02d}.csv"), encoding="utf-8-sig")):
        ours.setdefault(norm(r["player"]), []).append(r)
    rows = []
    for p, v in mv.items():
        cand = ours.get(norm(p), [])
        if len(cand) != 1:
            continue
        o = cand[0]
        pos = o["pos"]
        if f(o, "half_ppr") <= 0:
            continue
        def mean_of(m, ours_val):
            if m not in v:
                return ours_val, False
            key = m if m != "player_rush_yds" else f"player_rush_yds_{'QB' if pos == 'QB' else 'RB'}"
            return v[m] * (ratio(key, v[m]) if key in RATIO else 1.0), True
        ry, h_ry = mean_of("player_rush_yds", f(o, "rush_yds"))
        td, h_td = (v["player_anytime_td"], True) if "player_anytime_td" in v else (f(o, "rush_td") + f(o, "rec_td"), False)
        if pos == "QB":
            py, h_py = mean_of("player_pass_yds", f(o, "pass_yds"))
            ptd, h_ptd = (v["player_pass_tds"], True) if "player_pass_tds" in v else (f(o, "pass_td"), False)
            pts = .04 * py + 4 * ptd - 2 * f(o, "pass_int") + .1 * ry + 6 * td
            stats = {"pass yds": (f(o, "pass_yds"), py), "pass TD": (f(o, "pass_td"), ptd),
                     "rush yds": (f(o, "rush_yds"), ry), "rush TD": (f(o, "rush_td"), td)}
            cover = sum((h_py, h_ptd, h_ry, h_td))
        else:
            ryd, h_ryd = mean_of("player_reception_yds", f(o, "rec_yds"))
            rec, h_rec = mean_of("player_receptions", f(o, "rec"))
            pts = .5 * rec + .1 * (ryd + ry) + 6 * td
            stats = {"rec": (f(o, "rec"), rec), "rec yds": (f(o, "rec_yds"), ryd),
                     "rush yds": (f(o, "rush_yds"), ry), "TD": (f(o, "rec_td") + f(o, "rush_td"), td)}
            cover = sum((h_ryd, h_rec, h_td)) + (1 if h_ry else 0)
        rows.append({"pos": pos, "player": o["player"], "team": o["team"], "ours": f(o, "half_ppr"),
                     "props": pts, "cons": f(o, "consensus"), "stats": stats, "cover": cover, "has_td": h_td})
    # TD props carry extra book margin on "Yes" (summed per game they run ~10-25% over the
    # betting totals), so each TEAM's prop TDs are scaled to our team's TDs for the same players:
    # the market decides WHO scores, the game lines how many
    tm_o, tm_p = collections.defaultdict(float), collections.defaultdict(float)
    for r in rows:
        if r["has_td"]:
            k = "rush TD" if r["pos"] == "QB" else "TD"
            tm_o[r["team"]] += r["stats"][k][0]; tm_p[r["team"]] += r["stats"][k][1]
    for r in rows:
        if r["has_td"] and tm_p[r["team"]] > 0:
            k = "rush TD" if r["pos"] == "QB" else "TD"
            o_, p_ = r["stats"][k]
            p2 = p_ * tm_o[r["team"]] / tm_p[r["team"]]
            r["stats"][k] = (o_, p2)
            r["props"] += 6 * (p2 - p_)
    return rows, snap


def write(rows, a, snap):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "Props vs Model"
    hf, hfill = Font(name="Arial", bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E78")
    bf = Font(name="Arial", size=10)
    hi, lo = PatternFill("solid", fgColor="C6EFCE"), PatternFill("solid", fgColor="FFC7CE")
    ws.cell(1, 1, f"Week {a.week} -- our projections vs what the prop market implies (half PPR)").font = Font(name="Arial", size=12, bold=True)
    ws.cell(2, 1, f"Props snapshot {os.path.basename(snap)}. Prop lines turned into averages (not the 50/50 line); "
                  "pieces with no prop use our number. Diff = ours - props: green = we're higher, red = lower (2+ pts). "
                  "Rank diff = props rank - our rank (+ = we rank him higher).").font = Font(name="Arial", size=9, italic=True)
    col = 1
    print(f"  snapshot {os.path.basename(snap)}")
    for pos in ("QB", "RB", "WR", "TE"):
        g = [r for r in rows if r["pos"] == pos and r["cover"] >= 2]
        g.sort(key=lambda r: -r["ours"])
        rp = {id(r): i + 1 for i, r in enumerate(sorted(g, key=lambda r: -r["props"]))}
        skeys = list(g[0]["stats"]) if g else []
        heads = ["Player", "Team", "Ours", "Props", "Diff", "Our rk", "Props rk", "Rk diff"] + \
                [f"{k} ours/props" for k in skeys]
        ws.cell(4, col, pos).font = Font(name="Arial", size=11, bold=True)
        for j, h in enumerate(heads):
            c = ws.cell(5, col + j, h); c.font, c.fill = hf, hfill
            c.alignment = Alignment(horizontal="center", wrap_text=True)
        for i, r in enumerate(g):
            d = r["ours"] - r["props"]
            vals = [r["player"], r["team"], round(r["ours"], 2), round(r["props"], 2), round(d, 2), i + 1, rp[id(r)],
                    rp[id(r)] - (i + 1)] + [f"{x:.1f} / {y:.1f}" if k not in ("TD", "pass TD", "rush TD") else f"{x:.2f} / {y:.2f}"
                                            for k, (x, y) in r["stats"].items()]
            for j, v in enumerate(vals):
                c = ws.cell(6 + i, col + j, v); c.font = bf
                if j >= 2: c.alignment = Alignment(horizontal="center")
            if abs(d) >= 2:
                ws.cell(6 + i, col + 4).fill = hi if d > 0 else lo
        for j, w in enumerate([22, 5, 7, 7, 6, 6, 7, 6] + [14] * len(skeys)):
            ws.column_dimensions[get_column_letter(col + j)].width = w
        col += len(heads) + 1
        if g:
            n = len(g)
            mo = sum(r["ours"] for r in g) / n; mp = sum(r["props"] for r in g) / n
            top = [r for r in g if r["ours"] >= 8 or r["props"] >= 8]
            gap = sum(abs(r["ours"] - r["props"]) for r in top) / max(len(top), 1)
            cgap = sum(abs(r["cons"] - r["props"]) for r in top if r["cons"]) / max(sum(1 for r in top if r["cons"]), 1)
            print(f"  {pos}: {n} players | avg ours {mo:.2f} vs props {mp:.2f} | 8+ pt players: avg gap ours-props {gap:.2f}, "
                  f"consensus-props {cgap:.2f} (n {len(top)})")
            big = sorted(top, key=lambda r: -abs(r["ours"] - r["props"]))[:6]
            print("     biggest: " + "; ".join(f"{r['player']} {r['ours']:.1f} vs {r['props']:.1f}" for r in big))
    ws.freeze_panes = "A6"
    out = os.path.join(HERE, "site_rankings", f"{a.year}-wk{a.week:02d}", f"Week {a.week} Props vs Model.xlsx")
    wb.save(out)
    print("  ->", out)


if __name__ == "__main__":
    main()
