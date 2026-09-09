from __future__ import annotations

import math


def format_elapsed(seconds: float | int | None) -> str:
    """Format elapsed seconds as HH:MM:SS.s for the desktop UI."""
    if seconds is None:
        return "—"
    try:
        value = float(seconds)
    except (TypeError, ValueError):
        return "—"
    if not math.isfinite(value):
        return "—"

    total_tenths = max(0, round(value * 10))
    hours, remainder = divmod(total_tenths, 36_000)
    minutes, remainder = divmod(remainder, 600)
    whole_seconds, tenths = divmod(remainder, 10)
    return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d}.{tenths}"
