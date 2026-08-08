# ============================================================
#  Whisper 本機工具箱（中文版）
#  由 WhisperTools.cmd 啟動，集中管理：
#    - 系統環境偵測（GPU / CUDA / 套件 / 殘檔 健康檢查）
#    - 依賴下載、確認與更新
#    - Whisper 與 pyannote 模型更新
#  本檔請以 UTF-8 (含 BOM) 儲存，Windows PowerShell 5.1 才能正確顯示中文。
# ============================================================

$ErrorActionPreference = "Continue"
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

# 讓主控台以 UTF-8 輸出，中文與符號才不會變亂碼。
# 必須使用「不含 BOM」的 UTF-8：$OutputEncoding 會用於把 here-string 透過管線
# 送進 python 的 stdin，若帶 BOM 會讓 python 報 U+FEFF 語法錯誤。
try {
    $Utf8NoBom = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = $Utf8NoBom
    $OutputEncoding = $Utf8NoBom
} catch {}

$ProjectRoot  = Split-Path -Parent $MyInvocation.MyCommand.Path
$VenvPath     = Join-Path $ProjectRoot ".venv"
$Python       = Join-Path $VenvPath "Scripts\python.exe"
$SitePackages = Join-Path $VenvPath "Lib\site-packages"
$ModelDir     = Join-Path $ProjectRoot "models"
$PwSh         = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"

# faster-whisper 可用的模型尺寸（需與 app.py 介面一致）
$WhisperSizes = @("tiny", "base", "small", "medium", "large-v3")

# ------------------------------------------------------------
# 共用小工具
# ------------------------------------------------------------
function Write-Title($Text) {
    Write-Host ""
    Write-Host ("== " + $Text + " ==") -ForegroundColor Cyan
}

function Pause-Return {
    Write-Host ""
    Read-Host "按 Enter 返回主選單" | Out-Null
}

function Confirm-YesNo($Message) {
    $ans = (Read-Host ($Message + " (y/N)")).Trim().ToLower()
    return ($ans -eq "y" -or $ans -eq "yes" -or $ans -eq "是")
}

function Test-VenvPython {
    return (Test-Path $Python)
}

# 建立 venv（若不存在）。成功回傳 $true。
function Ensure-Venv {
    if (Test-VenvPython) { return $true }
    Write-Host "找不到專案虛擬環境 .venv，準備建立..." -ForegroundColor Yellow
    $sysPython = Get-Command python -ErrorAction SilentlyContinue
    if (-not $sysPython) {
        Write-Host "系統找不到 python，請先安裝 64 位元 Python 3.11、3.12 或 3.13 並加入 PATH。" -ForegroundColor Red
        return $false
    }
    & python -m venv $VenvPath
    if (-not (Test-VenvPython)) {
        Write-Host "建立虛擬環境失敗。" -ForegroundColor Red
        return $false
    }
    Write-Host "虛擬環境建立完成：$VenvPath" -ForegroundColor Green
    return $true
}

# 呼叫專案內既有的 PowerShell 腳本（可附加參數）
function Invoke-Child($ScriptName, [string[]]$ExtraArgs) {
    $path = Join-Path $ProjectRoot $ScriptName
    if (-not (Test-Path $path)) {
        Write-Host "找不到腳本：$ScriptName" -ForegroundColor Red
        return
    }
    if ($ExtraArgs) {
        & $PwSh -NoProfile -ExecutionPolicy Bypass -File $path @ExtraArgs
    } else {
        & $PwSh -NoProfile -ExecutionPolicy Bypass -File $path
    }
}

# 取得 site-packages 內以 ~ 開頭的殘檔資料夾（pip 中斷留下的）
function Get-LeftoverDirs {
    if (-not (Test-Path $SitePackages)) { return @() }
    return Get-ChildItem $SitePackages -Directory -Filter "~*" -ErrorAction SilentlyContinue
}

# ------------------------------------------------------------
# 3) 安裝／更新基本依賴
# ------------------------------------------------------------
function Install-BaseDeps {
    Write-Title "安裝已驗證的基本依賴 (requirements.lock)"
    if (-not (Ensure-Venv)) { return }
    & $Python -m pip install --upgrade pip
    & $Python -m pip install -r (Join-Path $ProjectRoot "requirements.lock")
    if ($LASTEXITCODE -eq 0) {
        Write-Host "基本依賴安裝／更新完成。" -ForegroundColor Green
    } else {
        Write-Host "安裝過程發生錯誤，請檢查網路或上方訊息。" -ForegroundColor Red
    }
}

