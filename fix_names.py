"""Apply ADP tab name renames to the live 2026ver file, then re-run JB ranks."""
import subprocess, sys
import win32com.client as win32

WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm"
xlUp = -4162

ADP_RENAMES = {
    'Cam Ward': 'Cameron Ward',
    'Mike Penix': 'Michael Penix Jr.',
    'Mike Penix Jr.': 'Michael Penix Jr.',
    'Mike Pittman': 'Michael Pittman Jr.',
    'Mike Pittman Jr.': 'Michael Pittman Jr.',
    'Tank Dell': 'Nathaniel Dell',
    'Chris Brooks': 'Christopher Brooks',
    'Hollywood Brown': 'Marquise Brown',
}

excel = win32.gencache.EnsureDispatch("Excel.Application")
excel.Visible = False
excel.DisplayAlerts = False
wb = excel.Workbooks.Open(WORKBOOK)

adp = wb.Sheets("ADP")
adp_last = adp.Cells(adp.Rows.Count, 1).End(xlUp).Row
renamed = 0
for r in range(2, adp_last + 1):
    name = adp.Cells(r, 1).Value
    if name in ADP_RENAMES:
        adp.Cells(r, 1).Value = ADP_RENAMES[name]
        print(f"  ADP: {name!r} -> {ADP_RENAMES[name]!r}")
        renamed += 1

print(f"Renamed {renamed} entries in ADP tab")
wb.Save()
wb.Close(False)
excel.Quit()
print("ADP tab saved. Now re-running Joe Bond ranks...")
