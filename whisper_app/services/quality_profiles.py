from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class QualityProfile:
    key: str
    label: str
    model_size: str
    device: str
    compute_type: str
    beam_size: int
    vad_filter: bool
    word_timestamps: bool
    note: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


PROFILES = {
    "fast": QualityProfile(
        "fast",
        "快速",
        "base",
        "auto",
        "int8",
        3,
        True,
        False,
        "適合快速整理與較低硬體需求。",
    ),
    "balanced": QualityProfile(
        "balanced",
        "平衡",
        "medium",
        "auto",
        "float16",
        5,
        True,
        False,
        "一般中文會議與訪談的建議起點。",
    ),
    "accurate": QualityProfile(
        "accurate",
        "高準確",
        "large-v3",
        "auto",
        "float16",
        7,
        True,
        True,
        "適合高品質輸出；需要更多時間、VRAM 與磁碟。",
    ),
}


def recommend_profile(
    environment_report: dict[str, Any],
) -> QualityProfile:
    whisper = (
        environment_report.get("pipelines", {})
        .get("whisper", {})
    )
    if not whisper.get("cuda_ready"):
        return QualityProfile(
            "cpu",
            "CPU 建議",
            "small",
            "cpu",
            "int8",
            4,
            True,
            False,
            "未偵測到可用 CUDA；使用 small／int8 控制等待時間。",
        )

    nvidia_memory = max(
        (
            float(gpu.get("memory_mb") or 0)
            for gpu in environment_report.get("gpus", [])
            if gpu.get("vendor") == "nvidia"
        ),
        default=0,
    )
    if nvidia_memory >= 11000:
        return PROFILES["accurate"]
    if nvidia_memory >= 6000:
        return PROFILES["balanced"]
    return QualityProfile(
        "gpu_compact",
        "GPU 精簡",
        "small",
        "cuda",
        "float16",
        5,
        True,
        False,
        "VRAM 低於 6GB；使用 small 避免記憶體不足。",
    )


def resolve_profile(
    key: str,
    environment_report: dict[str, Any],
) -> QualityProfile | None:
    if key == "custom":
        return None
    if key == "auto":
        return recommend_profile(environment_report)
    return PROFILES.get(key)
