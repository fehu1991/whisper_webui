from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class TranscriptWord:
    start: float
    end: float
    word: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class TranscriptSegment:
    segment_id: str
    sequence: int
    start: float
    end: float
    text: str
    speaker: str = ""
    words: list[TranscriptWord] = field(default_factory=list)

    @classmethod
    def from_row(
        cls,
        row: Sequence[Any],
        *,
        sequence: int,
        segment_id: str | None = None,
    ) -> "TranscriptSegment":
        if len(row) >= 5:
            start, end, speaker, text = row[1], row[2], row[3], row[4]
        elif len(row) >= 4:
            start, end, speaker, text = row[0], row[1], row[2], row[3]
        elif len(row) >= 3:
            start, end, text = row[0], row[1], row[2]
            speaker = ""
        else:
            raise ValueError("Transcript row must contain at least start, end, and text.")
        return cls(
            segment_id=segment_id or make_segment_id(sequence),
            sequence=sequence,
            start=float(start),
            end=float(end),
            speaker=str(speaker or ""),
            text=str(text or ""),
        )

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "TranscriptSegment":
        sequence = int(value["sequence"])
        words = [
            TranscriptWord(
                start=float(item["start"]),
                end=float(item["end"]),
                word=str(item["word"]),
            )
            for item in value.get("words", [])
        ]
        return cls(
            segment_id=str(value.get("segment_id") or make_segment_id(sequence)),
            sequence=sequence,
            start=float(value["start"]),
            end=float(value["end"]),
            speaker=str(value.get("speaker") or ""),
            text=str(value.get("text") or ""),
            words=words,
        )

    def to_row(self) -> list[Any]:
        return [self.start, self.end, self.speaker, self.text]

    def to_table_row(self) -> list[Any]:
        return [self.sequence, self.start, self.end, self.speaker, self.text]

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "segment_id": self.segment_id,
            "sequence": self.sequence,
            "start": self.start,
            "end": self.end,
            "speaker": self.speaker,
            "text": self.text,
        }
        if self.words:
            value["words"] = [word.to_dict() for word in self.words]
        return value


def make_segment_id(sequence: int) -> str:
    if sequence < 1:
        raise ValueError("Segment sequence must be greater than zero.")
    return f"seg-{sequence:06d}"
