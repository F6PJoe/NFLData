"""When our projection is far from consensus, who is closer to what happened? 2026 wks 3-8,
current model walk-forward (backtest dump) vs the archived consensus / FTN for that week."""
import csv, collections, sys, os
sys.path.insert(0, "C:/Users/jbond/OneDrive/Documents/FF_ADP/ff_weekly_model")
sys.argv = [sys.argv[0]]
assert os.environ.get("DUMPS"), "set DUMPS to the folder with d_now_2026.csv"
import importlib.util
spec = importlib.util.spec_from_file_location("cc", "research/consensus_closeness.py")
cc = importlib.util.module_from_spec(spec); spec.loader.exec_module(cc)   # builds cc.src, cc.base
from audit_vs_sources import norm
rows = []
for (pid, w), b in cc.base.items():
    c = cc.src.get(("consensus", w, norm(b["player"])))
    t = cc.src.get(("ftn", w, norm(b["player"])))
    if c is None: continue
    rows.append((b["pos"], b["player"], w, float(b["proj"]), c, t, float(b["actual"])))
print(f"player-weeks with a consensus line: {len(rows)}")
def summ(sel, lab):
    n = len(sel)
    if not n: return
    ours = sum(abs(p - a) for _, _, _, p, c, _, a in sel) / n
    cons = sum(abs(c - a) for _, _, _, p, c, _, a in sel) / n
    win = sum(1 for _, _, _, p, c, _, a in sel if abs(p - a) < abs(c - a)) / n
    print(f"  {lab:34s} n={n:4d}  our miss {ours:5.2f}  cons miss {cons:5.2f}  we were closer {win:.0%}")
for th in (2, 3, 4, 5):
    print(f"\nGAP {th}+ POINTS from consensus")
    big = [r for r in rows if abs(r[3] - r[4]) >= th]
    summ(big, "all")
    summ([r for r in big if r[3] > r[4]], "  we were HIGHER")
    summ([r for r in big if r[3] < r[4]], "  we were LOWER")
    for pos in ("QB", "RB", "WR", "TE"):
        summ([r for r in big if r[0] == pos], f"  {pos}")
print("\nALL player-weeks"); summ(rows, "all")
# starters only (cons 8+), where it shows
print("\nCONSENSUS 8+ POINTS (fantasy-relevant), gap 3+")
big = [r for r in rows if r[4] >= 8 and abs(r[3] - r[4]) >= 3]
summ(big, "all")
summ([r for r in big if r[3] > r[4]], "  we were HIGHER")
summ([r for r in big if r[3] < r[4]], "  we were LOWER")
for pos in ("QB", "RB", "WR", "TE"):
    summ([r for r in big if r[0] == pos], f"  {pos}")
# share of the gap we should keep: best blend weight on our side (0 = all consensus)
print("\nIF THE BIG GAPS (3+, cons 8+) WERE CUT BACK -- average miss on those player-weeks")
for k in (1.0, 0.75, 0.5, 0.25, 0.0):
    m = sum(abs(c + k * (p - c) - a) for _, _, _, p, c, _, a in big) / len(big)
    print(f"  keep {k:.0%} of our gap: miss {m:.2f}")
big.sort(key=lambda r: -abs(r[3] - r[4]))
print("\nBIGGEST 25 (cons 8+)")
for pos, nm, w, p, c, t, a in big[:25]:
    print(f"  wk{w} {nm:22s} {pos}  ours {p:5.1f}  cons {c:5.1f}  FTN {t if t is None else round(t,1)!s:>5}  actual {a:5.1f}  {'US' if abs(p-a) < abs(c-a) else 'cons'}")
