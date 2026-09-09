$ErrorActionPreference = "Stop"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

try {
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [Console]::InputEncoding = $Utf8NoBom
    [Console]::OutputEncoding = $Utf8NoBom
    $OutputEncoding = $Utf8NoBom
} catch {}

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonExe = Join-Path $VenvPath "Scripts\python.exe"
$ModelDir = Join-Path $ProjectRoot "models"
$BaseLock = Join-Path $ProjectRoot "requirements.lock"
$DiarizationLock = Join-Path $ProjectRoot "requirements-diarization.lock"
$Constraints = Join-Path $ProjectRoot "constraints-verified.txt"
$BootstrapScan = Join-Path $ProjectRoot "scripts\bootstrap_scan.ps1"
$WhisperSizes = @("base", "small", "medium", "large-v3")
$DiarizationModelDir = Join-Path $ModelDir "pyannote-speaker-diarization-community-1"
$MinimumFreeGb = 15
$OriginalHfToken = $env:HF_TOKEN
$DiarizationDownloadFailed = $false

function Write-Section([string]$Title) {
    Write-Host ""
    Write-Host ("== " + $Title + " ==") -ForegroundColor Cyan
}

function Invoke-Checked(
    [string]$Executable,
    [string[]]$Arguments,
    [string]$Label
) {
    Write-Host $Label -ForegroundColor Yellow
    & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ("{0}失敗，結束代碼：{1}。" -f $Label, $LASTEXITCODE)
    }
}

function Get-ExecutablePath($Command) {
    if ($Command.Path) { return $Command.Path }
    return $Command.Source
}

function Get-PythonInfo(
    [string]$Executable,
    [string[]]$Arguments
) {
    try {
        $code = "import json, struct, sys; print(json.dumps({'version': '.'.join(map(str, sys.version_info[:3])), 'major': sys.version_info.major, 'minor': sys.version_info.minor, 'bits': struct.calcsize('P') * 8}))"
        $raw = (& $Executable @Arguments -c $code 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or -not $raw) { return $null }
        return ($raw | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Test-SupportedPython($Info) {
    return (
        $Info -and
        [int]$Info.major -eq 3 -and
        [int]$Info.minor -in @(11, 12, 13) -and
        [int]$Info.bits -eq 64
    )
}

function Get-CompatiblePython {
    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        $pyPath = Get-ExecutablePath $py
        foreach ($minor in @(13, 12, 11)) {
            $arguments = @("-3.$minor")
            $info = Get-PythonInfo $pyPath $arguments
            if (Test-SupportedPython $info) {
                return [pscustomobject]@{
                    Executable = $pyPath
                    Arguments = $arguments
                    Info = $info
                }
            }
        }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        $pythonPath = Get-ExecutablePath $python
        $info = Get-PythonInfo $pythonPath @()
        if (Test-SupportedPython $info) {
            return [pscustomobject]@{
                Executable = $pythonPath
                Arguments = @()
                Info = $info
            }
        }
    }

    return $null
}

function Read-SecretToken {
    $secure = Read-Host "貼上 Hugging Face Read token（輸入時不會顯示；直接按 Enter 可略過）" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        return [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
    }
}

function Get-ProjectDriveFreeGb {
    $projectItem = Get-Item -LiteralPath $ProjectRoot
    $drive = Get-PSDrive -Name $projectItem.PSDrive.Name
    return [math]::Round(($drive.Free / 1GB), 1)
}

function Test-AllWhisperModelsReady {
    foreach ($size in $WhisperSizes) {
        $path = Join-Path $ModelDir ("models--Systran--faster-whisper-" + $size)
        if (-not (Test-Path -LiteralPath $path -PathType Container)) {
            return $false
        }
    }
    return $true
}

try {
    Clear-Host
    Write-Host "Whisper 本機轉錄工作台：首次部署" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "本程式會在目前資料夾建立專用 Python 環境，安裝必要套件，"
    Write-Host "並下載 base、small、medium、large-v3 四個 Whisper 模型。"
    Write-Host "原始模型約 5 GB；安裝套件與快取後會占用更多空間。"

    Write-Section "電腦與發布檔案檢查"
    if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
        throw "這個發布版只支援 Windows。"
    }
    if ([Environment]::OSVersion.Version.Major -lt 10) {
        throw "這個發布版只支援 Windows 10 或 Windows 11。"
    }
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw "這個發布版只支援 64 位元 Windows。"
    }

    $requiredFiles = @(
        $BaseLock,
        $DiarizationLock,
        $Constraints,
        $BootstrapScan,
        (Join-Path $ProjectRoot "app.py"),
        (Join-Path $ProjectRoot "RunWhisper.cmd"),
        (Join-Path $ProjectRoot "WhisperDoctor.cmd"),
        (Join-Path $ProjectRoot "WhisperTools.cmd")
    )
    foreach ($required in $requiredFiles) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw ("發布檔案不完整，缺少：{0}" -f $required)
        }
    }

    $python = Get-CompatiblePython
    if (-not $python) {
        throw "找不到 64 位元 Python 3.11、3.12 或 3.13。請安裝 Python 3.13 x64，安裝時勾選 Add python.exe to PATH，完成後再執行本檔。"
    }
    Write-Host ("Windows：{0}（64 位元）" -f [Environment]::OSVersion.VersionString) -ForegroundColor Green
    Write-Host ("Python：{0}（{1} 位元）" -f $python.Info.version, $python.Info.bits) -ForegroundColor Green

    $freeSpaceGb = Get-ProjectDriveFreeGb
    Write-Host ("目前磁碟可用空間：{0} GB" -f $freeSpaceGb)
    $needsLargeDownload = -not (Test-AllWhisperModelsReady)
    if ($needsLargeDownload -and $freeSpaceGb -lt $MinimumFreeGb) {
        throw ("磁碟空間不足。首次部署至少需要 {0} GB 可用空間，建議保留 20 GB。" -f $MinimumFreeGb)
    }

    Write-Host ""
    $startAnswer = (Read-Host "按 Enter 開始部署；輸入 Q 可離開").Trim().ToLowerInvariant()
    if ($startAnswer -eq "q") {
        Write-Host "已取消部署。"
        exit 0
    }

    Write-Section "建立專用 Python 環境"
    if (Test-Path -LiteralPath $PythonExe -PathType Leaf) {
        $venvInfo = Get-PythonInfo $PythonExe @()
        if (-not (Test-SupportedPython $venvInfo)) {
            throw "現有 .venv 使用不支援的 Python。請先將 .venv 資料夾改名備份，再重新執行部署。"
        }
        Write-Host ("沿用現有 .venv：Python {0}（{1} 位元）" -f $venvInfo.version, $venvInfo.bits) -ForegroundColor Green
    } else {
        $venvArguments = @($python.Arguments) + @("-m", "venv", $VenvPath)
        Invoke-Checked $python.Executable $venvArguments "建立 .venv"
    }

    if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
        throw ("無法建立專用 Python：{0}" -f $PythonExe)
    }

    Write-Section "安裝基本套件"
    Invoke-Checked $PythonExe @("-m", "pip", "install", "--upgrade", "pip") "更新 pip"
    Invoke-Checked $PythonExe @("-m", "pip", "install", "-r", $BaseLock) "安裝 Whisper 與操作介面"
    Invoke-Checked $PythonExe @("-c", "import faster_whisper, gradio, imageio_ffmpeg; print('Base runtime: OK')") "檢查基本套件"

    Write-Section "下載 Whisper 模型"
    New-Item -ItemType Directory -Path $ModelDir -Force | Out-Null
    $env:DEPLOY_MODEL_DIR = $ModelDir
    $env:DEPLOY_MODEL_SIZES = $WhisperSizes -join ","
    @'
