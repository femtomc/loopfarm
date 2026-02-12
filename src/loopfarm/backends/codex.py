from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import IO, TYPE_CHECKING

from ..events import StreamEventSink
from ..format_stream import CodexJsonlFormatter
from ..summary import extract_phase_summary_from_last_message
from ..util import env_flag, env_int
from .base import StreamBackend
from .stream_helpers import ensure_empty_last_message

if TYPE_CHECKING:
    from ..runner import CodexPhaseModel, LoopfarmConfig


@dataclass
class CodexBackend(StreamBackend):
    name: str = "codex"

    def _model_for_phase(self, phase: str, cfg: "LoopfarmConfig") -> "CodexPhaseModel":
        architecture_model = cfg.architecture_model or cfg.review_model
        if cfg.model_override:
            # Keep reasoning defaults even when overriding model.
            if phase in {"planning", "research", "curation"}:
                return type(cfg.plan_model)(cfg.model_override, cfg.plan_model.reasoning)
            if phase in {"backward", "documentation"}:
                return type(cfg.review_model)(cfg.model_override, cfg.review_model.reasoning)
            if phase == "architecture":
                return type(architecture_model)(
                    cfg.model_override, architecture_model.reasoning
                )
            return type(cfg.code_model)(cfg.model_override, cfg.code_model.reasoning)

        if phase in {"planning", "research", "curation"}:
            return cfg.plan_model
        if phase in {"backward", "documentation"}:
            return cfg.review_model
        if phase == "architecture":
            return architecture_model
        return cfg.code_model

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
            show_reasoning=bool(env_flag("LOOPFARM_SHOW_REASONING")),
            show_command_output=env_flag("LOOPFARM_SHOW_COMMAND_OUTPUT"),
            show_command_start=env_flag("LOOPFARM_SHOW_COMMAND_START"),
            show_small_output=env_flag("LOOPFARM_SHOW_SMALL_OUTPUT"),
            show_tokens=env_flag("LOOPFARM_SHOW_TOKENS"),
            max_output_lines=env_int("LOOPFARM_MAX_OUTPUT_LINES", 60),
            max_output_chars=env_int("LOOPFARM_MAX_OUTPUT_CHARS", 2000),
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
