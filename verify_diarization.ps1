$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $PythonExe)) {
    throw "Python virtual environment not found. Run WhisperTools.cmd option 3 first."
}

$env:MPLCONFIGDIR = Join-Path $ProjectRoot ".cache\matplotlib"
New-Item -ItemType Directory -Force -Path $env:MPLCONFIGDIR | Out-Null

if (-not $env:HF_TOKEN) {
    $secureToken = Read-Host "Enter Hugging Face token" -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken)
    try {
        $env:HF_TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr)
    }
    finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
}

@'
import math
import os
import sys
import warnings
import wave
from pathlib import Path

warnings.filterwarnings("ignore", message=".*torchcodec is not installed correctly.*")
warnings.filterwarnings("ignore", category=UserWarning, module=r"pyannote\.audio\.core\.io")

import torch
from pyannote.audio import Pipeline

import app

try:
    print("Loading pyannote speaker diarization pipeline...")
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-community-1",
        token=os.environ["HF_TOKEN"],
    )
    print("Pipeline loaded.")
    print(f"Torch CUDA available: {torch.cuda.is_available()}")

    test_audio = Path("transcriptions") / "_diarization_verify.wav"
    rate = 16000
    seconds = 2.0
    with wave.open(str(test_audio), "w") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(rate)
        frames = bytearray()
        for i in range(int(rate * seconds)):
            value = int(900 * math.sin(2 * math.pi * 220 * i / rate))
            frames.extend(value.to_bytes(2, "little", signed=True))
        wav.writeframes(frames)

    segments, status = app._run_diarization(
        str(test_audio),
        os.environ["HF_TOKEN"],
        "cpu",
        "",
        0,
        0,
        0,
    )
    print("Diarization executed.")
    print(status)
    print(f"Speaker segments: {len(segments)}")
    try:
        test_audio.unlink()
    except OSError:
        pass
except Exception as exc:
    try:
        test_audio.unlink()
    except Exception:
        pass
    message = str(exc)
    print("")
    print("Diarization verification failed.")
    if "public gated repositories" in message or "403 Forbidden" in message:
        print("Reason: Hugging Face token cannot access this gated model.")
        print("Fix:")
        print("1. Open https://huggingface.co/pyannote/speaker-diarization-community-1")
        print("2. Log in and accept the model conditions.")
        print("3. Edit or recreate your token and enable access to public gated repositories.")
        print("4. Run WhisperTools.cmd option 11 again.")
    elif "401" in message or "Unauthorized" in message:
        print("Reason: Hugging Face token is invalid or lacks read permission.")
        print("Fix: Create a new read token and run WhisperTools.cmd option 11 again.")
    else:
        print(type(exc).__name__)
        print(message)
    sys.exit(1)
'@ | & $PythonExe -
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}
