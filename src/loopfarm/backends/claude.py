from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING

from ..events import StreamEventSink
from ..format_stream import ClaudeStreamJsonFormatter
from .base import StreamBackend

if TYPE_CHECKING:
    from ..runner import LoopfarmConfig


@dataclass
class ClaudeBackend(StreamBackend):
    name: str = "claude"

    def build_argv(
        self,
        *,
        phase: str,
        prompt: str,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> list[str]:
        argv = [
            "claude",
            "--dangerously-skip-permissions",
            "-p",
            "--output-format",
            "stream-json",
            "--verbose",
            "--include-partial-messages",
        ]
        model = cfg.model_override or "claude-opus-4-6"
        argv += ["--model", model]
        argv.append(prompt)
        return argv

    def create_formatter(
        self,
        *,
        cfg: "LoopfarmConfig",
        stdout: IO[str],
        stderr: IO[str],
        event_sink: StreamEventSink | None,
    ) -> ClaudeStreamJsonFormatter:
        return ClaudeStreamJsonFormatter(
            stdout=stdout,
            stderr=stderr,
            repo_root=cfg.repo_root,
            event_sink=event_sink,
        )
