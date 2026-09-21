"""Delete the duplicate 'M. Valdes-Scantling' row from WR Projections and Cheat Sheet."""
import win32com.client as win32

WORKBOOK = r"C:\Users\jbond\Dropbox\F6P Admin\Fantasy Football Cheat Sheet\2026-Football-Cheat-Sheet-working-copy-2025ver.xlsm"
xlUp = -4162

excel = win32.gencache.EnsureDispatch("Excel.Application")
excel.Visible = False
excel.DisplayAlerts = False
wb = excel.Workbooks.Open(WORKBOOK)

def delete_player_row(sh, name, label):
    last = sh.Cells(sh.Rows.Count, 1).End(xlUp).Row
    for r in range(2, last + 1):
        if sh.Cells(r, 1).Value == name:
            sh.Rows(r).Delete()
            print(f"  {label}: deleted row {r} ({name!r})")
            return True
    print(f"  {label}: '{name}' not found")
    return False

delete_player_row(wb.Sheets("WR Projections"), "M. Valdes-Scantling", "WR Projections")
delete_player_row(wb.Sheets("Cheat Sheet"),    "M. Valdes-Scantling", "Cheat Sheet")

wb.Save()
wb.Close(False)
excel.Quit()
print("Saved.")
