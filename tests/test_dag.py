"""Tests for DAG runner 3-tier config resolution and review phase."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

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

        with patch("loopfarm.dag.get_backend") as mock_backend, \
             patch("loopfarm.dag.get_formatter") as mock_formatter:
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

        with patch("loopfarm.dag.get_backend") as mock_backend, \
             patch("loopfarm.dag.get_formatter") as mock_formatter:
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

        with patch("loopfarm.dag.get_backend") as mock_backend, \
             patch("loopfarm.dag.get_formatter") as mock_formatter:
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


class TestReviewPhase:
    """Test the review-triggered decomposition feature."""

    def _run_with_side_effect(
        self,
        tmp_path: Path,
        *,
        has_reviewer: bool = False,
        worker_outcome: str = "success",
        reviewer_changes_outcome: bool = False,
        review: bool = True,
        execution_spec: dict | None = None,
    ) -> tuple[DagRunner, IssueStore, ForumStore, dict, MagicMock]:
        """Shared helper: create a root issue, mock backend, run DAG one step."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(
            tmp_path, "cli: claude\nmodel: opus\nreasoning: high\n", "{{PROMPT}}\n"
        )
        if has_reviewer:
            _write_role(
                tmp_path,
                "reviewer",
                "cli: claude\nmodel: opus\nreasoning: high\n",
                "Review:\n{{PROMPT}}\n",
            )

        issue = store.create(
            "test task",
            tags=["node:agent", "node:root"],
            execution_spec=execution_spec,
        )
        issue_id = issue["id"]

        runner = DagRunner(store, forum, tmp_path)

        call_count = [0]

        def backend_side_effect(prompt, model, reasoning, cwd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Worker closes the issue
                store.close(issue_id, outcome=worker_outcome)
            elif call_count[0] == 2 and reviewer_changes_outcome:
                # Reviewer changes outcome to expanded and creates a child
                store.update(issue_id, outcome="expanded")
                child = store.create(
                    "Fix: something",
                    tags=["node:agent"],
                )
                store.add_dep(child["id"], "parent", issue_id)
            return 0

        with patch("loopfarm.dag.get_backend") as mock_backend, \
             patch("loopfarm.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.side_effect = backend_side_effect
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            runner.run(issue["id"], max_steps=1, review=review)

        return runner, store, forum, issue, mock_proc

    def test_no_review_without_reviewer_role(self, tmp_path: Path) -> None:
        """No reviewer.md → backend called once (worker only)."""
        _, store, _, issue, mock_proc = self._run_with_side_effect(
            tmp_path, has_reviewer=False, worker_outcome="success"
        )
        assert mock_proc.run.call_count == 1

    def test_review_triggered_on_success(self, tmp_path: Path) -> None:
        """reviewer.md exists → backend called twice (worker + reviewer)."""
        _, store, _, issue, mock_proc = self._run_with_side_effect(
            tmp_path, has_reviewer=True, worker_outcome="success"
        )
        assert mock_proc.run.call_count == 2

    def test_review_skipped_on_failure(self, tmp_path: Path) -> None:
        """outcome=failure → no review."""
        _, store, _, issue, mock_proc = self._run_with_side_effect(
            tmp_path, has_reviewer=True, worker_outcome="failure"
        )
        assert mock_proc.run.call_count == 1

    def test_review_skipped_on_expanded(self, tmp_path: Path) -> None:
        """outcome=expanded → no review."""
        _, store, _, issue, mock_proc = self._run_with_side_effect(
            tmp_path, has_reviewer=True, worker_outcome="expanded"
        )
        assert mock_proc.run.call_count == 1

    def test_review_false_disables(self, tmp_path: Path) -> None:
        """review=False → no review even with reviewer.md."""
        _, store, _, issue, mock_proc = self._run_with_side_effect(
            tmp_path,
            has_reviewer=True,
            worker_outcome="success",
            review=False,
        )
        assert mock_proc.run.call_count == 1

    def test_reviewer_creates_children(self, tmp_path: Path) -> None:
        """Reviewer changes outcome to expanded + creates children → DAG continues."""
        _, store, _, issue, mock_proc = self._run_with_side_effect(
            tmp_path,
            has_reviewer=True,
            worker_outcome="success",
            reviewer_changes_outcome=True,
        )
        assert mock_proc.run.call_count == 2
        updated = store.get(issue["id"])
        assert updated is not None
        assert updated.get("outcome") == "expanded"
        children = store.children(issue["id"])
        assert len(children) == 1
        assert children[0]["title"] == "Fix: something"

    def test_resolve_config_regression(self, tmp_path: Path) -> None:
        """Extracted _resolve_config produces same results as old inline code."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(
            tmp_path, "cli: codex\nmodel: gpt-5.3\nreasoning: xhigh\n", "{{PROMPT}}\n"
        )
        _write_role(
            tmp_path, "worker", "cli: claude\nmodel: opus\nreasoning: high\n", "Worker.\n"
        )
        issue = store.create(
            "test task",
            tags=["node:agent", "node:root"],
            execution_spec={"role": "worker", "model": "o3"},
        )

        runner = DagRunner(store, forum, tmp_path)
        cli, model, reasoning, prompt_path = runner._resolve_config(issue)

        # cli from role (claude), model from explicit spec (o3), reasoning from role (high)
        assert cli == "claude"
        assert model == "o3"
        assert reasoning == "high"
        assert prompt_path is not None
        assert "worker.md" in prompt_path

    def test_review_logged_to_forum(self, tmp_path: Path) -> None:
        """Forum has entry with author=reviewer, type=review."""
        _, store, forum, issue, _ = self._run_with_side_effect(
            tmp_path, has_reviewer=True, worker_outcome="success"
        )
        messages = forum.read(f"issue:{issue['id']}")
        review_msgs = [
            m for m in messages
            if m.get("author") == "reviewer"
        ]
        assert len(review_msgs) == 1
        body = json.loads(review_msgs[0]["body"])
        assert body["type"] == "review"
