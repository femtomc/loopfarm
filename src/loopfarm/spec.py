"""Execution spec: per-issue routing config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecutionSpec:
    role: str
    prompt_path: str
    cli: str = "claude"
    model: str = "opus"
    reasoning: str = "high"

    @classmethod
    def from_dict(cls, d: dict, repo_root: Path | None = None) -> ExecutionSpec:
        prompt_path = d.get("prompt_path", "")
        if repo_root and prompt_path and not Path(prompt_path).is_absolute():
            prompt_path = str(repo_root / prompt_path)
        return cls(
            role=d.get("role", "worker"),
            prompt_path=prompt_path,
            cli=d.get("cli", "claude"),
            model=d.get("model", "opus"),
            reasoning=d.get("reasoning", "high"),
        )
