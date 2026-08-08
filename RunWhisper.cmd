@echo off
setlocal
cd /d "%~dp0"
echo Starting Whisper speech-to-text UI...
echo.
echo This window must stay open while Whisper is running.
echo Open http://127.0.0.1:7860 if the browser does not open automatically.
echo.
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
set EXIT_CODE=%ERRORLEVEL%
echo.
echo Whisper stopped. Exit code: %EXIT_CODE%
echo Press any key to close this window.
pause >nul
exit /b %EXIT_CODE%
