from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

from whisper_app.services.timing import format_elapsed


@dataclass(frozen=True)
class HistoryRecord:
    task_id: str
    created_at: str
    source_name: str
    model_size: str
    device: str
    segment_count: int
    elapsed_seconds: float | None
    status: str
    files: tuple[str, ...]
    manifest_path: str = ""

    def to_row(self) -> list[Any]:
        return [
            self.created_at.replace("T", " ")[:19],
            self.source_name,
            self.model_size or "—",
            self.device or "—",
            self.segment_count,
            format_elapsed(self.elapsed_seconds),
            self.status,
            len(self.files),
        ]


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def write_history_manifest(
    output_dir: Path,
    *,
    stem: str,
    source_path: str,
    model_size: str,
    device: str,
    compute_type: str,
    segment_count: int,
    elapsed_seconds: float,
    files: Iterable[str],
    status: str = "completed",
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / f"{stem}.manifest.json"
    payload = {
        "schema_version": "1.1",
        "task_id": stem,
        "created_at": datetime.now(UTC).isoformat(),
        "source_name": Path(source_path).name,
        "model_size": model_size,
        "device": device,
        "compute_type": compute_type,
        "segment_count": segment_count,
        "elapsed_seconds": max(0.0, float(elapsed_seconds)),
        "status": status,
        "files": [str(Path(path).resolve()) for path in files],
    }
    _atomic_json(manifest_path, payload)
    return manifest_path


def _manifest_records(output_dir: Path) -> list[HistoryRecord]:
    records: list[HistoryRecord] = []
    for path in output_dir.glob("*.manifest.json"):
        try:
            payload = json.loads(
                path.read_text(encoding="utf-8-sig")
            )
            files = tuple(
                item
                for item in payload.get("files", [])
                if Path(item).exists()
            )
            records.append(
                HistoryRecord(
                    task_id=str(
                        payload.get("task_id")
                        or path.name.removesuffix(
                            ".manifest.json"
                        )
                    ),
                    created_at=str(
                        payload.get("created_at")
                        or datetime.fromtimestamp(
                            path.stat().st_mtime,
                            tz=UTC,
                        ).isoformat()
                    ),
                    source_name=str(
                        payload.get("source_name") or "未知來源"
                    ),
                    model_size=str(
                        payload.get("model_size") or ""
                    ),
                    device=str(payload.get("device") or ""),
                    segment_count=int(
                        payload.get("segment_count") or 0
                    ),
                    elapsed_seconds=(
                        float(payload["elapsed_seconds"])
                        if payload.get("elapsed_seconds") is not None
                        else None
                    ),
                    status=str(
                        payload.get("status") or "completed"
                    ),
                    files=files,
                    manifest_path=str(path.resolve()),
                )
            )
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
    return records


def _legacy_records(
    output_dir: Path,
    known_files: set[str],
) -> list[HistoryRecord]:
    groups: dict[str, list[Path]] = {}
    paths = output_dir.iterdir() if output_dir.exists() else []
    for path in paths:
        if (
            not path.is_file()
            or path.name.endswith(".manifest.json")
            or path.suffix.lower()
            not in {".txt", ".srt", ".vtt", ".json"}
            or str(path.resolve()) in known_files
        ):
            continue
        stem = path.stem
        if stem.endswith("_timeline"):
            stem = stem.removesuffix("_timeline")
        elif stem.endswith("_plain"):
            stem = stem.removesuffix("_plain")
        groups.setdefault(stem, []).append(path)

    records: list[HistoryRecord] = []
    for stem, group_paths in groups.items():
        newest = max(path.stat().st_mtime for path in group_paths)
        source_name = stem[:-16] if len(stem) > 16 and stem[-16] == "_" else stem
        records.append(
            HistoryRecord(
                task_id=stem,
                created_at=datetime.fromtimestamp(
                    newest,
                    tz=UTC,
                ).isoformat(),
                source_name=source_name,
                model_size="",
                device="",
                segment_count=0,
                elapsed_seconds=None,
                status="legacy",
                files=tuple(
                    str(path.resolve())
                    for path in sorted(group_paths)
                ),
            )
        )
    return records


def list_history(
    output_dir: Path,
    *,
    limit: int = 100,
) -> list[HistoryRecord]:
    manifests = _manifest_records(output_dir)
    known_files = {
        item
        for record in manifests
        for item in record.files
    }
    records = manifests + _legacy_records(
        output_dir,
        known_files,
    )
    return sorted(
        records,
        key=lambda record: record.created_at,
        reverse=True,
    )[:limit]
