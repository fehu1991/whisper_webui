$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$DeployExitCode = 0

function Write-Section($Title) {
    Write-Host ""
    Write-Host "== $Title =="
}

function Test-Command($Name) {
    return [bool](Get-Command $Name -ErrorAction SilentlyContinue)
}

function Find-Dll($Name) {
    $paths = @()
    if ($env:CUDA_PATH) {
        $paths += Join-Path $env:CUDA_PATH "bin"
    }
    if ($env:CUDA_PATH_V12_8) {
        $paths += Join-Path $env:CUDA_PATH_V12_8 "bin"
    }
    $cudaRoot = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    if (Test-Path $cudaRoot) {
        $paths += Get-ChildItem -Path $cudaRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "bin" }
    }
    $sitePackages = Join-Path $ProjectRoot ".venv\Lib\site-packages"
    $paths += @(
        (Join-Path $sitePackages "torch\lib"),
        (Join-Path $sitePackages "nvidia\cublas\bin"),
        (Join-Path $sitePackages "ctranslate2")
    )
    foreach ($path in ($paths | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique)) {
        $candidate = Join-Path $path $Name
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }
    return ""
}

function Try-InstallCudaToolkit() {
    Write-Section "CUDA Toolkit"
    $cublas = Find-Dll "cublas64_12.dll"
    if ($cublas) {
        Write-Host "cublas64_12.dll found: $cublas"
        return
    }

    Write-Host "cublas64_12.dll was not found. CTranslate2 needs CUDA 12.x runtime for GPU transcription."
    if (Test-Command "winget") {
        Write-Host "winget found. Trying to install NVIDIA CUDA Toolkit..."
        foreach ($packageId in @("Nvidia.CUDA", "NVIDIA.CUDA")) {
            & winget install --id $packageId --exact --source winget --accept-source-agreements --accept-package-agreements
            if ($LASTEXITCODE -eq 0 -and (Find-Dll "cublas64_12.dll")) {
                Write-Host "CUDA Toolkit installed."
                return
            }
        }
        Write-Host "winget could not install CUDA Toolkit with known package IDs."
    } else {
        Write-Host "winget was not found on this computer, so CUDA Toolkit cannot be installed automatically by this script."
    }

    Write-Host "Opening the official NVIDIA CUDA Toolkit archive. Install any CUDA 12.x Toolkit, then run WhisperTools.cmd again."
    Start-Process "https://developer.nvidia.com/cuda-toolkit-archive"
}

Write-Section "NVIDIA driver"
if (Test-Command "nvidia-smi") {
    & nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
} else {
    Write-Host "nvidia-smi was not found. Install or repair the NVIDIA display driver first."
    Write-Host "Opening the official NVIDIA driver download page..."
    Start-Process "https://www.nvidia.com/Download/index.aspx"
    exit 1
}

Write-Section "Python environment"
if (-not (Test-Path $PythonExe)) {
    Write-Host "Creating virtual environment..."
    python -m venv $VenvPath
}

Write-Host "Python: $PythonExe"
& $PythonExe -m pip install --upgrade pip
& $PythonExe -m pip install -r (Join-Path $ProjectRoot "requirements\requirements.lock")

Write-Section "PyTorch CUDA"
& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "scripts\install_torch_cuda.ps1")
if ($LASTEXITCODE -ne 0) {
    Write-Host "PyTorch CUDA installation did not complete."
    $DeployExitCode = $LASTEXITCODE
}

Write-Section "Speaker diarization"
if (Test-Path (Join-Path $ProjectRoot "requirements\requirements-diarization.lock")) {
    & $PythonExe -m pip install `
        -r (Join-Path $ProjectRoot "requirements\requirements-diarization.lock") `
        -c (Join-Path $ProjectRoot "requirements\constraints-verified.txt")
}

Write-Section "CTranslate2 / faster-whisper"
Write-Host "Re-applying the verified base dependency lock..."
& $PythonExe -m pip install -r (Join-Path $ProjectRoot "requirements\requirements.lock")

Try-InstallCudaToolkit

Write-Section "Verification"
& "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "scripts\gpu_diagnostics.ps1") -SmokeTest
$VerifyExitCode = $LASTEXITCODE

Write-Section "PyTorch CUDA verification"
@'
import sys
sys.stdout.reconfigure(encoding="utf-8")

try:
    import torch
    import torchaudio
except Exception as exc:
    print(f"PyTorch/torchaudio import failed: {exc}")
    raise SystemExit(5)

print(f"torch: {torch.__version__}")
print(f"torchaudio: {torchaudio.__version__}")
print(f"torch CUDA available: {torch.cuda.is_available()}")
if not torch.cuda.is_available() or "+cpu" in torch.__version__:
    raise SystemExit(6)
'@ | & $PythonExe -
$TorchVerifyExitCode = $LASTEXITCODE

Write-Host ""
if ($VerifyExitCode -ne 0 -or $TorchVerifyExitCode -ne 0 -or $DeployExitCode -ne 0) {
    Write-Host "GPU deployment is not complete yet."
    Write-Host "If the faster-whisper smoke test reports cublas64_12.dll missing, install CUDA Toolkit 12.x from NVIDIA and run this deployment again."
    Write-Host "If PyTorch is still CPU-only or torchaudio cannot load, run this tool again after confirming network access to https://download.pytorch.org/."
    Write-Host "Official CUDA Toolkit archive: https://developer.nvidia.com/cuda-toolkit-archive"
    Start-Process "https://developer.nvidia.com/cuda-toolkit-archive"
    if ($VerifyExitCode -ne 0) { exit $VerifyExitCode }
    if ($TorchVerifyExitCode -ne 0) { exit $TorchVerifyExitCode }
    exit $DeployExitCode
}

Write-Host "GPU deployment verified successfully."
