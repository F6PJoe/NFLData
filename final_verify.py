import win32com.client as win32
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm"
xlUp = -4162
excel = win32.gencache.EnsureDispatch("Excel.Application")
excel.Visible = False
wb = excel.Workbooks.Open(WORKBOOK)
cs = wb.Sheets("Cheat Sheet")
adp = wb.Sheets("ADP")

cs_last = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row
print(f"Cheat Sheet: {cs_last - 1} players\n")

print("First 15 rows (A=Name, B=Team, C=Bye, D=Pos):")
for r in range(2, 17):
    a = cs.Cells(r,1).Value
    b = cs.Cells(r,2).Value
    c = cs.Cells(r,3).Value
    d = cs.Cells(r,4).Value
    print(f"  {str(a):<28} {str(b):<5} {str(c):<4} {str(d)}")

print("\nADP tab spot-check (fixed suffix names):")
adp_last = adp.Cells(adp.Rows.Count, 1).End(xlUp).Row
checks = ['Cameron Ward','Kenneth Walker III','Travis Etienne Jr.','Nathaniel Dell',
          'Christopher Brooks','Marquise Brown','Chigoziem Okonkwo','Michael Pittman Jr.']
adp_names = {}
for r in range(2, adp_last+1):
    n = adp.Cells(r,1).Value
    v = adp.Cells(r,2).Value
    if n:
        adp_names[n] = v
for name in checks:
    adp_val = adp_names.get(name)
    print(f"  {'FOUND' if adp_val else 'MISS ':6} {name:<30} ADP={adp_val}")

wb.Close(False)
excel.Quit()
