from __future__ import annotations

from pathlib import Path
from typing import Protocol

from ..util import stream_process


class StreamFormatter(Protocol):
    def process_line(self, line: str) -> None:
        ...

    def finish(self) -> int:
        ...


def ensure_empty_last_message(path: Path) -> None:
    path.write_text("", encoding="utf-8")


def run_stream_backend(
    *,
    argv: list[str],
    formatter: StreamFormatter,
    cwd: Path,
    env: dict[str, str] | None,
    tee_path: Path | None,
) -> bool:
    result = stream_process(
        argv,
        cwd=cwd,
        env=env,
        on_line=formatter.process_line,
        tee_path=tee_path,
    )
    formatter.finish()
    return result.returncode == 0
