"""
Rename abbreviated/nickname player names in projection tabs col A and Cheat Sheet col A.
These names come from consensus CSVs and don't match canonical spellings in ADP/JB Ranks.

Projection tab col E (Player&Team) is a formula =CONCATENATE(A2,"",B2) so it auto-updates.
Cheat Sheet col A is a static value written by the rebuild step.
"""
import win32com.client as win32

WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm"
xlUp = -4162

# consensus CSV name → canonical name (used in ADP tab + JB Ranks)
PROJ_RENAMES = {
    'Cam Ward': 'Cameron Ward',
    'Tank Dell': 'Nathaniel Dell',
    'Hollywood Brown': 'Marquise Brown',
    'Chris Brooks': 'Christopher Brooks',
    'Chig Okonkwo': 'Chigoziem Okonkwo',
    'Mitch Evans': 'Mitchell Evans',
    'Mike Penix Jr.': 'Michael Penix Jr.',
    'Mike Pittman Jr.': 'Michael Pittman Jr.',
    'Mike Pittman': 'Michael Pittman Jr.',
    'Mike Penix': 'Michael Penix Jr.',
}

excel = win32.gencache.EnsureDispatch("Excel.Application")
excel.Visible = False
excel.DisplayAlerts = False
wb = excel.Workbooks.Open(WORKBOOK)

total = 0

# ── Rename in each Projection tab col A ──────────────────────────────────────
for tab in ['QB Projections', 'RB Projections', 'WR Projections', 'TE Projections']:
    sh = wb.Sheets(tab)
    last = sh.Cells(sh.Rows.Count, 1).End(xlUp).Row
    count = 0
    for r in range(2, last + 1):
        name = sh.Cells(r, 1).Value
        if name in PROJ_RENAMES:
            new_name = PROJ_RENAMES[name]
            print(f"  {tab}: row {r}: {name!r} -> {new_name!r}")
            sh.Cells(r, 1).Value = new_name
            count += 1
    print(f"  {tab}: {count} renames")
    total += count

# ── Rename in Cheat Sheet col A ───────────────────────────────────────────────
cs = wb.Sheets("Cheat Sheet")
cs_last = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
count = 0
for r in range(2, cs_last + 1):
    name = cs.Cells(r, 1).Value
    if name in PROJ_RENAMES:
        new_name = PROJ_RENAMES[name]
        cs.Cells(r, 1).Value = new_name
        count += 1
print(f"\n  Cheat Sheet col A: {count} renames")
total += count

wb.Save()
wb.Close(False)
excel.Quit()
print(f"\nTotal renames: {total}. Saved.")
