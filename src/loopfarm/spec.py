"""Execution spec: per-issue routing config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ExecutionSpec:
    role: str | None = None
    prompt_path: str | None = None
    cli: str | None = None
    model: str | None = None
    reasoning: str | None = None

    @classmethod
    def from_dict(cls, d: dict, repo_root: Path | None = None) -> ExecutionSpec:
        prompt_path = d.get("prompt_path") or None
        role = d.get("role") or None

        # Auto-resolve prompt_path from role name
        if not prompt_path and role and repo_root:
            candidate = repo_root / ".loopfarm" / "roles" / f"{role}.md"
            if candidate.exists():
                prompt_path = str(candidate)

        # Resolve relative prompt_path against repo_root
        if repo_root and prompt_path and not Path(prompt_path).is_absolute():
            prompt_path = str(repo_root / prompt_path)

        return cls(
            role=role,
            prompt_path=prompt_path,
            cli=d.get("cli") or None,
            model=d.get("model") or None,
            reasoning=d.get("reasoning") or None,
        )
