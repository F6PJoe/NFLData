"""
Rebuild Cheat Sheet A-D from projection tabs and sort by projected score
descending. Sorts in Python (avoids Excel column-scramble bug with formula
ranges), then writes A-D in sorted order and AutoFills E:U.
"""
import csv
from pathlib import Path
import win32com.client as win32

BASE = Path(__file__).resolve().parent
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm"
xlUp = -4162
xlFillCopy = 0

PROJ_RENAMES = {
    'Cam Ward': 'Cameron Ward',
    'Tank Dell': 'Nathaniel Dell',
    'Hollywood Brown': 'Marquise Brown',
    'Chris Brooks': 'Christopher Brooks',
    'Chig Okonkwo': 'Chigoziem Okonkwo',
    'Mitch Evans': 'Mitchell Evans',
    'Mike Penix Jr.': 'Michael Penix Jr.',
    'Mike Penix': 'Michael Penix Jr.',
    'Mike Pittman Jr.': 'Michael Pittman Jr.',
    'Mike Pittman': 'Michael Pittman Jr.',
    'M. Valdes-Scantling': 'Marquez Valdes-Scantling',
}

consensus = {}
with open(BASE / "combined_adp.csv", newline='', encoding='utf-8') as f:
    for row in csv.DictReader(f):
        c = row.get('Consensus', '')
        if c:
            consensus[row['Player']] = float(c)

excel = win32.gencache.EnsureDispatch("Excel.Application")
excel.Visible = False
excel.DisplayAlerts = False
wb = excel.Workbooks.Open(WORKBOOK)

# ── Read projected scores from projection tabs (col F = score formula result) ─
# Force recalc so we get real numeric scores, not formula strings
wb.Application.Calculate()

proj_scores = {}
for tab in ['QB Projections', 'RB Projections', 'WR Projections', 'TE Projections']:
    sh = wb.Sheets(tab)
    last = sh.Cells(sh.Rows.Count, 1).End(xlUp).Row
    data = sh.Range(f"A2:F{last}").Value
    for row in data:
        name = row[0]
        if not name:
            continue
        name = PROJ_RENAMES.get(name, name)
        score = float(row[5]) if row[5] is not None else 0
        proj_scores[name] = score

# ── Collect players in sorted order (by projected score descending) ───────────
players = []
for tab, pos in [('QB Projections','QB'),('RB Projections','RB'),
                 ('WR Projections','WR'),('TE Projections','TE')]:
    sh = wb.Sheets(tab)
    last = sh.Cells(sh.Rows.Count, 1).End(xlUp).Row
    data = sh.Range(f"A2:D{last}").Value
    for row in data:
        name = row[0]
        if not name:
            continue
        name = PROJ_RENAMES.get(name, name)
        team, bye, pos_val = row[1], row[2], row[3]
        score = proj_scores.get(name, 0)
        players.append((name, team, bye, pos_val, score))

# Sort by projected score descending
players.sort(key=lambda p: p[4], reverse=True)
print(f"Collected {len(players)} players, sorted by projected score descending")

# ── Write A-D in sorted order, AutoFill E:U ──────────────────────────────────
cs = wb.Sheets("Cheat Sheet")
old_last = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
new_last = 1 + len(players)

out = [[p[0], p[1], p[2], p[3]] for p in players]
cs.Range(f"A2:D{new_last}").Value = out

if new_last < old_last:
    cs.Range(f"A{new_last+1}:U{old_last}").ClearContents()

cs.Range("E2:U2").AutoFill(cs.Range(f"E2:U{new_last}"), xlFillCopy)

# Re-apply M formula
m_formula = (
    '=IFERROR('
    'IF(VLOOKUP(A2,ADP!$A:$B,2,FALSE)<999,'
        'VLOOKUP(A2,ADP!$A:$B,2,FALSE),'
        'MAXIFS(ADP!$B:$B,ADP!$B:$B,"<999")+1),'
    'MAXIFS(ADP!$B:$B,ADP!$B:$B,"<999")+1)'
)
cs.Range(f"M2:M{new_last}").Formula = m_formula
print(f"Rebuilt A-D ({len(players)} players), AutoFilled E:U, M formula applied")

wb.Application.Calculate()

# Verify top 10
print("\nTop 10 by projected score:")
print(f"  {'Name':<30} {'Pos':<4} {'Score':>7}  {'ADP':>6}")
for r in range(2, 12):
    name  = cs.Cells(r, 1).Value or ''
    pos   = cs.Cells(r, 4).Value or ''
    score = cs.Cells(r, 7).Value
    adp   = cs.Cells(r, 13).Value
    try:
        print(f"  {str(name):<30} {str(pos):<4} {float(score or 0):>7.1f}  {float(adp or 0):>6.1f}")
    except (TypeError, ValueError):
        print(f"  {str(name):<30} {str(pos):<4} score={score!r}  adp={adp!r}")

wb.Save()
wb.Close(False)
excel.Quit()
print("\nSaved.")
