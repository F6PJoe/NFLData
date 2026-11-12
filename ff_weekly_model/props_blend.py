#!/usr/bin/env python3
"""The week's projections with a props column and a 50/50 blend (a look, not adopted -- untested).

    python props_blend.py --year 2026 --week 9 [--snapshot data/props/<file>.csv] [--w 0.5]

Joe 2026-11-06: "can I get the week's projections with the pull of props from last night?"
Every projected player is listed. Blend = (1-w) x ours + w x props, where 'props' already uses our
number for any piece with no prop (props_compare.build_rows) -- so the blend only moves the pieces
the market actually priced, and a player with no props at all keeps our projection.
Writes "Week N Projections with Props.xlsx" next to the rankings files.
"""
import argparse, csv, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from props_compare import build_rows
from audit_vs_sources import norm

PIECES = {"QB": ("pass yds", "pass TD", "rush yds", "rush TD"), "X": ("rec", "rec yds", "rush yds", "TD")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, required=True)
    ap.add_argument("--week", type=int, required=True)
    ap.add_argument("--snapshot")
    ap.add_argument("--w", type=float, default=0.5)
    a = ap.parse_args()
    prows, snap = build_rows(a.year, a.week, a.snapshot)
    byname = {norm(r["player"]): r for r in prows}
    allp = []
    for o in csv.DictReader(open(os.path.join(HERE, "data", f"projections_{a.year}_wk{a.week:02d}.csv"), encoding="utf-8-sig")):
        ours = float(o["half_ppr"] or 0)
        if ours <= 0 or o["pos"] not in ("QB", "RB", "WR", "TE"):
            continue
        pr = byname.get(norm(o["player"]))
        if pr:
            had = [k for k, (x, y) in pr["stats"].items() if abs(x - y) > 1e-9]
            props = pr["props"]
        else:
            had, props = [], None
        blend = ours if props is None else (1 - a.w) * ours + a.w * props
        allp.append({"pos": o["pos"], "player": o["player"], "team": o["team"], "ours": ours,
                     "props": props, "blend": blend, "cons": float(o["consensus"] or 0), "had": had})
    write(allp, a, snap)


def write(allp, a, snap):
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter
    wb = openpyxl.Workbook(); wb.remove(wb.active)
    hf, hfill = Font(name="Arial", bold=True, color="FFFFFF"), PatternFill("solid", fgColor="1F4E78")
    bf, grey = Font(name="Arial", size=10), Font(name="Arial", size=10, color="808080")
    up, dn = PatternFill("solid", fgColor="C6EFCE"), PatternFill("solid", fgColor="FFC7CE")
    pct = int(a.w * 100)
    print(f"  props snapshot: {snap}")
    for pos in ("QB", "RB", "WR", "TE"):
        g = [r for r in allp if r["pos"] == pos]
        rk_o = {id(r): i + 1 for i, r in enumerate(sorted(g, key=lambda r: -r["ours"]))}
        g.sort(key=lambda r: -r["blend"])
        ws = wb.create_sheet(pos)
        ws.cell(1, 1, f"Week {a.week} {pos} -- our projections, props, and a {100 - pct}/{pct} blend (half PPR)").font = \
            Font(name="Arial", size=12, bold=True)
        ws.cell(2, 1, f"Sorted by the blend. Props = market averages for the pieces with a prop, our number for the rest; "
                      f"blank = no props (blend = ours). Diffs vs consensus: green = 2+ above, red = 2+ below. "
                      f"Not tested yet -- a look only. Snapshot: {snap}").font = \
            Font(name="Arial", size=9, italic=True)
        heads = ["Blend rk", "Player", "Team", "Consensus", "Ours", "Ours - cons", f"{100 - pct}/{pct}",
                 "Blend - cons", "Props", "Our rk", "Rank move", "Props on"]
        for j, h in enumerate(heads):
            c = ws.cell(4, j + 1, h); c.font, c.fill = hf, hfill
            c.alignment = Alignment(horizontal="center", wrap_text=True)
        rd = lambda x: round(x, 2)
        for i, r in enumerate(g):
            mv = rk_o[id(r)] - (i + 1)
            cons = r["cons"] or None
            vals = [i + 1, r["player"], r["team"], cons and rd(cons), rd(r["ours"]),
                    cons and rd(r["ours"] - cons), rd(r["blend"]), cons and rd(r["blend"] - cons),
                    None if r["props"] is None else rd(r["props"]), rk_o[id(r)], mv,
                    ", ".join(r["had"]) if r["had"] else "none"]
            for j, v in enumerate(vals):
                c = ws.cell(5 + i, j + 1, v); c.font = bf if r["had"] else grey
                if j not in (1, 11): c.alignment = Alignment(horizontal="center")
            if cons:
                for j, d in ((6, r["ours"] - cons), (8, r["blend"] - cons)):
                    if abs(d) >= 2:
                        ws.cell(5 + i, j).fill = up if d > 0 else dn
        for j, w in enumerate([7, 24, 6, 10, 7, 8, 7, 8, 7, 7, 7, 30]):
            ws.column_dimensions[get_column_letter(j + 1)].width = w
        ws.freeze_panes = "C5"
        top = sorted(g, key=lambda r: -r["ours"])[:{"QB": 24, "RB": 36, "WR": 48, "TE": 24}[pos]]
        n_any = sum(1 for r in top if r["had"]); n_none = [r["player"] for r in top if not r["had"]]
        tc = [r for r in top if r["cons"]]
        print(f"  {pos}: avg gap to consensus, our top {len(top)}: ours {sum(abs(r['ours'] - r['cons']) for r in tc) / len(tc):.2f}"
              f", blend {sum(abs(r['blend'] - r['cons']) for r in tc) / len(tc):.2f}; 2+ pt gaps: ours "
              f"{sum(abs(r['ours'] - r['cons']) >= 2 for r in tc)}, blend {sum(abs(r['blend'] - r['cons']) >= 2 for r in tc)}")
        print(f"  {pos}: {len(g)} players, {sum(1 for r in g if r['had'])} with props | our top "
              f"{len(top)}: {n_any} with props; none: {', '.join(n_none) or '-'}")
    out = os.path.join(HERE, "site_rankings", f"{a.year}-wk{a.week:02d}", f"Week {a.week} Projections with Props.xlsx")
    wb.save(out)
    print("  ->", out)


if __name__ == "__main__":
    main()
