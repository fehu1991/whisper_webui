from __future__ import annotations

import html
import json
import os
import socket
import time
import warnings
from pathlib import Path
from typing import Any, Iterator

from whisper_app.privacy import configure_offline

configure_offline(Path(__file__).resolve().parent)

import gradio as gr
import imageio_ffmpeg

from whisper_app.config import UserSettings, load_settings, save_settings
from whisper_app.domain.jobs import JobStatus
from whisper_app.domain.requests import (
    DiarizationOptions,
    ExportOptions,
    TranscriptionRequest,
)
from whisper_app.domain.results import TranscriptSegment
from whisper_app.environment import build_environment_report
from whisper_app.environment.runtime_paths import (
    activate_gpu_dll_dirs,
    gpu_dll_candidate_dirs,
)
from whisper_app.jobs import (
    JobBusyError,
    JobCancelledError,
    JobManager,
)
from whisper_app.services.export import (
    display_lines_from_rows as _display_lines_from_rows,
    format_timestamp as _format_timestamp,
    numbered_table_rows as _numbered_table_rows,
    write_transcription_outputs,
)
from whisper_app.services.history import (
    list_history,
    write_history_manifest,
)
from whisper_app.services.quality_profiles import (
    resolve_profile,
)
from whisper_app.services.speaker_assignment import assign_speakers
from whisper_app.services.storage import (
    cleanup_old_wheel_cache,
    format_size,
    model_inventory,
    plan_wheel_cache_cleanup,
    storage_summary,
)
from whisper_app.services.timing import format_elapsed


BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "transcriptions"
OUTPUT_DIR.mkdir(exist_ok=True)
MPL_CACHE_DIR = BASE_DIR / ".cache" / "matplotlib"
MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)

os.environ.setdefault("MPLCONFIGDIR", str(MPL_CACHE_DIR))
os.environ["PATH"] = str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent) + os.pathsep + os.environ.get("PATH", "")

_DLL_DIRECTORY_HANDLES: list[Any] = []


def _gpu_dll_candidate_dirs() -> list[Path]:
    return gpu_dll_candidate_dirs(BASE_DIR)


def _activate_gpu_dll_dirs() -> None:
    if _DLL_DIRECTORY_HANDLES:
        return
    _DLL_DIRECTORY_HANDLES.extend(activate_gpu_dll_dirs(BASE_DIR))


_activate_gpu_dll_dirs()

from whisper_app.services.diarization import (
    DiarizationService,
    find_cached_pyannote_model,
    resolve_hf_token,
)
from whisper_app.services.transcription import (
    RuntimeSelection,
    TranscriptionError,
    TranscriptionService,
)


_ENVIRONMENT_REPORT_CACHE: dict[str, Any] | None = None
_TRANSCRIPTION_SERVICE = TranscriptionService(BASE_DIR)
_DIARIZATION_SERVICE = DiarizationService(BASE_DIR)
_JOB_MANAGER = JobManager()
_USER_SETTINGS = load_settings(BASE_DIR)
warnings.filterwarnings(
    "ignore",
    message="(?s).*torchcodec is not installed correctly.*",
)
warnings.filterwarnings("ignore", category=UserWarning, module=r"pyannote\.audio\.core\.io")

# 語言下拉選單：顯示文字 -> Whisper 語言碼（"auto" 代表自動偵測）
LANGUAGE_CHOICES: list[tuple[str, str]] = [
    ("自動偵測", "auto"),
    ("中文", "zh"),
    ("英文", "en"),
    ("日文", "ja"),
    ("韓文", "ko"),
    ("西班牙文", "es"),
    ("法文", "fr"),
    ("德文", "de"),
]

OUTPUT_FORMAT_CHOICES: list[tuple[str, str]] = [
    ("TXT 時間軸紀錄", "txt_timeline"),
    ("TXT 純文字", "txt_plain"),
    ("SRT 字幕", "srt"),
    ("VTT 字幕", "vtt"),
    ("JSON 分段資料", "json"),
]

# 畫面串流更新的最小間隔（秒），避免長音檔每段都重繪造成卡頓
STREAM_UPDATE_INTERVAL = 0.4

START_JS = """
(...args) => {
    document.title = "Whisper 轉錄中...";
    return args;
}
"""

DONE_JS = """
() => {
    document.title = "Whisper 轉錄完成";
    if ("Notification" in window && Notification.permission === "granted") {
        new Notification("Whisper 轉錄完成", { body: "語音轉文字已完成。" });
    }
    window.focus();
}
"""

DESKTOP_WIDTH_JS = """
(() => {
    const updateDesktopWidthWarning = () => {
        const warning = document.getElementById("desktop-width-warning");
        if (!warning) {
            return false;
        }
        const tooNarrow = window.innerWidth < 1280;
        warning.style.display = tooNarrow ? "flex" : "none";
        warning.setAttribute("aria-hidden", tooNarrow ? "false" : "true");
        return true;
    };
    window.addEventListener("resize", updateDesktopWidthWarning, {
        passive: true,
    });
    let attempts = 0;
    const waitForInterface = window.setInterval(() => {
        attempts += 1;
        if (updateDesktopWidthWarning() || attempts >= 100) {
            window.clearInterval(waitForInterface);
        }
    }, 50);
})();
"""


def _environment_report(force: bool = False) -> dict[str, Any]:
    global _ENVIRONMENT_REPORT_CACHE
    if _ENVIRONMENT_REPORT_CACHE is not None and not force:
        return _ENVIRONMENT_REPORT_CACHE

    bootstrap_path = BASE_DIR / ".cache" / "environment" / "bootstrap-report.json"
    _ENVIRONMENT_REPORT_CACHE = build_environment_report(
        BASE_DIR,
        bootstrap_report=bootstrap_path if bootstrap_path.exists() else None,
    )
    return _ENVIRONMENT_REPORT_CACHE


