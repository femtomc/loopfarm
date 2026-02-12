from __future__ import annotations

from pathlib import Path
import sys
from typing import IO, TYPE_CHECKING

from ..summary import summarize_with_haiku
from ..events import StreamEventSink
from .stream_helpers import StreamFormatter, run_stream_backend

if TYPE_CHECKING:
    from ..runner import LoopfarmConfig


class StreamBackend:
    name: str

    def build_argv(
        self,
        *,
        phase: str,
        prompt: str,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> list[str]:
        raise NotImplementedError

    def create_formatter(
        self,
        *,
        cfg: "LoopfarmConfig",
        stdout: IO[str],
        stderr: IO[str],
        event_sink: StreamEventSink | None,
    ) -> StreamFormatter:
        raise NotImplementedError

    def prompt_suffix(self, *, phase: str, cfg: "LoopfarmConfig") -> str:
        return ""

    def prepare_run(
        self,
        *,
        phase: str,
        prompt: str,
        output_path: Path,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> None:
        return None

    def run_env(self, *, phase: str, cfg: "LoopfarmConfig") -> dict[str, str] | None:
        return None

    def run(
        self,
        *,
        phase: str,
        prompt: str,
        output_path: Path,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
        event_sink: StreamEventSink | None = None,
        stdout: IO[str] | None = None,
        stderr: IO[str] | None = None,
    ) -> bool:
        self.prepare_run(
            phase=phase,
            prompt=prompt,
            output_path=output_path,
            last_message_path=last_message_path,
            cfg=cfg,
        )
        formatter = self.create_formatter(
            cfg=cfg,
            stdout=stdout or sys.stdout,
            stderr=stderr or sys.stderr,
            event_sink=event_sink,
        )
        return run_stream_backend(
            argv=self.build_argv(
                phase=phase,
                prompt=prompt,
                last_message_path=last_message_path,
                cfg=cfg,
            ),
            formatter=formatter,
            cwd=cfg.repo_root,
            env=self.run_env(phase=phase, cfg=cfg),
            tee_path=output_path,
        )

    def extract_summary(
        self,
        *,
        phase: str,
        output_path: Path,
        last_message_path: Path,
        cfg: "LoopfarmConfig",
    ) -> str:
        return summarize_with_haiku(phase, output_path)
