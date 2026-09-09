from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from faster_whisper.audio import decode_audio

from whisper_app.domain.requests import DiarizationOptions
from whisper_app.jobs import CancellationToken


class DiarizationError(RuntimeError):
    pass


def resolve_hf_token(value: str | None) -> str:
    return (
        value
        or os.environ.get("HF_TOKEN")
        or os.environ.get("HUGGINGFACE_TOKEN")
        or ""
    ).strip()


def find_cached_pyannote_model(base_dir: Path) -> str:
    model_dir = base_dir / "models"
    direct_candidates = [
        (
            Path(os.environ["PYANNOTE_MODEL_DIR"])
            if os.environ.get("PYANNOTE_MODEL_DIR")
            else None
        ),
        model_dir / "pyannote-speaker-diarization-community-1",
        model_dir / "models--pyannote--speaker-diarization-community-1",
        base_dir
        / ".cache"
        / "pyannote-speaker-diarization-community-1",
    ]
    for candidate in [path for path in direct_candidates if path]:
        expanded = Path(candidate).expanduser()
        if (expanded / "config.yaml").exists():
            return str(expanded.resolve())
        snapshots = expanded / "snapshots"
        if snapshots.exists():
            for snapshot in sorted(snapshots.iterdir(), reverse=True):
                if snapshot.is_dir() and (
                    snapshot / "config.yaml"
                ).exists():
                    return str(snapshot.resolve())

    cache_roots = [
        (
            Path(os.environ["HF_HOME"]) / "hub"
            if os.environ.get("HF_HOME")
            else None
        ),
        Path.home() / ".cache" / "huggingface" / "hub",
        base_dir / ".cache" / "huggingface" / "hub",
        model_dir,
    ]
    for root in [path for path in cache_roots if path]:
        snapshots = (
            root
            / "models--pyannote--speaker-diarization-community-1"
            / "snapshots"
        )
        if not snapshots.exists():
            continue
        for candidate in sorted(snapshots.iterdir(), reverse=True):
            if candidate.is_dir() and (
                candidate / "config.yaml"
            ).exists():
                return str(candidate.resolve())
    return ""


def extract_diarization_segments(
    output: Any,
) -> list[dict[str, Any]]:
    diarization = getattr(
        output,
        "exclusive_speaker_diarization",
        None,
    )
    if diarization is None:
        diarization = getattr(
            output,
            "speaker_diarization",
            output,
        )

    segments: list[dict[str, Any]] = []
    if hasattr(diarization, "itertracks"):
        for turn, _, speaker in diarization.itertracks(
            yield_label=True
        ):
            segments.append(
                {
                    "start": round(float(turn.start), 3),
                    "end": round(float(turn.end), 3),
                    "speaker": str(speaker),
                }
            )
    else:
        for turn, speaker in diarization:
            segments.append(
                {
                    "start": round(float(turn.start), 3),
                    "end": round(float(turn.end), 3),
                    "speaker": str(speaker),
                }
            )
    return sorted(
        segments,
        key=lambda item: (
            item["start"],
            item["end"],
            item["speaker"],
        ),
    )


class DiarizationService:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir.resolve()
        self._pipeline_cache: dict[tuple[str, str], Any] = {}

    def _load_pipeline(
        self,
        options: DiarizationOptions,
        device: str,
    ) -> tuple[Any, str]:
        try:
            import torch
            from pyannote.audio import Pipeline
        except ImportError as exc:
            raise DiarizationError(
                "尚未安裝說話人分離套件。請執行 "
                "WhisperTools.cmd 選項 5。"
            ) from exc

        cache_device = "cpu"
        device_note = "pyannote 使用 CPU。"
        if device in {"auto", "cuda"} and torch.cuda.is_available():
            cache_device = "cuda"
            device_note = "pyannote 使用 GPU。"
        elif device == "cuda":
            raise DiarizationError(
                "pyannote CUDA 不可用；請執行 "
                "WhisperTools.cmd 選項 6。"
            )

        token = resolve_hf_token(options.token)
        local_model_path = (
            options.model_path
            or os.environ.get("PYANNOTE_MODEL_DIR")
            or ""
        ).strip()
        if not local_model_path and not token:
            local_model_path = find_cached_pyannote_model(
                self.base_dir
            )

        if local_model_path:
            resolved_model = str(
                Path(local_model_path).expanduser().resolve()
            )
            if not Path(resolved_model).exists():
                raise DiarizationError(
                    "找不到本機 pyannote 模型資料夾："
                    + resolved_model
                )
            source_key = f"local:{resolved_model}"
            source_note = (
                f"從本機模型資料夾載入：{resolved_model}。"
            )
        else:
            if not token:
                raise DiarizationError(
                    "請提供 Hugging Face token 或本機 "
                    "pyannote 模型資料夾。"
                )
            resolved_model = (
                "pyannote/speaker-diarization-community-1"
            )
            source_key = f"hf:{token[-8:]}"
            source_note = (
                "從 Hugging Face 載入 pyannote community-1。"
            )

        key = (source_key, cache_device)
        if key not in self._pipeline_cache:
            try:
                pipeline = Pipeline.from_pretrained(
                    resolved_model,
                    token=token or None,
                )
            except Exception as exc:
                message = str(exc)
                if (
                    "public gated repositories" in message
                    or "403 Forbidden" in message
                ):
                    raise DiarizationError(
                        "無法存取 pyannote gated model；"
                        "請先接受模型條款並開啟 gated repository 權限。"
                    ) from exc
                if "401" in message or "Unauthorized" in message:
                    raise DiarizationError(
                        "Hugging Face token 無效或權限不足。"
                    ) from exc
                raise DiarizationError(
                    f"pyannote 模型載入失敗：{exc}"
                ) from exc
            if cache_device == "cuda":
                pipeline.to(torch.device("cuda"))
            self._pipeline_cache[key] = pipeline
        return (
            self._pipeline_cache[key],
            source_note + device_note,
        )

    def release_models(self) -> None:
        self._pipeline_cache.clear()

    def run(
        self,
        audio_path: str,
        options: DiarizationOptions,
        device: str,
        token: CancellationToken | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        cancellation = token or CancellationToken()
        cancellation.raise_if_cancelled()
        pipeline, device_note = self._load_pipeline(options, device)
        kwargs = options.speaker_count_kwargs()
        cancellation.raise_if_cancelled()

        try:
            output = pipeline(audio_path, **kwargs)
        except Exception:
            import torch

            waveform = decode_audio(
                audio_path,
                sampling_rate=16000,
            )
            cancellation.raise_if_cancelled()
            waveform_tensor = (
                torch.from_numpy(waveform).float().unsqueeze(0)
            )
            output = pipeline(
                {
                    "waveform": waveform_tensor,
                    "sample_rate": 16000,
                },
                **kwargs,
            )

        cancellation.raise_if_cancelled()
        segments = extract_diarization_segments(output)
        status = (
            f"pyannote community-1，{device_note} "
            f"說話人片段數：{len(segments)}。"
        )
        return segments, status
