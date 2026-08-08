from __future__ import annotations

import threading
import uuid
from collections import deque
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from typing import Iterator

from whisper_app.domain.jobs import JobRecord, JobStatus

from .cancellation import CancellationToken, JobCancelledError


class JobBusyError(RuntimeError):
    pass


class JobManager:
    def __init__(self, history_limit: int = 100) -> None:
        self._resource_lock = threading.Lock()
        self._state_lock = threading.RLock()
        self._active: JobRecord | None = None
        self._active_token: CancellationToken | None = None
        self._history: deque[JobRecord] = deque(maxlen=history_limit)

    @property
    def active(self) -> JobRecord | None:
        with self._state_lock:
            return (
                replace(self._active)
                if self._active is not None
                else None
            )

    def history(self) -> list[JobRecord]:
        with self._state_lock:
            return [
                replace(record)
                for record in self._history
            ]

    def update(
        self,
        status: JobStatus,
        message: str = "",
    ) -> None:
        with self._state_lock:
            if self._active is None:
                return
            self._active.status = status
            self._active.message = message

    def cancel_active(self) -> bool:
        with self._state_lock:
            if self._active_token is None or self._active is None:
                return False
            self._active_token.cancel()
            self._active.status = JobStatus.CANCELLED
            self._active.message = "工作已由使用者取消。"
            return True

    @contextmanager
    def run(
        self,
        kind: str,
        source: str,
    ) -> Iterator[CancellationToken]:
        if not self._resource_lock.acquire(blocking=False):
            active = self.active
            detail = (
                f"目前正在處理：{active.source}"
                if active
                else "目前已有工作使用推理資源"
            )
            raise JobBusyError(detail)

        record = JobRecord(
            job_id=uuid.uuid4().hex,
            kind=kind,
            source=source,
            status=JobStatus.PREPARING,
            started_at=datetime.now(UTC).isoformat(),
        )
        token = CancellationToken()
        with self._state_lock:
            self._active = record
            self._active_token = token

        try:
            yield token
            token.raise_if_cancelled()
            record.status = JobStatus.COMPLETED
        except JobCancelledError:
            record.status = JobStatus.CANCELLED
            record.message = "工作已由使用者取消。"
            raise
        except Exception as exc:
            record.status = JobStatus.FAILED
            record.message = str(exc)
            raise
        finally:
            record.finished_at = datetime.now(UTC).isoformat()
            with self._state_lock:
                self._history.appendleft(record)
                self._active = None
                self._active_token = None
            self._resource_lock.release()
