from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EnvironmentReport:
    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EnvironmentReport:
        return cls(copy.deepcopy(data))

    @classmethod
    def from_json(cls, value: str) -> EnvironmentReport:
        return cls.from_dict(json.loads(value))

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(self.data)

    def to_json(self) -> str:
        return json.dumps(
            self.data,
            ensure_ascii=False,
            indent=2,
        )

    @property
    def recommendations(self) -> list[dict[str, Any]]:
        return list(self.data.get("recommendations", []))

    @property
    def whisper_cuda_ready(self) -> bool:
        return bool(
            self.data.get("pipelines", {})
            .get("whisper", {})
            .get("cuda_ready")
        )
