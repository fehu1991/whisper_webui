from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from whisper_app.domain.requests import ExportOptions
from whisper_app.domain.results import TranscriptSegment
from whisper_app.jobs import CancellationToken


TranscriptRow = Sequence[Any] | Mapping[str, Any] | TranscriptSegment


def format_timestamp(seconds: float, comma: bool = False) -> str:
    milliseconds = int(round(float(seconds) * 1000))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    separator = "," if comma else "."
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{separator}{millis:03d}"


def clock(seconds: float) -> str:
    total = int(float(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def row_parts(row: TranscriptRow) -> tuple[Any, Any, str, str]:
    if isinstance(row, TranscriptSegment):
        return row.start, row.end, row.speaker, row.text
    if isinstance(row, Mapping):
        return (
            row["start"],
            row["end"],
            str(row.get("speaker") or ""),
            str(row.get("text") or ""),
        )
    if len(row) >= 5:
        return row[1], row[2], str(row[3] or ""), str(row[4] or "")
    if len(row) >= 4:
        return row[0], row[1], str(row[2] or ""), str(row[3] or "")
    if len(row) >= 3:
        return row[0], row[1], "", str(row[2] or "")
    raise ValueError("Transcript row must contain at least start, end, and text.")


def numbered_table_rows(rows: Sequence[TranscriptRow]) -> list[list[Any]]:
    table_rows: list[list[Any]] = []
    for sequence, row in enumerate(rows, start=1):
        start, end, speaker, text = row_parts(row)
        table_rows.append([sequence, start, end, speaker, text])
    return table_rows


def srt_from_segments(rows: Sequence[TranscriptRow]) -> str:
    blocks = []
    for sequence, row in enumerate(rows, start=1):
        start, end, speaker, text = row_parts(row)
        subtitle_text = f"{speaker}: {text}" if speaker else text
        blocks.append(
            f"{sequence}\n"
            f"{format_timestamp(float(start), comma=True)} --> "
            f"{format_timestamp(float(end), comma=True)}\n"
            f"{subtitle_text}"
        )
    return "\n\n".join(blocks) + ("\n" if blocks else "")


def vtt_from_segments(rows: Sequence[TranscriptRow]) -> str:
    cues = []
    for sequence, row in enumerate(rows, start=1):
        start, end, speaker, text = row_parts(row)
        subtitle_text = f"{speaker}: {text}" if speaker else text
        cues.append(
            f"{sequence}\n"
            f"{format_timestamp(float(start))} --> {format_timestamp(float(end))}\n"
            f"{subtitle_text}"
        )
    return "WEBVTT\n\n" + "\n\n".join(cues) + ("\n" if cues else "")


def txt_timeline_from_segments(
    rows: Sequence[TranscriptRow],
    source_name: str,
    language: str,
    diarization_status: str,
    *,
    include_numbers: bool = True,
) -> str:
    lines = [
        f"來源：{source_name}",
        f"偵測語言：{language}",
        f"說話人分離：{diarization_status}",
        "",
    ]
    for sequence, row in enumerate(rows, start=1):
        start, end, speaker, text = row_parts(row)
        number_prefix = f"{sequence}. " if include_numbers else ""
        speaker_prefix = f"[{speaker}] " if speaker else ""
        lines.append(
            f"{number_prefix}{speaker_prefix}"
            f"[{format_timestamp(float(start))} - {format_timestamp(float(end))}] {text}"
        )
    return "\n".join(lines).rstrip() + "\n"


def txt_plain_from_segments(
    rows: Sequence[TranscriptRow],
    *,
    include_numbers: bool = True,
) -> str:
    lines = []
    for sequence, row in enumerate(rows, start=1):
        _, _, speaker, text = row_parts(row)
        number_prefix = f"{sequence}. " if include_numbers else ""
        text_line = f"{speaker}: {text}" if speaker else text
        lines.append(f"{number_prefix}{text_line}")
    return "\n".join(lines).strip() + ("\n" if lines else "")


def display_lines_from_rows(
    rows: Sequence[TranscriptRow],
    *,
    include_numbers: bool = True,
) -> list[str]:
    lines = []
    for sequence, row in enumerate(rows, start=1):
        start, _, speaker, text = row_parts(row)
        number_prefix = f"{sequence}. " if include_numbers else ""
        speaker_prefix = f"[{speaker}] " if speaker else ""
        lines.append(f"{number_prefix}{speaker_prefix}[{clock(float(start))}] {text}")
    return lines


@dataclass(frozen=True)
class ExportBundle:
    stem: str
    files: tuple[str, ...]


def output_stem(audio_path: str) -> str:
    raw = Path(audio_path).stem or "transcription"
    safe = "".join(
        character
        if character.isalnum() or character in "-_."
        else "_"
        for character in raw
    ).strip("._") or "transcription"
    return f"{safe}_{datetime.now():%Y%m%d_%H%M%S_%f}"


def _atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def write_transcription_outputs(
    output_dir: Path,
    audio_path: str,
    segments: Sequence[TranscriptSegment],
    options: ExportOptions,
    *,
    language: str,
    language_probability: float,
    diarization_status: str,
    diarization_segments: Sequence[dict[str, Any]],
    token: CancellationToken | None = None,
) -> ExportBundle:
    cancellation = token or CancellationToken()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = output_stem(audio_path)
    created: list[Path] = []

    def write(path: Path, content: str) -> None:
        cancellation.raise_if_cancelled()
        _atomic_write_text(path, content)
        created.append(path)

    try:
        if "txt_timeline" in options.formats:
            path = output_dir / f"{stem}_timeline.txt"
            write(
                path,
                txt_timeline_from_segments(
                    segments,
                    Path(audio_path).name,
                    language,
                    diarization_status,
                    include_numbers=options.include_segment_numbers,
                ),
            )
        if "txt_plain" in options.formats:
            path = output_dir / f"{stem}_plain.txt"
            write(
                path,
                txt_plain_from_segments(
                    segments,
                    include_numbers=options.include_segment_numbers,
                ),
            )
        if "srt" in options.formats:
            path = output_dir / f"{stem}.srt"
            write(path, srt_from_segments(segments))
        if "vtt" in options.formats:
            path = output_dir / f"{stem}.vtt"
            write(path, vtt_from_segments(segments))
        if "json" in options.formats:
            path = output_dir / f"{stem}.json"
            write(
                path,
                json.dumps(
                    {
                        "language": language,
                        "language_probability": round(
                            language_probability,
                            4,
                        ),
                        "speaker_diarization": diarization_status,
                        "diarization_segments": list(
                            diarization_segments
                        ),
                        "segments": [
                            segment.to_dict()
                            for segment in segments
                        ],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        cancellation.raise_if_cancelled()
    except Exception:
        for path in created:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        raise
    return ExportBundle(
        stem,
        tuple(str(path) for path in created),
    )
