"""Domain models shared by transcription, export, jobs, and UI adapters."""

from .results import TranscriptSegment, TranscriptWord

__all__ = ["TranscriptSegment", "TranscriptWord"]
from .environment import EnvironmentReport
from .jobs import JobRecord, JobStatus
from .requests import (
    DiarizationOptions,
    ExportOptions,
    TranscriptionRequest,
)
from .results import TranscriptSegment, TranscriptWord

__all__ = [
    "DiarizationOptions",
    "EnvironmentReport",
    "ExportOptions",
    "JobRecord",
    "JobStatus",
    "TranscriptSegment",
    "TranscriptWord",
    "TranscriptionRequest",
]
