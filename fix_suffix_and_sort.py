"""
1. Rename suffix-dropped ADP names to match Cheat Sheet canonical names.
2. Sort Cheat Sheet by col Q (Overall Value) descending.
"""
import win32com.client as win32

WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm"
xlUp = -4162
xlSortOnValues = 0
xlDescending = 2
xlYes = 1

SUFFIX_RENAMES = {
    'Kenneth Walker': 'Kenneth Walker III',
    'Travis Etienne': 'Travis Etienne Jr.',
    'Luther Burden': 'Luther Burden III',
    'Harold Fannin': 'Harold Fannin Jr.',
    'Marvin Harrison': 'Marvin Harrison Jr.',
    'Kyle Pitts': 'Kyle Pitts Sr.',
    'Brian Thomas': 'Brian Thomas Jr.',
    'Aaron Jones': 'Aaron Jones Sr.',
    'Chris Rodriguez': 'Chris Rodriguez Jr.',
    'Omar Cooper': 'Omar Cooper Jr.',
    'Tyrone Tracy': 'Tyrone Tracy Jr.',
    'Brian Robinson': 'Brian Robinson Jr.',
    'Mike Washington': 'Mike Washington Jr.',
    'Chris Brazzell': 'Chris Brazzell II',
    'Marvin Mims': 'Marvin Mims Jr.',
}

excel = win32.gencache.EnsureDispatch("Excel.Application")
excel.Visible = False
excel.DisplayAlerts = False
wb = excel.Workbooks.Open(WORKBOOK)

# ── 1. Rename ADP tab ────────────────────────────────────────────────────────
adp = wb.Sheets("ADP")
adp_last = adp.Cells(adp.Rows.Count, 1).End(xlUp).Row
renamed = 0
for r in range(2, adp_last + 1):
    name = adp.Cells(r, 1).Value
    if name in SUFFIX_RENAMES:
        adp.Cells(r, 1).Value = SUFFIX_RENAMES[name]
        print(f"  ADP: {name!r} -> {SUFFIX_RENAMES[name]!r}")
        renamed += 1
print(f"ADP: {renamed} renames\n")

# ── 2. Sort Cheat Sheet by col Q (Overall Value) descending ─────────────────
cs = wb.Sheets("Cheat Sheet")
cs_last = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
sort_range = cs.Range(f"A2:U{cs_last}")
sort_key   = cs.Range("Q2")

sort_range.Sort(
    Key1=sort_key,
    Order1=xlDescending,
    Header=xlYes - 1,   # xlNo = 2; we're passing the data range without header
)
print(f"Cheat Sheet sorted by col Q descending ({cs_last - 1} rows)")

wb.Save()
wb.Close(False)
excel.Quit()
print("Saved.")
