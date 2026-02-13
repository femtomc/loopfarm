from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from loopfarm.runtime.issue_dag_events import validate_issue_dag_event
from loopfarm.runtime.issue_dag_orchestrator import IssueDagOrchestrator


@dataclass
class FakeIssueClient:
    ready_rows: list[dict[str, Any]] = field(default_factory=list)
    resumable_rows: list[dict[str, Any]] = field(default_factory=list)
    claim_plan: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    claim_calls: list[tuple[str, str | None, tuple[str, ...]]] = field(default_factory=list)

    def ready(
        self,
        *,
        limit: int = 20,
        root: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        _ = limit
        _ = root
        _ = tags
        return [dict(row) for row in self.ready_rows]

    def resumable(
        self,
        *,
        limit: int = 20,
        root: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        _ = limit
        _ = root
        _ = tags
        return [dict(row) for row in self.resumable_rows]

    def claim_ready_leaf(
        self,
        issue_id: str,
        *,
        root: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        self.claim_calls.append((issue_id, root, tuple(tags or [])))
        rows = self.claim_plan.get(issue_id, [])
        if rows:
            return dict(rows.pop(0))
        return {
            "id": issue_id,
            "claimed": False,
            "claimed_at": None,
            "issue": {"id": issue_id, "status": "open"},
        }

    def validate_orchestration_subtree(self, root_id: str) -> dict[str, Any]:
        return {
            "root_id": root_id,
            "termination": {
                "is_final": False,
                "reason": "not_terminal",
                "outcome": None,
            },
            "errors": [],
            "warnings": [],
            "orphaned_expanded_nodes": [],
        }


@dataclass
class FakeForumClient:
    posts: list[dict[str, Any]] = field(default_factory=list)

    def post_json(self, topic: str, payload: Any, *, author: str | None = None) -> None:
        self.posts.append({"topic": topic, "payload": payload, "author": author})


def _write_role(repo_root: Path, role: str) -> None:
    path = repo_root / ".loopfarm" / "roles" / f"{role}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {role}\n", encoding="utf-8")


def _write_orchestrator_prompt(repo_root: Path) -> None:
    path = repo_root / ".loopfarm" / "orchestrator.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# orchestrator\n", encoding="utf-8")


def _claim(
    issue_id: str,
    *,
    tags: list[str],
    claimed_at: int = 100,
    execution_spec: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": issue_id,
        "claimed": True,
        "claimed_at": claimed_at,
        "issue": {
            "id": issue_id,
            "status": "in_progress",
            "priority": 1,
            "updated_at": claimed_at,
            "tags": tags,
            "execution_spec": execution_spec,
        },
    }


def _execute_payload(forum: FakeForumClient) -> dict[str, Any]:
    return next(post["payload"] for post in forum.posts if post["payload"].get("kind") == "node.execute")


def test_non_atomic_routes_to_orchestrator_prompt(tmp_path: Path) -> None:
    _write_orchestrator_prompt(tmp_path)
    _write_role(tmp_path, "worker")
    issue = FakeIssueClient(
        ready_rows=[
            {
                "id": "loopfarm-plan",
                "priority": 1,
                "updated_at": 50,
                "tags": ["node:agent", "team:platform"],
            }
        ],
        claim_plan={
            "loopfarm-plan": [
                _claim("loopfarm-plan", tags=["node:agent", "team:platform"])
            ]
        },
    )
    forum = FakeForumClient()
    orchestrator = IssueDagOrchestrator(repo_root=tmp_path, issue=issue, forum=forum)

    selection = orchestrator.select_next_execution(root_id="loopfarm-root")

    assert selection is not None
    assert selection.role == "orchestrator"
    assert selection.program == "orchestrator"
    assert selection.team == "platform"
    assert selection.metadata["route"] == "orchestrator_planning"
    assert selection.metadata["team_assembly"]["selected"]["role_doc"] == ".loopfarm/orchestrator.md"

    execute_payload = _execute_payload(forum)
    assert execute_payload["route"] == "orchestrator_planning"
    assert validate_issue_dag_event(execute_payload) == []


def test_execution_spec_routes_to_spec_execution_role(tmp_path: Path) -> None:
    _write_orchestrator_prompt(tmp_path)
    _write_role(tmp_path, "worker")
    _write_role(tmp_path, "reviewer")
    execution_spec = {
        "version": 1,
        "role": "worker",
        "prompt_path": ".loopfarm/roles/worker.md",
    }
    issue = FakeIssueClient(
        ready_rows=[
            {
                "id": "loopfarm-work",
                "priority": 1,
                "updated_at": 50,
                "tags": ["node:agent"],
                "execution_spec": execution_spec,
            }
        ],
        claim_plan={
            "loopfarm-work": [
                _claim(
                    "loopfarm-work",
                    tags=["node:agent"],
                    execution_spec=execution_spec,
                )
            ]
        },
    )
    forum = FakeForumClient()
    orchestrator = IssueDagOrchestrator(repo_root=tmp_path, issue=issue, forum=forum)

    selection = orchestrator.select_next_execution(root_id="loopfarm-root")

    assert selection is not None
    assert selection.role == "worker"
    assert selection.program == "spec:worker"
    assert selection.team == "dynamic"
    assert selection.metadata["route"] == "spec_execution"
    assert selection.metadata["role_source"] == "execution_spec"


def test_invalid_execution_spec_fails_fast(tmp_path: Path) -> None:
    _write_orchestrator_prompt(tmp_path)
    _write_role(tmp_path, "reviewer")
    _write_role(tmp_path, "qa")
    issue = FakeIssueClient(
        ready_rows=[
            {
                "id": "loopfarm-work",
                "priority": 1,
                "updated_at": 50,
                "tags": ["node:agent"],
                "execution_spec": {"role": ""},
            }
        ],
        claim_plan={
            "loopfarm-work": [
                _claim(
                    "loopfarm-work",
                    tags=["node:agent"],
                    execution_spec={"role": ""},
                )
            ]
        },
    )
    forum = FakeForumClient()
    orchestrator = IssueDagOrchestrator(repo_root=tmp_path, issue=issue, forum=forum)

    with pytest.raises(ValueError, match="invalid execution_spec"):
        orchestrator.select_next_execution(root_id="loopfarm-root")


def test_execution_spec_honors_explicit_role(tmp_path: Path) -> None:
    _write_orchestrator_prompt(tmp_path)
    _write_role(tmp_path, "worker")
    _write_role(tmp_path, "reviewer")
    execution_spec = {
        "version": 1,
        "role": "reviewer",
        "prompt_path": ".loopfarm/roles/reviewer.md",
    }
    issue = FakeIssueClient(
        ready_rows=[
            {
                "id": "loopfarm-review",
                "priority": 1,
                "updated_at": 50,
                "tags": ["node:agent", "role:reviewer"],
                "execution_spec": execution_spec,
            }
        ],
        claim_plan={
            "loopfarm-review": [
                _claim(
                    "loopfarm-review",
                    tags=["node:agent", "role:reviewer"],
                    execution_spec=execution_spec,
                )
            ]
        },
    )
    forum = FakeForumClient()
    orchestrator = IssueDagOrchestrator(repo_root=tmp_path, issue=issue, forum=forum)

    selection = orchestrator.select_next_execution(root_id="loopfarm-root")

    assert selection is not None
    assert selection.role == "reviewer"
    assert selection.program == "spec:reviewer"
    assert selection.metadata["role_source"] == "execution_spec"
