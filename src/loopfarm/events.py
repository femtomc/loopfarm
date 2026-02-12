from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class LoopfarmEvent:
    type: str
    timestamp: str
    phase: str | None
    iteration: int | None
    payload: dict[str, Any] = field(default_factory=dict)


EventSink = Callable[[LoopfarmEvent], None]
StreamEventSink = Callable[[str, dict[str, Any]], None]
