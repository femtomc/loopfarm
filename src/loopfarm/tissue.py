from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import CommandError, run_json


ISSUE_BINARIES = ("synth-issue",)


@dataclass
class Tissue:
    cwd: Path

    def list_in_progress(self) -> list[dict[str, Any]]:
        for binary in ISSUE_BINARIES:
            try:
                out = run_json(
                    [binary, "list", "--status", "in_progress", "--json"],
                    cwd=self.cwd,
                )
            except FileNotFoundError:
                continue
            except CommandError:
                continue
            if isinstance(out, list):
                return out
        return []
