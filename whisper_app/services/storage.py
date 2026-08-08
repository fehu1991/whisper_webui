from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any


def directory_size(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        if not item.is_file():
            continue
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total


def format_size(size_bytes: int) -> str:
    value = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return (
                f"{value:.0f}{unit}"
                if unit in {"B", "KB"}
                else f"{value:.1f}{unit}"
            )
        value /= 1024
    return f"{value:.1f}TB"


def model_inventory(base_dir: Path) -> list[list[Any]]:
    model_root = base_dir / "models"
    if not model_root.exists():
        return []
    rows: list[list[Any]] = []
    for path in sorted(
        (
            item
            for item in model_root.iterdir()
            if item.is_dir()
            and not item.name.startswith(".")
        ),
        key=lambda item: item.name.casefold(),
    ):
        name = path.name
        model_type = "其他"
        display_name = name
        if name.startswith("models--Systran--faster-whisper-"):
            model_type = "Whisper"
            display_name = name.removeprefix(
                "models--Systran--faster-whisper-"
            )
        elif "pyannote" in name.casefold():
            model_type = "pyannote"
        size = directory_size(path)
        modified = datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=UTC,
        ).astimezone()
        rows.append(
            [
                model_type,
                display_name,
                format_size(size),
                modified.strftime("%Y-%m-%d %H:%M"),
            ]
        )
    return rows


@dataclass(frozen=True)
class CacheCleanupPlan:
    candidates: tuple[Path, ...]
    total_bytes: int
    retained: tuple[Path, ...]


def plan_wheel_cache_cleanup(
    base_dir: Path,
    *,
    retention_days: int = 14,
) -> CacheCleanupPlan:
    root = (base_dir / ".cache" / "wheels").resolve()
    if not root.exists():
        return CacheCleanupPlan((), 0, ())
    directories = sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not directories:
        return CacheCleanupPlan((), 0, ())

    newest = directories[0]
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    candidates: list[Path] = []
    retained: list[Path] = [newest]
    for path in directories[1:]:
        modified = datetime.fromtimestamp(
            path.stat().st_mtime,
            tz=UTC,
        )
        if modified < cutoff:
            candidates.append(path)
        else:
            retained.append(path)
    return CacheCleanupPlan(
        tuple(candidates),
        sum(directory_size(path) for path in candidates),
        tuple(retained),
    )


def cleanup_old_wheel_cache(
    base_dir: Path,
    *,
    confirmed: bool,
    retention_days: int = 14,
) -> tuple[int, int]:
    if not confirmed:
        raise ValueError("請先勾選確認，再清理舊安裝快取。")
    root = (base_dir / ".cache" / "wheels").resolve()
    plan = plan_wheel_cache_cleanup(
        base_dir,
        retention_days=retention_days,
    )
    removed = 0
    reclaimed = 0
    for path in plan.candidates:
        resolved = path.resolve()
        if resolved.parent != root or not resolved.name:
            raise RuntimeError(
                f"拒絕清理不安全的路徑：{resolved}"
            )
        size = directory_size(resolved)
        shutil.rmtree(resolved)
        removed += 1
        reclaimed += size
    return removed, reclaimed


def storage_summary(base_dir: Path) -> dict[str, Any]:
    return {
        "models_bytes": directory_size(base_dir / "models"),
        "wheel_cache_bytes": directory_size(
            base_dir / ".cache" / "wheels"
        ),
        "transcriptions_bytes": directory_size(
            base_dir / "transcriptions"
        ),
    }
