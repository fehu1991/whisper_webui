from __future__ import annotations

import re
from typing import Any


SUPPORTED_PYTHON_MINORS = {(3, 11), (3, 12), (3, 13)}


def _python_minor(value: Any) -> tuple[int, int] | None:
    match = re.search(r"(\d+)\.(\d+)", str(value or ""))
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2))


def _recommendation(
    code: str,
    severity: str,
    title: str,
    reason: str,
    action: str,
    *,
    requires_confirmation: bool = False,
    estimated_download_mb: int = 0,
    restart_required: bool = False,
) -> dict[str, Any]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "reason": reason,
        "action": action,
        "requires_confirmation": requires_confirmation,
        "estimated_download_mb": estimated_download_mb,
        "restart_required": restart_required,
    }


def build_recommendations(report: dict[str, Any]) -> list[dict[str, Any]]:
    recommendations: list[dict[str, Any]] = []

    python_status = report.get("python", {})
    if not python_status.get("project_available"):
        recommendations.append(
            _recommendation(
                "ENV-PYTHON-MISSING",
                "blocking",
                "尚未建立專案 Python 環境",
                "找不到專案專用的虛擬環境，因此無法載入轉錄套件。",
                "執行 WhisperTools.cmd，選擇選項 3 建立環境並安裝基本依賴。",
                requires_confirmation=True,
                estimated_download_mb=100,
            )
        )
    else:
        project_version = _python_minor(
            python_status.get("project_version")
        )
        if (
            project_version is not None
            and project_version not in SUPPORTED_PYTHON_MINORS
        ):
            recommendations.append(
                _recommendation(
                    "ENV-PYTHON-UNSUPPORTED",
                    "blocking",
                    "Python 版本不在已驗證範圍",
                    (
                        "目前專案環境為 Python "
                        f"{project_version[0]}.{project_version[1]}，"
                        "已驗證版本為 3.11、3.12 與 3.13。"
                    ),
                    (
                        "安裝 64 位元 Python 3.13，重新建立 .venv，"
                        "再執行環境檢測與 CPU 試跑。"
                    ),
                    requires_confirmation=True,
                )
            )

    disks = report.get("disks", [])
    project_disk = disks[0] if disks else {}
    free_gb = float(project_disk.get("free_gb") or 0)
    if free_gb and free_gb < 10:
        recommendations.append(
            _recommendation(
                "ENV-DISK-LOW",
                "blocking",
                "專案磁碟可用空間不足",
                f"專案所在磁碟只剩 {free_gb:.1f}GB。",
                "先釋放至少 10GB；空間有限時只安裝 CPU 環境並使用較小模型。",
            )
        )
    elif free_gb and free_gb < 20:
        recommendations.append(
            _recommendation(
                "ENV-DISK-LOW",
                "warning",
                "專案磁碟空間偏低",
                f"目前可用 {free_gb:.1f}GB；GPU 套件與模型可能占用超過 10GB。",
                "優先使用 small 以下模型，安裝完成後清除舊套件快取。",
            )
        )

    gpus = report.get("gpus", [])
    nvidia_gpus = [gpu for gpu in gpus if gpu.get("vendor") == "nvidia"]
    non_nvidia_gpus = [
        gpu
        for gpu in gpus
        if gpu.get("vendor") in {"amd", "intel"}
    ]

    if not nvidia_gpus:
        gpu_names = ", ".join(str(gpu.get("name")) for gpu in non_nvidia_gpus)
        reason = (
            f"偵測到 {gpu_names}，但目前支援的 GPU 加速路徑需要 NVIDIA CUDA。"
            if gpu_names
            else "未偵測到可使用 CUDA 的 NVIDIA GPU。"
        )
        recommendations.append(
            _recommendation(
                "ENV-CUDA-HARDWARE-UNAVAILABLE",
                "info",
                "建議使用 CPU 轉錄設定",
                reason,
                "裝置選擇 cpu、精度選擇 int8，模型先從 tiny、base 或 small 開始。",
            )
        )
    elif not any(gpu.get("nvidia_smi_ready") for gpu in nvidia_gpus):
        recommendations.append(
            _recommendation(
                "ENV-NVIDIA-DRIVER-MISSING",
                "blocking",
                "NVIDIA 驅動尚未就緒",
                "已偵測到 NVIDIA GPU，但 nvidia-smi 無法讀取裝置狀態。",
                "安裝或修復 NVIDIA 官方顯示驅動，重新啟動 Windows 後再次檢測。",
                requires_confirmation=True,
                restart_required=True,
            )
        )

    runtimes = report.get("runtimes", {})
    ctranslate2 = runtimes.get("ctranslate2", {})
    if nvidia_gpus and not ctranslate2.get("cuda_ready"):
        recommendations.append(
            _recommendation(
                "ENV-CT2-CUDA-MISSING",
                "warning",
                "Whisper CUDA 執行環境尚未就緒",
                ctranslate2.get("note")
                or "CTranslate2 無法使用已偵測到的 NVIDIA GPU。",
                "執行 WhisperTools.cmd 選項 6 部署 GPU 環境，再以選項 2 執行 CUDA 試跑。",
                requires_confirmation=True,
                estimated_download_mb=3000,
            )
        )

    dlls = runtimes.get("dlls", {})
    if nvidia_gpus and not dlls.get("cublas64_12"):
        recommendations.append(
            _recommendation(
                "ENV-CUBLAS-MISSING",
                "warning",
                "缺少 CUDA BLAS 執行元件",
                "在專案與系統執行路徑中找不到 cublas64_12.dll。",
                "執行 WhisperTools.cmd 選項 6 部署 GPU 環境，完成後重新檢測。",
                requires_confirmation=True,
                estimated_download_mb=3000,
            )
        )

    torch_status = runtimes.get("torch", {})
    if torch_status.get("available") and not torch_status.get("cuda_ready"):
        recommendations.append(
            _recommendation(
                "ENV-TORCH-CPU-ONLY",
                "warning",
                "說話人分離目前只能使用 CPU",
                torch_status.get("note")
                or "目前安裝的 PyTorch 無法使用 CUDA。",
                "如需 GPU 說話人分離，執行 WhisperTools.cmd 選項 4 安裝 CUDA 版 PyTorch。",
                requires_confirmation=True,
                estimated_download_mb=3000,
            )
        )

    if torch_status.get("version_mismatch"):
        recommendations.append(
            _recommendation(
                "ENV-TORCH-AUDIO-MISMATCH",
                "blocking",
                "torch 與 torchaudio 版本不一致",
                "兩個套件必須使用相同的主要與次要版本。",
                "執行 WhisperTools.cmd 選項 4，從同一來源重新安裝兩個套件。",
                requires_confirmation=True,
                estimated_download_mb=3000,
            )
        )

    packages = report.get("packages", {})
    if not packages.get("pyannote.audio", {}).get("installed"):
        recommendations.append(
            _recommendation(
                "ENV-PYANNOTE-MISSING",
                "info",
                "尚未安裝說話人分離功能",
                "基本 Whisper 轉錄功能仍可正常使用。",
                "需要說話人標籤時，再執行 WhisperTools.cmd 選項 5 安裝選用依賴。",
                requires_confirmation=True,
                estimated_download_mb=1000,
            )
        )

    models = report.get("models", {})
    if not models.get("whisper"):
        recommendations.append(
            _recommendation(
                "ENV-WHISPER-MODEL-MISSING",
                "info",
                "尚未下載 Whisper 模型",
                "找不到已快取的 faster-whisper 模型；首次轉錄需要下載。",
                (
                    "先以 tiny 或 base 執行一次短音訊測試；"
                    "確認可用後再下載較大的模型。"
                ),
                requires_confirmation=True,
                estimated_download_mb=1500,
            )
        )
    if (
        packages.get("pyannote.audio", {}).get("installed")
        and not models.get("pyannote", {}).get("available")
    ):
        recommendations.append(
            _recommendation(
                "ENV-PYANNOTE-MODEL-MISSING",
                "warning",
                "缺少說話人分離模型",
                "找不到本機 pyannote community-1 模型。",
                "接受模型條款後執行 WhisperTools.cmd 選項 10，或在介面選擇既有模型資料夾。",
                requires_confirmation=True,
                estimated_download_mb=1000,
            )
        )

    wheel_cache = (
        report.get("storage", {}).get("wheel_cache", {})
    )
    cleanup_count = int(
        wheel_cache.get("cleanup_candidate_count") or 0
    )
    cleanup_size_mb = float(
        wheel_cache.get("cleanup_candidate_size_mb") or 0
    )
    if cleanup_count > 0:
        recommendations.append(
            _recommendation(
                "ENV-CACHE-CLEANUP",
                "info",
                "可以清理舊安裝快取",
                (
                    f"找到 {cleanup_count} 組超過 14 天的舊 wheel "
                    f"快取，共 {cleanup_size_mb:.0f}MB。"
                ),
                "保留最近一次成功安裝所需檔案，移除較舊的套件快取。",
                requires_confirmation=True,
            )
        )

    failed_smoke_tests = [
        name
        for name, result in report.get("smoke_tests", {}).items()
        if (
            result is False
            or (
                isinstance(result, dict)
                and result.get("ok") is False
            )
        )
    ]
    if failed_smoke_tests:
        recommendations.append(
            _recommendation(
                "ENV-SMOKE-TEST-FAILED",
                "blocking",
                "實際推論試跑失敗",
                "失敗項目：" + "、".join(sorted(failed_smoke_tests)),
                (
                    "保留環境報告與錯誤訊息，執行修復流程後重新試跑；"
                    "在通過前不要視為 GPU 已可用。"
                ),
            )
        )

    severity_order = {"blocking": 0, "warning": 1, "info": 2}
    return sorted(
        recommendations,
        key=lambda item: (severity_order[item["severity"]], item["code"]),
    )