# ------------------------------------------------------------
# 7) 檢查並更新已安裝套件（安全更新，避免覆蓋 CUDA 版 PyTorch）
# ------------------------------------------------------------
function Update-AllDeps {
    Write-Title "檢查並更新已安裝套件"
    if (-not (Test-VenvPython)) {
        Write-Host "尚未建立虛擬環境，請先執行選項 3。" -ForegroundColor Yellow
        return
    }

    Write-Host "目前可更新的套件清單：" -ForegroundColor Cyan
    & $Python -m pip list --outdated

    Write-Host ""
    Write-Host "注意：為避免把 GPU 版 PyTorch 覆蓋成 CPU 版，本動作只重新套用已驗證的依賴鎖，" -ForegroundColor Yellow
    Write-Host "      且不會主動升級 torch / torchaudio。CUDA 版 PyTorch 請改用選項 4。" -ForegroundColor Yellow
    if (-not (Confirm-YesNo "要依 requirements 更新專案依賴嗎？")) {
        Write-Host "已取消。"
        return
    }

    & $Python -m pip install --upgrade pip
    # only-if-needed：torch 等相依套件除非版本限制要求，否則不動，避免拉到 PyPI 的 CPU 版
    & $Python -m pip install --upgrade-strategy only-if-needed `
        -r (Join-Path $ProjectRoot "requirements.lock")
    $diar = Join-Path $ProjectRoot "requirements-diarization.lock"
    if (Test-Path $diar) {
        & $Python -m pip install --upgrade --upgrade-strategy only-if-needed `
            -r $diar `
            -c (Join-Path $ProjectRoot "constraints-verified.txt")
    }

    Write-Host ""
    Write-Host "檢查相依衝突 (pip check)：" -ForegroundColor Cyan
    & $Python -m pip check

    # 更新後再確認 PyTorch 是否仍為 GPU 版
@'
import sys
sys.stdout.reconfigure(encoding="utf-8")
try:
    import torch
    if "+cpu" in torch.__version__ or not torch.cuda.is_available():
        print("")
        print(f"[警告] 目前 PyTorch 為 {torch.__version__}，CUDA 不可用。")
        print("       若需要 GPU 說話人分離，請執行選項 4 重新安裝 cu128 版 PyTorch。")
    else:
        print("")
        print(f"PyTorch 仍為 GPU 版：{torch.__version__}（CUDA {torch.version.cuda}）")
except Exception:
    pass
'@ | & $Python -

    Write-Host ""
    Write-Host "依賴確認與更新完成。" -ForegroundColor Green
}

# ------------------------------------------------------------
# 8) 修復環境（清除殘檔 / 檢查相依 / 可選重建 venv）
# ------------------------------------------------------------
function Repair-Environment {
    Write-Title "修復環境"
    if (-not (Test-Path $SitePackages)) {
        Write-Host "尚未建立虛擬環境，無需修復。請先執行選項 3。" -ForegroundColor Yellow
        return
    }

    $leftovers = Get-LeftoverDirs
    if ($leftovers.Count -gt 0) {
        Write-Host "發現以下 pip 中斷殘留資料夾：" -ForegroundColor Yellow
        foreach ($l in $leftovers) { Write-Host ("  - " + $l.FullName) }
        if (Confirm-YesNo "要刪除這些殘留資料夾嗎？") {
            foreach ($l in $leftovers) {
                try {
                    Remove-Item -LiteralPath $l.FullName -Recurse -Force -ErrorAction Stop
                    Write-Host ("  已刪除：" + $l.Name) -ForegroundColor Green
                } catch {
                    Write-Host ("  刪除失敗：" + $l.Name + " — " + $_.Exception.Message) -ForegroundColor Red
                }
            }
        }
    } else {
        Write-Host "未發現殘留資料夾。" -ForegroundColor Green
    }

    Write-Host ""
    Write-Host "檢查相依衝突 (pip check)：" -ForegroundColor Cyan
    & $Python -m pip check

    Write-Host ""
    Write-Host "若環境已嚴重損壞，可整個重建虛擬環境（會刪除 .venv 後重裝基本依賴）。" -ForegroundColor Yellow
    if (Confirm-YesNo "要刪除並重建 .venv 嗎？（耗時，需重新下載套件）") {
        try {
            Remove-Item -LiteralPath $VenvPath -Recurse -Force -ErrorAction Stop
            Write-Host "已刪除舊的 .venv。" -ForegroundColor Green
        } catch {
            Write-Host ("刪除 .venv 失敗：" + $_.Exception.Message) -ForegroundColor Red
            return
        }
        if (Ensure-Venv) {
            & $Python -m pip install --upgrade pip
            & $Python -m pip install `
                -r (Join-Path $ProjectRoot "requirements.lock")
            Write-Host "已重建虛擬環境並安裝基本依賴。GPU 版 PyTorch 請再執行選項 4。" -ForegroundColor Green
        }
    }
}