def gpu_status_html(force: bool = False) -> str:
    report = _environment_report(force=force)
    cpu = report.get("cpu", [{}])[0]
    memory = report.get("memory", {})
    disks = report.get("disks", [])
    project_disk = disks[0] if disks else {}
    gpus = report.get("gpus", [])
    gpu_names = "、".join(
        f"{str(gpu.get('vendor') or 'unknown').upper()} · "
        f"{str(gpu.get('name') or '未知 GPU')}"
        for gpu in gpus
    ) or "未偵測到獨立 GPU"
    gpu_memory = max(
        [
            float(gpu.get("memory_mb") or 0)
            for gpu in gpus
        ],
        default=0,
    )

    pipelines = report.get("pipelines", {})
    whisper = pipelines.get("whisper", {})
    diarization = pipelines.get("diarization", {})
    whisper_gpu = bool(whisper.get("cuda_ready"))
    whisper_cpu = bool(whisper.get("cpu_ready"))
    diar_gpu = bool(diarization.get("cuda_ready"))
    diar_cpu = bool(diarization.get("cpu_ready"))
    whisper_state = "ready" if whisper_gpu or whisper_cpu else "warn"
    diar_state = "ready" if diar_gpu or diar_cpu else "warn"
    whisper_label = (
        "GPU 就緒"
        if whisper_gpu
        else "CPU 就緒"
        if whisper_cpu
        else "尚未就緒"
    )
    diar_label = (
        "GPU 就緒"
        if diar_gpu
        else "CPU 就緒"
        if diar_cpu
        else "尚未就緒"
    )
    whisper_note = report.get("runtimes", {}).get("ctranslate2", {}).get(
        "note",
        "",
    )
    diar_note = report.get("runtimes", {}).get("torch", {}).get(
        "note",
        "",
    )
    recommendations = report.get("recommendations", [])
    top_recommendation = recommendations[0] if recommendations else None
    recommendation_html = ""
    if top_recommendation:
        recommendation_html = f"""
        <div class="environment-advice {html.escape(str(top_recommendation["severity"]))}">
          <strong>{html.escape(str(top_recommendation["title"]))}</strong>
          <span>{html.escape(str(top_recommendation["action"]))}</span>
        </div>
        """

    return f"""
    <div class="gpu-strip">
      <div class="gpu-item">
        <span>CPU 與記憶體</span>
        <strong>{html.escape(str(cpu.get("name") or "未知 CPU").strip())}</strong>
        <small>{html.escape(str(memory.get("total_gb") or "—"))}GB RAM · 磁碟可用 {html.escape(str(project_disk.get("free_gb") or "—"))}GB</small>
      </div>
      <div class="gpu-item">
        <span>顯示裝置</span>
        <strong>{html.escape(gpu_names)}</strong>
        <small>{f"{gpu_memory:.0f}MB VRAM · CUDA {'可用' if whisper_gpu else '不可用'}" if gpu_memory else "目前使用 CPU 路徑 · CUDA 不可用"}</small>
      </div>
      <div class="gpu-item {whisper_state}">
        <span>Whisper 轉錄</span>
        <strong>{whisper_label}</strong>
        <small>{html.escape(str(whisper_note))}</small>
      </div>
      <div class="gpu-item {diar_state}">
        <span>說話人分離</span>
        <strong>{diar_label}</strong>
        <small>{html.escape(str(diar_note))}</small>
      </div>
    </div>
    {recommendation_html}
    """


def refresh_gpu_status() -> tuple[str, str]:
    _TRANSCRIPTION_SERVICE.clear_runtime_cache()
    return gpu_status_html(force=True), "環境狀態已重新檢查。"


def apply_quality_profile(
    profile_key: str,
    current_model: str,
    current_device: str,
    current_compute: str,
    current_beam: int,
    current_vad: bool,
    current_words: bool,
) -> tuple[str, str, str, int, bool, bool, str]:
    profile = resolve_profile(
        profile_key,
        _environment_report(),
    )
    if profile is None:
        return (
            current_model,
            current_device,
            current_compute,
            int(current_beam),
            bool(current_vad),
            bool(current_words),
            "已切換為自訂設定；後續調整不會被設定檔覆蓋。",
        )
    return (
        profile.model_size,
        profile.device,
        profile.compute_type,
        profile.beam_size,
        profile.vad_filter,
        profile.word_timestamps,
        f"已套用「{profile.label}」：{profile.note}",
    )


def environment_recommendation_rows(
    force: bool = False,
) -> list[list[Any]]:
    report = _environment_report(force=force)
    severity_labels = {
        "blocking": "需先處理",
        "warning": "建議處理",
        "info": "可選優化",
    }
    return [
        [
            severity_labels.get(
                str(item.get("severity")),
                str(item.get("severity") or "—"),
            ),
            str(item.get("code") or ""),
            str(item.get("title") or ""),
            str(item.get("reason") or ""),
            str(item.get("action") or ""),
        ]
        for item in report.get("recommendations", [])
    ]


def export_environment_report() -> tuple[str, str]:
    report = _environment_report(force=True)
    path = (
        BASE_DIR
        / ".cache"
        / "environment"
        / "environment-report.json"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)
    return str(path), "環境報告已更新，可直接下載或提供除錯使用。"


def _storage_summary_text() -> str:
    summary = storage_summary(BASE_DIR)
    plan = plan_wheel_cache_cleanup(BASE_DIR)
    return (
        f"模型 {format_size(summary['models_bytes'])} · "
        f"安裝快取 {format_size(summary['wheel_cache_bytes'])} · "
        f"轉錄輸出 {format_size(summary['transcriptions_bytes'])} · "
        f"可安全清理 {len(plan.candidates)} 組舊快取"
        f"（{format_size(plan.total_bytes)}）"
    )


def refresh_storage_view() -> tuple[list[list[Any]], str]:
    return model_inventory(BASE_DIR), _storage_summary_text()


def cleanup_cache_ui(
    confirmed: bool,
) -> tuple[list[list[Any]], str, bool]:
    try:
        removed, reclaimed = cleanup_old_wheel_cache(
            BASE_DIR,
            confirmed=confirmed,
        )
    except ValueError as exc:
        raise gr.Error(str(exc)) from exc
    return (
        model_inventory(BASE_DIR),
        (
            f"已清理 {removed} 組舊安裝快取，"
            f"釋放 {format_size(reclaimed)}。"
            f"{_storage_summary_text()}"
        ),
        False,
    )


def refresh_history_view() -> tuple[list[list[Any]], list[str] | None, str]:
    records = list_history(OUTPUT_DIR, limit=100)
    rows = [record.to_row() for record in records]
    files = [
        path
        for record in records[:20]
        for path in record.files
        if Path(path).exists()
    ][:20]
    return (
        rows,
        files or None,
        f"已載入 {len(records)} 筆轉錄紀錄。",
    )


def cancel_active_job() -> str:
    if _JOB_MANAGER.cancel_active():
        return "正在取消工作；已完成的原子輸出會保留，未完成輸出不會寫入。"
    return "目前沒有執行中的工作。"


def _hf_token(value: str | None) -> str:
    return resolve_hf_token(value)


def _cached_pyannote_model_path() -> str:
    return find_cached_pyannote_model(BASE_DIR)


def refresh_pyannote_model_path() -> tuple[str, str]:
    path = _cached_pyannote_model_path()
    if path:
        return path, f"已自動偵測 pyannote 本機模型：{path}"
    return "", "未找到本機 pyannote 模型；可用 WhisperTools.cmd 下載離線模型，或填入 Hugging Face token。"


def _run_diarization(
    audio_path: str,
    token: str,
    device: str,
    model_path: str | None,
    num_speakers: float | None,
    min_speakers: float | None,
    max_speakers: float | None,
) -> tuple[list[dict[str, Any]], str]:
    return _DIARIZATION_SERVICE.run(
        audio_path,
        DiarizationOptions(
            enabled=True,
            token=token,
            model_path=model_path or "",
            num_speakers=int(num_speakers or 0),
            min_speakers=int(min_speakers or 0),
            max_speakers=int(max_speakers or 0),
        ),
        device,
    )
def _as_path(file_item: Any) -> str:
    if isinstance(file_item, (str, os.PathLike)):
        return str(file_item)
    if hasattr(file_item, "name"):
        return str(file_item.name)
    if isinstance(file_item, dict):
        return str(file_item.get("path") or file_item.get("name") or "")
    return str(file_item)


