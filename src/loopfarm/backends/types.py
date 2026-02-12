from __future__ import annotations

from pathlib import Path
from typing import IO, TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from ..runner import LoopfarmConfig
    from ..events import StreamEventSink


class Backend(Protocol):
    name: str

    def build_argv(
        self,
        *,
        phase: str,
        prompt: str,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> list[str]:
        ...

    def run(
        self,
        *,
        phase: str,
        prompt: str,
        output_path: Path,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
        event_sink: "StreamEventSink | None" = None,
        stdout: IO[str] | None = None,
        stderr: IO[str] | None = None,
    ) -> bool:
        ...

    def extract_summary(
        self,
        *,
        phase: str,
        output_path: Path,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> str:
        ...

    def prompt_suffix(self, *, phase: str, cfg: "LoopfarmConfig") -> str:
        ...
