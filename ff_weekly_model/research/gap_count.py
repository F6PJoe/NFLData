"""Big gaps vs consensus, baseline vs variant dumps (2026 wks 3-8): how many fantasy-relevant
player-weeks are 2+ / 3+ points from consensus, avg |gap| vs consensus and FTN, and the miss."""
import csv, sys, os, importlib.util
sys.path.insert(0, "C:/Users/jbond/OneDrive/Documents/FF_ADP/ff_weekly_model")
tags = sys.argv[1:]; sys.argv = sys.argv[:1]
os.chdir("C:/Users/jbond/OneDrive/Documents/FF_ADP/ff_weekly_model")
spec = importlib.util.spec_from_file_location("cc", "research/consensus_closeness.py")
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()):
    cc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cc)
from audit_vs_sources import norm
D = os.environ["DUMPS"]
def load(p): return {(r["player_id"], int(r["week"])): r for r in csv.DictReader(open(p, encoding="utf-8")) if 3 <= int(r["week"]) <= 8}
base = load(f"{D}/d_now_2026.csv")
def stats(dump, pos):
    n = g2 = g3 = 0; sc = sf = nf = 0.0; miss = 0.0
    for k, r in dump.items():
        if r["pos"] != pos: continue
        c = cc.src.get(("consensus", k[1], norm(r["player"])))
        if c is None: continue
        p = float(r["proj"])
        if max(p, c) < 5: continue
        n += 1; gap = abs(p - c); sc += gap; g2 += gap >= 2; g3 += gap >= 3
        t = cc.src.get(("ftn", k[1], norm(r["player"])))
        if t is not None: sf += abs(p - t); nf += 1
        miss += (p - float(r["actual"])) ** 2
    return n, g2, g3, sc / n, sf / max(nf, 1), (miss / n) ** .5
print(f"{'':10s}{'pos':4s}{'n':>5s}{'2+ gaps':>9s}{'3+ gaps':>9s}{'|vs cons|':>10s}{'|vs FTN|':>9s}{'miss':>7s}")
for pos in ("WR", "TE", "QB"):
    for lab, dmp in [("baseline", base)] + [(t, load(f"{D}/c_{t}.csv")) for t in tags]:
        n, g2, g3, sc, sf, m = stats(dmp, pos)
        print(f"{lab:10s}{pos:4s}{n:5d}{g2:9d}{g3:9d}{sc:10.3f}{sf:9.3f}{m:7.3f}")
