"""QB carries split three ways -- designed runs, scrambles, kneel-downs.

Joe 2026-11-04: "would it be important to figure out avg number of rushes by
designed runs and scrambles. I would think designed runs is more predictable
than scrambles" + "is a scramble considered a pass play in the run-pass split".

Starter games only (the QB with the most dropbacks, 15+). 2023-2026 REG.
"""
import collections, os, sys
import numpy as np
import pandas as pd

ROOT = r"C:\Users\jbond\OneDrive\Documents\FF_ADP"
PBP = os.path.join(ROOT, "ff_utilization", "cached", "nflverse", "pbp_{}.csv")
DATA = os.path.join(ROOT, "ff_weekly_model", "data")
YEARS = [2023, 2024, 2025, 2026]
COLS = ["game_id", "season_type", "week", "posteam", "play_type", "qb_dropback",
        "qb_kneel", "qb_scramble", "two_point_attempt", "passer_player_id",
        "rusher_player_id", "rushing_yards", "result", "home_team"]

games = []          # one row per starter game
check = []
for yr in YEARS:
    df = pd.read_csv(PBP.format(yr), usecols=COLS, low_memory=False)
    df = df[(df.season_type == "REG") & (df.two_point_attempt.fillna(0) != 1)]
    df = df[df.play_type.isin(["pass", "run", "qb_kneel"])]
    st = pd.read_csv(os.path.join(DATA, f"stats_player_week_{yr}.csv"), low_memory=False)
    st = st[st.season_type == "REG"]
    qbs = set(st.loc[st.position == "QB", "player_id"])
    names = dict(zip(st.player_id, st.player_display_name))
    carries_line = {(r.player_id, int(r.week)): r.carries for r in st[st.position == "QB"].itertuples()}
    df["db"] = (df.qb_dropback == 1) & df.play_type.isin(["pass", "run"])
    df["who_db"] = np.where(df.passer_player_id.notna(), df.passer_player_id, df.rusher_player_id)
    df["scr"] = (df.play_type == "run") & (df.qb_scramble == 1)
    df["des"] = (df.play_type == "run") & (df.qb_scramble != 1) & df.rusher_player_id.isin(qbs)
    df["knl"] = df.play_type == "qb_kneel"
    df["run_all"] = (df.play_type == "run") & ~df.scr        # every designed run, any player
    for (gid, tm), g in df.groupby(["game_id", "posteam"]):
        dbs = g[g.db].groupby("who_db").size()
        dbs = dbs[dbs.index.isin(qbs)]
        if dbs.empty or dbs.max() < 15:
            continue
        q = dbs.idxmax()
        wk = int(g.week.iloc[0])
        mine = g.rusher_player_id == q
        des, scr = g[g.des & mine], g[g.scr & mine]
        knl = g[g.knl & ((g.rusher_player_id == q) | g.rusher_player_id.isna())]
        res = g.result.iloc[0]
        margin = res if g.home_team.iloc[0] == tm else -res
        games.append(dict(year=yr, week=wk, team=tm, qb=q, name=names.get(q, q),
                          db=int(dbs.max()), team_db=int(g.db.sum()),
                          team_runs=int(g.run_all.sum()),
                          des=len(des), des_y=des.rushing_yards.sum(),
                          scr=len(scr), scr_y=scr.rushing_yards.sum(),
                          knl=len(knl), knl_y=knl.rushing_yards.sum(), margin=margin))
        cl = carries_line.get((q, wk))
        if cl is not None:
            check.append((cl, len(des) + len(scr) + len(knl)))
G = pd.DataFrame(games)
G["car"] = G.des + G.scr + G.knl
c = np.array(check)
print(f"starter games: {len(G)}   stat-line carries match designed+scramble+kneel in "
      f"{(c[:, 0] == c[:, 1]).mean():.0%} of games (mean gap {np.mean(c[:, 0] - c[:, 1]):+.2f})")

# ---- A. what a QB carry is
print("\nA. A STARTER'S CARRIES PER GAME (2023-26)")
mob = G.groupby(["year", "qb"]).car.transform("mean") >= 5
for lab, s in (("all starters", G), ("runners (5+ a game that season)", G[mob])):
    n = len(s)
    print(f"  {lab:34s} n={n:4d}  designed {s.des.mean():.2f} ({s.des_y.sum()/max(s.des.sum(),1):.1f} ypc)"
          f"  scrambles {s.scr.mean():.2f} ({s.scr_y.sum()/max(s.scr.sum(),1):.1f} ypc)"
          f"  kneels {s.knl.mean():.2f} ({s.knl_y.sum()/max(s.knl.sum(),1):.1f})")
    tot = s.des_y.sum() + s.scr_y.sum() + s.knl_y.sum()
    print(f"  {'':34s} all carries {s.car.mean():.2f} at {tot/s.car.sum():.2f} ypc;"
          f" without kneels {(s.des_y.sum()+s.scr_y.sum())/(s.des.sum()+s.scr.sum()):.2f}")
