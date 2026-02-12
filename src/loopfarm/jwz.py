from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import CommandError, eprint, run_capture, run_json


FORUM_BINARIES = ("synth-forum",)


@dataclass
class Jwz:
    cwd: Path

    def post_json(self, topic: str, payload: Any) -> None:
        msg = json.dumps(payload, ensure_ascii=False)
        last_error: CommandError | None = None
        missing_binaries: list[str] = []
        for binary in FORUM_BINARIES:
            try:
                run_capture([binary, "post", topic, "-m", msg], cwd=self.cwd)
                return
            except FileNotFoundError:
                missing_binaries.append(binary)
                continue
            except CommandError as exc:
                last_error = exc

        if last_error is not None:
            eprint(
                f"warning: synth-forum post failed for {topic} "
                f"(exit {last_error.returncode})"
            )
            eprint(f"argv: {last_error.argv}")
            if last_error.stderr.strip():
                eprint(last_error.stderr.strip())
            return

        if missing_binaries:
            eprint(
                "warning: no forum CLI binary found. looked for: "
                + ", ".join(missing_binaries)
            )

    def read_json(self, topic: str, *, limit: int) -> list[dict[str, Any]]:
        for binary in FORUM_BINARIES:
            try:
                out = run_json(
                    [binary, "read", topic, "--limit", str(limit), "--json"],
                    cwd=self.cwd,
                )
            except FileNotFoundError:
                continue
            except CommandError:
                continue
            if isinstance(out, list):
                return out
        return []
