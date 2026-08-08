from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from importlib import metadata
from pathlib import Path
from typing import Any

from .recommendations import build_recommendations
from .runtime_paths import activate_gpu_dll_dirs, find_dll


PACKAGE_NAMES = (
    "gradio",
    "faster-whisper",
    "ctranslate2",
    "imageio-ffmpeg",
    "pyannote.audio",
    "torch",
    "torchaudio",
)


def _package_version(name: str) -> str | None:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None


def _directory_stats(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"available": False, "files": 0, "size_mb": 0.0}
    files = 0
    size = 0
    try:
        for item in path.rglob("*"):
            if not item.is_file():
                continue
            files += 1
            try:
                size += item.stat().st_size
            except OSError:
                continue
    except OSError:
        pass
    return {
        "available": True,
        "files": files,
        "size_mb": round(size / (1024 * 1024), 1),
    }


def _wheel_cache_stats(
    path: Path,
    *,
    retention_days: int = 14,
) -> dict[str, Any]:
    stats = _directory_stats(path)
    stats.update(
        {
            "cleanup_candidate_count": 0,
            "cleanup_candidate_size_mb": 0.0,
        }
    )
    if not path.exists():
        return stats
    try:
        directories = sorted(
            (
                item
                for item in path.iterdir()
                if item.is_dir()
            ),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return stats
    if len(directories) < 2:
        return stats

    cutoff = datetime.now(UTC) - timedelta(
        days=retention_days
    )
    candidates = [
        item
        for item in directories[1:]
        if datetime.fromtimestamp(
            item.stat().st_mtime,
            tz=UTC,
        )
        < cutoff
    ]
    candidate_size_mb = sum(
        _directory_stats(item)["size_mb"]
        for item in candidates
    )
    stats["cleanup_candidate_count"] = len(candidates)
    stats["cleanup_candidate_size_mb"] = round(
        candidate_size_mb,
        1,
    )
    return stats


def _redact_path(path: Path | None, base_dir: Path) -> str:
    if path is None:
        return ""
    resolved = str(path.resolve())
    replacements = (
        (str(base_dir.resolve()), "$PROJECT"),
        (str(Path.home().resolve()), "$HOME"),
    )
    for prefix, replacement in replacements:
        if resolved.casefold().startswith(prefix.casefold()):
            return replacement + resolved[len(prefix) :]
    return resolved


def _load_bootstrap_report(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _run_pip_check() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "check"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    output = (result.stdout or result.stderr).strip()
    return {
        "ok": result.returncode == 0,
        "exit_code": result.returncode,
        "message": output,
    }


def _collect_ctranslate2_status() -> dict[str, Any]:
    version = _package_version("ctranslate2")
    if version is None:
        return {
            "available": False,
            "version": None,
            "cuda_ready": False,
            "cuda_device_count": 0,
            "compute_types": [],
            "note": "尚未安裝 CTranslate2。",
        }
    try:
        import ctranslate2

        device_count = int(ctranslate2.get_cuda_device_count())
        compute_types = (
            sorted(ctranslate2.get_supported_compute_types("cuda"))
            if device_count > 0
            else []
        )
        return {
            "available": True,
            "version": ctranslate2.__version__,
            "cuda_ready": device_count > 0,
            "cuda_device_count": device_count,
            "compute_types": compute_types,
            "note": (
                f"CTranslate2 已偵測到 {device_count} 個 CUDA 裝置。"
                if device_count > 0
                else "CTranslate2 未偵測到 CUDA 裝置。"
            ),
        }
    except Exception as exc:
        return {
            "available": True,
            "version": version,
            "cuda_ready": False,
            "cuda_device_count": 0,
            "compute_types": [],
            "note": f"CTranslate2 檢測失敗：{exc}",
        }


def _base_version(version: str | None) -> str:
    if not version:
        return ""
    return version.split("+", 1)[0].rsplit(".", 1)[0]


def _collect_torch_status() -> dict[str, Any]:
    version = _package_version("torch")
    audio_version = _package_version("torchaudio")
    if version is None:
        return {
            "available": False,
            "version": None,
            "torchaudio_version": audio_version,
            "cuda_ready": False,
            "cuda_version": None,
            "device_count": 0,
            "device_name": "",
            "version_mismatch": False,
            "note": "尚未安裝 PyTorch。",
        }
    try:
        import torch

        cuda_ready = bool(torch.cuda.is_available())
        device_count = int(torch.cuda.device_count())
        device_name = (
            torch.cuda.get_device_name(0)
            if cuda_ready and device_count > 0
            else ""
        )
        mismatch = bool(audio_version) and (
            _base_version(torch.__version__) != _base_version(audio_version)
        )
        return {
            "available": True,
            "version": torch.__version__,
            "torchaudio_version": audio_version,
            "cuda_ready": cuda_ready,
            "cuda_version": torch.version.cuda,
            "device_count": device_count,
            "device_name": device_name,
            "version_mismatch": mismatch,
            "note": (
                f"PyTorch CUDA 已就緒：{device_name}。"
                if cuda_ready
                else "目前安裝的 PyTorch 無法使用 CUDA。"
            ),
        }
    except Exception as exc:
        return {
            "available": True,
            "version": version,
            "torchaudio_version": audio_version,
            "cuda_ready": False,
            "cuda_version": None,
            "device_count": 0,
            "device_name": "",
            "version_mismatch": False,
            "note": f"PyTorch 檢測失敗：{exc}",
        }


def _find_pyannote_model(base_dir: Path) -> Path | None:
    direct = base_dir / "models" / "pyannote-speaker-diarization-community-1"
    if (direct / "config.yaml").exists():
        return direct

    roots = [
        base_dir / "models" / "models--pyannote--speaker-diarization-community-1",
        base_dir / ".cache" / "huggingface" / "hub"
        / "models--pyannote--speaker-diarization-community-1",
        Path.home()
        / ".cache"
        / "huggingface"
        / "hub"
        / "models--pyannote--speaker-diarization-community-1",
    ]
    for root in roots:
        snapshots = root / "snapshots"
        if not snapshots.exists():
            continue
        for candidate in sorted(snapshots.iterdir(), reverse=True):
            if candidate.is_dir() and (candidate / "config.yaml").exists():
                return candidate
    return None


def _collect_models(base_dir: Path) -> dict[str, Any]:
    model_root = base_dir / "models"
    whisper_models = []
    if model_root.exists():
        for path in sorted(model_root.glob("models--Systran--faster-whisper-*")):
            stats = _directory_stats(path)
            whisper_models.append(
                {
                    "name": path.name.replace(
                        "models--Systran--faster-whisper-",
                        "",
                    ),
                    "size_mb": stats["size_mb"],
                }
            )
    pyannote_path = _find_pyannote_model(base_dir)
    return {
        "whisper": whisper_models,
        "pyannote": {
            "available": pyannote_path is not None,
            "path": _redact_path(pyannote_path, base_dir),
        },
    }


def _fallback_system(base_dir: Path) -> dict[str, Any]:
    disk = shutil.disk_usage(base_dir)
    return {
        "system": {
            "os": platform.platform(),
            "architecture": platform.machine(),
            "powershell": None,
        },
        "cpu": [
            {
                "name": platform.processor() or "Unknown CPU",
                "manufacturer": "",
                "cores": os.cpu_count(),
                "logical_processors": os.cpu_count(),
                "avx2": None,
            }
        ],
        "memory": {},
        "disks": [
            {
                "name": base_dir.drive,
                "total_gb": round(disk.total / (1024**3), 1),
                "free_gb": round(disk.free / (1024**3), 1),
            }
        ],
        "gpus": _fallback_nvidia_gpus(),
        "python": {
            "system_available": True,
            "system_version": platform.python_version(),
            "project_available": True,
            "project_version": platform.python_version(),
            "architecture": platform.architecture()[0],
        },
    }


def _fallback_nvidia_gpus() -> list[dict[str, Any]]:
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,driver_version,memory.total,compute_cap",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=5,
            check=False,
        )
    except Exception:
        return []
    if result.returncode != 0:
        return []
    gpus = []
    for line in result.stdout.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if not parts or not parts[0]:
            continue
        gpus.append(
            {
                "name": parts[0],
                "vendor": "nvidia",
                "driver_version": parts[1] if len(parts) > 1 else "",
                "memory_mb": _parse_float(parts[2] if len(parts) > 2 else None),
                "compute_capability": parts[3] if len(parts) > 3 else "",
                "nvidia_smi_ready": True,
            }
        )
    return gpus


def _parse_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_environment_report(
    base_dir: Path | None = None,
    *,
    bootstrap_report: Path | None = None,
) -> dict[str, Any]:
    project_root = (base_dir or Path.cwd()).resolve()
    _dll_handles = activate_gpu_dll_dirs(project_root)
    bootstrap = _load_bootstrap_report(bootstrap_report)
    base = bootstrap or _fallback_system(project_root)

    packages = {
        name: {
            "installed": (version := _package_version(name)) is not None,
            "version": version,
        }
        for name in PACKAGE_NAMES
    }
    cublas = find_dll(project_root, "cublas64_12.dll")
    cudnn = find_dll(project_root, "cudnn64_9.dll")
    ctranslate2_status = _collect_ctranslate2_status()
    torch_status = _collect_torch_status()

    report: dict[str, Any] = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(),
        "system": base.get("system", {}),
        "cpu": base.get("cpu", []),
        "memory": base.get("memory", {}),
        "disks": base.get("disks", []),
        "gpus": base.get("gpus", []),
        "python": base.get("python", {}),
        "packages": packages,
        "runtimes": {
            "dlls": {
                "cublas64_12": _redact_path(cublas, project_root),
                "cudnn64_9": _redact_path(cudnn, project_root),
            },
            "ctranslate2": ctranslate2_status,
            "torch": torch_status,
            "ffmpeg": {
                "available": shutil.which("ffmpeg") is not None
                or packages["imageio-ffmpeg"]["installed"],
            },
        },
        "models": _collect_models(project_root),
        "storage": {
            "models": _directory_stats(project_root / "models"),
            "cache": _directory_stats(project_root / ".cache"),
            "wheel_cache": _wheel_cache_stats(
                project_root / ".cache" / "wheels"
            ),
            "transcriptions": _directory_stats(
                project_root / "transcriptions"
            ),
        },
        "pip_check": _run_pip_check(),
        "pipelines": {
            "whisper": {
                "cpu_ready": packages["faster-whisper"]["installed"],
                "cuda_ready": (
                    ctranslate2_status["cuda_ready"] and cublas is not None
                ),
            },
            "diarization": {
                "cpu_ready": packages["pyannote.audio"]["installed"],
                "cuda_ready": (
                    packages["pyannote.audio"]["installed"]
                    and torch_status["cuda_ready"]
                ),
            },
        },
        "privacy": {
            "contains_token": False,
            "paths_redacted": True,
        },
    }
    report["recommendations"] = build_recommendations(report)
    return report


