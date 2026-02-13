from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopfarm import cli
from loopfarm.forum import Forum
from loopfarm.issue import Issue
from loopfarm.runtime.issue_dag_execution import (
    DEFAULT_RUN_TOPIC,
    NodeExecutionRunResult,
    NodeExecutionSelection,
)


def _bootstrap_orchestration_prompts(tmp_path: Path, *, roles: tuple[str, ...]) -> None:
    orchestrator = tmp_path / ".loopfarm" / "orchestrator.md"
    orchestrator.parent.mkdir(parents=True, exist_ok=True)
    orchestrator.write_text("# orchestrator\n", encoding="utf-8")

    roles_dir = tmp_path / ".loopfarm" / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    for role in roles:
        (roles_dir / f"{role}.md").write_text(f"# {role}\n", encoding="utf-8")


def _execution_spec(
    *,
    role: str,
    team: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "version": 1,
        "role": role,
        "prompt_path": f".loopfarm/roles/{role}.md",
    }
    if team:
        payload["team"] = team
    return payload


def test_issue_list_empty_prints_message_and_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["issue", "list"])

    out = capsys.readouterr().out
    assert "(no issues)" in out
    assert not (tmp_path / ".loopfarm").exists()


def test_issue_show_missing_prints_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["issue", "show", "loopfarm-missing"])

    stderr = capsys.readouterr().err
    assert raised.value.code == 1
    assert "error: issue not found: loopfarm-missing" in stderr


def test_issue_show_json_includes_comments_and_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    src = issue.create("Parent")
    dst = issue.create("Child")
    issue.add_dep(src["id"], "blocks", dst["id"])
    issue.add_comment(dst["id"], "Needs docs", author="reviewer")

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "show", dst["id"], "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["id"] == dst["id"]
    assert "comments" in payload
    assert len(payload["comments"]) == 1
    assert payload["comments"][0]["body"] == "Needs docs"
    assert "dependencies" in payload
    assert len(payload["dependencies"]) == 1
    assert payload["created_at_iso"].endswith("Z")
    assert payload["updated_at_iso"].endswith("Z")


def test_issue_list_non_json_uses_table_columns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    issue.create("Implement parser", tags=["feature"])

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "list"])

    out = capsys.readouterr().out
    assert "ID" in out
    assert "STATUS" in out
    assert "TITLE" in out
    assert "Implement parser" in out


def test_issue_list_rich_output_renders_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    issue.create("Implement parser", tags=["feature"])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    cli.main(["issue", "list", "--output", "rich"])

    out = capsys.readouterr().out
    assert "Issues" in out
    assert "ID" in out
    assert "Implement" in out or "parser" in out


def test_issue_ready_rich_output_renders_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Ready task")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    cli.main(["issue", "ready", "--output", "rich"])

    out = capsys.readouterr().out
    assert "Ready Issues" in out
    assert row["id"] in out
    assert "Ready task" in out


