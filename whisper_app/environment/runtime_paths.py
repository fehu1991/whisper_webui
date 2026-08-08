from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def gpu_dll_candidate_dirs(base_dir: Path) -> list[Path]:
    site_packages = base_dir / ".venv" / "Lib" / "site-packages"
    candidates = [
        site_packages / "ctranslate2",
        site_packages / "torch" / "lib",
        site_packages / "nvidia" / "cublas" / "bin",
        site_packages / "nvidia" / "cudnn" / "bin",
        site_packages / "nvidia" / "cuda_runtime" / "bin",
    ]
    if os.environ.get("CUDA_PATH"):
        candidates.append(Path(os.environ["CUDA_PATH"]) / "bin")
    if os.environ.get("CUDA_PATH_V12_8"):
        candidates.append(Path(os.environ["CUDA_PATH_V12_8"]) / "bin")

    cuda_root = Path("C:/Program Files/NVIDIA GPU Computing Toolkit/CUDA")
    if cuda_root.exists():
        candidates.extend(
            path / "bin"
            for path in sorted(cuda_root.glob("v*"), reverse=True)
        )

    cudnn_root = Path("C:/Program Files/NVIDIA/CUDNN")
    if cudnn_root.exists():
        candidates.extend(
            path
            for path in cudnn_root.rglob("bin")
            if path.is_dir()
        )

    nvidia_root = site_packages / "nvidia"
    if nvidia_root.exists():
        candidates.extend(
            path
            for path in nvidia_root.rglob("bin")
            if path.is_dir()
        )
        candidates.extend(
            path
            for path in nvidia_root.rglob("lib")
            if path.is_dir()
        )

    seen: set[str] = set()
    unique: list[Path] = []
    for path in candidates:
        if not path.exists():
            continue
        resolved = str(path.resolve()).casefold()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path.resolve())
    return unique


def activate_gpu_dll_dirs(base_dir: Path) -> list[Any]:
    paths = gpu_dll_candidate_dirs(base_dir)
    if paths:
        existing_path = os.environ.get("PATH", "")
        os.environ["PATH"] = os.pathsep.join(
            [str(path) for path in paths] + [existing_path]
        )

    handles: list[Any] = []
    if hasattr(os, "add_dll_directory"):
        for path in paths:
            try:
                handles.append(os.add_dll_directory(str(path)))
            except OSError:
                continue
    return handles


def find_dll(base_dir: Path, filename: str) -> Path | None:
    for directory in gpu_dll_candidate_dirs(base_dir):
        candidate = directory / filename
        if candidate.exists():
            return candidate.resolve()

    for item in os.environ.get("PATH", "").split(os.pathsep):
        if not item:
            continue
        candidate = Path(item) / filename
        if candidate.exists():
            return candidate.resolve()
    return None
