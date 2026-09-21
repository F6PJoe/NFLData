import win32com.client as win32
WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm"
xlUp = -4162
excel = win32.gencache.EnsureDispatch("Excel.Application")
excel.Visible = False
wb = excel.Workbooks.Open(WORKBOOK)
cs = wb.Sheets("Cheat Sheet")

print("Top 15 players by Overall Value (col Q):")
print(f"  {'Name':<28} {'Pos':<4} {'Score':>6}  {'ADP':>6}  {'JBRank':>7}  {'Q':>7}")
for r in range(2, 17):
    name  = cs.Cells(r, 1).Value or ''
    pos   = cs.Cells(r, 4).Value or ''
    score = cs.Cells(r, 7).Value  # col G
    adp   = cs.Cells(r, 13).Value # col M
    jbr   = cs.Cells(r, 15).Value # col O
    q     = cs.Cells(r, 17).Value # col Q
    print(f"  {str(name):<28} {str(pos):<4} {score or 0:>6.1f}  {adp or 0:>6.1f}  {jbr or 0:>7.0f}  {q or 0:>7.3f}")

wb.Close(False)
excel.Quit()
