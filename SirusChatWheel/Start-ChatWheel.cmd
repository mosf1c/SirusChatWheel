@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Check-Updates.ps1" -Quiet
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0SoundCatalog.ps1" -LaunchGame -SkipCatalogUpdate
if errorlevel 1 pause
