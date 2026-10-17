@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0SoundCatalog.ps1" -Watch
if errorlevel 1 pause
