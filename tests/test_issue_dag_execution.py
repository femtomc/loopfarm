from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from loopfarm.runtime.issue_dag_events import validate_issue_dag_event
from loopfarm.runtime.issue_dag_execution import (
    DEFAULT_SELECTION_TEAM,
    IssueDagExecutionPlanner,
    IssueDagNodeExecutionAdapter,
    NodeExecutionSelection,
)


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


@dataclass
class FakeForumClient:
    posts: list[dict[str, Any]] = field(default_factory=list)
    messages_by_topic: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    _next_message_id: int = 1
    _next_created_at: int = 1

    def post_json(self, topic: str, payload: Any, *, author: str | None = None) -> None:
        message = {
            "id": self._next_message_id,
            "topic": topic,
            "body": json.dumps(payload, ensure_ascii=False),
            "author": author,
            "created_at": self._next_created_at,
        }
        self._next_message_id += 1
        self._next_created_at += 1
        self.messages_by_topic.setdefault(topic, []).insert(0, message)
        self.posts.append({"topic": topic, "payload": payload, "author": author})

    def read_json(self, topic: str, *, limit: int) -> list[dict[str, Any]]:
        rows = self.messages_by_topic.get(topic, [])
        return [dict(item) for item in rows[: max(1, int(limit))]]


@dataclass
class FakeIssueExecutionClient:
    rows: dict[str, dict[str, Any]] = field(default_factory=dict)

    def show(self, issue_id: str) -> dict[str, Any] | None:
        row = self.rows.get(issue_id)
        if row is None:
            return None
        return dict(row)


def _write_role(repo_root: Path, role: str) -> None:
    path = repo_root / ".loopfarm" / "roles" / f"{role}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {role}\n", encoding="utf-8")


def _write_orchestrator_prompt(repo_root: Path) -> None:
    path = repo_root / ".loopfarm" / "orchestrator.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# orchestrator\n", encoding="utf-8")


def _claim(issue_id: str, *, tags: list[str], claimed_at: int = 100) -> dict[str, Any]:
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
        },
    }


def test_execution_planner_builds_selection_with_dynamic_team_by_default() -> None:
    issue = FakeIssueClient(
        ready_rows=[{"id": "loopfarm-a", "priority": 1, "updated_at": 50}],
        claim_plan={"loopfarm-a": [_claim("loopfarm-a", tags=["node:agent"]) ]},
    )
    forum = FakeForumClient()
    planner = IssueDagExecutionPlanner(issue=issue, forum=forum)

    selection = planner.select_next_execution(
        role="worker",
        program="role:worker",
        tags=["node:agent"],
    )

    assert selection is not None
    assert selection.issue_id == "loopfarm-a"
    assert selection.team == DEFAULT_SELECTION_TEAM
    assert selection.role == "worker"
    assert selection.program == "role:worker"
    assert issue.claim_calls == [("loopfarm-a", None, ("node:agent",))]

    execute_payload = next(
        post["payload"]
        for post in forum.posts
        if post["payload"].get("kind") == "node.execute"
    )
    assert execute_payload["team"] == DEFAULT_SELECTION_TEAM
    assert validate_issue_dag_event(execute_payload) == []


def test_execution_planner_respects_explicit_team_override() -> None:
    issue = FakeIssueClient(
        ready_rows=[{"id": "loopfarm-a", "priority": 1, "updated_at": 50}],
        claim_plan={"loopfarm-a": [_claim("loopfarm-a", tags=["node:agent"]) ]},
    )
    forum = FakeForumClient()
    planner = IssueDagExecutionPlanner(issue=issue, forum=forum)

    selection = planner.build_selection(
        issue={"id": "loopfarm-a", "status": "in_progress", "tags": ["node:agent"]},
        mode="claim",
        role="worker",
        program="role:worker",
        team="platform",
        root_id="loopfarm-root",
        tags=["node:agent"],
        claim_timestamp=123,
    )

    assert selection is not None
    assert selection.team == "platform"


def test_node_execution_adapter_routes_planning_to_orchestrator_prompt(tmp_path: Path) -> None:
    _write_orchestrator_prompt(tmp_path)
    _write_role(tmp_path, "worker")
    issue_state = FakeIssueExecutionClient(
        rows={
            "loopfarm-a": {
                "id": "loopfarm-a",
                "title": "Plan",
                "body": "body",
                "status": "in_progress",
                "outcome": None,
                "tags": ["node:agent"],
            }
        }
    )
    forum = FakeForumClient()
    captured_prompt_override: list[tuple[str, str]] = []

    def fake_run_session(cfg, _session_id: str) -> int:
        captured_prompt_override.extend(cfg.phase_prompt_overrides)
        issue_state.rows["loopfarm-a"]["status"] = "closed"
        issue_state.rows["loopfarm-a"]["outcome"] = "expanded"
        return 0

    adapter = IssueDagNodeExecutionAdapter(
        repo_root=tmp_path,
        issue=issue_state,
        forum=forum,
        run_session=fake_run_session,
        session_id_factory=lambda: "sess-plan",
    )

    result = adapter.execute_selection(
        NodeExecutionSelection(
            issue_id="loopfarm-a",
            team="dynamic",
            role="orchestrator",
            program="orchestrator",
            mode="claim",
            claim_timestamp=123,
            issue={"id": "loopfarm-a", "tags": ["node:agent"]},
            metadata={"route": "planning"},
        ),
        root_id="loopfarm-root",
    )

    assert result.success is True
    assert captured_prompt_override == [("role", str(tmp_path / ".loopfarm" / "orchestrator.md"))]