def _sort_audio_files(files: list[Any], sort_mode: str) -> list[str]:
    paths = [path for path in (_as_path(item) for item in files or []) if path]

    def modified_at(path: str) -> float:
        try:
            return Path(path).stat().st_mtime
        except OSError:
            return 0.0

    if sort_mode in {"name_desc", "檔名 Z-A"}:
        return sorted(paths, key=lambda p: Path(p).name.casefold(), reverse=True)
    if sort_mode in {"mtime_asc", "修改時間 舊到新"}:
        return sorted(paths, key=modified_at)
    if sort_mode in {"mtime_desc", "修改時間 新到舊"}:
        return sorted(paths, key=modified_at, reverse=True)
    return sorted(paths, key=lambda p: Path(p).name.casefold())


def preview_batch_queue(files: list[Any] | None, sort_mode: str) -> tuple[list[list[Any]], str]:
    paths = _sort_audio_files(files or [], sort_mode)
    rows = [
        [index, Path(path).name, "等待處理", "—"]
        for index, path in enumerate(paths, start=1)
    ]
    status = f"已排序 {len(rows)} 個音檔。" if rows else "尚未加入批次音檔。"
    return rows, status


def _queue_rows(queue_override: Any) -> list[list[Any]]:
    if queue_override is None:
        return []
    if hasattr(queue_override, "values"):
        return queue_override.values.tolist()
    if isinstance(queue_override, dict) and "data" in queue_override:
        return queue_override["data"]
    return list(queue_override or [])


def _create_request(
    audio_path: str | None,
    model_size: str,
    language: str,
    task: str,
    beam_size: int,
    vad_filter: bool,
    word_timestamps: bool,
    device: str,
    compute_type: str,
    output_formats: list[str] | None,
    enable_diarization: bool,
    hf_token: str | None,
    diarization_model_path: str | None,
    num_speakers: float | None,
    min_speakers: float | None,
    max_speakers: float | None,
    include_segment_numbers: bool,
) -> TranscriptionRequest:
    if not audio_path:
        raise ValueError("請先上傳音訊檔，或用麥克風錄音。")
    return TranscriptionRequest(
        source_path=str(audio_path),
        model_size=model_size,
        language=language,
        task=task,
        beam_size=int(beam_size),
        vad_filter=bool(vad_filter),
        word_timestamps=bool(word_timestamps),
        device=device,
        compute_type=compute_type,
        diarization=DiarizationOptions(
            enabled=bool(enable_diarization),
            token=_hf_token(hf_token),
            model_path=(diarization_model_path or "").strip(),
            num_speakers=int(num_speakers or 0),
            min_speakers=int(min_speakers or 0),
            max_speakers=int(max_speakers or 0),
        ),
        export=ExportOptions(
            formats=tuple(
                output_formats or ["txt_timeline"]
            ),
            include_segment_numbers=bool(
                include_segment_numbers
            ),
        ),
    )


def _save_current_settings(
    request: TranscriptionRequest,
    quality_profile: str,
) -> None:
    save_settings(
        BASE_DIR,
        UserSettings(
            quality_profile=quality_profile,
            model_size=request.model_size,
            language=request.language,
            device=request.device,
            compute_type=request.compute_type,
            beam_size=request.beam_size,
            vad_filter=request.vad_filter,
            word_timestamps=request.word_timestamps,
            output_formats=request.export.formats,
            include_segment_numbers=(
                request.export.include_segment_numbers
            ),
        ),
    )


def _transcribe_impl(
    request: TranscriptionRequest,
    token: Any,
    *,
    quality_profile: str = "custom",
) -> Iterator[
    tuple[
        str,
        str,
        list[list[Any]],
        list[str] | None,
        str,
    ]
]:
    started_at = time.monotonic()
    _save_current_settings(request, quality_profile)
    segments: list[TranscriptSegment] = []
    runtime = RuntimeSelection(
        request.device,
        request.compute_type,
    )
    language = ""
    language_probability = 0.0
    last_emit = 0.0

    _JOB_MANAGER.update(
        JobStatus.PREPARING,
        "正在準備轉錄。",
    )
    for event in _TRANSCRIPTION_SERVICE.stream(request, token):
        runtime = event.runtime
        status_prefix = (
            f"模型：{request.model_size}，"
            f"裝置：{runtime.device}，"
            f"精度：{runtime.compute_type}"
        )
        if runtime.note:
            status_prefix += f"，{runtime.note}"
        if event.stage in {"loading", "analyzing", "fallback"}:
            detected = (
                "偵測語言：載入模型中..."
                if event.stage == "loading"
                else "偵測語言：分析中..."
            )
            yield (
                "",
                detected,
                [],
                None,
                (
                    f"{event.message} {status_prefix}，"
                    f"已用時：{format_elapsed(time.monotonic() - started_at)}"
                ),
            )
            continue
        if event.segment is not None:
            _JOB_MANAGER.update(
                JobStatus.TRANSCRIBING,
                event.message,
            )
            segments.append(event.segment)
            language = event.language
            language_probability = (
                event.language_probability
            )
            now = time.monotonic()
            if now - last_emit < STREAM_UPDATE_INTERVAL:
                continue
            last_emit = now
            display = "\n".join(
                _display_lines_from_rows(
                    segments,
                    include_numbers=(
                        request.export.include_segment_numbers
                    ),
                )
            )
            detected = (
                f"偵測語言：{language}，"
                f"信心：{language_probability:.2f}"
            )
            yield (
                display,
                detected,
                _numbered_table_rows(segments),
                None,
                (
                    "轉錄中... 已完成到 "
                    f"{_format_timestamp(event.segment.end)}，"
                    f"目前分段數：{len(segments)}，"
                    f"{status_prefix}，"
                    f"已用時：{format_elapsed(time.monotonic() - started_at)}"
                ),
            )
        elif event.stage == "completed":
            language = event.language
            language_probability = (
                event.language_probability
            )

    display_full = "\n".join(
        _display_lines_from_rows(
            segments,
            include_numbers=(
                request.export.include_segment_numbers
            ),
        )
    )
    detected = (
        f"偵測語言：{language}，"
        f"信心：{language_probability:.2f}"
    )
    speaker_segments: list[dict[str, Any]] = []
    diarization_status = (
        "未啟用；Whisper 僅提供文字與時間軸。"
    )

    if request.diarization.enabled:
        _JOB_MANAGER.update(
            JobStatus.DIARIZING,
            "正在執行說話人分離。",
        )
        if runtime.device == "cuda":
            _TRANSCRIPTION_SERVICE.release_models()
        yield (
            display_full,
            detected,
            _numbered_table_rows(segments),
            None,
            (
                "轉錄完成，正在執行說話人分離；"
                "長音檔可能需要數分鐘。"
            ),
        )
        try:
            speaker_segments, diarization_status = (
                _DIARIZATION_SERVICE.run(
                    request.source_path,
                    request.diarization,
                    runtime.device,
                    token,
                )
            )
            segments = assign_speakers(
                segments,
                speaker_segments,
            )
            display_full = "\n".join(
                _display_lines_from_rows(
                    segments,
                    include_numbers=(
                        request.export.include_segment_numbers
                    ),
                )
            )
            yield (
                display_full,
                detected,
                _numbered_table_rows(segments),
                None,
                f"說話人分離完成。{diarization_status}",
            )
        except JobCancelledError:
            raise
        except Exception as exc:
            segments = assign_speakers(segments, [])
            diarization_status = f"啟用但失敗：{exc}"
            yield (
                display_full,
                detected,
                _numbered_table_rows(segments),
                None,
                (
                    "說話人分離失敗，已保留一般轉錄結果。"
                    f"{exc}"
                ),
            )
    else:
        segments = assign_speakers(segments, [])

    token.raise_if_cancelled()
    _JOB_MANAGER.update(
        JobStatus.EXPORTING,
        "正在建立輸出檔。",
    )
    bundle = write_transcription_outputs(
        OUTPUT_DIR,
        request.source_path,
        segments,
        request.export,
        language=language,
        language_probability=language_probability,
        diarization_status=diarization_status,
        diarization_segments=speaker_segments,
        token=token,
    )
    elapsed_seconds = time.monotonic() - started_at
    write_history_manifest(
        OUTPUT_DIR,
        stem=bundle.stem,
        source_path=request.source_path,
        model_size=request.model_size,
        device=runtime.device,
        compute_type=runtime.compute_type,
        segment_count=len(segments),
        elapsed_seconds=elapsed_seconds,
        files=bundle.files,
    )
    status_parts = [
        "轉錄完成",
        f"模型：{request.model_size}",
        f"裝置：{runtime.device}",
        f"精度：{runtime.compute_type}",
        f"分段數：{len(segments)}",
        f"輸出檔數：{len(bundle.files)}",
        f"用時：{format_elapsed(elapsed_seconds)}",
    ]
    if runtime.note:
        status_parts.append(runtime.note)
    if request.diarization.enabled:
        status_parts.append(
            f"說話人分離：{diarization_status}"
        )
    yield (
        display_full,
        detected,
        _numbered_table_rows(segments),
        list(bundle.files),
        "，".join(status_parts),
    )