import os
import sys

from faster_whisper import download_model

sys.stdout.reconfigure(encoding="utf-8")
model_dir = os.environ["DEPLOY_MODEL_DIR"]
sizes = [item.strip() for item in os.environ["DEPLOY_MODEL_SIZES"].split(",") if item.strip()]
exit_code = 0

for size in sizes:
    print(f"下載或檢查 Whisper 模型：{size}")
    try:
        path = download_model(size, cache_dir=model_dir)
        print(f"  完成：{path}")
    except Exception as exc:
        exit_code = 1
        print(f"  失敗：{size}：{exc!r}")

raise SystemExit(exit_code)
'@ | & $PythonExe -
    if ($LASTEXITCODE -ne 0) {
        throw "部分 Whisper 模型下載失敗。請確認網路與磁碟空間後，重新執行 DeployWhisper.cmd；已完成的檔案不會重複下載。"
    }

    $env:DEPLOY_VERIFY_MODEL_DIR = $ModelDir
    @'
import os
import sys
from faster_whisper import WhisperModel

sys.stdout.reconfigure(encoding="utf-8")
print("檢查 base 模型是否能以 CPU 載入⋯⋯")
WhisperModel(
    "base",
    device="cpu",
    compute_type="int8",
    download_root=os.environ["DEPLOY_VERIFY_MODEL_DIR"],
    local_files_only=True,
)
print("Whisper CPU 模型載入：正常")
'@ | & $PythonExe -
    if ($LASTEXITCODE -ne 0) {
        throw "模型已下載，但 CPU 載入測試失敗。請安裝最新版 Microsoft Visual C++ x64 Runtime，再重新執行。"
    }

    Write-Section "選用：說話人標註"
    Write-Host "說話人標註會產生 SPEAKER_00、SPEAKER_01 等匿名標籤，"
    Write-Host "只能分辨不同聲音，無法判斷真實姓名。"
    $downloadDiarization = (Read-Host "是否安裝 pyannote 說話人標註？直接按 Enter 代表是；輸入 N 略過 (Y/n)").Trim().ToLowerInvariant()
    if ($downloadDiarization -notin @("n", "no", "否")) {
        $token = $env:HF_TOKEN
        if (-not $token) {
            Write-Host ""
            Write-Host "請先用瀏覽器完成兩件事：" -ForegroundColor Yellow
            Write-Host "1. 登入並接受模型條款：https://huggingface.co/pyannote/speaker-diarization-community-1"
            Write-Host "2. 建立 Read token：https://huggingface.co/settings/tokens"
            Write-Host ""
            $token = Read-SecretToken
        }

        if ([string]::IsNullOrWhiteSpace($token)) {
            Write-Host "未輸入 token，已略過 pyannote。Whisper 語音轉文字仍可正常使用。" -ForegroundColor Yellow
        } else {
            $env:HF_TOKEN = $token
            Write-Host ""
            Invoke-Checked $PythonExe @("-m", "pip", "install", "-r", $DiarizationLock, "-c", $Constraints) "安裝 pyannote 與 CPU 版 PyTorch"
            Invoke-Checked $PythonExe @("-c", "import torch; from pyannote.audio import Pipeline; print('Diarization runtime: OK')") "檢查說話人標註套件"

            $env:DEPLOY_DIARIZATION_DIR = $DiarizationModelDir
            @'
import os
import sys
from huggingface_hub import snapshot_download

sys.stdout.reconfigure(encoding="utf-8")
target_dir = os.environ["DEPLOY_DIARIZATION_DIR"]
print("下載 pyannote speaker-diarization-community-1⋯⋯")
snapshot_download(
    repo_id="pyannote/speaker-diarization-community-1",
    token=os.environ["HF_TOKEN"],
    local_dir=target_dir,
)
print(f"pyannote 模型下載完成：{target_dir}")
'@ | & $PythonExe -
            if ($LASTEXITCODE -ne 0) {
                $DiarizationDownloadFailed = $true
                Write-Host "pyannote 下載失敗。Whisper 轉錄已可使用；請確認模型條款與 token 權限後，執行 WhisperTools.cmd 的選項 10。" -ForegroundColor Red
            }
        }
    } else {
        Write-Host "已略過 pyannote。日後可用 WhisperTools.cmd 的選項 5、10、11 安裝與驗證。"
    }

    Write-Section "建立輸出資料夾"
    New-Item -ItemType Directory -Path (Join-Path $ProjectRoot "transcriptions") -Force | Out-Null
    New-Item -ItemType Directory -Path (Join-Path $ProjectRoot ".cache") -Force | Out-Null
    Write-Host ("程式資料夾：{0}" -f $ProjectRoot)
    Write-Host ("模型資料夾：{0}" -f $ModelDir)

    Write-Section "部署結果"
    if ($DiarizationDownloadFailed) {
        Write-Host "Whisper 轉錄已完成部署；pyannote 尚未完成。" -ForegroundColor Yellow
        Write-Host "下一步：雙擊 WhisperDoctor.cmd，再雙擊 RunWhisper.cmd。"
        exit 1
    }

    Write-Host "部署完成。" -ForegroundColor Green
    Write-Host "下一步：" -ForegroundColor Cyan
    Write-Host "1. 雙擊 WhisperDoctor.cmd 檢查環境。"
    Write-Host "2. 雙擊 RunWhisper.cmd 啟動介面。"
    Write-Host "3. NVIDIA 使用者若要 GPU 加速，再開啟 WhisperTools.cmd，執行選項 6 與選項 2。"
    Write-Host "4. 如需即時收音及邊聽邊改文字稿，再執行 DeployLive.cmd；會議前請先完成部署與離線測試。"
    exit 0
} catch {
    Write-Host ""
    Write-Host ("部署中止：" + $_.Exception.Message) -ForegroundColor Red
    Write-Host ""
    Write-Host "可先檢查以下項目："
    Write-Host "- Python 必須是 64 位元 3.11、3.12 或 3.13；建議安裝 3.13。"
    Write-Host "- 磁碟至少保留 15 GB，建議 20 GB。"
    Write-Host "- 網路中斷時可直接重新執行 DeployWhisper.cmd。"
    Write-Host "- 若出現 DLL load failed，安裝：https://aka.ms/vc14/vc_redist.x64.exe"
    exit 1
} finally {
    $env:DEPLOY_MODEL_DIR = $null
    $env:DEPLOY_MODEL_SIZES = $null
    $env:DEPLOY_VERIFY_MODEL_DIR = $null
    $env:DEPLOY_DIARIZATION_DIR = $null
    if ($null -eq $OriginalHfToken) {
        $env:HF_TOKEN = $null
    } else {
        $env:HF_TOKEN = $OriginalHfToken
    }
}
