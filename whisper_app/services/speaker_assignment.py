from __future__ import annotations

from dataclasses import replace
from typing import Any, Sequence

from whisper_app.domain.results import TranscriptSegment


def assign_speakers(
    segments: Sequence[TranscriptSegment],
    speaker_segments: Sequence[dict[str, Any]],
    *,
    fill_nearest: bool = True,
) -> list[TranscriptSegment]:
    if not speaker_segments:
        return [replace(segment, speaker="") for segment in segments]

    assigned: list[TranscriptSegment] = []
    for segment in segments:
        overlap_by_speaker: dict[str, float] = {}
        for speaker_segment in speaker_segments:
            intersection = min(
                float(speaker_segment["end"]),
                segment.end,
            ) - max(
                float(speaker_segment["start"]),
                segment.start,
            )
            if intersection <= 0:
                continue
            speaker = str(speaker_segment["speaker"])
            overlap_by_speaker[speaker] = (
                overlap_by_speaker.get(speaker, 0.0)
                + intersection
            )

        if overlap_by_speaker:
            speaker = max(
                overlap_by_speaker.items(),
                key=lambda item: item[1],
            )[0]
        elif fill_nearest:
            midpoint = (segment.start + segment.end) / 2
            nearest = min(
                speaker_segments,
                key=lambda item: abs(
                    (
                        (
                            float(item["start"])
                            + float(item["end"])
                        )
                        / 2
                    )
                    - midpoint
                ),
            )
            speaker = str(nearest["speaker"])
        else:
            speaker = "UNKNOWN"
        assigned.append(replace(segment, speaker=speaker))
    return assigned