def transcribe(
    audio_path: str | None,
    model_size: str,
    language: str,
    task: str,
    beam_size: int,
    vad_filter: bool,
    word_timestamps: bool,
    device: str,
    compute_type: str,
    output_formats: list[str] | None = None,
    enable_diarization: bool = False,
    hf_token: str | None = None,
    diarization_model_path: str | None = None,
    num_speakers: float | None = None,
    min_speakers: float | None = None,
    max_speakers: float | None = None,
    include_segment_numbers: bool = True,
    quality_profile: str = "custom",
) -> Iterator[tuple[str, str, list[list[Any]], list[str] | None, str]]:
    try:
        request = _create_request(
            audio_path,
            model_size,
            language,
            task,
            beam_size,
            vad_filter,
            word_timestamps,
            device,
            compute_type,
            output_formats,
            enable_diarization,
            hf_token,
            diarization_model_path,
            num_speakers,
            min_speakers,
            max_speakers,
            include_segment_numbers,
        )
        with _JOB_MANAGER.run(
            "single",
            Path(request.source_path).name,
        ) as token:
            yield from _transcribe_impl(
                request,
                token,
                quality_profile=quality_profile,
            )
    except JobCancelledError as exc:
        raise gr.Error(str(exc)) from exc
    except (
        JobBusyError,
        TranscriptionError,
        ValueError,
    ) as exc:
        raise gr.Error(str(exc)) from exc


def batch_transcribe(
    audio_files: list[Any] | None,
    sort_mode: str,
    queue_override: list[list[Any]] | None,
    model_size: str,
    language: str,
    task: str,
    beam_size: int,
    vad_filter: bool,
    word_timestamps: bool,
    device: str,
    compute_type: str,
    output_formats: list[str] | None = None,
    enable_diarization: bool = False,
    hf_token: str | None = None,
    diarization_model_path: str | None = None,
    num_speakers: float | None = None,
    min_speakers: float | None = None,
    max_speakers: float | None = None,
    include_segment_numbers: bool = True,
    quality_profile: str = "custom",
) -> Iterator[
    tuple[str, str, list[list[Any]], list[str] | None, str, list[list[Any]], list[str] | None]
]:
    yield from _batch_entry(
        audio_files,
        sort_mode,
        queue_override,
        model_size,
        language,
        task,
        beam_size,
        vad_filter,
        word_timestamps,
        device,
        compute_type,
        output_formats,
        enable_diarization,
        hf_token,
        diarization_model_path,
        num_speakers,
        min_speakers,
        max_speakers,
        include_segment_numbers,
        quality_profile,
        failed_only=False,
    )


def retry_failed_batch(
    audio_files: list[Any] | None,
    sort_mode: str,
    queue_override: list[list[Any]] | None,
    model_size: str,
    language: str,
    task: str,
    beam_size: int,
    vad_filter: bool,
    word_timestamps: bool,
    device: str,
    compute_type: str,
    output_formats: list[str] | None = None,
    enable_diarization: bool = False,
    hf_token: str | None = None,
    diarization_model_path: str | None = None,
    num_speakers: float | None = None,
    min_speakers: float | None = None,
    max_speakers: float | None = None,
    include_segment_numbers: bool = True,
    quality_profile: str = "custom",
) -> Iterator[
    tuple[str, str, list[list[Any]], list[str] | None, str, list[list[Any]], list[str] | None]
]:
    yield from _batch_entry(
        audio_files,
        sort_mode,
        queue_override,
        model_size,
        language,
        task,
        beam_size,
        vad_filter,
        word_timestamps,
        device,
        compute_type,
        output_formats,
        enable_diarization,
        hf_token,
        diarization_model_path,
        num_speakers,
        min_speakers,
        max_speakers,
        include_segment_numbers,
        quality_profile,
        failed_only=True,
    )


def _ordered_batch_paths(
    audio_files: list[Any] | None,
    sort_mode: str,
    queue_override: list[list[Any]] | None,
    *,
    failed_only: bool,
) -> list[str]:
    paths = _sort_audio_files(audio_files or [], sort_mode)
    override_rows = _queue_rows(queue_override)
    if not override_rows:
        return [] if failed_only else paths

    name_to_paths: dict[str, list[str]] = {}
    for path in paths:
        name_to_paths.setdefault(Path(path).name, []).append(path)
    ordered_rows = sorted(
        override_rows,
        key=lambda row: (
            float(row[0])
            if row
            and str(row[0]).replace(".", "", 1).isdigit()
            else 999999
        ),
    )
    if failed_only:
        ordered_rows = [
            row
            for row in ordered_rows
            if len(row) >= 3
            and str(row[2]).startswith("失敗")
        ]
    ordered_paths: list[str] = []
    for row in ordered_rows:
        if len(row) < 2:
            continue
        name = str(row[1])
        if name_to_paths.get(name):
            ordered_paths.append(name_to_paths[name].pop(0))
    if not failed_only:
        used = set(ordered_paths)
        ordered_paths.extend(
            path for path in paths if path not in used
        )
    return ordered_paths


