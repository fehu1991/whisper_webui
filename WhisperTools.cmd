@echo off
rem ============================================================
rem  WhisperTools bootstrap
rem  Keep this file ASCII-only and WITHOUT a BOM, otherwise
rem  cmd.exe may fail to parse it. All Chinese UI text lives in
rem  WhisperTools.ps1, which handles UTF-8 properly.
rem ============================================================
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"

"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\WhisperTools.ps1"
set EXIT_CODE=%ERRORLEVEL%

endlocal & exit /b %EXIT_CODE%
