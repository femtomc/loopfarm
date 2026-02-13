from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_session_id() -> str:
    return f"loopfarm-{uuid.uuid4().hex[:8]}"


def format_duration(seconds: int) -> str:
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    if hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    if minutes > 0:
        return f"{minutes}m {secs}s"
    return f"{secs}s"


def json_dumps_compact(obj: Any) -> str:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False)


class CommandError(RuntimeError):
    def __init__(self, argv: list[str], returncode: int, stdout: str, stderr: str):
        super().__init__(f"command failed: {argv} (exit {returncode})")
        self.argv = argv
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def run_capture(argv: list[str], *, cwd: Path | None = None, env: dict[str, str] | None = None) -> str:
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        raise CommandError(argv, proc.returncode, proc.stdout, proc.stderr)
    return proc.stdout


def run_json(argv: list[str], *, cwd: Path | None = None) -> Any:
    out = run_capture(argv, cwd=cwd)
    return json.loads(out) if out.strip() else None


def which(cmd: str) -> str | None:
    for p in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(p) / cmd
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None

def eprint(*parts: object) -> None:
    print(*parts, file=sys.stderr)


@dataclass(frozen=True)
class ExecResult:
    returncode: int


def stream_process(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None,
    on_line: callable | None,
    tee_path: Path | None,
) -> ExecResult:
    with subprocess.Popen(
        argv,
        cwd=str(cwd),
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    ) as proc:
        assert proc.stdout is not None
        tee_f = tee_path.open("w", encoding="utf-8") if tee_path else None
        try:
            for line in proc.stdout:
                if tee_f:
                    tee_f.write(line)
                    tee_f.flush()
                if on_line:
                    on_line(line)
                else:
                    print(line, end="")
        finally:
            if tee_f:
                tee_f.close()

        return ExecResult(returncode=proc.wait())


def sleep_seconds(seconds: int) -> None:
    time.sleep(seconds)
