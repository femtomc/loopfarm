"""Tests for inshallah init command template generation."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from rich.console import Console

from inshallah.cli import cmd_init


def test_init_writes_prompt_descriptions(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    console = Console(record=True)

    with patch("inshallah.cli._find_repo_root", return_value=tmp_path):
        rc = cmd_init(console)

    assert rc == 0

    orchestrator = (tmp_path / ".inshallah" / "orchestrator.md").read_text()
    worker = (tmp_path / ".inshallah" / "roles" / "worker.md").read_text()

    assert "description: Plan and decompose root goals into atomic issues, assign the best role to each issue, and manage dependency order." in orchestrator
    assert "inshallah roles --pretty" in orchestrator
    assert "description: Best for concrete execution tasks; implement exactly one atomic issue (code/tests/docs), verify results, then close with a terminal outcome." in worker

    reviewer = (tmp_path / ".inshallah" / "roles" / "reviewer.md").read_text()
    assert "description: Independently verify completed work and either approve or mark the issue as needs_work." in reviewer
    assert "{{ISSUE_ID}}" in reviewer
