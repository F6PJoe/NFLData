"""Score a played week: our projection vs the props market vs blends (Joe 2026-11-06: "it would be
interesting to see if a 50/50 split of our model and player props did better than just our model").

Players with props, a frozen projection (data/projections_<yr>_wk<NN>_final.csv) and a stat line.
Props = each game's LATEST pull before kickoff (props_compare.week_rows); --first = earliest pull.
Pieces with no prop already use our number, so a blend only moves what the market priced.

    python research/props_score.py --year 2026 --week 9 [--first]
"""
import argparse, csv, os, sys, math, collections
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from props_compare import build_rows
from audit_vs_sources import norm

def actual(r, pos):
    f = lambda k: float(r.get(k) or 0)
    if pos == "QB":
        return (.04 * f("passing_yards") + 4 * f("passing_tds") - 2 * f("passing_interceptions")
                + .1 * f("rushing_yards") + 6 * f("rushing_tds") - 2 * f("rushing_fumbles_lost") - 2 * f("sack_fumbles_lost"))
    return (.5 * f("receptions") + .1 * (f("receiving_yards") + f("rushing_yards")) + 6 * (f("receiving_tds") + f("rushing_tds"))
            - 2 * (f("rushing_fumbles_lost") + f("receiving_fumbles_lost")))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True); ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--first", action="store_true"); ap.add_argument("--min", type=float, default=5.0)
    a = ap.parse_args()
    fin = os.path.join(HERE, "data", f"projections_{a.year}_wk{a.week:02d}_final.csv")
    rows, snap = build_rows(a.year, a.week, first=a.first, proj_path=fin)
    act = {}
    for r in csv.DictReader(open(os.path.join(HERE, "data", f"stats_player_week_{a.year}.csv"), encoding="utf-8")):
        if r["week"] == str(a.week) and r.get("season_type", "REG") == "REG":
            act[norm(r["player_display_name"])] = r
    g = []
    for r in rows:
        s = act.get(norm(r["player"]))
        if s is None or max(r["ours"], r["props"], r["cons"]) < a.min:
            continue
        r["act"] = actual(s, r["pos"]); r["s"] = s; g.append(r)
    W = (0, .25, .5, .75, 1)
    rmse = lambda xs: math.sqrt(sum(x * x for x in xs) / len(xs)) if xs else float("nan")
    print(f"  week {a.week}: {len(g)} players (with props, {a.min}+ pts by us, props or consensus, played)")
    print(f"  props: {snap}\n")
    print(f"  {'':6}{'n':>4}  " + "  ".join(f"{'ours' if w == 0 else 'props' if w == 1 else f'{int(w*100)}% props':>9}" for w in W) + "  consensus")
    for pos in ("ALL", "QB", "RB", "WR", "TE"):
        h = [r for r in g if pos == "ALL" or r["pos"] == pos]
        if not h: continue
        vals = [rmse([(1 - w) * r["ours"] + w * r["props"] - r["act"] for r in h]) for w in W]
        c = rmse([r["cons"] - r["act"] for r in h if r["cons"]])
        print(f"  {pos:6}{len(h):>4}  " + "  ".join(f"{v:9.2f}" for v in vals) + f"  {c:9.2f}")
    print("\n  RMSE by stat (ours vs props) -- players whose prop covered that stat")
    keymap = {"rec": "receptions", "rec yds": "receiving_yards", "rush yds": "rushing_yards", "pass yds": "passing_yards",
              "pass TD": "passing_tds"}
    for k, col in keymap.items():
        h = [r for r in g if k in r["stats"] and abs(r["stats"][k][0] - r["stats"][k][1]) > 1e-9]
        if h:
            ao = [r["stats"][k][0] - float(r["s"].get(col) or 0) for r in h]; ap_ = [r["stats"][k][1] - float(r["s"].get(col) or 0) for r in h]
            print(f"    {k:9} n={len(h):3}  ours {rmse(ao):6.2f}  props {rmse(ap_):6.2f}  bias ours {sum(ao)/len(ao):+.2f} props {sum(ap_)/len(ap_):+.2f}")
    h = [r for r in g if r["has_td"]]
    tdk = lambda r: "rush TD" if r["pos"] == "QB" else "TD"
    tda = lambda r: float(r["s"].get("rushing_tds") or 0) + (0 if r["pos"] == "QB" else float(r["s"].get("receiving_tds") or 0))
    print(f"    {'TDs':9} n={len(h):3}  ours {rmse([r['stats'][tdk(r)][0]-tda(r) for r in h]):6.2f}  props {rmse([r['stats'][tdk(r)][1]-tda(r) for r in h]):6.2f}")
    print("\n  biggest swings (|ours - props| >= 3): who was closer")
    for r in sorted((r for r in g if abs(r["ours"] - r["props"]) >= 3), key=lambda r: -abs(r["ours"] - r["props"])):
        win = "props" if abs(r["props"] - r["act"]) < abs(r["ours"] - r["act"]) else "ours"
        print(f"    {r['player']:24}{r['pos']:3} ours {r['ours']:5.1f}  props {r['props']:5.1f}  cons {r['cons']:5.1f}  actual {r['act']:5.1f}  -> {win}")

if __name__ == "__main__":
    main()
