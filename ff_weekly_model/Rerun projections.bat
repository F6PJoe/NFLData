@echo off
rem Rerun this week's projections after making calls in "F6P Week N Review.xlsx".
rem Save and close the workbook first. See rerun.py.
cd /d "%~dp0"
"C:\Users\jbond\AppData\Local\Programs\Python\Python313\python.exe" rerun.py
pause
