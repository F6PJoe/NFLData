import win32com.client as win32
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy.xlsm"
xlUp = -4162
excel = win32.gencache.EnsureDispatch("Excel.Application")
excel.Visible = False
wb = excel.Workbooks.Open(WORKBOOK)
calc = wb.Sheets("Calculations")
cs = wb.Sheets("Cheat Sheet")

print("=== POSITIONAL TABLE rows 26-29 ===")
for row in (26, 27, 28, 29):
    vals = []
    for col in ("E","F","G","H","I","J"):
        v = calc.Range(f"{col}{row}").Value
        if v is None: v = ""
        elif isinstance(v, float): v = f"{v:.4f}"
        vals.append(str(v)[:10])
    print(f"  Row {row}: {' | '.join(vals)}")

print("\n=== DEMAND MULTIPLIERS TABLE rows 31-37 ===")
for row in range(31, 38):
    vals = []
    for col in ("E","F","G","H","I"):
        v = calc.Range(f"{col}{row}").Value
        if v is None: v = ""
        elif isinstance(v, float): v = f"{v:.2f}"
        vals.append(str(v)[:12])
    print(f"  Row {row}: {' | '.join(vals)}")

print("\n=== ADP DROPDOWN A-B rows 31-35 (must be intact) ===")
for row in range(31, 36):
    print(f"  A{row}={calc.Range(f'A{row}').Value!r}  B{row}={calc.Range(f'B{row}').Value!r}")

print("\n=== Q COLUMN top 10 ===")
for row in range(2, 12):
    name = cs.Range(f"A{row}").Value or ""
    pos  = cs.Range(f"D{row}").Value or ""
    q    = cs.Range(f"Q{row}").Value
    if isinstance(q, float): q = f"{q:.2f}"
    print(f"  {str(name)[:22]:<22} {pos:<4} Q={q}")

wb.Close(SaveChanges=False)
excel.Quit()
