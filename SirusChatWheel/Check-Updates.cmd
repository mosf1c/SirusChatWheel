@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Check-Updates.ps1"
if errorlevel 1 echo Could not check for updates. Installed files were not replaced.
pause
