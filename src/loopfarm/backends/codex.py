from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING

from ..runtime.events import StreamEventSink
from ..format_stream import CodexJsonlFormatter
from ..summary import extract_phase_summary_from_last_message
from .base import StreamBackend
from .stream_helpers import ensure_empty_last_message

if TYPE_CHECKING:
    from ..runner import CodexPhaseModel, LoopfarmConfig


@dataclass
class CodexBackend(StreamBackend):
    name: str = "codex"

    def _model_for_phase(self, phase: str, cfg: "LoopfarmConfig") -> "CodexPhaseModel":
        model = cfg.phase_model(phase)
        if model is None:
            raise SystemExit(f"missing model for phase {phase!r}")
        return model

    def build_argv(
        self,
        *,
        phase: str,
        prompt: str,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> list[str]:
        phase_model = self._model_for_phase(phase, cfg)
        return [
            "codex",
            "exec",
            "--dangerously-bypass-approvals-and-sandbox",
            "--json",
            "-C",
            str(cfg.repo_root),
            "-m",
            phase_model.model,
            "-c",
            f"reasoning={phase_model.reasoning}",
            "--output-last-message",
            str(last_message_path),
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
    ) -> CodexJsonlFormatter:
        return CodexJsonlFormatter(
            stdout=stdout,
            stderr=stderr,
            repo_root=cfg.repo_root,
            event_sink=event_sink,
            show_reasoning=bool(cfg.show_reasoning),
            show_command_output=bool(cfg.show_command_output),
            show_command_start=bool(cfg.show_command_start),
            show_small_output=bool(cfg.show_small_output),
            show_tokens=bool(cfg.show_tokens),
            max_output_lines=max(1, int(cfg.max_output_lines)),
            max_output_chars=max(1, int(cfg.max_output_chars)),
        )

    def extract_summary(
        self,
        *,
        phase: str,
        output_path: Path,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> str:
        return extract_phase_summary_from_last_message(last_message_path)