def _batch_entry(
    audio_files: list[Any] | None,
    sort_mode: str,
    queue_override: list[list[Any]] | None,
    model_size: str,
    language: str,
    task: str,
    beam_size: int,
    vad_filter: bool,
    word_timestamps: bool,
    device: str,
    compute_type: str,
    output_formats: list[str] | None,
    enable_diarization: bool,
    hf_token: str | None,
    diarization_model_path: str | None,
    num_speakers: float | None,
    min_speakers: float | None,
    max_speakers: float | None,
    include_segment_numbers: bool,
    quality_profile: str,
    *,
    failed_only: bool,
) -> Iterator[
    tuple[str, str, list[list[Any]], list[str] | None, str, list[list[Any]], list[str] | None]
]:
    paths = _ordered_batch_paths(
        audio_files,
        sort_mode,
        queue_override,
        failed_only=failed_only,
    )
    if not paths:
        message = (
            "目前沒有可重試的失敗音檔。"
            if failed_only
            else "請先加入一個或多個音檔。"
        )
        raise gr.Error(message)

    try:
        with _JOB_MANAGER.run(
            "batch-retry" if failed_only else "batch",
            f"{len(paths)} 個音檔",
        ) as token:
            queue_rows = [
                [index, Path(path).name, "等待處理", "—"]
                for index, path in enumerate(paths, start=1)
            ]
            all_output_files: list[str] = []
            prefix = "失敗重試" if failed_only else "批次"
            yield (
                "",
                "偵測語言：等待批次處理",
                [],
                None,
                f"{prefix}已準備，共 {len(paths)} 個音檔。",
                queue_rows,
                None,
            )
            last_text = ""
            last_language = ""
            last_segments: list[list[Any]] = []

            for index, path in enumerate(paths, start=1):
                token.raise_if_cancelled()
                file_started_at = time.monotonic()
                queue_rows[index - 1][2] = "處理中"
                queue_rows[index - 1][3] = format_elapsed(0)
                batch_status = (
                    f"{prefix}處理中：{index}/{len(paths)} - "
                    f"{Path(path).name}"
                )
                yield (
                    last_text,
                    last_language,
                    last_segments,
                    all_output_files or None,
                    batch_status,
                    queue_rows,
                    all_output_files or None,
                )
                try:
                    request = _create_request(
                        path,
                        model_size,
                        language,
                        task,
                        beam_size,
                        vad_filter,
                        word_timestamps,
                        device,
                        compute_type,
                        output_formats,
                        enable_diarization,
                        hf_token,
                        diarization_model_path,
                        num_speakers,
                        min_speakers,
                        max_speakers,
                        include_segment_numbers,
                    )
                    last_files: list[str] | None = None
                    for (
                        text,
                        detected,
                        segments,
                        files,
                        status,
                    ) in _transcribe_impl(
                        request,
                        token,
                        quality_profile=quality_profile,
                    ):
                        last_text = text
                        last_language = detected
                        last_segments = segments
                        if files:
                            last_files = files
                        queue_rows[index - 1][3] = format_elapsed(
                            time.monotonic() - file_started_at
                        )
                        yield (
                            text,
                            detected,
                            segments,
                            all_output_files or None,
                            f"{batch_status}，{status}",
                            queue_rows,
                            all_output_files or None,
                        )
                    if last_files:
                        all_output_files.extend(last_files)
                    queue_rows[index - 1][2] = "完成"
                except JobCancelledError:
                    queue_rows[index - 1][2] = "已取消"
                    queue_rows[index - 1][3] = format_elapsed(
                        time.monotonic() - file_started_at
                    )
                    raise
                except Exception as exc:
                    queue_rows[index - 1][2] = f"失敗：{exc}"
                queue_rows[index - 1][3] = format_elapsed(
                    time.monotonic() - file_started_at
                )

                completed = sum(
                    row[2] == "完成" for row in queue_rows
                )
                yield (
                    last_text,
                    last_language,
                    last_segments,
                    all_output_files or None,
                    (
                        f"{prefix}進度：{index}/{len(paths)}，"
                        f"已完成 {completed} 個。"
                    ),
                    queue_rows,
                    all_output_files or None,
                )

            failed = sum(
                str(row[2]).startswith("失敗")
                for row in queue_rows
            )
            yield (
                last_text,
                last_language,
                last_segments,
                all_output_files or None,
                (
                    f"{prefix}完成：共 {len(paths)} 個音檔，"
                    f"失敗 {failed} 個，"
                    f"產生 {len(all_output_files)} 個檔案。"
                ),
                queue_rows,
                all_output_files or None,
            )
    except JobCancelledError:
        return
    except JobBusyError as exc:
        raise gr.Error(str(exc)) from exc


