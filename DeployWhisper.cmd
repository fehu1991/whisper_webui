@echo off
rem Whisper release installer. Keep this wrapper ASCII-only.
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0DeployWhisper.ps1"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
pause
endlocal & exit /b %EXIT_CODE%
