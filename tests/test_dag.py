"""Tests for DAG runner 3-tier config resolution."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from loopfarm.dag import DagRunner
from loopfarm.store import ForumStore, IssueStore


def _setup_stores(tmp_path: Path) -> tuple[IssueStore, ForumStore]:
    lf = tmp_path / ".loopfarm"
    lf.mkdir(parents=True, exist_ok=True)
    (lf / "issues.jsonl").touch()
    (lf / "forum.jsonl").touch()
    (lf / "logs").mkdir(exist_ok=True)
    return IssueStore(lf / "issues.jsonl"), ForumStore(lf / "forum.jsonl")


def _write_orchestrator(tmp_path: Path, frontmatter: str, body: str) -> None:
    lf = tmp_path / ".loopfarm"
    lf.mkdir(parents=True, exist_ok=True)
    (lf / "orchestrator.md").write_text(f"---\n{frontmatter}---\n{body}")


def _write_role(tmp_path: Path, name: str, frontmatter: str, body: str) -> None:
    roles_dir = tmp_path / ".loopfarm" / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    (roles_dir / f"{name}.md").write_text(f"---\n{frontmatter}---\n{body}")


class TestThreeTierResolution:
    """Test the 3-tier config resolution: orchestrator -> role -> execution_spec."""

    def test_fallback_defaults(self, tmp_path: Path) -> None:
        """No orchestrator.md, no execution_spec — uses hardcoded fallbacks."""
        store, forum = _setup_stores(tmp_path)
        issue = store.create("test task", tags=["node:agent", "node:root"])

        runner = DagRunner(store, forum, tmp_path)

        with patch("loopfarm.dag.get_backend") as mock_backend, \
             patch("loopfarm.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_fmt = MagicMock()
            mock_formatter.return_value = mock_fmt

            # Run one step — will pick up the issue
            runner.run(issue["id"], max_steps=1)

            mock_backend.assert_called_with("claude")
            mock_proc.run.assert_called_once()
            call_args = mock_proc.run.call_args
            assert call_args[0][1] == "opus"  # model
            assert call_args[0][2] == "high"  # reasoning

    def test_orchestrator_overrides_fallbacks(self, tmp_path: Path) -> None:
        """Orchestrator frontmatter overrides hardcoded fallbacks."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(tmp_path, "cli: codex\nmodel: gpt-5.3\nreasoning: xhigh\n", "{{PROMPT}}\n")
        issue = store.create("test task", tags=["node:agent", "node:root"])

        runner = DagRunner(store, forum, tmp_path)

        with patch("loopfarm.dag.get_backend") as mock_backend, \
             patch("loopfarm.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            runner.run(issue["id"], max_steps=1)

            mock_backend.assert_called_with("codex")
            call_args = mock_proc.run.call_args
            assert call_args[0][1] == "gpt-5.3"
            assert call_args[0][2] == "xhigh"

    def test_role_overrides_orchestrator(self, tmp_path: Path) -> None:
        """Role frontmatter overrides orchestrator defaults."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(tmp_path, "cli: claude\nmodel: opus\nreasoning: high\n", "{{PROMPT}}\n")
        _write_role(tmp_path, "worker", "cli: codex\nmodel: gpt-5.2\nreasoning: xhigh\n", "Worker.\n")
        issue = store.create(
            "test task",
            tags=["node:agent", "node:root"],
            execution_spec={"role": "worker"},
        )

        runner = DagRunner(store, forum, tmp_path)

        with patch("loopfarm.dag.get_backend") as mock_backend, \
             patch("loopfarm.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            runner.run(issue["id"], max_steps=1)

            mock_backend.assert_called_with("codex")
            call_args = mock_proc.run.call_args
            assert call_args[0][1] == "gpt-5.2"
            assert call_args[0][2] == "xhigh"

    def test_explicit_spec_overrides_role(self, tmp_path: Path) -> None:
        """Explicit execution_spec fields override role frontmatter."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(tmp_path, "cli: claude\nmodel: opus\nreasoning: high\n", "{{PROMPT}}\n")
        _write_role(tmp_path, "worker", "cli: codex\nmodel: gpt-5.2\nreasoning: xhigh\n", "Worker.\n")
        issue = store.create(
            "test task",
            tags=["node:agent", "node:root"],
            execution_spec={"role": "worker", "model": "o3", "cli": "claude"},
        )

        runner = DagRunner(store, forum, tmp_path)

        with patch("loopfarm.dag.get_backend") as mock_backend, \
             patch("loopfarm.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            runner.run(issue["id"], max_steps=1)

            # cli and model from explicit spec, reasoning from role
            mock_backend.assert_called_with("claude")
            call_args = mock_proc.run.call_args
            assert call_args[0][1] == "o3"
            assert call_args[0][2] == "xhigh"  # from role, not overridden

    def test_role_only_spec_resolves_prompt(self, tmp_path: Path) -> None:
        """A spec with only role set auto-resolves prompt_path to the role file."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(tmp_path, "cli: claude\nmodel: opus\nreasoning: high\n", "{{PROMPT}}\n")
        _write_role(tmp_path, "worker", "cli: codex\nmodel: gpt-5.2\nreasoning: xhigh\n", "{{PROMPT}}\nWorker prompt.\n")
        issue = store.create(
            "test task",
            tags=["node:agent", "node:root"],
            execution_spec={"role": "worker"},
        )

        runner = DagRunner(store, forum, tmp_path)

        with patch("loopfarm.dag.get_backend") as mock_backend, \
             patch("loopfarm.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            runner.run(issue["id"], max_steps=1)

            # The rendered prompt should come from the role file, not orchestrator
            call_args = mock_proc.run.call_args
            rendered = call_args[0][0]
            assert "Worker prompt." in rendered
