from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING

from ..runtime.events import StreamEventSink
from ..summary import extract_phase_summary_from_last_message
from .base import StreamBackend
from .stream_helpers import StreamFormatter, ensure_empty_last_message

if TYPE_CHECKING:
    from ..runner import LoopfarmConfig


@dataclass
class _GeminiTextFormatter(StreamFormatter):
    stdout: IO[str]
    stderr: IO[str]
    event_sink: StreamEventSink | None
    processed_lines: int = 0
    text_chunks: list[str] = field(default_factory=list)

    def process_line(self, line: str) -> None:
        if not line:
            return
        self.processed_lines += 1
        self.stdout.write(line)
        if line.strip():
            self.text_chunks.append(line.rstrip("\n"))

    def finish(self) -> int:
        text = "\n".join(self.text_chunks).strip()
        if text and self.event_sink:
            self.event_sink("stream.text", {"text": text})
        if self.processed_lines == 0:
            self.stderr.write("⚠ No output received from gemini backend\n")
            return 1
        return 0


@dataclass
class GeminiBackend(StreamBackend):
    name: str = "gemini"

    def _model(self, phase: str, cfg: "LoopfarmConfig") -> str:
        explicit_model = cfg.phase_model(phase)
        if explicit_model is None:
            raise SystemExit(f"missing model for phase {phase!r}")
        return explicit_model.model

    def build_argv(
        self,
        *,
        phase: str,
        prompt: str,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> list[str]:
        return [
            "gemini",
            "--approval-mode",
            "yolo",
            "--output-format",
            "text",
            "--model",
            self._model(phase, cfg),
            "--prompt",
            prompt,
        ]

    def prepare_run(
        self,
        *,
        phase: str,
        prompt: str,
        output_path: Path,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> None:
        ensure_empty_last_message(last_message_path)

    def create_formatter(
        self,
        *,
        cfg: "LoopfarmConfig",
        stdout: IO[str],
        stderr: IO[str],
        event_sink: StreamEventSink | None,
    ) -> StreamFormatter:
        return _GeminiTextFormatter(stdout=stdout, stderr=stderr, event_sink=event_sink)

    def extract_summary(
        self,
        *,
        phase: str,
        output_path: Path,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> str:
        return extract_phase_summary_from_last_message(output_path)