print(f"  scrambles per dropback: all {G.scr.sum()/G.db.sum():.3f}, runners {G[mob].scr.sum()/G[mob].db.sum():.3f}")

# ---- B. split-half: how much of the gap between QBs is real
print("\nB. SAME QB, ODD vs EVEN STARTS OF A SEASON (8+ starts): correlation across QBs")
rows = []
for (yr, q), s in G.groupby(["year", "qb"]):
    if len(s) < 8:
        continue
    s = s.sort_values("week")
    a, b = s.iloc[0::2], s.iloc[1::2]
    rows.append([a.des.mean(), b.des.mean(), a.scr.mean(), b.scr.mean(),
                 a.scr.sum() / a.db.sum(), b.scr.sum() / b.db.sum(), a.knl.mean(), b.knl.mean(),
                 a.car.mean(), b.car.mean(),
                 a.des_y.sum() / max(a.des.sum(), 1), b.des_y.sum() / max(b.des.sum(), 1),
                 a.scr_y.sum() / max(a.scr.sum(), 1), b.scr_y.sum() / max(b.scr.sum(), 1)])
R = np.array(rows)
for i, lab in enumerate(["designed runs a game", "scrambles a game", "scrambles per dropback",
                         "kneels a game", "all carries a game", "designed ypc", "scramble ypc"]):
    print(f"  {lab:24s} r = {np.corrcoef(R[:, 2*i], R[:, 2*i+1])[0, 1]:.2f}   (QB-seasons {len(R)})")

# ---- C. next game from his earlier starts (last 17, both seasons, 4+)
print("\nC. NEXT GAME FROM HIS EARLIER STARTS (last 17 starts, 4+ needed), 2024-26")
G = G.sort_values(["qb", "year", "week"]).reset_index(drop=True)
lg = {k: G[k].mean() for k in ("des", "scr", "knl", "car")}
lg_rate = G.scr.sum() / G.db.sum()
pred = []
for q, s in G.groupby("qb"):
    s = s.reset_index(drop=True)
    for i in range(len(s)):
        if s.year[i] < 2024:
            continue
        p = s.iloc[max(0, i - 17):i]
        p = p[p.year >= s.year[i] - 1]
        if len(p) < 4:
            continue
        pred.append(dict(year=s.year[i], n=len(p), des_p=p.des.sum(), scr_p=p.scr.sum(), db_p=p.db.sum(),
                         knl_p=p.knl.sum(), car_p=p.car.sum(), db_avg=p.db.mean(),
                         des=s.des[i], scr=s.scr[i], knl=s.knl[i], car=s.car[i], db=s.db[i]))
P = pd.DataFrame(pred)


def shr(tot, n, lgv, k):
    return (tot + k * lgv) / (n + k)


def best_k(f, act):
    out = []
    for k in (0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 50):
        out.append((np.sqrt(np.mean((f(k) - act) ** 2)), k))
    return min(out)


for lab, tot, lgv, act in (("designed runs", "des_p", lg["des"], "des"),
                           ("scrambles", "scr_p", lg["scr"], "scr"),
                           ("kneels", "knl_p", lg["knl"], "knl"),
                           ("all carries", "car_p", lg["car"], "car")):
    e, k = best_k(lambda k: shr(P[tot], P.n, lgv, k), P[act])
    f = shr(P[tot], P.n, lgv, k)
    r = np.corrcoef(f, P[act])[0, 1]
    print(f"  {lab:14s} avg {P[act].mean():.2f}  miss (RMSE) {e:.2f}  = {e/P[act].mean():.0%} of avg;"
          f"  r {r:.2f}; best pull to league = {k} games")

# ---- D. game script: within the same QB-season
print("\nD. GAME SCRIPT (each QB-season's own average taken out)")
H = G.copy()
for k in ("des", "scr", "db", "team_db", "team_runs", "car"):
    H[k + "_d"] = H[k] - H.groupby(["year", "qb"])[k].transform("mean")
for a, b in (("scr", "db"), ("des", "team_runs"), ("des", "db"), ("car", "db")):
    x, y = H[b + "_d"], H[a + "_d"]
    print(f"  {a:4s} vs {b:9s}: +10 {b} -> {10*np.polyfit(x, y, 1)[0]:+.2f} {a}   r {np.corrcoef(x, y)[0, 1]:+.2f}")
for lab, m in (("won by 10+", H.margin >= 10), ("within 9", H.margin.abs() <= 9), ("lost by 10+", H.margin <= -10)):
    s = H[m]
    print(f"  {lab:12s} n={len(s):4d}: designed {s.des_d.mean():+.2f}  scrambles {s.scr_d.mean():+.2f}"
          f"  kneels {(s.knl - H.knl.mean()).mean():+.2f}  dropbacks {s.db_d.mean():+.1f}")

