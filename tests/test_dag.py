"""Tests for DAG runner 3-tier config resolution and review phase."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

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


class TestReviewPhase:
    """Test the review-triggered re-orchestration feature."""

    def _run_with_side_effect(
        self,
        tmp_path: Path,
        *,
        has_reviewer: bool = False,
        worker_outcome: str = "success",
        reviewer_marks_needs_work: bool = False,
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
            elif call_count[0] == 2 and reviewer_marks_needs_work:
                # Reviewer rejects work; orchestrator is responsible for
                # expanding remediation children.
                store.update(issue_id, outcome="needs_work")
            return 0

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
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

    def test_reviewer_marks_needs_work(self, tmp_path: Path) -> None:
        """Reviewer marks needs_work; runner reopens the issue for orchestration."""
        _, store, _, issue, mock_proc = self._run_with_side_effect(
            tmp_path,
            has_reviewer=True,
            worker_outcome="success",
            reviewer_marks_needs_work=True,
        )
        assert mock_proc.run.call_count == 2
        updated = store.get(issue["id"])
        assert updated is not None
        # Runner clears outcome + reopens so orchestrator.md runs next.
        assert updated.get("status") == "open"
        assert updated.get("outcome") is None
        assert updated.get("execution_spec") is None

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


class TestCollapseReview:
    """Test the collapse review feature: aggregate review on subtree completion."""

    def _setup_expanded(
        self,
        tmp_path: Path,
        *,
        has_reviewer: bool = True,
    ) -> tuple[IssueStore, ForumStore, dict, list[dict]]:
        """Create an expanded root with 2 success children."""
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

        root = store.create("root task", tags=["node:agent", "node:root"])
        c1 = store.create("child 1", tags=["node:agent"])
        c2 = store.create("child 2", tags=["node:agent"])
        store.add_dep(c1["id"], "parent", root["id"])
        store.add_dep(c2["id"], "parent", root["id"])

        # Simulate: root was expanded, both children succeeded
        store.close(root["id"], outcome="expanded")
        store.close(c1["id"], outcome="success")
        store.close(c2["id"], outcome="success")

        return store, forum, root, [c1, c2]

    def test_collapse_review_fires(self, tmp_path: Path) -> None:
        """Expanded root + 2 success children → collapse review fires, outcome → success."""
        store, forum, root, _ = self._setup_expanded(tmp_path)
        runner = DagRunner(store, forum, tmp_path)

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            result = runner.run(root["id"], max_steps=3)

        # Backend called once for collapse review
        assert mock_proc.run.call_count == 1
        # Root outcome promoted to success
        updated = store.get(root["id"])
        assert updated is not None
        assert updated["outcome"] == "success"
        assert result.status == "root_final"

    def test_collapse_review_skipped_without_reviewer(self, tmp_path: Path) -> None:
        """No reviewer.md → no collapse review, DAG terminates normally."""
        store, forum, root, _ = self._setup_expanded(
            tmp_path, has_reviewer=False
        )
        runner = DagRunner(store, forum, tmp_path)

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            result = runner.run(root["id"], max_steps=3)

        # No backend calls — DAG sees "all work completed" immediately
        assert mock_proc.run.call_count == 0
        assert result.status == "root_final"

    def test_collapse_review_skipped_review_false(self, tmp_path: Path) -> None:
        """review=False → no collapse review."""
        store, forum, root, _ = self._setup_expanded(tmp_path)
        runner = DagRunner(store, forum, tmp_path)

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            result = runner.run(root["id"], max_steps=3, review=False)

        assert mock_proc.run.call_count == 0
        assert result.status == "root_final"

    def test_collapse_review_needs_work_triggers_orchestrator_remediation(self, tmp_path: Path) -> None:
        """Collapse reviewer marks needs_work; orchestrator expands remediation children."""
        store, forum, root, _ = self._setup_expanded(tmp_path)
        runner = DagRunner(store, forum, tmp_path)
        root_id = root["id"]

        call_count = [0]
        remediation_id: list[str] = []

        def backend_side_effect(prompt, model, reasoning, cwd, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                # Collapse reviewer rejects aggregate; orchestrator will handle expansion.
                store.update(root_id, outcome="needs_work")
            elif call_count[0] == 2:
                # Orchestrator expands: creates remediation child + keeps parent expanded.
                remediation = store.create("Fix gap", tags=["node:agent"])
                store.add_dep(remediation["id"], "parent", root_id)
                remediation_id.append(remediation["id"])
                store.close(root_id, outcome="expanded")
            elif call_count[0] == 3:
                # Worker closes the remediation issue directly
                store.close(remediation_id[0], outcome="success")
            # call_count[0] == 4: per-issue review on remediation (no state change)
            # call_count[0] == 5: second collapse review (passes)
            return 0

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.side_effect = backend_side_effect
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            result = runner.run(root_id, max_steps=6)

        # call 1: collapse review (marks needs_work)
        # call 2: orchestrator on root (creates remediation child)
        # call 3: worker on remediation
        # call 4: per-issue review on remediation (reviewer.md exists)
        # call 5: second collapse review (passes)
        assert call_count[0] == 5
        updated = store.get(root_id)
        assert updated is not None
        assert updated["outcome"] == "success"
        assert result.status == "root_final"

    def test_collapse_review_logged_to_forum(self, tmp_path: Path) -> None:
        """Forum entry with type=collapse-review, author=reviewer."""
        store, forum, root, _ = self._setup_expanded(tmp_path)
        runner = DagRunner(store, forum, tmp_path)

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.return_value = 0
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            runner.run(root["id"], max_steps=3)

        messages = forum.read(f"issue:{root['id']}")
        collapse_msgs = [
            m for m in messages if m.get("author") == "reviewer"
        ]
        assert len(collapse_msgs) == 1
        body = json.loads(collapse_msgs[0]["body"])
        assert body["type"] == "collapse-review"

    def test_nested_collapse_bottom_up(self, tmp_path: Path) -> None:
        """Two-level expansion → inner reviewed before outer."""
        store, forum = _setup_stores(tmp_path)
        _write_orchestrator(
            tmp_path, "cli: claude\nmodel: opus\nreasoning: high\n", "{{PROMPT}}\n"
        )
        _write_role(
            tmp_path,
            "reviewer",
            "cli: claude\nmodel: opus\nreasoning: high\n",
            "Review:\n{{PROMPT}}\n",
        )

        root = store.create("root", tags=["node:agent", "node:root"])
        child = store.create("child", tags=["node:agent"])
        gc1 = store.create("gc1", tags=["node:agent"])
        gc2 = store.create("gc2", tags=["node:agent"])
        store.add_dep(child["id"], "parent", root["id"])
        store.add_dep(gc1["id"], "parent", child["id"])
        store.add_dep(gc2["id"], "parent", child["id"])
        store.close(root["id"], outcome="expanded")
        store.close(child["id"], outcome="expanded")
        store.close(gc1["id"], outcome="success")
        store.close(gc2["id"], outcome="success")

        runner = DagRunner(store, forum, tmp_path)
        reviewed_ids: list[str] = []

        def backend_side_effect(prompt, model, reasoning, cwd, **kwargs):
            # Track which issue is being collapse-reviewed via Assigned issue line
            for line in prompt.splitlines():
                if line.startswith("Assigned issue:"):
                    issue_id = line.split(":", 1)[1].strip()
                    reviewed_ids.append(issue_id)
                    break
            return 0

        with patch("inshallah.dag.get_backend") as mock_backend, \
             patch("inshallah.dag.get_formatter") as mock_formatter:
            mock_proc = MagicMock()
            mock_proc.run.side_effect = backend_side_effect
            mock_backend.return_value = mock_proc
            mock_formatter.return_value = MagicMock()

            result = runner.run(root["id"], max_steps=5)

        # Inner (child) reviewed first, then outer (root)
        assert len(reviewed_ids) == 2
        assert reviewed_ids[0] == child["id"]
        assert reviewed_ids[1] == root["id"]
        assert result.status == "root_final"
