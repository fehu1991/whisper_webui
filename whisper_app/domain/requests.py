from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


SUPPORTED_MODELS = ("tiny", "base", "small", "medium", "large-v3")
SUPPORTED_DEVICES = ("auto", "cuda", "cpu")
SUPPORTED_COMPUTE_TYPES = ("default", "int8", "float16", "float32")
SUPPORTED_TASKS = ("transcribe", "translate")
SUPPORTED_EXPORT_FORMATS = (
    "txt_timeline",
    "txt_plain",
    "srt",
    "vtt",
    "json",
)


@dataclass(frozen=True)
class DiarizationOptions:
    enabled: bool = False
    token: str = field(default="", repr=False)
    model_path: str = ""
    num_speakers: int = 0
    min_speakers: int = 0
    max_speakers: int = 0

    def __post_init__(self) -> None:
        counts = (
            self.num_speakers,
            self.min_speakers,
            self.max_speakers,
        )
        if any(int(value) < 0 for value in counts):
            raise ValueError("speaker counts cannot be negative")
        if (
            self.min_speakers > 0
            and self.max_speakers > 0
            and self.min_speakers > self.max_speakers
        ):
            raise ValueError(
                "min_speakers cannot exceed max_speakers"
            )

    def speaker_count_kwargs(self) -> dict[str, int]:
        if self.num_speakers > 0:
            return {"num_speakers": self.num_speakers}
        result: dict[str, int] = {}
        if self.min_speakers > 0:
            result["min_speakers"] = self.min_speakers
        if self.max_speakers > 0:
            result["max_speakers"] = self.max_speakers
        return result

    def public_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("token", None)
        data["token_provided"] = bool(self.token)
        return data

    @classmethod
    def from_dict(
        cls,
        data: dict[str, Any],
    ) -> DiarizationOptions:
        payload = dict(data)
        payload.pop("token_provided", None)
        return cls(**payload)


@dataclass(frozen=True)
class ExportOptions:
    formats: tuple[str, ...] = ("txt_timeline",)
    include_segment_numbers: bool = True

    def __post_init__(self) -> None:
        normalized = tuple(dict.fromkeys(self.formats or ("txt_timeline",)))
        invalid = set(normalized) - set(SUPPORTED_EXPORT_FORMATS)
        if invalid:
            raise ValueError(
                "Unsupported export formats: " + ", ".join(sorted(invalid))
            )
        object.__setattr__(self, "formats", normalized)


@dataclass(frozen=True)
class TranscriptionRequest:
    source_path: str
    model_size: str = "medium"
    language: str = "auto"
    task: str = "transcribe"
    device: str = "auto"
    compute_type: str = "float16"
    beam_size: int = 5
    vad_filter: bool = True
    word_timestamps: bool = False
    diarization: DiarizationOptions = field(
        default_factory=DiarizationOptions
    )
    export: ExportOptions = field(default_factory=ExportOptions)

    def __post_init__(self) -> None:
        if not self.source_path.strip():
            raise ValueError("source_path is required")
        if self.model_size not in SUPPORTED_MODELS:
            raise ValueError(f"Unsupported model: {self.model_size}")
        if self.device not in SUPPORTED_DEVICES:
            raise ValueError(f"Unsupported device: {self.device}")
        if self.compute_type not in SUPPORTED_COMPUTE_TYPES:
            raise ValueError(
                f"Unsupported compute type: {self.compute_type}"
            )
        if self.task not in SUPPORTED_TASKS:
            raise ValueError(f"Unsupported task: {self.task}")
        if not 1 <= int(self.beam_size) <= 10:
            raise ValueError("beam_size must be between 1 and 10")

    @property
    def language_code(self) -> str | None:
        return None if self.language == "auto" else self.language

    def public_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "model_size": self.model_size,
            "language": self.language,
            "task": self.task,
            "device": self.device,
            "compute_type": self.compute_type,
            "beam_size": self.beam_size,
            "vad_filter": self.vad_filter,
            "word_timestamps": self.word_timestamps,
            "diarization": self.diarization.public_dict(),
            "export": asdict(self.export),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> TranscriptionRequest:
        payload = dict(data)
        payload["diarization"] = DiarizationOptions.from_dict(
            payload.get("diarization", {})
        )
        export_data = payload.get("export", {})
        if "formats" in export_data:
            export_data = {
                **export_data,
                "formats": tuple(export_data["formats"]),
            }
        payload["export"] = ExportOptions(**export_data)
        return cls(**payload)