def _find_free_port(preferred: int) -> int:
    """優先用指定埠；被占用時往後找一個可用埠。"""
    for port in range(preferred, preferred + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return preferred


# 本機工作台：把音訊來源、GPU/模型設定、結果輸出分成穩定的三欄。
CUSTOM_CSS = """
:root {
  --app-bg: #f4f6f8;
  --panel: #ffffff;
  --panel-soft: #f8fafc;
  --line: #d7dde6;
  --line-strong: #b9c3d0;
  --ink: #172033;
  --muted: #667085;
  --blue: #2457a6;
  --blue-soft: #e9f1ff;
  --green: #087f5b;
  --green-soft: #e8f7f1;
  --amber: #9a5b00;
  --amber-soft: #fff4db;
  --red: #b42318;
  --red-soft: #fff0ee;
}
body,
.gradio-container {
  background: var(--app-bg) !important;
  color: var(--ink) !important;
  font-size: 15px !important;
  font-family: "Segoe UI Variable Text", "Segoe UI", "Noto Sans TC", sans-serif !important;
  font-variant-numeric: tabular-nums;
}
.gradio-container {
  box-sizing: border-box !important;
  width: min(1540px, calc(100vw - 32px)) !important;
  min-width: 1248px !important;
  max-width: 1540px !important;
  margin: 0 auto !important;
  padding: 20px 24px 28px !important;
}
#desktop-width-warning {
  display: none;
  position: fixed;
  inset: 0;
  z-index: 10000;
  align-items: center;
  justify-content: center;
  background: rgba(23, 32, 51, 0.92);
  padding: 32px;
}
.desktop-width-card {
  width: 520px;
  border: 1px solid #efd18b;
  border-radius: 10px;
  background: #fff;
  color: var(--ink);
  padding: 28px 30px;
  box-shadow: 0 18px 54px rgba(23, 32, 51, 0.28);
}
.desktop-width-card strong {
  display: block;
  margin-bottom: 10px;
  color: var(--amber);
  font-size: 20px;
}
.desktop-width-card span {
  display: block;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.7;
}
.main,
.contain,
.wrap {
  max-width: none !important;
  width: 100% !important;
}
.main {
  padding: 0 !important;
}
.app-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  padding: 2px 0 14px;
  margin-bottom: 12px;
}
.app-title {
  font-size: 28px;
  line-height: 1.1;
  font-weight: 780;
  letter-spacing: 0;
  color: var(--ink);
}
.app-subtitle {
  margin-top: 7px;
  color: var(--muted);
  font-size: 14px;
}
.app-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.app-chip {
  border: 1px solid var(--line);
  background: #fff;
  color: var(--muted);
  border-radius: 7px;
  padding: 7px 10px;
  font-size: 12px;
  font-weight: 700;
}
.gpu-strip {
  display: grid;
  grid-template-columns: 1.15fr 1fr 1fr 1.2fr;
  gap: 10px;
  margin-bottom: 14px;
}
.gpu-item {
  min-height: 78px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  padding: 11px 12px;
  overflow: hidden;
}
.gpu-item span {
  display: block;
  color: var(--muted);
  font-size: 11px;
  font-weight: 780;
  margin-bottom: 5px;
}
.gpu-item strong {
  display: block;
  color: var(--ink);
  font-size: 14px;
  font-weight: 780;
  line-height: 1.25;
  word-break: break-word;
}
.gpu-item small {
  display: block;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.35;
  margin-top: 5px;
  word-break: break-word;
}
.gpu-item.ready {
  background: var(--green-soft);
  border-color: #a9dec7;
}
.gpu-item.ready strong {
  color: var(--green);
}
.gpu-item.warn {
  background: var(--amber-soft);
  border-color: #efd18b;
}
.gpu-item.warn strong {
  color: var(--amber);
}
.environment-advice {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin: -4px 0 14px;
  border: 1px solid #bcd3f5;
  border-radius: 8px;
  background: var(--blue-soft);
  color: var(--blue);
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.5;
}
.environment-advice strong {
  flex: 0 0 auto;
  font-weight: 800;
}
.environment-advice span {
  color: var(--ink);
}
.environment-advice.warning {
  border-color: #efd18b;
  background: var(--amber-soft);
  color: var(--amber);
}
.environment-advice.blocking {
  border-color: #f2b8b5;
  background: var(--red-soft);
  color: var(--red);
}
.panel {
  border: 1px solid var(--line) !important;
  border-radius: 8px !important;
  background: var(--panel) !important;
  padding: 13px !important;
  box-shadow: 0 1px 2px rgba(23, 32, 51, 0.035);
}
.gr-group.panel > .gr-group.panel {
  border: 0 !important;
  border-radius: 0 !important;
  background: transparent !important;
  padding: 0 !important;
  box-shadow: none !important;
}
.panel .styler {
  background: transparent !important;
  border: 0 !important;
  padding: 0 !important;
}
.panel.tight {
  padding: 12px !important;
}
.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 0 0 11px;
  font-size: 13px;
  font-weight: 800;
  color: var(--ink);
}
.section-note {
  color: var(--muted);
  font-size: 11px;
  font-weight: 700;
}
.block-title,
.block-label,
label > span {
  background: transparent !important;
  border: 0 !important;
  color: var(--muted) !important;
  font-size: 12px !important;
  font-weight: 700 !important;
  padding: 0 0 6px !important;
  box-shadow: none !important;
}
label.float {
  position: static !important;
  display: block !important;
  width: fit-content !important;
  height: auto !important;
  min-height: 0 !important;
  background: transparent !important;
  color: var(--muted) !important;
  padding: 0 0 8px !important;
  margin: 0 !important;
  font-size: 12px !important;
  font-weight: 760 !important;
}
#source-tabs,
#result-tabs {
  border: 0 !important;
}
.tabs {
  gap: 8px !important;
}
.tab-nav,
.tabitem {
  border-radius: 8px !important;
}
.tab-nav button {
  border-radius: 7px !important;
  font-weight: 760 !important;
}
#audio-input label.float svg.feather-music {
  display: none !important;
}
.wrap,
.form,
.block,
.input-container {
  border-radius: 8px !important;
}
textarea,
input,
select,
.dropdown-container {
  border-radius: 7px !important;
}
#audio-input {
  min-height: 220px !important;
}
#audio-input .audio-container,
#audio-input .wrap {
  border-radius: 8px !important;
}
#audio-input .audio-container {
  height: 210px !important;
}
#audio-input button.center,
#audio-input .center.boundedheight {
  height: 150px !important;
  min-height: 150px !important;
}
#audio-input .audio-container .wrap,
#audio-input .wrap {
  height: 150px !important;
  min-height: 150px !important;
  padding-top: 4px !important;
}
#audio-input .icon-wrap svg {
  width: 22px !important;
  height: 22px !important;
}
#run-btn,
#run-batch-btn,
#retry-batch-btn,
#gpu-refresh-btn {
  font-weight: 760 !important;
  min-height: 44px;
  border-radius: 7px !important;
}
#stop-btn,
#stop-batch-btn {
  min-height: 44px;
  border-radius: 7px !important;
}
button {
  transition:
    transform 160ms ease,
    background-color 180ms ease,
    border-color 180ms ease,
    box-shadow 180ms ease !important;
}
button:hover:not(:disabled) {
  transform: translateY(-1px);
}
button:active:not(:disabled) {
  transform: translateY(1px) scale(0.99);
}
button:focus-visible,
input:focus-visible,
textarea:focus-visible,
[role="listbox"]:focus-visible {
  outline: 3px solid rgba(36, 87, 166, 0.28) !important;
  outline-offset: 2px !important;
}
.status-bar {
  margin-bottom: 14px !important;
  background: var(--blue-soft) !important;
  border-color: #bcd3f5 !important;
  padding: 10px 14px !important;
}
.status-bar .section-note {
  color: var(--blue) !important;
}
#status-box textarea {
  min-height: 44px !important;
  font-size: 14px !important;
  font-weight: 650 !important;
  line-height: 1.5 !important;
  color: var(--blue) !important;
  background: transparent !important;
  border: 0 !important;
  box-shadow: none !important;
  padding: 2px 0 0 !important;
}
#status-box {
  min-height: 44px !important;
  border: 0 !important;
  border-radius: 0 !important;
  background: transparent !important;
  padding: 0 !important;
  box-shadow: none !important;
}
/* 巢狀進階折疊區：視覺退一階，和主設定區分 */
.panel .accordion .accordion {
  background: var(--panel-soft) !important;
  border-radius: 8px !important;
}
#transcript-box textarea {
  min-height: 520px !important;
  font-size: 15px !important;
  line-height: 1.65 !important;
  background: #fbfcfe !important;
}
#language-box textarea {
  min-height: 44px !important;
  color: var(--green) !important;
  font-weight: 650 !important;
}
#batch-queue {
  min-height: 220px !important;
}
#management-panel {
  margin-top: 14px !important;
  border: 1px solid var(--line) !important;
  border-radius: 9px !important;
  background: var(--panel) !important;
}
#management-panel table {
  font-variant-numeric: tabular-nums;
}
.download-panel {
  margin-top: 0 !important;
}
.app-footer {
  text-align: center;
  color: var(--muted);
  margin-top: 16px;
  font-size: 12px;
}
"""

THEME = gr.themes.Soft(
    primary_hue="teal",
    secondary_hue="indigo",
    neutral_hue="slate",
    font=[
        gr.themes.Font("Segoe UI Variable Text"),
        gr.themes.Font("Segoe UI"),
        gr.themes.Font("Noto Sans TC"),
        gr.themes.Font("sans-serif"),
    ],
)

with gr.Blocks(title="Whisper 語音轉文字", analytics_enabled=False) as demo:
    gr.HTML(
        """
        <div id="desktop-width-warning" aria-hidden="true">
          <div class="desktop-width-card">
            <strong>請放大桌面視窗</strong>
            <span>此工作台只提供桌面版，最低寬度為 1280px。請將瀏覽器最大化或改用較大的桌面顯示器；介面不會切換成手機版。</span>
          </div>
        </div>
        """
    )
    gr.HTML(
        """
        <header class="app-header">
          <div>
            <div class="app-title">Whisper 本機轉錄工作台</div>
            <div class="app-subtitle">轉錄、批次排序、說話人標註與字幕輸出集中處理。</div>
          </div>
          <div class="app-actions">
            <a href="/live/" class="app-chip">即時收音／文字稿編輯 →</a>
            <div class="app-chip">Desktop 1280+</div>
            <div class="app-chip">Local only</div>
          </div>
        </header>
        """
    )
    gpu_status_panel = gr.HTML(value=gpu_status_html())

    # 執行狀態：拉到最上方的整行橫幅，轉錄/分離進度一眼可見
    with gr.Group(elem_classes=["panel", "status-bar"]):
        gr.HTML('<div class="section-title" style="margin-bottom:4px">執行狀態 <span class="section-note">即時進度</span></div>')
        status_output = gr.Textbox(
            value="等待音訊",
            interactive=False,
            show_label=False,
            container=False,
            lines=1,
            max_lines=3,
            elem_id="status-box",
        )

    with gr.Row():
        with gr.Column(scale=4, min_width=320):
            with gr.Group(elem_classes=["panel"]):
                gr.HTML('<div class="section-title">來源 <span class="section-note">單檔或批次</span></div>')
                with gr.Tabs(elem_id="source-tabs"):
                    with gr.Tab("單檔轉錄"):
                        audio = gr.Audio(
                            sources=["upload", "microphone"],
                            type="filepath",
                            label="音訊檔或麥克風錄音",
                            elem_id="audio-input",
                        )
                        with gr.Row():
                            run_button = gr.Button("開始轉錄", variant="primary", scale=3, elem_id="run-btn")
                            stop_button = gr.Button("取消", variant="stop", scale=1, elem_id="stop-btn")

                    with gr.Tab("批次排序"):
                        batch_audio = gr.Files(
                            label="多個音檔",
                            file_count="multiple",
                            type="filepath",
                        )
                        with gr.Row():
                            batch_sort = gr.Dropdown(
                                [
                                    ("檔名 A-Z", "name_asc"),
                                    ("檔名 Z-A", "name_desc"),
                                    ("修改時間 舊到新", "mtime_asc"),
                                    ("修改時間 新到舊", "mtime_desc"),
                                ],
                                value="name_asc",
                                label="排序方式",
                            )
                            preview_batch_button = gr.Button("更新佇列", scale=1)
                        batch_queue = gr.Dataframe(
                            headers=["序號", "檔名", "狀態", "用時"],
                            label="處理佇列（修改序號即可調整順序）",
                            interactive=True,
                            elem_id="batch-queue",
                        )
                        with gr.Row():
                            run_batch_button = gr.Button("依序處理", variant="primary", scale=2, elem_id="run-batch-btn")
                            retry_batch_button = gr.Button("只重試失敗", scale=1, elem_id="retry-batch-btn")
                            stop_batch_button = gr.Button("停止批次", variant="stop", scale=1, elem_id="stop-batch-btn")

        with gr.Column(scale=3, min_width=300):
            with gr.Group(elem_classes=["panel", "tight"]):
                gr.HTML('<div class="section-title">模型與執行裝置 <span class="section-note">依環境自動選擇</span></div>')
                quality_profile = gr.Dropdown(
                    [
                        ("依目前環境自動建議", "auto"),
                        ("快速", "fast"),
                        ("平衡", "balanced"),
                        ("高準確", "accurate"),
                        ("自訂", "custom"),
                    ],
                    value=_USER_SETTINGS.quality_profile,
                    label="品質設定檔",
                    info="選擇設定檔會同步更新模型、裝置、精度與辨識細節。",
                )
                with gr.Row():
                    model_size = gr.Dropdown(
                        ["tiny", "base", "small", "medium", "large-v3"],
                        value=_USER_SETTINGS.model_size,
                        label="模型",
                    )
                    language = gr.Dropdown(
                        LANGUAGE_CHOICES,
                        value=_USER_SETTINGS.language,
                        label="語言",
                    )
                task = gr.Radio(
                    [("轉錄原文", "transcribe"), ("翻譯成英文", "translate")],
                    value="transcribe",
                    label="模式",
                )
                with gr.Row():
                    device = gr.Dropdown(
                        ["auto", "cuda", "cpu"],
                        value=_USER_SETTINGS.device,
                        label="裝置",
                    )
                    compute_type = gr.Dropdown(
                        ["default", "int8", "float16", "float32"],
                        value=_USER_SETTINGS.compute_type,
                        label="精度",
                    )
                gpu_refresh_button = gr.Button("重新檢查環境", elem_id="gpu-refresh-btn")

            with gr.Group(elem_classes=["panel", "tight"]):
                gr.HTML('<div class="section-title">輸出</div>')
                output_formats = gr.CheckboxGroup(
                    OUTPUT_FORMAT_CHOICES,
                    value=list(_USER_SETTINGS.output_formats),
                    label="輸出格式",
                )
                include_segment_numbers = gr.Checkbox(
                    value=_USER_SETTINGS.include_segment_numbers,
                    label="顯示句段編號",
                    info="畫面與 TXT 以 1、2、3 編號；JSON、SRT、VTT 永遠保留可定位序號。",
                )
                with gr.Accordion("說話人標註", open=True):
                    enable_diarization = gr.Checkbox(
                        value=bool(_cached_pyannote_model_path() or _hf_token(None)),
                        label="啟用說話人標註（pyannote）",
                        info="偵測到本機模型或環境 token 時預設開啟；未就緒時保持關閉。",
                    )
                    with gr.Accordion("進階：模型與人數設定", open=False):
                        diarization_model_path = gr.Textbox(
                            label="本機 pyannote 模型資料夾（自動偵測）",
                            value=_cached_pyannote_model_path(),
                            placeholder="未偵測到時可手動貼上模型資料夾",
                        )
                        detect_pyannote_button = gr.Button("自動偵測本機模型")
                        hf_token = gr.Textbox(
                            label="Hugging Face token",
                            type="password",
                            placeholder="線上首次下載才需要；純離線可留空",
                        )
                        with gr.Row():
                            num_speakers = gr.Number(value=0, label="固定人數", precision=0)
                            min_speakers = gr.Number(value=0, label="最少", precision=0)
                            max_speakers = gr.Number(value=0, label="最多", precision=0)
                with gr.Accordion("辨識細節", open=False):
                    beam_size = gr.Slider(
                        1,
                        10,
                        value=_USER_SETTINGS.beam_size,
                        step=1,
                        label="辨識精細度",
                    )
                    vad_filter = gr.Checkbox(
                        value=_USER_SETTINGS.vad_filter,
                        label="自動略過靜音",
                    )
                    word_timestamps = gr.Checkbox(
                        value=_USER_SETTINGS.word_timestamps,
                        label="逐字時間資訊（JSON）",
                    )

        with gr.Column(scale=5, min_width=420):
            with gr.Group(elem_classes=["panel"]):
                gr.HTML('<div class="section-title">結果 <span class="section-note">串流分段</span></div>')
                language_output = gr.Textbox(
                    label="偵測語言",
                    interactive=False,
                    elem_id="language-box",
                )
                text_output = gr.Textbox(
                    label="轉錄文字",
                    lines=20,
                    placeholder="轉錄開始後，帶編號的句段會顯示在這裡。",
                    elem_id="transcript-box",
                )
            with gr.Group(elem_classes=["panel", "tight"]):
                with gr.Tabs(elem_id="result-tabs"):
                    with gr.Tab("下載"):
                        with gr.Row():
                            files_output = gr.Files(
                                label="單檔輸出",
                                elem_classes=["download-panel"],
                            )
                            batch_files_output = gr.Files(
                                label="批次輸出",
                                elem_classes=["download-panel"],
                            )
                    with gr.Tab("分段表"):
                        segments_output = gr.Dataframe(
                            headers=["序號", "開始秒數", "結束秒數", "說話人", "文字"],
                            label=None,
                            interactive=False,
                        )

    with gr.Accordion(
        "環境、儲存與歷史",
        open=False,
        elem_id="management-panel",
    ):
        with gr.Tabs():
            with gr.Tab("環境診斷"):
                environment_recommendations = gr.Dataframe(
                    headers=[
                        "優先級",
                        "代碼",
                        "項目",
                        "原因",
                        "建議動作",
                    ],
                    value=environment_recommendation_rows(),
                    interactive=False,
                    label="環境設定建議",
                )
                with gr.Row():
                    export_environment_button = gr.Button(
                        "更新並匯出環境報告",
                        variant="primary",
                    )
                    environment_report_file = gr.File(
                        label="環境報告 JSON",
                        interactive=False,
                    )
            with gr.Tab("模型與快取"):
                model_table = gr.Dataframe(
                    headers=[
                        "類型",
                        "模型",
                        "容量",
                        "更新時間",
                    ],
                    value=model_inventory(BASE_DIR),
                    interactive=False,
                    label="已下載模型",
                )
                storage_status = gr.Textbox(
                    value=_storage_summary_text(),
                    label="容量摘要",
                    interactive=False,
                )
                confirm_cache_cleanup = gr.Checkbox(
                    value=False,
                    label="我確認只清理 14 天以前的舊 wheel 快取，並保留最新一組",
                )
                with gr.Row():
                    refresh_storage_button = gr.Button("重新計算容量")
                    cleanup_cache_button = gr.Button(
                        "清理舊安裝快取",
                        variant="stop",
                    )
            with gr.Tab("轉錄歷史"):
                history_table = gr.Dataframe(
                    headers=[
                        "時間",
                        "來源",
                        "模型",
                        "裝置",
                        "句段",
                        "用時",
                        "狀態",
                        "檔案數",
                    ],
                    value=[
                        record.to_row()
                        for record in list_history(
                            OUTPUT_DIR,
                            limit=100,
                        )
                    ],
                    interactive=False,
                    label="最近 100 筆",
                )
                history_files = gr.Files(
                    value=[
                        path
                        for record in list_history(
                            OUTPUT_DIR,
                            limit=20,
                        )
                        for path in record.files
                        if Path(path).exists()
                    ][:20]
                    or None,
                    label="最近輸出檔",
                )
                refresh_history_button = gr.Button("重新整理歷史")

    gr.HTML('<div class="app-footer">本機執行 · faster-whisper · pyannote · 輸出保存在 transcriptions 資料夾</div>')

    quality_profile.change(
        apply_quality_profile,
        inputs=[
            quality_profile,
            model_size,
            device,
            compute_type,
            beam_size,
            vad_filter,
            word_timestamps,
        ],
        outputs=[
            model_size,
            device,
            compute_type,
            beam_size,
            vad_filter,
            word_timestamps,
            status_output,
        ],
    )

    run_event = run_button.click(
        transcribe,
        inputs=[
            audio,
            model_size,
            language,
            task,
            beam_size,
            vad_filter,
            word_timestamps,
            device,
            compute_type,
            output_formats,
            enable_diarization,
            hf_token,
            diarization_model_path,
            num_speakers,
            min_speakers,
            max_speakers,
            include_segment_numbers,
            quality_profile,
        ],
        outputs=[text_output, language_output, segments_output, files_output, status_output],
        js=START_JS,
    )
    run_event.success(js=DONE_JS)
    stop_event = stop_button.click(
        cancel_active_job,
        outputs=status_output,
    )
    stop_event.then(fn=None, cancels=[run_event])
    gpu_refresh_event = gpu_refresh_button.click(
        refresh_gpu_status,
        outputs=[gpu_status_panel, status_output],
    )
    gpu_refresh_event.then(
        environment_recommendation_rows,
        outputs=environment_recommendations,
    )
    detect_pyannote_button.click(
        refresh_pyannote_model_path,
        outputs=[diarization_model_path, status_output],
    )

    preview_batch_button.click(
        preview_batch_queue,
        inputs=[batch_audio, batch_sort],
        outputs=[batch_queue, status_output],
    )
    batch_event = run_batch_button.click(
        batch_transcribe,
        inputs=[
            batch_audio,
            batch_sort,
            batch_queue,
            model_size,
            language,
            task,
            beam_size,
            vad_filter,
            word_timestamps,
            device,
            compute_type,
            output_formats,
            enable_diarization,
            hf_token,
            diarization_model_path,
            num_speakers,
            min_speakers,
            max_speakers,
            include_segment_numbers,
            quality_profile,
        ],
        outputs=[
            text_output,
            language_output,
            segments_output,
            files_output,
            status_output,
            batch_queue,
            batch_files_output,
        ],
        js=START_JS,
    )
    batch_event.success(js=DONE_JS)
    retry_event = retry_batch_button.click(
        retry_failed_batch,
        inputs=[
            batch_audio,
            batch_sort,
            batch_queue,
            model_size,
            language,
            task,
            beam_size,
            vad_filter,
            word_timestamps,
            device,
            compute_type,
            output_formats,
            enable_diarization,
            hf_token,
            diarization_model_path,
            num_speakers,
            min_speakers,
            max_speakers,
            include_segment_numbers,
            quality_profile,
        ],
        outputs=[
            text_output,
            language_output,
            segments_output,
            files_output,
            status_output,
            batch_queue,
            batch_files_output,
        ],
        js=START_JS,
    )
    retry_event.success(js=DONE_JS)
    stop_batch_event = stop_batch_button.click(
        cancel_active_job,
        outputs=status_output,
    )
    stop_batch_event.then(
        fn=None,
        cancels=[batch_event, retry_event],
    )

    export_environment_button.click(
        export_environment_report,
        outputs=[environment_report_file, status_output],
    )
    refresh_storage_button.click(
        refresh_storage_view,
        outputs=[model_table, storage_status],
    )
    cleanup_cache_button.click(
        cleanup_cache_ui,
        inputs=confirm_cache_cleanup,
        outputs=[
            model_table,
            storage_status,
            confirm_cache_cleanup,
        ],
    )
    refresh_history_button.click(
        refresh_history_view,
        outputs=[
            history_table,
            history_files,
            status_output,
        ],
    )


def create_desktop_app():
    from whisper_app.live.server import create_live_app

    def release_models():
        _DIARIZATION_SERVICE.release_models()
        _TRANSCRIPTION_SERVICE.release_models()

    http_app = create_live_app(BASE_DIR, _JOB_MANAGER, release_models)
    return gr.mount_gradio_app(
        http_app, demo.queue(default_concurrency_limit=1), path="/",
        theme=THEME, css=CUSTOM_CSS, js=DESKTOP_WIDTH_JS,
    )


if __name__ == "__main__":
    import threading
    import webbrowser
    import uvicorn

    port = _find_free_port(int(os.environ.get("WHISPER_PORT", "7860")))
    http_app = create_desktop_app()
    if os.environ.get("WHISPER_NO_BROWSER") != "1":
        @http_app.on_event("startup")
        async def open_browser():
            threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    uvicorn.run(http_app, host="127.0.0.1", port=port, access_log=False, ws_max_size=65536)
