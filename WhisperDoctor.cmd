@echo off
rem Cross-machine Whisper environment scan. Keep this bootstrap ASCII-only.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\bootstrap_scan.ps1"
set EXIT_CODE=%ERRORLEVEL%

echo.
echo Environment scan finished with exit code %EXIT_CODE%.
echo Press any key to close this window.
pause >nul
endlocal & exit /b %EXIT_CODE%