# ------------------------------------------------------------
# 9) 檢視／下載／更新 Whisper 模型
# ------------------------------------------------------------
function Manage-WhisperModels {
    Write-Title "Whisper 模型管理"
    if (-not (Test-VenvPython)) {
        Write-Host "尚未建立虛擬環境，請先執行選項 3。" -ForegroundColor Yellow
        return
    }

    Write-Host "模型存放路徑：$ModelDir"
    Write-Host "目前狀態：" -ForegroundColor Cyan
    foreach ($s in $WhisperSizes) {
        $dir = Join-Path $ModelDir ("models--Systran--faster-whisper-" + $s)
        if (Test-Path $dir) {
            $sum = (Get-ChildItem $dir -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
            $mb = if ($sum) { [math]::Round($sum / 1MB, 1) } else { 0 }
            Write-Host ("  " + $s.PadRight(10) + "：已下載（" + $mb + " MB）") -ForegroundColor Green
        } else {
            Write-Host ("  " + $s.PadRight(10) + "：未下載")
        }
    }

    Write-Host ""
    Write-Host "可輸入：單一模型名稱（如 base）、all（全部）、或直接 Enter 略過。"
    $sel = (Read-Host "要下載／更新哪個模型").Trim().ToLower()
    if (-not $sel) { Write-Host "未選擇，略過。"; return }
    if ($sel -ne "all" -and ($WhisperSizes -notcontains $sel)) {
        Write-Host ("無效的模型名稱：" + $sel) -ForegroundColor Red
        return
    }

    $env:WT_MODEL_SIZE = $sel
    $env:WT_MODEL_DIR  = $ModelDir
@'
import os, sys
sys.stdout.reconfigure(encoding="utf-8")
from faster_whisper import download_model

size  = os.environ["WT_MODEL_SIZE"]
cache = os.environ["WT_MODEL_DIR"]
sizes = ["tiny", "base", "small", "medium", "large-v3"] if size == "all" else [size]

rc = 0
for s in sizes:
    print(f"下載／更新模型：{s} ...")
    try:
        path = download_model(s, cache_dir=cache)
        print(f"  完成：{s} -> {path}")
    except Exception as exc:
        rc = 1
        print(f"  失敗：{s} — {exc!r}")

sys.exit(rc)
'@ | & $Python -

    if ($LASTEXITCODE -eq 0) {
        Write-Host "模型下載／更新完成。" -ForegroundColor Green
    } else {
        Write-Host "部分模型下載失敗，請檢查網路或上方訊息。" -ForegroundColor Red
    }
}

# ------------------------------------------------------------
# 主選單
# ------------------------------------------------------------
function Show-Menu {
    Clear-Host
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host "        Whisper 本機工具箱（中文版）" -ForegroundColor Cyan
    Write-Host "============================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  系統環境"
    Write-Host "    1) 跨電腦環境檢測（CPU / GPU / CUDA / 套件 / 模型）"
    Write-Host "    2) GPU 診斷與 faster-whisper CUDA 試跑"
    Write-Host ""
    Write-Host "  依賴管理"
    Write-Host "    3) 安裝已驗證的基本依賴 (requirements.lock)"
    Write-Host "    4) 安裝／更新 GPU 版 PyTorch (CUDA cu128)"
    Write-Host "    5) 安裝／更新說話人分離依賴 (pyannote)"
    Write-Host "    6) 一鍵部署完整 GPU 環境"
    Write-Host "    7) 檢查並更新已安裝套件（安全更新）"
    Write-Host "    8) 修復環境（清除殘檔 / 檢查相依 / 重建）"
    Write-Host ""
    Write-Host "  模型管理"
    Write-Host "    9) 檢視／下載／更新 Whisper 模型"
    Write-Host "   10) 下載本機 pyannote 模型（離線用）"
    Write-Host "   11) 驗證說話人分離模型存取"
    Write-Host ""
    Write-Host "  執行"
    Write-Host "   12) 啟動 Whisper 介面"
    Write-Host ""
    Write-Host "    Q) 離開"
    Write-Host ""
}

:mainloop while ($true) {
    Show-Menu
    $choice = (Read-Host "請輸入選項").Trim()

    switch ($choice.ToLower()) {
        "1"  { Invoke-Child "scripts\bootstrap_scan.ps1"; Pause-Return }
        "2"  {
            if (Confirm-YesNo "要一併執行 faster-whisper CUDA 試跑 (smoke test) 嗎？") {
                Invoke-Child "gpu_diagnostics.ps1" @("-SmokeTest")
            } else {
                Invoke-Child "gpu_diagnostics.ps1"
            }
            Pause-Return
        }
        "3"  { Install-BaseDeps; Pause-Return }
        "4"  { Invoke-Child "install_torch_cuda.ps1"; Pause-Return }
        "5"  { Invoke-Child "install_diarization.ps1"; Pause-Return }
        "6"  { Invoke-Child "deploy_gpu_environment.ps1"; Pause-Return }
        "7"  { Update-AllDeps; Pause-Return }
        "8"  { Repair-Environment; Pause-Return }
        "9"  { Manage-WhisperModels; Pause-Return }
        "10" { Invoke-Child "prepare_pyannote_model.ps1"; Pause-Return }
        "11" { Invoke-Child "verify_diarization.ps1"; Pause-Return }
        "12" { & $PwSh -NoProfile -ExecutionPolicy Bypass -File (Join-Path $ProjectRoot "start.ps1"); Pause-Return }
        "q"  { Write-Host "再見。"; break mainloop }
        default { Write-Host "無效選項，請重新輸入。" -ForegroundColor Yellow; Start-Sleep -Milliseconds 800 }
    }
}
