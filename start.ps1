$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    python -m venv $VenvPath
}

& $PythonExe -c "import faster_whisper, gradio, imageio_ffmpeg" 2>$null
if ($LASTEXITCODE -ne 0) {
    & $PythonExe -m pip install --upgrade pip
    & $PythonExe -m pip install `
        -r (Join-Path $ProjectRoot "requirements.lock")
}

& $PythonExe (Join-Path $ProjectRoot "app.py")
