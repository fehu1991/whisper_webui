$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
try {
    if (-not (Test-Path -LiteralPath $PythonExe)) {
        throw "請先完成 Whisper 工作台的首次部署，再執行即時功能部署。"
    }
    Write-Host "即時功能部署會連網下載套件與 small 模型，不會讀取或上傳錄音及逐字稿。"
    Write-Host "請在會議前完成；使用時不需要再次執行本檔。"
    & $PythonExe -m pip install --disable-pip-version-check -r (Join-Path $ProjectRoot "requirements-live.txt") -c (Join-Path $ProjectRoot "constraints-verified.txt")
    if ($LASTEXITCODE -ne 0) { throw "即時套件安裝失敗。" }
    $env:HF_HUB_OFFLINE = "0"
    & $PythonExe (Join-Path $ProjectRoot "scripts\prepare_live_model.py")
    if ($LASTEXITCODE -ne 0) { throw "即時模型準備失敗。" }
    Write-Host "即時功能已備妥。請執行 RunWhisper.cmd，再點選「即時收音／文字稿編輯」。" -ForegroundColor Green
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
