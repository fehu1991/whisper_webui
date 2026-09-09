param(
    [switch]$SmokeTest
)

$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $ProjectRoot
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

function Write-Section($Title) {
    Write-Host ""
    Write-Host "== $Title =="
}

function Find-DllOnPath($Name) {
    $sitePackages = Join-Path $ProjectRoot ".venv\Lib\site-packages"
    $extraEntries = @(
        (Join-Path $sitePackages "ctranslate2"),
        (Join-Path $sitePackages "torch\lib"),
        (Join-Path $sitePackages "nvidia\cublas\bin"),
        (Join-Path $sitePackages "nvidia\cudnn\bin"),
        (Join-Path $sitePackages "nvidia\cuda_runtime\bin")
    )
    if ($env:CUDA_PATH) {
        $extraEntries += Join-Path $env:CUDA_PATH "bin"
    }
    if ($env:CUDA_PATH_V12_8) {
        $extraEntries += Join-Path $env:CUDA_PATH_V12_8 "bin"
    }
    $cudaToolkitRoot = "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA"
    if (Test-Path $cudaToolkitRoot) {
        $extraEntries += Get-ChildItem -Path $cudaToolkitRoot -Directory -ErrorAction SilentlyContinue |
            Sort-Object Name -Descending |
            ForEach-Object { Join-Path $_.FullName "bin" }
    }
    $cudnnRoot = "C:\Program Files\NVIDIA\CUDNN"
    if (Test-Path $cudnnRoot) {
        $extraEntries += Get-ChildItem -Path $cudnnRoot -Directory -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -eq "bin" } |
            ForEach-Object { $_.FullName }
    }
    if (Test-Path (Join-Path $sitePackages "nvidia")) {
        $extraEntries += Get-ChildItem -Path (Join-Path $sitePackages "nvidia") -Directory -Recurse -ErrorAction SilentlyContinue |
            Where-Object { $_.Name -in @("bin", "lib") } |
            ForEach-Object { $_.FullName }
    }
    $pathEntries = @($extraEntries + ($env:PATH -split ";")) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -Unique
    foreach ($entry in $pathEntries) {
        $candidate = Join-Path $entry $Name
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }
    return $null
}

Write-Section "Project"
Write-Host "Project root: $ProjectRoot"
if (Test-Path $PythonExe) {
    Write-Host "Python: $PythonExe"
} else {
    Write-Host "Python virtual environment was not found. Run RunWhisper.cmd once first."
    exit 1
}

Write-Section "NVIDIA Driver"
if (Get-Command nvidia-smi -ErrorAction SilentlyContinue) {
    & nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
} else {
    Write-Host "nvidia-smi was not found. NVIDIA driver may be missing or not on PATH."
}

Write-Section "CUDA Toolkit and DLLs"
$cudaRoots = @(
    "C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA",
    "C:\Program Files\NVIDIA\CUDNN"
) | Where-Object { Test-Path $_ }

if ($cudaRoots.Count -gt 0) {
    foreach ($root in $cudaRoots) {
        Write-Host "Found: $root"
    }
} else {
    Write-Host "No CUDA Toolkit/cuDNN folder found in the default Program Files locations."
}

foreach ($dllName in @("cublas64_12.dll", "cudnn64_9.dll")) {
    $dllPath = Find-DllOnPath $dllName
    if ($dllPath) {
        Write-Host "${dllName}: FOUND at $dllPath"
    } else {
        Write-Host "${dllName}: NOT FOUND on PATH"
    }
}

Write-Section "Python GPU Status"
$runtimeDirs = @()
foreach ($dllName in @("cublas64_12.dll", "cudnn64_9.dll")) {
    $dllPath = Find-DllOnPath $dllName
    if ($dllPath) {
        $runtimeDirs += Split-Path -Parent $dllPath
    }
}
if ($runtimeDirs.Count -gt 0) {
    $env:PATH = (($runtimeDirs | Select-Object -Unique) -join ";") + ";" + $env:PATH
}

$env:WHISPER_GPU_SMOKE_TEST = if ($SmokeTest) { "1" } else { "0" }
$env:WHISPER_PROJECT_ROOT = $ProjectRoot
@'
import os
import sys
import tempfile
import wave
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

def line(label, value):
    print(f"{label}: {value}")

try:
    import ctranslate2
    line("ctranslate2", ctranslate2.__version__)
    line("ctranslate2 CUDA devices", ctranslate2.get_cuda_device_count())
    line("ctranslate2 CUDA compute types", sorted(ctranslate2.get_supported_compute_types("cuda")))
except Exception as exc:
    line("ctranslate2 error", repr(exc))

try:
    import torch
    line("torch", torch.__version__)
    line("torch CUDA available", torch.cuda.is_available())
    line("torch CUDA version", torch.version.cuda)
    line("torch CUDA devices", torch.cuda.device_count())
    if torch.cuda.is_available():
        line("torch CUDA device 0", torch.cuda.get_device_name(0))
    try:
        import torchaudio
        line("torchaudio", torchaudio.__version__)
        torch_base = torch.__version__.split("+", 1)[0].rsplit(".", 1)[0]
        torchaudio_base = torchaudio.__version__.split("+", 1)[0].rsplit(".", 1)[0]
        if torch_base != torchaudio_base:
            line("torch/torchaudio status", "VERSION MISMATCH - rerun WhisperTools.cmd option 4")
    except Exception as audio_exc:
        line("torchaudio error", repr(audio_exc))
except Exception as exc:
    line("torch error", repr(exc))

if os.environ.get("WHISPER_GPU_SMOKE_TEST") == "1":
    print("")
    print("== faster-whisper CUDA smoke test ==")
    try:
        from faster_whisper import WhisperModel

        project_root = Path(os.environ.get("WHISPER_PROJECT_ROOT", "."))
        download_root = project_root / "models"
        wav_path = Path(tempfile.gettempdir()) / "whisper_gpu_smoke_test.wav"
        sample_rate = 16000
        frames = b"\x00\x00" * sample_rate
        with wave.open(str(wav_path), "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(sample_rate)
            handle.writeframes(frames)

        model = WhisperModel(
            "base",
            device="cuda",
            compute_type="float16",
            download_root=str(download_root),
            local_files_only=True,
        )
        segments, info = model.transcribe(str(wav_path), beam_size=1, vad_filter=False)
        list(segments)
        line("smoke test", f"OK, detected language={info.language}")
    except Exception as exc:
        line("smoke test", "FAILED")
        line("reason", repr(exc))
        raise SystemExit(2)
'@ | & $PythonExe -
$PythonStatus = $LASTEXITCODE

Write-Host ""
if ($SmokeTest) {
    Write-Host "Smoke test finished. If it failed with a missing DLL, run WhisperTools.cmd option 6 or install the recommended CUDA runtime, then run this again."
} else {
    Write-Host "Diagnostics finished. Use WhisperTools.cmd option 2 and confirm the smoke test when prompted."
}
if ($SmokeTest -and $PythonStatus -ne 0) {
    exit $PythonStatus
}
