"""Tests for DAG runner 3-tier config resolution and review phase."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from inshallah.dag import DagRunner
from inshallah.store import ForumStore, IssueStore


def _setup_stores(tmp_path: Path) -> tuple[IssueStore, ForumStore]:
    lf = tmp_path / ".inshallah"
    lf.mkdir(parents=True, exist_ok=True)
    (lf / "issues.jsonl").touch()
    (lf / "forum.jsonl").touch()
    (lf / "logs").mkdir(exist_ok=True)
    return IssueStore(lf / "issues.jsonl"), ForumStore(lf / "forum.jsonl")


def _write_orchestrator(tmp_path: Path, frontmatter: str, body: str) -> None:
    lf = tmp_path / ".inshallah"
    lf.mkdir(parents=True, exist_ok=True)
    (lf / "orchestrator.md").write_text(f"---\n{frontmatter}---\n{body}")


def _write_role(tmp_path: Path, name: str, frontmatter: str, body: str) -> None:
    roles_dir = tmp_path / ".inshallah" / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    (roles_dir / f"{name}.md").write_text(f"---\n{frontmatter}---\n{body}")


class TestThreeTierResolution:
    """Test the 3-tier config resolution: orchestrator -> role -> execution_spec."""

    def test_fallback_defaults(self, tmp_path: Path) -> None:
        """No orchestrator.md, no execution_spec — uses hardcoded fallbacks."""
        store, forum = _setup_stores(tmp_path)
        issue = store.create("test task", tags=["node:agent", "node:root"])

        runner = DagRunner(store, forum, tmp_path)

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_fmt = MagicMock()
            mock_formatter.return_value = mock_fmt

            # Run one step — will pick up the issue
            runner.run(issue["id"], max_steps=1)

            mock_backend.assert_called_with("codex")
            mock_proc.run.assert_called_once()
            call_args = mock_proc.run.call_args
            assert call_args[0][1] == "gpt-5.3-codex"  # model
            assert call_args[0][2] == "xhigh"  # reasoning

    def test_orchestrator_overrides_fallbacks(self, tmp_path: Path) -> None:
        """Orchestrator frontmatter overrides hardcoded fallbacks."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(tmp_path, "cli: codex\nmodel: gpt-5.3\nreasoning: xhigh\n", "{{PROMPT}}\n")
        issue = store.create("test task", tags=["node:agent", "node:root"])

        runner = DagRunner(store, forum, tmp_path)

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            runner.run(issue["id"], max_steps=1)

            mock_backend.assert_called_with("codex")
            call_args = mock_proc.run.call_args
            assert call_args[0][1] == "gpt-5.3"
            assert call_args[0][2] == "xhigh"

    def test_orchestrator_can_select_opencode(self, tmp_path: Path) -> None:
        """Orchestrator frontmatter can target OpenCode backend."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(
            tmp_path,
            "cli: opencode\nmodel: openai/gpt-5\nreasoning: high\n",
            "{{PROMPT}}\n",
        )
        issue = store.create("test task", tags=["node:agent", "node:root"])

        runner = DagRunner(store, forum, tmp_path)

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            runner.run(issue["id"], max_steps=1)

            mock_backend.assert_called_with("opencode")
            call_args = mock_proc.run.call_args
            assert call_args[0][1] == "openai/gpt-5"
            assert call_args[0][2] == "high"

    def test_orchestrator_can_select_pi(self, tmp_path: Path) -> None:
        """Orchestrator frontmatter can target pi backend."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(
            tmp_path,
            "cli: pi\nmodel: openai/gpt-5\nreasoning: high\n",
            "{{PROMPT}}\n",
        )
        issue = store.create("test task", tags=["node:agent", "node:root"])

        runner = DagRunner(store, forum, tmp_path)

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            runner.run(issue["id"], max_steps=1)

            mock_backend.assert_called_with("pi")
            call_args = mock_proc.run.call_args
            assert call_args[0][1] == "openai/gpt-5"
            assert call_args[0][2] == "high"

    def test_orchestrator_can_select_gemini(self, tmp_path: Path) -> None:
        """Orchestrator frontmatter can target Gemini backend."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(
            tmp_path,
            "cli: gemini\nmodel: gemini-2.5-pro\nreasoning: high\n",
            "{{PROMPT}}\n",
        )
        issue = store.create("test task", tags=["node:agent", "node:root"])

        runner = DagRunner(store, forum, tmp_path)

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            runner.run(issue["id"], max_steps=1)

            mock_backend.assert_called_with("gemini")
            call_args = mock_proc.run.call_args
            assert call_args[0][1] == "gemini-2.5-pro"
            assert call_args[0][2] == "high"

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

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
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

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
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

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            runner.run(issue["id"], max_steps=1)

            # The rendered prompt should come from the role file, not orchestrator
            call_args = mock_proc.run.call_args
            rendered = call_args[0][0]
            assert "Worker prompt." in rendered


class TestAutoPromotion:
    """Test auto-promotion of collapsible expanded nodes."""

    def test_auto_promotes_collapsible(self, tmp_path: Path) -> None:
        """Expanded root + 2 success children → auto-promoted to success, no backend call."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(
            tmp_path, "cli: claude\nmodel: opus\nreasoning: high\n", "{{PROMPT}}\n"
        )

        root = store.create("root task", tags=["node:agent", "node:root"])
        c1 = store.create("child 1", tags=["node:agent"])
        c2 = store.create("child 2", tags=["node:agent"])
        store.add_dep(c1["id"], "parent", root["id"])
        store.add_dep(c2["id"], "parent", root["id"])

        store.close(root["id"], outcome="expanded")
        store.close(c1["id"], outcome="success")
        store.close(c2["id"], outcome="success")

        runner = DagRunner(store, forum, tmp_path)

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            result = runner.run(root["id"], max_steps=3)

        # No backend calls — auto-promotion requires no agent
        assert mock_proc.run.call_count == 0
        updated = store.get(root["id"])
        assert updated is not None
        assert updated["outcome"] == "success"
        assert result.status == "root_final"
