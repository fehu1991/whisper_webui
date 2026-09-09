@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0DeployLive.ps1"
set EXIT_CODE=%ERRORLEVEL%
pause
exit /b %EXIT_CODE%
