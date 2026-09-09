$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$TorchLock = Join-Path $ProjectRoot "requirements\requirements-torch-cu128.txt"
$WheelhouseRoot = Join-Path $ProjectRoot ".cache\wheels"
$Wheelhouse = Join-Path $WheelhouseRoot ("pytorch-cu128-" + (Get-Date -Format "yyyyMMddHHmmss"))

if (-not (Test-Path $PythonExe)) {
    Write-Host "Python virtual environment was not found. Run RunWhisper.cmd once first."
    exit 1
}
if (-not (Test-Path $TorchLock)) {
    Write-Host "Missing dependency lock: requirements-torch-cu128.txt"
    exit 1
}

Write-Host "Installing PyTorch CUDA build for speaker diarization..."
Write-Host "This updates torch and torchaudio inside this project's .venv only."
Write-Host ""

& $PythonExe -m pip install --upgrade pip

New-Item -ItemType Directory -Force -Path $Wheelhouse | Out-Null
Write-Host "Downloading CUDA wheels first. Existing torch will not be removed unless download succeeds."
& $PythonExe -m pip download --only-binary=:all: --no-deps --dest $Wheelhouse --index-url https://download.pytorch.org/whl/cu128 -r $TorchLock
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Could not download CUDA PyTorch wheels."
    Write-Host "Possible causes: network blocked, PyTorch CUDA wheel unavailable for this Python version, or PyTorch server unavailable."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "CUDA wheels downloaded. Replacing torch and torchaudio..."
& $PythonExe -m pip uninstall -y torch torchaudio
& $PythonExe -m pip install --no-index --find-links $Wheelhouse --no-deps -r $TorchLock
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing downloaded CUDA wheels failed."
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "Verifying PyTorch CUDA..."
@'
import sys
sys.stdout.reconfigure(encoding="utf-8")

import torch
import torchaudio

print(f"torch: {torch.__version__}")
print(f"torchaudio: {torchaudio.__version__}")
print(f"torch CUDA available: {torch.cuda.is_available()}")
print(f"torch CUDA version: {torch.version.cuda}")
print(f"torch CUDA devices: {torch.cuda.device_count()}")
if torch.cuda.is_available():
    print(f"torch CUDA device 0: {torch.cuda.get_device_name(0)}")
else:
    print("PyTorch still cannot use CUDA. Check NVIDIA driver and the installed PyTorch CUDA wheel.")
    raise SystemExit(2)

if "+cpu" in torch.__version__:
    print("torch is still a CPU build.")
    raise SystemExit(3)
'@ | & $PythonExe -
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "PyTorch CUDA installation finished."
