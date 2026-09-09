from __future__ import annotations

import gc
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator

import ctranslate2
from faster_whisper import WhisperModel

from whisper_app.domain.requests import TranscriptionRequest
from whisper_app.domain.results import (
    TranscriptSegment,
    TranscriptWord,
    make_segment_id,
)
from whisper_app.environment.runtime_paths import find_dll
from whisper_app.jobs import CancellationToken


class TranscriptionError(RuntimeError):
    pass


@dataclass(frozen=True)
class RuntimeSelection:
    device: str
    compute_type: str
    note: str = ""


@dataclass(frozen=True)
class TranscriptionEvent:
    stage: str
    message: str
    runtime: RuntimeSelection
    segment: TranscriptSegment | None = None
    language: str = ""
    language_probability: float = 0.0


class TranscriptionService:
    def __init__(
        self,
        base_dir: Path,
        *,
        model_factory: Callable[..., Any] = WhisperModel,
        cuda_device_count: Callable[[], int] | None = None,
    ) -> None:
        self.base_dir = base_dir.resolve()
        self.model_dir = self.base_dir / "models"
        self._model_factory = model_factory
        self._cuda_device_count = (
            cuda_device_count or ctranslate2.get_cuda_device_count
        )
        self._model_cache: dict[tuple[str, str, str], Any] = {}
        self._cuda_status_cache: tuple[bool, str] | None = None

    def clear_runtime_cache(self) -> None:
        self._cuda_status_cache = None

    def cuda_runtime_status(self) -> tuple[bool, str]:
        if self._cuda_status_cache is not None:
            return self._cuda_status_cache

        try:
            device_count = int(self._cuda_device_count())
        except Exception as exc:
            self._cuda_status_cache = (
                False,
                f"CUDA 偵測失敗：{exc}",
            )
            return self._cuda_status_cache

        if device_count < 1:
            self._cuda_status_cache = (
                False,
                "未偵測到可用 CUDA 裝置。",
            )
            return self._cuda_status_cache

        if find_dll(self.base_dir, "cublas64_12.dll") is None:
            self._cuda_status_cache = (
                False,
                "偵測到 NVIDIA GPU，但缺少 cublas64_12.dll；"
                "auto 先使用 CPU。請執行 WhisperTools.cmd 選項 6。",
            )
            return self._cuda_status_cache

        self._cuda_status_cache = (
            True,
            f"偵測到 {device_count} 個 CUDA 裝置，auto 使用 GPU。",
        )
        return self._cuda_status_cache

    def resolve_runtime(
        self,
        device: str,
        compute_type: str,
    ) -> RuntimeSelection:
        notes: list[str] = []
        resolved_device = device
        resolved_compute = compute_type
        if resolved_device == "auto":
            cuda_ready, note = self.cuda_runtime_status()
            resolved_device = "cuda" if cuda_ready else "cpu"
            notes.append(note)
        if (
            resolved_compute == "float16"
            and resolved_device != "cuda"
        ):
            resolved_compute = "int8"
            notes.append(
                "已將 float16 自動改為 int8；CPU 不支援 float16 推論。"
            )
        return RuntimeSelection(
            resolved_device,
            resolved_compute,
            " ".join(notes),
        )

    def _load_model(
        self,
        model_size: str,
        runtime: RuntimeSelection,
    ) -> Any:
        key = (
            model_size,
            runtime.device,
            runtime.compute_type,
        )
        if key not in self._model_cache:
            self.model_dir.mkdir(exist_ok=True)
            self._model_cache[key] = self._model_factory(
                model_size,
                device=runtime.device,
                compute_type=runtime.compute_type,
                download_root=str(self.model_dir),
                local_files_only=True,
            )
        return self._model_cache[key]

    def stream(
        self,
        request: TranscriptionRequest,
        token: CancellationToken | None = None,
    ) -> Iterator[TranscriptionEvent]:
        cancellation = token or CancellationToken()
        requested_device = request.device
        runtime = self.resolve_runtime(
            request.device,
            request.compute_type,
        )
        cancellation.raise_if_cancelled()
        yield TranscriptionEvent(
            "loading",
            "正在載入本機模型（未下載的模型請先執行部署）...",
            runtime,
        )

        try:
            model = self._load_model(request.model_size, runtime)
            cancellation.raise_if_cancelled()
            yield TranscriptionEvent(
                "analyzing",
                "模型已載入，正在分析音訊...",
                runtime,
            )
            segments, info = model.transcribe(
                request.source_path,
                language=request.language_code,
                task=request.task,
                beam_size=int(request.beam_size),
                vad_filter=request.vad_filter,
                word_timestamps=request.word_timestamps,
            )
        except Exception as exc:
            if runtime.device == "cuda" and requested_device != "cuda":
                runtime = RuntimeSelection(
                    "cpu",
                    "int8",
                    (
                        runtime.note
                        + " CUDA 不可用，已自動退回 CPU。"
                    ).strip(),
                )
                yield TranscriptionEvent(
                    "fallback",
                    "CUDA 不可用，已退回 CPU 重試...",
                    runtime,
                )
                try:
                    model = self._load_model(request.model_size, runtime)
                    segments, info = model.transcribe(
                        request.source_path,
                        language=request.language_code,
                        task=request.task,
                        beam_size=int(request.beam_size),
                        vad_filter=request.vad_filter,
                        word_timestamps=request.word_timestamps,
                    )
                except Exception as fallback_exc:
                    raise TranscriptionError(
                        f"轉錄失敗：{fallback_exc}"
                    ) from fallback_exc
            else:
                prefix = (
                    "GPU 轉錄失敗"
                    if requested_device == "cuda"
                    else "轉錄失敗"
                )
                raise TranscriptionError(f"{prefix}：{exc}") from exc

        sequence = 0
        try:
            for raw_segment in segments:
                cancellation.raise_if_cancelled()
                text = str(raw_segment.text).strip()
                if not text:
                    continue
                sequence += 1
                words: list[TranscriptWord] = []
                if (
                    request.word_timestamps
                    and getattr(raw_segment, "words", None)
                ):
                    words = [
                        TranscriptWord(
                            start=round(float(word.start), 3),
                            end=round(float(word.end), 3),
                            word=str(word.word),
                        )
                        for word in raw_segment.words
                    ]
                segment = TranscriptSegment(
                    segment_id=make_segment_id(sequence),
                    sequence=sequence,
                    start=round(float(raw_segment.start), 3),
                    end=round(float(raw_segment.end), 3),
                    text=text,
                    words=words,
                )
                yield TranscriptionEvent(
                    "transcribing",
                    f"已完成到 {segment.end:.3f} 秒",
                    runtime,
                    segment=segment,
                    language=str(info.language),
                    language_probability=float(
                        info.language_probability
                    ),
                )
        except TranscriptionError:
            raise
        except Exception as exc:
            raise TranscriptionError(f"轉錄失敗：{exc}") from exc

        cancellation.raise_if_cancelled()
        yield TranscriptionEvent(
            "completed",
            "轉錄完成。",
            runtime,
            language=str(info.language),
            language_probability=float(info.language_probability),
        )

    def release_models(self) -> None:
        self._model_cache.clear()
        gc.collect()
        try:
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                torch.cuda.synchronize()
        except Exception:
            pass
