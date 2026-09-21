import win32com.client as win32

WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm"
xlUp = -4162

excel = win32.gencache.EnsureDispatch("Excel.Application")
excel.Visible = False
excel.DisplayAlerts = False
wb = excel.Workbooks.Open(WORKBOOK)
cs = wb.Sheets("Cheat Sheet")
last_row = cs.Cells(cs.Rows.Count, 1).End(xlUp).Row

# If player not in ADP or ADP >= 999: use MAXIFS(excluding 999) + 1
m_formula = (
    '=IFERROR('
    'IF(VLOOKUP(A2,ADP!$A:$B,2,FALSE)<999,'
        'VLOOKUP(A2,ADP!$A:$B,2,FALSE),'
        'MAXIFS(ADP!$B:$B,ADP!$B:$B,"<999")+1),'
    'MAXIFS(ADP!$B:$B,ADP!$B:$B,"<999")+1)'
)
cs.Range(f"M2:M{last_row}").Formula = m_formula
print(f"M2:M{last_row} updated ({last_row - 1} rows)")

print("\nSample M values (rows 2-15):")
for r in range(2, 16):
    name = cs.Cells(r, 1).Value
    m = cs.Cells(r, 13).Value
    print(f"  {str(name)[:25]:<25} M={m}")

wb.Save()
print("\nSaved.")
wb.Close(False)
excel.Quit()
