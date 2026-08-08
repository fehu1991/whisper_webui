$ErrorActionPreference = "Stop"

param(
    [string]$TargetDir = "models\pyannote-speaker-diarization-community-1"
)

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$TargetPath = Join-Path $ProjectRoot $TargetDir

if (-not (Test-Path $PythonExe)) {
    throw "Python virtual environment not found. Run WhisperTools.cmd option 3 first."
}

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

$env:PYANNOTE_TARGET_DIR = $TargetPath

@'
import os
import sys
from huggingface_hub import snapshot_download

target_dir = os.environ["PYANNOTE_TARGET_DIR"]
try:
    snapshot_download(
        repo_id="pyannote/speaker-diarization-community-1",
        token=os.environ["HF_TOKEN"],
        local_dir=target_dir,
    )
    print(f"Model downloaded to: {target_dir}")
except Exception as exc:
    message = str(exc)
    print("")
    print("Model download failed.")
    if "public gated repositories" in message or "403 Forbidden" in message:
        print("Reason: Hugging Face token cannot access this gated model.")
        print("Fix:")
        print("1. Open https://huggingface.co/pyannote/speaker-diarization-community-1")
        print("2. Log in and accept the model conditions.")
        print("3. Edit or recreate your token and enable access to public gated repositories.")
        print("4. Run WhisperTools.cmd option 10 again.")
    elif "401" in message or "Unauthorized" in message:
        print("Reason: Hugging Face token is invalid or lacks read permission.")
        print("Fix: Create a new read token and run WhisperTools.cmd option 10 again.")
    else:
        print(type(exc).__name__)
        print(message)
    sys.exit(1)
'@ | & $PythonExe -
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host ""
Write-Host "For offline use, paste this folder into the UI:"
Write-Host $TargetPath
Write-Host "Or set PYANNOTE_MODEL_DIR to this folder."
