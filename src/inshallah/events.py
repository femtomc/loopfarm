"""Append-only JSONL event log for inshallah.

This log is intentionally:
- fixed envelope schema (versioned)
- append-only (no rewrites)
- concurrency-safe for basic multi-process usage (single-write append + flock when available)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

EVENT_VERSION = 1

_run_id_var: ContextVar[str | None] = ContextVar("inshallah_run_id", default=None)


def now_ts_ms() -> int:
    return time.time_ns() // 1_000_000


def new_run_id() -> str:
    return uuid.uuid4().hex


def current_run_id() -> str | None:
    return _run_id_var.get()


@contextmanager
def run_context(*, run_id: str | None) -> Any:
    token = _run_id_var.set(run_id)
    try:
        yield
    finally:
        _run_id_var.reset(token)


class EventLog:
    """Append-only JSONL event log."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def from_repo_root(cls, repo_root: Path) -> "EventLog":
        return cls(repo_root / ".inshallah" / "events.jsonl")

    def emit(
        self,
        event_type: str,
        *,
        source: str,
        payload: dict[str, Any] | None = None,
        issue_id: str | None = None,
        run_id: str | None = None,
        ts_ms: int | None = None,
    ) -> dict[str, Any]:
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")

        resolved_run_id = run_id if run_id is not None else current_run_id()
        event: dict[str, Any] = {
            "v": EVENT_VERSION,
            "ts_ms": int(ts_ms if ts_ms is not None else now_ts_ms()),
            "type": event_type,
            "source": source,
        }
        if resolved_run_id is not None:
            event["run_id"] = resolved_run_id
        if issue_id is not None:
            event["issue_id"] = issue_id
        event["payload"] = payload

        self._append(event)
        return event

    def _append(self, event: dict[str, Any]) -> None:
        # One os.write() per event line to avoid interleaving when multiple
        # processes append concurrently.
        line = json.dumps(event, separators=(",", ":"), ensure_ascii=True) + "\n"
        data = line.encode("utf-8")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        lock_impl = None
        locked = False
        try:
            try:
                import fcntl  # type: ignore

                lock_impl = fcntl
            except ImportError:
                lock_impl = None

            if lock_impl is not None:
                lock_impl.flock(fd, lock_impl.LOCK_EX)
                locked = True

            written = 0
            while written < len(data):
                n = os.write(fd, data[written:])
                if n <= 0:
                    raise OSError("short write while appending event log")
                written += n
        finally:
            if locked and lock_impl is not None:
                try:
                    lock_impl.flock(fd, lock_impl.LOCK_UN)
                except OSError:
                    pass
            os.close(fd)

