@echo off
REM Build this week's rankings. Just double-click this file. Nothing to configure.
REM
REM Optional, only if you want them:
REM   weekly.bat --scoring all     build PPR and Standard too, not just half-PPR
REM   weekly.bat --open            also open the copy page in a browser when done
cd /d "%~dp0"
python run_weekly.py %*
echo.
if errorlevel 1 (
  echo Finished WITH WARNINGS - read the output above before pasting.
) else (
  echo Finished clean.
)
pause