# ---- E. QB on the injury report going in (2024-26)
print("\nE. QB ON THAT WEEK'S INJURY REPORT (played, 15+ dropbacks) vs his other starts")
lst = {}
for yr in (2024, 2025, 2026):
    ip = os.path.join(DATA, f"injuries_{yr}.csv")
    inj = pd.read_csv(ip, low_memory=False)
    inj = inj[(inj.position == "QB") & (inj.game_type.fillna("REG") == "REG")]
    inj = inj[inj.report_primary_injury.notna() | inj.practice_primary_injury.notna()]
    for r in inj.itertuples():
        st_ = r.report_status if isinstance(r.report_status, str) else ""
        lst[(yr, r.gsis_id, int(r.week))] = st_
H["listed"] = [lst.get((y, q, w)) for y, q, w in zip(H.year, H.qb, H.week)]
H2 = H[H.year >= 2024]
mobq = H2.groupby(["year", "qb"]).car.transform("mean") >= 4
for lab, m in (("listed, no game status", H2.listed == ""),
               ("Questionable/Doubtful", H2.listed.isin(["Questionable", "Doubtful"])),
               ("not listed", H2.listed.isna())):
    for who, mm in (("all", m), ("runners 4+", m & mobq)):
        s = H2[mm]
        print(f"  {lab:24s} {who:10s} n={len(s):4d}: designed {s.des_d.mean():+.2f}  scrambles {s.scr_d.mean():+.2f}"
              f"  dropbacks {s.db_d.mean():+.1f}")

# ---- F. does modelling them apart help? next-game total carries
print("\nF. NEXT-GAME CARRIES: one number vs designed + scrambles apart")
e0, k0 = best_k(lambda k: shr(P.car_p, P.n, lg["car"], k), P.car)
best = None
for kd in (0, 2, 4, 6, 8, 12, 16):
    for ks in (0, 2, 4, 6, 8, 12, 16, 24, 32, 50):
        for kk in (4, 16, 50):
            f = shr(P.des_p, P.n, lg["des"], kd) + shr(P.scr_p, P.n, lg["scr"], ks) + shr(P.knl_p, P.n, lg["knl"], kk)
            e = np.sqrt(np.mean((f - P.car) ** 2))
            if not best or e < best[0]:
                best = (e, kd, ks, kk)
print(f"  one number (k {k0}):                         miss {e0:.3f}")
print(f"  apart (designed k {best[1]}, scrambles k {best[2]}, kneels k {best[3]}): miss {best[0]:.3f}")
# scrambles as a rate per dropback x this game's REAL dropbacks (best case: pass volume known)
for lab, dbx in (("his usual dropbacks", P.db_p / P.n), ("the game's real dropbacks", P.db)):
    bb = None
    for ks in (0, 50, 100, 200, 400, 800):
        f = (shr(P.des_p, P.n, lg["des"], best[1]) + shr(P.scr_p, P.db_p, lg_rate, ks) * dbx
             + shr(P.knl_p, P.n, lg["knl"], best[3]))
        e = np.sqrt(np.mean((f - P.car) ** 2))
        if not bb or e < bb[0]:
            bb = (e, ks)
    print(f"  scrambles per dropback x {lab:25s} miss {bb[0]:.3f} (k {bb[1]} dropbacks)")
for yr in (2024, 2025, 2026):
    m = P.year == yr
    f1 = shr(P.car_p, P.n, lg["car"], k0)
    f2 = shr(P.des_p, P.n, lg["des"], best[1]) + shr(P.scr_p, P.n, lg["scr"], best[2]) + shr(P.knl_p, P.n, lg["knl"], best[3])
    print(f"   {yr}: one number {np.sqrt(np.mean((f1[m]-P.car[m])**2)):.3f}   apart {np.sqrt(np.mean((f2[m]-P.car[m])**2)):.3f}  (n {m.sum()})")

# ---- G. the big runners this season
print("\nG. 2026 STARTERS, 4+ CARRIES A GAME: designed / scrambles / kneels a game")
s = G[G.year == 2026].groupby(["qb", "name"]).agg(g=("des", "size"), des=("des", "mean"), scr=("scr", "mean"),
                                                  knl=("knl", "mean"), car=("car", "mean"),
                                                  dy=("des_y", "sum"), dn=("des", "sum"), sy=("scr_y", "sum"),
                                                  sn=("scr", "sum")).reset_index()
s = s[s.car >= 4].sort_values("car", ascending=False)
for r in s.itertuples():
    print(f"  {r.name:22s} {r.g:2d} g  {r.des:4.1f} des ({r.dy/max(r.dn,1):4.1f} ypc)  {r.scr:4.1f} scr"
          f" ({r.sy/max(r.sn,1):4.1f} ypc)  {r.knl:3.1f} kneel   = {r.car:4.1f}")
G.to_csv(os.path.join(os.path.dirname(__file__), "qb_run_types.csv"), index=False)