def _summary_lines(report: dict[str, Any]) -> list[str]:
    lines = ["Whisper 環境檢測報告", ""]
    cpu = report.get("cpu", [])
    if cpu:
        lines.append(f"CPU：{cpu[0].get('name', '未知')}")
    for gpu in report.get("gpus", []):
        lines.append(
            f"GPU：{gpu.get('name', '未知')} "
            f"({gpu.get('vendor', 'unknown')})"
        )
    pipelines = report.get("pipelines", {})
    whisper = pipelines.get("whisper", {})
    diarization = pipelines.get("diarization", {})
    lines.extend(
        [
            f"Whisper CPU：{'就緒' if whisper.get('cpu_ready') else '未就緒'}",
            f"Whisper CUDA：{'就緒' if whisper.get('cuda_ready') else '未就緒'}",
            f"說話人分離 CPU：{'就緒' if diarization.get('cpu_ready') else '未就緒'}",
            f"說話人分離 CUDA：{'就緒' if diarization.get('cuda_ready') else '未就緒'}",
            "",
            "建議：",
        ]
    )
    for item in report.get("recommendations", []):
        lines.append(
            f"- [{item['severity']}] {item['code']}: {item['title']}"
        )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inspect the local Whisper runtime and produce a redacted report."
    )
    parser.add_argument("--bootstrap-report", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    report = build_environment_report(
        Path.cwd(),
        bootstrap_report=args.bootstrap_report,
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print("\n".join(_summary_lines(report)))

    blocking = any(
        item["severity"] == "blocking"
        for item in report["recommendations"]
    )
    return 1 if blocking else 0


if __name__ == "__main__":
    raise SystemExit(main())
