from __future__ import annotations

from pathlib import Path

MODEL_SIZES = ("base", "small", "medium", "large-v3")
WLK_VERSION = "0.2.26"


def local_model(base: Path, size: str) -> Path:
    if size not in MODEL_SIZES:
        raise ValueError("不支援的模型。")
    from huggingface_hub import snapshot_download

    path = Path(snapshot_download(
        f"Systran/faster-whisper-{size}", cache_dir=str(base / "models"),
        local_files_only=True,
    ))
    for name in ("model.bin", "config.json", "tokenizer.json"):
        if not (path / name).is_file():
            raise FileNotFoundError(f"本機 {size} 模型不完整，請先執行部署。")
    return path


def readiness(base: Path) -> dict:
    from importlib.metadata import PackageNotFoundError, version

    try:
        installed = version("whisperlivekit")
        conversion_ready = version("opencc-python-reimplemented") == "0.1.7"
    except PackageNotFoundError:
        installed = ""
        conversion_ready = False
    models = []
    for size in MODEL_SIZES:
        try:
            local_model(base, size)
            models.append(size)
        except (OSError, ValueError):
            pass
    return {"installed": installed == WLK_VERSION and conversion_ready, "version": installed,
            "required_version": WLK_VERSION, "models": models}
