from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from whisper_app.domain.requests import (
    SUPPORTED_COMPUTE_TYPES,
    SUPPORTED_DEVICES,
    SUPPORTED_EXPORT_FORMATS,
    SUPPORTED_MODELS,
)


@dataclass(frozen=True)
class UserSettings:
    quality_profile: str = "auto"
    model_size: str = "medium"
    language: str = "auto"
    device: str = "auto"
    compute_type: str = "float16"
    beam_size: int = 5
    vad_filter: bool = True
    word_timestamps: bool = False
    output_formats: tuple[str, ...] = ("txt_timeline", "srt")
    include_segment_numbers: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> UserSettings:
        defaults = cls()
        payload = {
            key: value
            for key, value in data.items()
            if key in cls.__dataclass_fields__
        }
        allowed_profiles = {
            "auto",
            "fast",
            "balanced",
            "accurate",
            "custom",
        }
        if payload.get("quality_profile") not in allowed_profiles:
            payload["quality_profile"] = defaults.quality_profile
        allowed_values = {
            "model_size": SUPPORTED_MODELS,
            "device": SUPPORTED_DEVICES,
            "compute_type": SUPPORTED_COMPUTE_TYPES,
        }
        for key, choices in allowed_values.items():
            if key in payload and payload[key] not in choices:
                payload[key] = getattr(defaults, key)
        if "beam_size" in payload:
            try:
                beam_size = int(payload["beam_size"])
            except (TypeError, ValueError):
                beam_size = defaults.beam_size
            payload["beam_size"] = (
                beam_size
                if 1 <= beam_size <= 10
                else defaults.beam_size
            )
        if "output_formats" in payload:
            valid_formats = tuple(
                dict.fromkeys(
                    item
                    for item in (payload["output_formats"] or ())
                    if item in SUPPORTED_EXPORT_FORMATS
                )
            )
            payload["output_formats"] = (
                valid_formats
                or defaults.output_formats
            )
        return cls(**payload)


def settings_path(base_dir: Path) -> Path:
    return base_dir / ".whisper" / "settings.json"


def load_settings(base_dir: Path) -> UserSettings:
    path = settings_path(base_dir)
    if not path.exists():
        return UserSettings()
    try:
        return UserSettings.from_dict(
            json.loads(path.read_text(encoding="utf-8-sig"))
        )
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return UserSettings()


def save_settings(
    base_dir: Path,
    settings: UserSettings,
) -> Path:
    path = settings_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(
            asdict(settings),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(path)
    return path
