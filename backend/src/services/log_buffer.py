"""In-memory tail of this app's own log output, for the judge-facing demo page.

Scoped to the "services" logger, not root: every logger this app actually uses
(flaky_pipeline, github_artifacts, junit, github_jobs, ...) is a child of it, and
root's default level is WARNING (today's logger.info calls are silently dropped
without this). Scoping below root also keeps httpx's own per-request INFO logs
("HTTP Request: GET ... 200 OK") out of the buffer.
"""

import logging
from collections import deque
from datetime import UTC, datetime
from typing import TypedDict


class LogEntry(TypedDict):
    timestamp: str
    level: str
    logger: str
    message: str


class RingBufferHandler(logging.Handler):
    def __init__(self, capacity: int) -> None:
        super().__init__()
        self._entries: deque[LogEntry] = deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        self._entries.append(
            LogEntry(
                timestamp=datetime.fromtimestamp(record.created, UTC).isoformat(),
                level=record.levelname,
                logger=record.name,
                message=self.format(record),
            )
        )

    def snapshot(self, limit: int | None = None) -> list[LogEntry]:
        entries = list(self._entries)
        return entries[-limit:] if limit else entries


def install(logger_name: str = "services", level: int = logging.INFO, capacity: int = 2000) -> RingBufferHandler:
    """Attach a ring-buffer handler to logging.getLogger(logger_name). Call once, from create_app()."""
    handler = RingBufferHandler(capacity)
    handler.setFormatter(logging.Formatter("%(message)s"))
    target = logging.getLogger(logger_name)
    target.addHandler(handler)
    target.setLevel(level)
    return handler