def test_node_execution_adapter_routes_execution_to_role_doc(tmp_path: Path) -> None:
    _write_orchestrator_prompt(tmp_path)
    _write_role(tmp_path, "worker")
    issue_state = FakeIssueExecutionClient(
        rows={
            "loopfarm-a": {
                "id": "loopfarm-a",
                "title": "Work",
                "body": "body",
                "status": "in_progress",
                "outcome": None,
                "tags": ["node:agent", "granularity:atomic"],
            }
        }
    )
    forum = FakeForumClient()
    captured_prompt_override: list[tuple[str, str]] = []

    def fake_run_session(cfg, _session_id: str) -> int:
        captured_prompt_override.extend(cfg.phase_prompt_overrides)
        issue_state.rows["loopfarm-a"]["status"] = "closed"
        issue_state.rows["loopfarm-a"]["outcome"] = "success"
        return 0

    adapter = IssueDagNodeExecutionAdapter(
        repo_root=tmp_path,
        issue=issue_state,
        forum=forum,
        run_session=fake_run_session,
        session_id_factory=lambda: "sess-work",
    )

    result = adapter.execute_selection(
        NodeExecutionSelection(
            issue_id="loopfarm-a",
            team="dynamic",
            role="worker",
            program="role:worker",
            mode="claim",
            claim_timestamp=123,
            issue={"id": "loopfarm-a", "tags": ["node:agent", "granularity:atomic"]},
            metadata={"route": "execution"},
        ),
        root_id="loopfarm-root",
    )

    assert result.success is True
    assert captured_prompt_override == [
        ("role", str(tmp_path / ".loopfarm" / "roles" / "worker.md"))
    ]


def test_node_execution_adapter_enforces_planning_postcondition(tmp_path: Path) -> None:
    _write_orchestrator_prompt(tmp_path)
    _write_role(tmp_path, "worker")
    issue_state = FakeIssueExecutionClient(
        rows={
            "loopfarm-a": {
                "id": "loopfarm-a",
                "title": "Plan",
                "body": "body",
                "status": "in_progress",
                "outcome": None,
                "tags": ["node:agent"],
            }
        }
    )
    forum = FakeForumClient()

    def fake_run_session(_cfg, _session_id: str) -> int:
        issue_state.rows["loopfarm-a"]["status"] = "closed"
        issue_state.rows["loopfarm-a"]["outcome"] = "success"
        return 0

    adapter = IssueDagNodeExecutionAdapter(
        repo_root=tmp_path,
        issue=issue_state,
        forum=forum,
        run_session=fake_run_session,
        session_id_factory=lambda: "sess-bad",
    )

    result = adapter.execute_selection(
        NodeExecutionSelection(
            issue_id="loopfarm-a",
            team="dynamic",
            role="orchestrator",
            program="orchestrator",
            mode="claim",
            claim_timestamp=123,
            issue={"id": "loopfarm-a", "tags": ["node:agent"]},
            metadata={"route": "planning"},
        ),
        root_id="loopfarm-root",
    )

    assert result.success is False
    assert result.error is not None
    assert "outcome=expanded" in result.error


def test_node_execution_adapter_requires_orchestrator_prompt_for_planning(
    tmp_path: Path,
) -> None:
    _write_role(tmp_path, "worker")
    issue_state = FakeIssueExecutionClient(
        rows={
            "loopfarm-a": {
                "id": "loopfarm-a",
                "status": "in_progress",
                "outcome": None,
                "tags": ["node:agent"],
            }
        }
    )
    forum = FakeForumClient()
    adapter = IssueDagNodeExecutionAdapter(
        repo_root=tmp_path,
        issue=issue_state,
        forum=forum,
        run_session=lambda _cfg, _sid: 0,
        session_id_factory=lambda: "sess-missing",
    )

    with pytest.raises(ValueError, match="missing orchestrator prompt"):
        adapter.execute_selection(
            NodeExecutionSelection(
                issue_id="loopfarm-a",
                team="dynamic",
                role="orchestrator",
                program="orchestrator",
                mode="claim",
                claim_timestamp=123,
                issue={"id": "loopfarm-a", "tags": ["node:agent"]},
                metadata={"route": "planning"},
            ),
            root_id="loopfarm-root",
        )
