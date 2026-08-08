"""Cross-machine environment detection and setup recommendations."""

from pathlib import Path
from typing import Any


def build_environment_report(
    base_dir: Path | None = None,
    *,
    bootstrap_report: Path | None = None,
) -> dict[str, Any]:
    from .doctor import build_environment_report as build_report

    return build_report(
        base_dir,
        bootstrap_report=bootstrap_report,
    )


__all__ = ["build_environment_report"]
