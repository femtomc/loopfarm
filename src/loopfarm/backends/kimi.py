from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING

from ..runtime.events import StreamEventSink
from ..format_stream import KimiJsonFormatter
from .base import StreamBackend

if TYPE_CHECKING:
    from ..runner import LoopfarmConfig


@dataclass
class KimiBackend(StreamBackend):
    name: str = "kimi"

    def build_argv(
        self,
        *,
        phase: str,
        prompt: str,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> list[str]:
        return [
            "kimi",
            "--print",
            "--work-dir",
            str(cfg.repo_root),
            "--output-format",
            "stream-json",
            "--max-loopfarm-iterations",
            "0",
            "-p",
            prompt,
        ]

    def create_formatter(
        self,
        *,
        cfg: "LoopfarmConfig",
        stdout: IO[str],
        stderr: IO[str],
        event_sink: StreamEventSink | None,
    ) -> KimiJsonFormatter:
        return KimiJsonFormatter(
            stdout=stdout,
            stderr=stderr,
            repo_root=cfg.repo_root,
            event_sink=event_sink,
        )
