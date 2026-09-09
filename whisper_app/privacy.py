"""Offline runtime policy. Deployment scripts intentionally run separately."""
from __future__ import annotations

import os
from pathlib import Path


def configure_offline(base_dir: Path) -> None:
    for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY",
                 "HF_HUB_DISABLE_UPDATE_CHECK", "DO_NOT_TRACK", "HF_HUB_DISABLE_IMPLICIT_TOKEN"):
        os.environ[name] = "1"
    os.environ["GRADIO_ANALYTICS_ENABLED"] = "False"
    os.environ["GRADIO_SHARE"] = "False"
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    os.environ["GRADIO_TEMP_DIR"] = str(base_dir / ".whisper" / "gradio-temp")


def deny_worker_network() -> None:
    """Block Python-level network calls in the inference-only child process.

    This supplements offline model paths, not an OS firewall or a network audit.
    """
    import sys

    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.sendto"}:
            raise PermissionError("即時辨識程序禁止網路連線。")

    sys.addaudithook(audit)
