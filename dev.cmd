@echo off
cd /d "%~dp0"
start "Rebate Backend" cmd /k "cd /d %~dp0 && powershell -NoProfile -ExecutionPolicy Bypass -File dev-backend.ps1"
start "Rebate Frontend" cmd /k "cd /d %~dp0 && powershell -NoProfile -ExecutionPolicy Bypass -File dev-frontend.ps1"
exit