def test_issue_ready_json_supports_root_and_tag_filters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root")
    other_root = issue.create("Other root")
    matching = issue.create(
        "Scoped worker",
        tags=["granularity:atomic", "node:agent", "team:alpha"],
    )
    wrong_team = issue.create(
        "Wrong team worker",
        tags=["granularity:atomic", "node:agent", "team:beta"],
    )
    other_root_worker = issue.create(
        "Other root worker",
        tags=["granularity:atomic", "node:agent", "team:alpha"],
    )

    issue.add_dep(root["id"], "parent", matching["id"])
    issue.add_dep(root["id"], "parent", wrong_team["id"])
    issue.add_dep(other_root["id"], "parent", other_root_worker["id"])

    monkeypatch.chdir(tmp_path)
    cli.main(
        [
            "issue",
            "ready",
            "--root",
            root["id"],
            "--tag",
            "granularity:atomic",
            "--tag",
            "node:agent",
            "--tag",
            "team:alpha",
            "--json",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert [row["id"] for row in payload] == [matching["id"]]


def test_issue_orchestrate_json_claims_leaf_and_emits_node_execute(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root", tags=["node:agent", "team:platform"])
    leaf = issue.create(
        "Atomic leaf",
        tags=["node:agent", "team:platform"],
        execution_spec=_execution_spec(role="worker", team="platform"),
    )
    issue.add_dep(root["id"], "parent", leaf["id"])
    _bootstrap_orchestration_prompts(tmp_path, roles=("worker",))

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "orchestrate", "--root", root["id"], "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["root_id"] == root["id"]
    assert payload["required_tags"] == ["node:agent"]
    assert payload["selection"] is not None
    assert payload["selection"]["id"] == leaf["id"]
    assert payload["selection"]["team"] == "platform"
    assert payload["selection"]["role"] == "worker"
    assert payload["selection"]["program"] == "spec:worker"
    assert payload["selection"]["mode"] == "claim"
    assert payload["selection"]["issue"]["status"] == "in_progress"

    forum = Forum.from_workdir(tmp_path)
    run_messages = forum.read(DEFAULT_RUN_TOPIC, limit=5)
    assert run_messages
    run_payloads = [json.loads(str(row["body"])) for row in run_messages]
    assert any(
        entry.get("kind") == "node.execute"
        and entry.get("id") == leaf["id"]
        and entry.get("role") == "worker"
        and entry.get("program") == "spec:worker"
        for entry in run_payloads
    )


def test_issue_orchestrate_json_includes_team_assembly_loop_details(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root", tags=["node:agent", "team:platform"])
    leaf = issue.create(
        "Atomic leaf",
        tags=["node:agent", "team:platform"],
        execution_spec=_execution_spec(role="worker", team="platform"),
    )
    issue.add_dep(root["id"], "parent", leaf["id"])
    _bootstrap_orchestration_prompts(tmp_path, roles=("worker", "reviewer"))

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "orchestrate", "--root", root["id"], "--json"])
    payload = json.loads(capsys.readouterr().out)

    metadata = payload["selection"]["metadata"]
    team_assembly = metadata["team_assembly"]
    selected = team_assembly["selected"]
    assert selected["role"] == "worker"
    assert selected["program"] == "spec:worker"
    assert selected["role_doc"] == ".loopfarm/roles/worker.md"
    roles = {row["role"] for row in team_assembly["roles"]}
    assert roles == {"worker", "reviewer"}


def test_issue_orchestrate_routes_non_atomic_leaf_to_planner_role(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root", tags=["node:agent", "team:platform"])
    leaf = issue.create("Needs planning", tags=["node:agent", "team:platform"])
    issue.add_dep(root["id"], "parent", leaf["id"])
    _bootstrap_orchestration_prompts(tmp_path, roles=("worker",))

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "orchestrate", "--root", root["id"], "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["selection"] is not None
    assert payload["selection"]["id"] == leaf["id"]
    assert payload["selection"]["role"] == "orchestrator"
    assert payload["selection"]["program"] == "orchestrator"
    assert payload["selection"]["metadata"]["role_source"] == "orchestrator.prompt"


def test_issue_orchestrate_routes_non_atomic_leaf_to_orchestrator_role(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root", tags=["node:agent", "team:platform"])
    leaf = issue.create("Needs planning", tags=["node:agent", "team:platform"])
    issue.add_dep(root["id"], "parent", leaf["id"])
    _bootstrap_orchestration_prompts(tmp_path, roles=("worker", "orchestrator"))

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "orchestrate", "--root", root["id"], "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["selection"] is not None
    assert payload["selection"]["id"] == leaf["id"]
    assert payload["selection"]["role"] == "orchestrator"
    assert payload["selection"]["program"] == "orchestrator"
    assert payload["selection"]["metadata"]["role_source"] == "orchestrator.prompt"


def test_issue_orchestrate_fails_fast_without_orchestrator_prompt_when_no_spec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root", tags=["node:agent", "team:platform"])
    leaf = issue.create(
        "Atomic leaf",
        tags=["node:agent", "team:platform", "granularity:atomic"],
    )
    issue.add_dep(root["id"], "parent", leaf["id"])

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as raised:
        cli.main(["issue", "orchestrate", "--root", root["id"], "--json"])

    assert raised.value.code == 1
    stderr = capsys.readouterr().err
    assert "missing orchestrator prompt" in stderr


def test_issue_orchestrate_run_fails_fast_without_orchestrator_prompt_when_no_spec(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root", tags=["node:agent", "team:platform"])
    leaf = issue.create(
        "Atomic leaf",
        tags=["node:agent", "team:platform", "granularity:atomic"],
    )
    issue.add_dep(root["id"], "parent", leaf["id"])

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as raised:
        cli.main(["issue", "orchestrate-run", "--root", root["id"], "--json"])

    assert raised.value.code == 1
    stderr = capsys.readouterr().err
    assert "missing orchestrator prompt" in stderr


def test_issue_orchestrate_json_recursive_max_passes_returns_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root", tags=["node:agent", "team:platform"])
    first = issue.create(
        "Atomic first",
        priority=1,
        tags=["node:agent", "team:platform", "granularity:atomic"],
    )
    second = issue.create(
        "Atomic second",
        priority=2,
        tags=["node:agent", "team:platform", "granularity:atomic"],
    )
    issue.add_dep(root["id"], "parent", first["id"])
    issue.add_dep(root["id"], "parent", second["id"])
    _bootstrap_orchestration_prompts(tmp_path, roles=("worker",))

    monkeypatch.chdir(tmp_path)
    cli.main(
        [
            "issue",
            "orchestrate",
            "--root",
            root["id"],
            "--max-passes",
            "2",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["max_passes"] == 2
    assert payload["pass_count"] == 2
    assert payload["executed_count"] == 2
    assert payload["stop_reason"] == "max_passes_exhausted"

    passes = payload["passes"]
    assert len(passes) == 2
    assert passes[0]["selection"] is not None
    assert passes[1]["selection"] is not None
    assert passes[0]["selection"]["id"] == first["id"]
    assert passes[1]["selection"]["id"] == second["id"]

    forum = Forum.from_workdir(tmp_path)
    run_messages = forum.read(DEFAULT_RUN_TOPIC, limit=10)
    run_payloads = [json.loads(str(row["body"])) for row in run_messages]
    execute_ids = [
        entry.get("id")
        for entry in run_payloads
        if entry.get("kind") == "node.execute"
    ]
    assert first["id"] in execute_ids
    assert second["id"] in execute_ids


def test_issue_orchestrate_json_root_final_before_first_pass(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root final", tags=["node:agent", "team:platform"])
    issue.set_status(
        root["id"],
        "closed",
        outcome="success",
        outcome_provided=True,
    )

    monkeypatch.chdir(tmp_path)
    cli.main(
        [
            "issue",
            "orchestrate",
            "--root",
            root["id"],
            "--max-passes",
            "4",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["selection"] is None
    assert payload["pass_count"] == 0
    assert payload["executed_count"] == 0
    assert payload["stop_reason"] == "root_final"
    assert payload["termination"]["is_final"] is True


def _fake_run_result(
    selection: NodeExecutionSelection,
    *,
    success: bool = True,
    error: str | None = None,
) -> NodeExecutionRunResult:
    return NodeExecutionRunResult(
        issue_id=selection.issue_id,
        root_id=str(selection.metadata.get("root_id") or "") or None,
        team=selection.team,
        role=selection.role,
        program=selection.program,
        mode=selection.mode,
        session_id=f"sess-{selection.issue_id}",
        started_at=1,
        started_at_iso="1970-01-01T00:00:00Z",
        ended_at=2,
        ended_at_iso="1970-01-01T00:00:00Z",
        exit_code=0 if success else 1,
        status="closed" if success else "in_progress",
        outcome="success" if success else None,
        postconditions_met=success,
        success=success,
        error=error,
    )


def test_issue_orchestrate_run_json_executes_steps_until_max_steps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root", tags=["team:platform"])
    first = issue.create(
        "Atomic first",
        priority=1,
        tags=["node:agent", "team:platform", "granularity:atomic"],
    )
    second = issue.create(
        "Atomic second",
        priority=2,
        tags=["node:agent", "team:platform", "granularity:atomic"],
    )
    issue.add_dep(root["id"], "parent", first["id"])
    issue.add_dep(root["id"], "parent", second["id"])
    _bootstrap_orchestration_prompts(tmp_path, roles=("worker",))

    def fake_execute_selection(self, selection: NodeExecutionSelection, *, root_id: str | None = None):
        _ = self
        _ = root_id
        return _fake_run_result(selection)

    monkeypatch.setattr(
        "loopfarm.runtime.issue_dag_execution.IssueDagNodeExecutionAdapter.execute_selection",
        fake_execute_selection,
    )

    monkeypatch.chdir(tmp_path)
    cli.main(
        [
            "issue",
            "orchestrate-run",
            "--root",
            root["id"],
            "--max-steps",
            "2",
            "--scan-limit",
            "5",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["root_id"] == root["id"]
    assert payload["max_steps"] == 2
    assert payload["step_count"] == 2
    assert payload["executed_count"] == 2
    assert payload["stop_reason"] == "max_steps_exhausted"
    assert [step["selection"]["id"] for step in payload["steps"]] == [
        first["id"],
        second["id"],
    ]
    assert all(step["execution"]["success"] is True for step in payload["steps"])
    assert all(step["maintenance"]["mode"] == "incremental" for step in payload["steps"])

    forum = Forum.from_workdir(tmp_path)
    run_messages = forum.read(DEFAULT_RUN_TOPIC, limit=10)
    run_payloads = [json.loads(str(row["body"])) for row in run_messages]
    execute_ids = [
        entry.get("id")
        for entry in run_payloads
        if entry.get("kind") == "node.execute"
    ]
    assert first["id"] in execute_ids
    assert second["id"] in execute_ids


def test_issue_orchestrate_run_json_returns_no_executable_leaf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root", tags=["team:platform"])

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "orchestrate-run", "--root", root["id"], "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["root_id"] == root["id"]
    assert payload["step_count"] == 0
    assert payload["stop_reason"] == "no_executable_leaf"


def test_issue_close_reopen_and_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Close me")

    monkeypatch.chdir(tmp_path)

    cli.main(["issue", "close", row["id"]])
    closed = Issue.from_workdir(tmp_path).show(row["id"])
    assert closed is not None
    assert closed["status"] == "closed"
    assert closed["outcome"] is None

    cli.main(["issue", "reopen", row["id"]])
    reopened = Issue.from_workdir(tmp_path).show(row["id"])
    assert reopened is not None
    assert reopened["status"] == "open"
    assert reopened["outcome"] is None

    with pytest.raises(SystemExit) as raised:
        cli.main(["issue", "delete", row["id"]])
    assert raised.value.code == 1
    assert "refusing to delete without --yes" in capsys.readouterr().err

    cli.main(["issue", "delete", row["id"], "--yes"])
    assert Issue.from_workdir(tmp_path).show(row["id"]) is None


def test_issue_close_with_outcome_and_show_displays_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Close with failure")

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "close", row["id"], "--outcome", "failure"])
    _ = capsys.readouterr()

    shown = Issue.from_workdir(tmp_path).show(row["id"])
    assert shown is not None
    assert shown["status"] == "closed"
    assert shown["outcome"] == "failure"

    cli.main(["issue", "show", row["id"]])
    out = capsys.readouterr().out
    assert "outcome: failure" in out


def test_issue_edit_sets_and_clears_outcome(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Outcome edits")

    monkeypatch.chdir(tmp_path)
    cli.main(
        [
            "issue",
            "edit",
            row["id"],
            "--status",
            "closed",
            "--outcome",
            "skipped",
        ]
    )
    _ = capsys.readouterr()

    updated = Issue.from_workdir(tmp_path).show(row["id"])
    assert updated is not None
    assert updated["status"] == "closed"
    assert updated["outcome"] == "skipped"

    cli.main(["issue", "edit", row["id"], "--clear-outcome"])
    _ = capsys.readouterr()
    cleared = Issue.from_workdir(tmp_path).show(row["id"])
    assert cleared is not None
    assert cleared["outcome"] is None


def test_issue_status_rejects_outcome_for_non_terminal_status(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Cannot set outcome while open")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as raised:
        cli.main(["issue", "status", row["id"], "open", "--outcome", "success"])

    assert raised.value.code == 1
    err = capsys.readouterr().err
    assert "terminal statuses" in err


def test_issue_reconcile_json_prunes_and_closes_control_node(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    node = issue.create("Fallback node", tags=["node:control", "cf:fallback"])
    alt_a = issue.create("Alternative A")
    alt_b = issue.create("Alternative B")
    alt_c = issue.create("Alternative C")

    issue.add_dep(node["id"], "parent", alt_a["id"])
    issue.add_dep(node["id"], "parent", alt_b["id"])
    issue.add_dep(node["id"], "parent", alt_c["id"])
    issue.add_dep(alt_a["id"], "blocks", alt_b["id"])
    issue.add_dep(alt_b["id"], "blocks", alt_c["id"])

    issue.set_status(alt_a["id"], "closed", outcome="failure", outcome_provided=True)
    issue.set_status(alt_b["id"], "closed", outcome="success", outcome_provided=True)

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "reconcile", node["id"], "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["id"] == node["id"]
    assert payload["control_flow"] == "fallback"
    assert payload["outcome"] == "success"
    assert payload["pruned_count"] == 1
    assert payload["pruned_ids"] == [alt_c["id"]]

    pruned = Issue.from_workdir(tmp_path).show(alt_c["id"])
    assert pruned is not None
    assert pruned["status"] == "duplicate"
    assert pruned["outcome"] == "skipped"


def test_issue_reconcile_root_json_walks_subtree(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root")
    node = issue.create("Sequence node", tags=["node:control", "cf:sequence"])
    first = issue.create("First")
    second = issue.create("Second")

    issue.add_dep(root["id"], "parent", node["id"])
    issue.add_dep(node["id"], "parent", first["id"])
    issue.add_dep(node["id"], "parent", second["id"])
    issue.add_dep(first["id"], "blocks", second["id"])
    issue.set_status(first["id"], "closed", outcome="failure", outcome_provided=True)

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "reconcile", root["id"], "--root", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["root_id"] == root["id"]
    assert payload["reconciled_count"] == 1
    assert payload["reconciled"][0]["id"] == node["id"]
    assert payload["validation"]["root_id"] == root["id"]
    assert payload["validation"]["termination"]["reason"] == "root_not_terminal"


def test_issue_reconcile_root_plain_prints_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root")
    child = issue.create("Child")
    issue.add_dep(root["id"], "parent", child["id"])
    issue.set_status(root["id"], "closed", outcome="expanded", outcome_provided=True)
    issue.set_status(child["id"], "closed", outcome="success", outcome_provided=True)

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "reconcile", root["id"], "--root"])

    out = capsys.readouterr().out
    assert "validation errors:" in out
    assert "ERROR orphaned_expanded_node" in out
    assert "root_expanded_without_active_descendants" in out


def test_issue_validate_dag_plain_prints_errors_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root")
    child = issue.create("Child", tags=["node:agent"])
    issue.add_dep(root["id"], "parent", child["id"])
    issue.set_status(child["id"], "closed")

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as raised:
        cli.main(["issue", "validate-dag", "--root", root["id"]])

    out = capsys.readouterr().out
    assert raised.value.code == 1
    assert f"root: {root['id']}" in out
    assert "checks:" in out
    assert "ERROR terminal_node_missing_outcome" in out


def test_issue_validate_dag_json_emits_payload_and_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    root = issue.create("Root")
    left_parent = issue.create("Left parent")
    right_parent = issue.create("Right parent")
    left = issue.create("Left")
    right = issue.create("Right")
    issue.add_dep(root["id"], "parent", left_parent["id"])
    issue.add_dep(root["id"], "parent", right_parent["id"])
    issue.add_dep(left_parent["id"], "parent", left["id"])
    issue.add_dep(right_parent["id"], "parent", right["id"])
    issue.add_dep(left["id"], "blocks", right["id"])

    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit) as raised:
        cli.main(["issue", "validate-dag", "--root", root["id"], "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert raised.value.code == 1
    assert payload["root_id"] == root["id"]
    assert payload["checks"]["blocks_sibling_wiring"] is False
    assert any(
        err["code"] == "blocks_not_siblings"
        and err["src_id"] == left["id"]
        and err["dst_id"] == right["id"]
        for err in payload["errors"]
    )


def test_issue_comments_subcommand(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Needs follow-up")
    issue.add_comment(row["id"], "Ship it", author="reviewer")

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "comments", row["id"]])

    out = capsys.readouterr().out
    assert "reviewer" in out
    assert "Ship it" in out


def test_issue_show_rich_output_renders_sections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    src = issue.create("Parent")
    dst = issue.create("Child", body="Needs docs")
    issue.add_dep(src["id"], "blocks", dst["id"])
    issue.add_comment(dst["id"], "Ship it", author="reviewer")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    cli.main(["issue", "show", dst["id"], "--output", "rich"])

    out = capsys.readouterr().out
    assert f"Issue {dst['id']}" in out
    assert "Description" in out
    assert "Dependencies" in out
    assert "SOURCE" in out
    assert "TARGET" in out
    assert "Comment [" in out
    assert "Ship it" in out


def test_issue_comments_rich_output_renders_panels(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Needs follow-up")
    issue.add_comment(row["id"], "Ship it", author="reviewer")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    cli.main(["issue", "comments", row["id"], "--output", "rich"])

    out = capsys.readouterr().out
    assert "reviewer" in out
    assert "Ship it" in out


def test_issue_deps_rich_output_renders_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    src = issue.create("Parent")
    dst = issue.create("Child")
    issue.add_dep(src["id"], "blocks", dst["id"])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    cli.main(["issue", "deps", dst["id"], "--output", "rich"])

    out = capsys.readouterr().out
    assert f"Dependencies: {dst['id']}" in out
    assert "SOURCE" in out
    assert "TYPE" in out
    assert "TARGET" in out


def test_forum_read_empty_prints_message_and_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["forum", "read", "unknown-topic"])

    out = capsys.readouterr().out
    assert "(no messages)" in out
    assert not (tmp_path / ".loopfarm").exists()


def test_forum_show_missing_prints_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["forum", "show", "12345"])

    stderr = capsys.readouterr().err
    assert raised.value.code == 1
    assert "error: message not found: 12345" in stderr


def test_forum_topic_list_empty_prints_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["forum", "topic", "list"])

    out = capsys.readouterr().out
    assert "(no topics)" in out


def test_forum_read_non_json_uses_human_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    forum = Forum.from_workdir(tmp_path)
    forum.post("loopfarm:test", "hello", author="agent")

    monkeypatch.chdir(tmp_path)
    cli.main(["forum", "read", "loopfarm:test", "--limit", "1"])

    out = capsys.readouterr().out
    assert "@20" in out
    assert "T" in out
    assert "Z" in out


def test_sessions_list_empty_prints_message_and_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["sessions"])

    out = capsys.readouterr().out
    assert "(no sessions)" in out
    assert not (tmp_path / ".loopfarm").exists()


def test_sessions_and_history_commands_show_session_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_id = "loopfarm-a1b2c3d4"
    forum = Forum.from_workdir(tmp_path)
    forum.post_json(
        f"loopfarm:session:{session_id}",
        {
            "prompt": "Improve cli ergonomics",
            "status": "running",
            "phase": "forward",
            "iteration": 2,
            "started": "2026-02-12T10:00:00Z",
        },
    )
    forum.post_json(
        f"loopfarm:status:{session_id}",
        {
            "decision": "CONTINUE",
            "summary": "one more forward pass",
        },
    )
    forum.post_json(
        f"loopfarm:briefing:{session_id}",
        {
            "phase": "forward",
            "iteration": 2,
            "summary": "Added lifecycle commands",
        },
    )

    monkeypatch.chdir(tmp_path)

    cli.main(["sessions", "list"])
    sessions_list_out = capsys.readouterr().out
    assert session_id in sessions_list_out
    assert "CONTINUE" in sessions_list_out

    cli.main(["history"])
    history_out = capsys.readouterr().out
    assert session_id in history_out

    cli.main(["sessions", "show", session_id, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["session_id"] == session_id
    assert payload["status"] == "running"
    assert payload["decision"] == "CONTINUE"
    assert len(payload["briefings"]) == 1


def test_history_help_uses_history_prog_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["history", "--help"])

    captured = capsys.readouterr()
    assert raised.value.code == 0
    out = captured.out + captured.err
    assert "loopfarm history" in out
    assert "loopfarm history list" in out
    assert "loopfarm sessions" not in out
