@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0SoundCatalog.ps1"
if errorlevel 1 echo Sound catalog update failed. See the message above.
pause
