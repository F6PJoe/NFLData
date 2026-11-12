"""Joe's published RANKINGS vs the model's projections, as rankings, against how players finished.

Joe 2026-11-05: "the model and the rankings are waaaaay off in quite a few spots ... Ideally these
projections become my rankings in the future too so they need to be really really good."

For each week: the players in Joe's published top N at a position (ff_rankings/weekly/<yr>-wkNN/
NFL_<yr>_Week_N_Half_PPR_Weekly_Rankings.csv) who played, ranked three ways --
  rankings : Joe's published order
  model    : the model as PUBLISHED that week (data/projections_<yr>_wkNN_final.csv)
  today    : today's model rerun on that week (a backtest dump; knows who played -- flattering)
-- and scored against their actual half-PPR finish within the same group:
  rho      : rank correlation with actual points (higher = better order)
  big gaps : players whose model and rankings ranks differ by GAP+ spots -- whose rank was closer
             to where he actually finished

    python research/rank_check.py --dump <today's 2026 backtest dump> [--weeks 4-8] [--gap 5]
"""
import argparse, csv, collections, os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
from audit_vs_sources import norm
DATA = os.path.join(HERE, "data")
RK = os.path.join(os.path.dirname(HERE), "ff_rankings", "weekly")
TOPN = {"QB": 24, "RB": 36, "WR": 48, "TE": 24}
f = lambda r, k: float((r or {}).get(k) or 0)


def actual_pts(r):
    if r["position"] == "QB":
        return (f(r, "passing_yards") * .04 + f(r, "passing_tds") * 4 - f(r, "passing_interceptions") * 2
                + f(r, "rushing_yards") * .1 + f(r, "rushing_tds") * 6)
    return (f(r, "receptions") * .5 + f(r, "receiving_yards") * .1 + f(r, "receiving_tds") * 6
            + f(r, "rushing_yards") * .1 + f(r, "rushing_tds") * 6)


def ranks(vals):
    """value list -> rank list (1 = best), ties averaged."""
    order = sorted(range(len(vals)), key=lambda i: -vals[i])
    out = [0.0] * len(vals)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
            j += 1
        for k in range(i, j + 1):
            out[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return out


def spearman(a, b):
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = sum((x - ma) ** 2 for x in ra) ** .5
    vb = sum((y - mb) ** 2 for y in rb) ** .5
    return cov / (va * vb) if va and vb else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--weeks", default="4-8")
    ap.add_argument("--dump", required=True)
    ap.add_argument("--gap", type=int, default=5)
    a = ap.parse_args()
    w0, w1 = (int(x) for x in a.weeks.split("-"))
    act = {}
    for r in csv.DictReader(open(os.path.join(DATA, f"stats_player_week_{a.year}.csv"), encoding="utf-8")):
        if r.get("season_type", "REG") == "REG":
            act[(int(r["week"]), norm(r["player_display_name"]))] = actual_pts(r)
    today = {}
    for r in csv.DictReader(open(a.dump, encoding="utf-8")):
        today[(int(r["week"]), norm(r["player"]))] = float(r["proj"])
    tot = collections.defaultdict(lambda: collections.defaultdict(list))
    gaps = collections.defaultdict(list)
    for w in range(w0, w1 + 1):
        p = os.path.join(RK, f"{a.year}-wk{w:02d}", f"NFL_{a.year}_Week_{w}_Half_PPR_Weekly_Rankings.csv")
        if not os.path.exists(p):
            continue
        rows = list(csv.reader(open(p, encoding="utf-8-sig")))
        head = rows[0]
        fin = {}
        for r in csv.DictReader(open(os.path.join(DATA, f"projections_{a.year}_wk{w:02d}_final.csv"), encoding="utf-8-sig")):
            fin[norm(r["player"])] = float(r["half_ppr"] or 0)
        for i in range(0, len(head), 7):
            pos = head[i]
            if pos not in TOPN:
                continue
            names = [norm(r[i]) for r in rows[2:] if i < len(r) and r[i].strip()][:TOPN[pos]]
            grp = [n for n in names if (w, n) in act and n in fin and (w, n) in today]
            if len(grp) < 8:
                continue
            rk_val = [-(names.index(n)) for n in grp]                   # published order
            mo_val = [fin[n] for n in grp]
            td_val = [today[(w, n)] for n in grp]
            ac_val = [act[(w, n)] for n in grp]
            for lab, v in (("rankings", rk_val), ("model", mo_val), ("today", td_val)):
                tot[pos][lab].append(spearman(v, ac_val))
            r_rk, r_mo, r_td, r_ac = ranks(rk_val), ranks(mo_val), ranks(td_val), ranks(ac_val)
            for k, n in enumerate(grp):
                if abs(r_mo[k] - r_rk[k]) >= a.gap:
                    gaps[pos].append((w, n, r_rk[k], r_mo[k], r_td[k], r_ac[k]))
    print(f"rank correlation with actual finish (avg over weeks {w0}-{w1}; 1.0 = perfect order)")
    for pos in TOPN:
        if pos in tot:
            t = tot[pos]
            print(f"  {pos}  (top {TOPN[pos]}, {len(t['rankings'])} weeks)  rankings {sum(t['rankings'])/len(t['rankings']):.3f}"
                  f"   model as published {sum(t['model'])/len(t['model']):.3f}   today's model {sum(t['today'])/len(t['today']):.3f}")
    print(f"\nplayers where the PUBLISHED model and the rankings differ by {a.gap}+ spots -- whose rank was closer to his finish")
    for pos, g in gaps.items():
        n = len(g)
        win_m = sum(1 for _, _, rk, mo, td, ac in g if abs(mo - ac) < abs(rk - ac))
        win_r = sum(1 for _, _, rk, mo, td, ac in g if abs(rk - ac) < abs(mo - ac))
        win_t = sum(1 for _, _, rk, mo, td, ac in g if abs(td - ac) < abs(rk - ac))
        e = lambda i: sum(abs(x[i] - x[5]) for x in g) / n
        print(f"  {pos}: {n} player-weeks | rankings closer {win_r}, model closer {win_m} | avg rank miss: rankings {e(2):.1f}, "
              f"model {e(3):.1f}, today's model {e(4):.1f} (today closer than rankings {win_t})")


if __name__ == "__main__":
    main()
