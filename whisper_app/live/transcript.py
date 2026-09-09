"""Turn WLK committed tokens into append-only editable rows, not ASR hypotheses."""
from __future__ import annotations

import math


class TranscriptAssembler:
    def __init__(self):
        self.seen: set[tuple] = set()
        self.pending: list[tuple] = []
        self.sequence = 0
        self.latest_end = 0.0

    def _commit(self):
        self.sequence += 1
        row = {"id": f"live-{self.sequence}", "start": self.pending[0][0],
               "end": self.pending[-1][1], "speaker": "待標註",
               "text": "".join(token[2] for token in self.pending).strip()}
        self.pending = []
        return row

    def update(self, tokens, final=False):
        rows = []
        for token in tokens:
            start, end, text = float(token.start), float(token.end), str(token.text or "")
            if not math.isfinite(start + end) or start < 0 or end < start or not text:
                continue
            key = (round(start, 4), round(end, 4), text)
            if key in self.seen or end < self.latest_end - 0.001:
                continue
            self.seen.add(key)
            self.latest_end = max(self.latest_end, end)
            if self.pending and start - self.pending[-1][1] > 1.0:
                rows.append(self._commit())
            self.pending.append(key)
            duration = end - self.pending[0][0]
            if (text.rstrip().endswith(tuple("。！？.!?"))
                    or duration >= 4 and text.rstrip().endswith(tuple("，,；;"))
                    or duration >= 8):
                rows.append(self._commit())
        if self.pending and final:
            rows.append(self._commit())
        self.seen = {key for key in self.seen if key[1] >= self.latest_end - 120}
        return rows

    @property
    def preview(self):
        return "".join(token[2] for token in self.pending)
