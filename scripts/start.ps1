$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    throw "尚未完成環境部署。請先完成首次部署；啟動程式不會連網安裝套件。"
}

& $PythonExe -c "import faster_whisper, gradio, imageio_ffmpeg" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw "轉錄套件不完整，請先修復環境。啟動程式不會連網安裝套件。"
}

& $PythonExe (Join-Path $ProjectRoot "app.py")
