$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    python -m venv $VenvPath
}

& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install `
    -r (Join-Path $ProjectRoot "requirements.lock")
& $PythonExe -m pip install `
    -r (Join-Path $ProjectRoot "requirements-diarization.lock") `
    -c (Join-Path $ProjectRoot "constraints-verified.txt")

Write-Host ""
Write-Host "Diarization dependencies installed."
Write-Host "Before using pyannote community-1 online, accept the model terms on Hugging Face and provide a token in the UI or HF_TOKEN."
Write-Host "For offline use, return to WhisperTools.cmd and choose option 10 to prepare a local model folder."
