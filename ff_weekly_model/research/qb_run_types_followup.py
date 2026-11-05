"""Follow-up: where the 'apart' gain comes from, and rushing YARDS (what scores)."""
import os
import numpy as np
import pandas as pd

G = pd.read_csv(os.path.join(os.path.dirname(__file__), "qb_run_types.csv"))
G["car"] = G.des + G.scr + G.knl
G["yds"] = G.des_y + G.scr_y + G.knl_y
G = G.sort_values(["qb", "year", "week"]).reset_index(drop=True)
lg = {k: G[k].mean() for k in ("des", "scr", "knl", "car", "yds", "des_y", "scr_y", "knl_y")}
lg_ds = (G.des + G.scr).mean()
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
        d = {k + "_p": p[k].sum() for k in ("des", "scr", "knl", "car", "yds", "des_y", "scr_y", "knl_y", "db")}
        d.update({k: s[k][i] for k in ("des", "scr", "knl", "car", "yds", "year")})
        d["n"] = len(p)
        pred.append(d)
P = pd.DataFrame(pred)
sh = lambda t, n, l, k: (t + k * l) / (n + k)
rm = lambda f, a: np.sqrt(np.mean((f - a) ** 2))
ks = (0, 1, 2, 3, 4, 6, 8, 12, 16, 24, 32, 50)

print("CARRIES -- where the gain comes from")
print(f"  one number                      {min(rm(sh(P.car_p, P.n, lg['car'], k), P.car) for k in ks):.3f}")
print(f"  kneels at league avg, rest one  {min(rm(sh(P.des_p + P.scr_p, P.n, lg_ds, k) + lg['knl'], P.car) for k in ks):.3f}")
print(f"  all three apart                 {min(rm(sh(P.des_p, P.n, lg['des'], a) + sh(P.scr_p, P.n, lg['scr'], b) + lg['knl'], P.car) for a in ks for b in ks):.3f}")

print("\nRUSHING YARDS (next game)")
# one: own carries x own ypc (both shrunk)
best1 = min((rm(sh(P.car_p, P.n, lg["car"], k) * sh(P.yds_p, P.car_p, lg["yds"] / lg["car"], ky), P.yds), k, ky)
            for k in (2, 3, 4) for ky in (0, 25, 50, 100, 200, 300, 500))
print(f"  carries x one ypc               {best1[0]:.2f}  (k {best1[1]}, ypc k {best1[2]})")
bd = lg["des_y"] / lg["des"]; bs = lg["scr_y"] / lg["scr"]
best2 = min((rm(sh(P.des_p, P.n, lg["des"], a) * sh(P.des_y_p, P.des_p, bd, kd)
                + sh(P.scr_p, P.n, lg["scr"], b) * sh(P.scr_y_p, P.scr_p, bs, ks_)
                + lg["knl_y"], P.yds), a, b, kd, ks_)
            for a in (1, 2, 3) for b in (1, 2, 3) for kd in (0, 25, 50, 100, 200, 400)
            for ks_ in (0, 25, 50, 100, 200, 400))
print(f"  designed x its ypc + scrambles x its ypc + kneels  {best2[0]:.2f}  (k {best2[1:]})")
print(f"  avg yards {P.yds.mean():.1f}")
for yr in (2024, 2025, 2026):
    m = P.year == yr
    f1 = sh(P.car_p, P.n, lg["car"], best1[1]) * sh(P.yds_p, P.car_p, lg["yds"] / lg["car"], best1[2])
    a, b, kd, ks_ = best2[1:]
    f2 = (sh(P.des_p, P.n, lg["des"], a) * sh(P.des_y_p, P.des_p, bd, kd)
          + sh(P.scr_p, P.n, lg["scr"], b) * sh(P.scr_y_p, P.scr_p, bs, ks_) + lg["knl_y"])
    print(f"   {yr}: one {rm(f1[m], P.yds[m]):.2f}   apart {rm(f2[m], P.yds[m]):.2f}")
