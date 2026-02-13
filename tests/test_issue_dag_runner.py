from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from loopfarm.runtime.issue_dag_execution import NodeExecutionRunResult, NodeExecutionSelection
from loopfarm.runtime.issue_dag_runner import IssueDagRunner


def _termination(*, is_final: bool, reason: str) -> dict[str, Any]:
    return {
        "root_id": "loopfarm-root",
        "termination": {
            "is_final": is_final,
            "reason": reason,
            "outcome": "success" if is_final else None,
        },
        "errors": [],
        "warnings": [],
        "orphaned_expanded_nodes": [],
    }


@dataclass
class FakeIssueClient:
    validation_plan: list[dict[str, Any]] = field(default_factory=list)
    incremental_calls: list[tuple[str, str]] = field(default_factory=list)
    reconcile_calls: list[str] = field(default_factory=list)

    def validate_orchestration_subtree(self, root_issue_id: str) -> dict[str, Any]:
        _ = root_issue_id
        if self.validation_plan:
            return dict(self.validation_plan.pop(0))
        return _termination(is_final=False, reason="not_terminal")

    def reconcile_control_flow_subtree(self, root_issue_id: str) -> dict[str, Any]:
        self.reconcile_calls.append(root_issue_id)
        return {
            "root_id": root_issue_id,
            "reconciled_count": 0,
            "validation": _termination(is_final=False, reason="not_terminal"),
        }

    def reconcile_control_flow_ancestors(
        self,
        issue_id: str,
        *,
        root_issue_id: str,
    ) -> dict[str, Any]:
        self.incremental_calls.append((issue_id, root_issue_id))
        return {
            "root_id": root_issue_id,
            "issue_id": issue_id,
            "target_count": 0,
            "target_ids": [],
            "reconciled_count": 0,
            "reconciled": [],
            "validation": _termination(is_final=False, reason="not_terminal"),
        }


@dataclass
class FakeForumClient:
    posts: list[dict[str, Any]] = field(default_factory=list)

    def post_json(self, topic: str, payload: Any, *, author: str | None = None) -> None:
        self.posts.append({"topic": topic, "payload": payload, "author": author})


@dataclass
class FakeOrchestrator:
    selections: list[NodeExecutionSelection | None] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def select_next_execution(
        self,
        *,
        root_id: str | None = None,
        tags: list[str] | None = None,
        resume_mode: str = "manual",
    ) -> NodeExecutionSelection | None:
        self.calls.append({"root_id": root_id, "tags": list(tags or []), "resume_mode": resume_mode})
        if self.selections:
            return self.selections.pop(0)
        return None


@dataclass
class FakeExecutor:
    results: list[NodeExecutionRunResult] = field(default_factory=list)
    calls: list[tuple[str, str | None]] = field(default_factory=list)

    def execute_selection(
        self,
        selection: NodeExecutionSelection,
        *,
        root_id: str | None = None,
    ) -> NodeExecutionRunResult:
        self.calls.append((selection.issue_id, root_id))
        if self.results:
            return self.results.pop(0)
        return _result(selection.issue_id)


def _selection(issue_id: str) -> NodeExecutionSelection:
    return NodeExecutionSelection(
        issue_id=issue_id,
        team="dynamic",
        role="worker",
        program="role:worker",
        mode="claim",
        claim_timestamp=100,
        issue={
            "id": issue_id,
            "status": "in_progress",
            "tags": ["node:agent", "granularity:atomic"],
        },
        metadata={"route": "execution"},
    )


def _result(
    issue_id: str,
    *,
    success: bool = True,
    error: str | None = None,
) -> NodeExecutionRunResult:
    return NodeExecutionRunResult(
        issue_id=issue_id,
        root_id="loopfarm-root",
        team="dynamic",
        role="worker",
        program="role:worker",
        mode="claim",
        session_id=f"session-{issue_id}",
        started_at=10,
        started_at_iso="1970-01-01T00:00:00Z",
        ended_at=20,
        ended_at_iso="1970-01-01T00:00:00Z",
        exit_code=0 if success else 1,
        status="closed",
        outcome="success" if success else "failure",
        postconditions_met=success,
        success=success,
        error=error,
    )


def test_runner_stops_on_no_executable_leaf_after_successful_step() -> None:
    issue = FakeIssueClient()
    forum = FakeForumClient()
    orchestrator = FakeOrchestrator(selections=[_selection("loopfarm-a"), None])
    executor = FakeExecutor(results=[_result("loopfarm-a")])
    runner = IssueDagRunner(
        repo_root=Path("."),
        issue=issue,
        forum=forum,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        executor=executor,  # type: ignore[arg-type]
    )

    run = runner.run(root_id="loopfarm-root", max_steps=5)

    assert run.stop_reason == "no_executable_leaf"
    assert len(run.steps) == 1
    assert executor.calls == [("loopfarm-a", "loopfarm-root")]
    assert issue.incremental_calls == [("loopfarm-a", "loopfarm-root")]


def test_runner_stops_with_error_when_execution_fails() -> None:
    issue = FakeIssueClient()
    forum = FakeForumClient()
    orchestrator = FakeOrchestrator(selections=[_selection("loopfarm-a")])
    executor = FakeExecutor(results=[_result("loopfarm-a", success=False, error="boom")])
    runner = IssueDagRunner(
        repo_root=Path("."),
        issue=issue,
        forum=forum,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        executor=executor,  # type: ignore[arg-type]
    )

    run = runner.run(root_id="loopfarm-root", max_steps=3)

    assert run.stop_reason == "error"
    assert run.error == "boom"
    assert len(run.steps) == 1


def test_runner_exits_immediately_when_root_is_final() -> None:
    issue = FakeIssueClient(validation_plan=[_termination(is_final=True, reason="root_final_outcome")])
    forum = FakeForumClient()
    orchestrator = FakeOrchestrator(selections=[_selection("loopfarm-a")])
    executor = FakeExecutor()
    runner = IssueDagRunner(
        repo_root=Path("."),
        issue=issue,
        forum=forum,
        orchestrator=orchestrator,  # type: ignore[arg-type]
        executor=executor,  # type: ignore[arg-type]
    )

    run = runner.run(root_id="loopfarm-root", max_steps=3)

    assert run.stop_reason == "root_final"
    assert len(run.steps) == 0
    assert orchestrator.calls == []
