from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from loopfarm import cli
from loopfarm.forum import Forum
from loopfarm.issue import Issue


def test_forum_round_trip_json_message(tmp_path: Path) -> None:
    forum = Forum.from_workdir(tmp_path)

    forum.post_json("loopfarm:test", {"status": "ok", "count": 1})
    rows = forum.read_json("loopfarm:test", limit=1)

    assert len(rows) == 1
    payload = json.loads(rows[0]["body"])
    assert payload["status"] == "ok"
    assert payload["count"] == 1


def test_issue_ready_prefers_leaf_and_unblocked(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    parent = issue.create("Parent epic", priority=2)
    child = issue.create("Leaf task", priority=1)
    blocker = issue.create("Blocking task", priority=1)
    blocked = issue.create("Blocked task", priority=1)

    issue.add_dep(parent["id"], "parent", child["id"])
    issue.add_dep(blocker["id"], "blocks", blocked["id"])

    ready_ids = [row["id"] for row in issue.ready(limit=20)]

    assert child["id"] in ready_ids
    assert parent["id"] not in ready_ids
    assert blocked["id"] not in ready_ids


def test_issue_ready_scales_without_dropping_ready_rows(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    ready = issue.create("Single ready leaf", priority=3)
    blocker = issue.create("Global blocker", priority=1)
    paused_child = issue.create("Paused blocker child", status="paused", priority=1)
    issue.add_dep(blocker["id"], "parent", paused_child["id"])

    for index in range(80):
        blocked = issue.create(f"Blocked leaf {index:02d}", priority=1)
        issue.add_dep(blocker["id"], "blocks", blocked["id"])

    rows = issue.ready(limit=1)
    assert [row["id"] for row in rows] == [ready["id"]]


def test_issue_ready_supports_root_scoping(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    root_alpha = issue.create("Root alpha")
    root_beta = issue.create("Root beta")
    alpha_leaf = issue.create("Alpha leaf", priority=2)
    beta_leaf = issue.create("Beta leaf", priority=1)

    issue.add_dep(root_alpha["id"], "parent", alpha_leaf["id"])
    issue.add_dep(root_beta["id"], "parent", beta_leaf["id"])

    global_ready = {row["id"] for row in issue.ready(limit=20)}
    assert alpha_leaf["id"] in global_ready
    assert beta_leaf["id"] in global_ready

    alpha_ready = [row["id"] for row in issue.ready(limit=20, root=root_alpha["id"])]
    beta_ready = [row["id"] for row in issue.ready(limit=20, root=root_beta["id"])]

    assert alpha_ready == [alpha_leaf["id"]]
    assert beta_ready == [beta_leaf["id"]]


def test_issue_ready_root_requires_existing_issue(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    with pytest.raises(ValueError, match="unknown issue: loopfarm-missing"):
        issue.ready(limit=5, root="loopfarm-missing")


def test_issue_ready_supports_repeatable_tag_filters(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    matching = issue.create(
        "Atomic worker",
        tags=["granularity:atomic", "node:agent", "team:alpha"],
    )
    issue.create(
        "No team tag",
        tags=["granularity:atomic", "node:agent"],
    )
    issue.create(
        "Wrong team",
        tags=["granularity:atomic", "node:agent", "team:beta"],
    )

    rows = issue.ready(
        limit=10,
        tags=["granularity:atomic", "node:agent", "team:alpha"],
    )
    assert [row["id"] for row in rows] == [matching["id"]]


def test_issue_resolve_team_prefers_leaf_tag_over_parent_or_default(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)

    root = issue.create("Root", tags=["team:platform"])
    leaf = issue.create("Leaf", tags=["node:agent", "team:worker"])
    issue.add_dep(root["id"], "parent", leaf["id"])

    resolved = issue.resolve_team(leaf["id"], default_team="fallback")

    assert resolved["team"] == "worker"
    assert resolved["source"] == "issue_tag"
    assert resolved["source_issue_id"] == leaf["id"]
    assert resolved["source_tag"] == "team:worker"


def test_issue_resolve_team_inherits_nearest_ancestor_tag(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    grandparent = issue.create("Grandparent", tags=["team:platform"])
    parent = issue.create("Parent", tags=["team:ops"])
    leaf = issue.create("Leaf", tags=["node:agent"])
    issue.add_dep(grandparent["id"], "parent", parent["id"])
    issue.add_dep(parent["id"], "parent", leaf["id"])

    resolved = issue.resolve_team(leaf["id"])

    assert resolved["team"] == "ops"
    assert resolved["source"] == "ancestor_tag"
    assert resolved["source_issue_id"] == parent["id"]
    assert resolved["depth"] == 1


def test_issue_resolve_team_errors_on_multiple_team_tags(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)
    leaf = issue.create(
        "Leaf",
        tags=["node:agent", "team:alpha", "team:beta"],
    )

    with pytest.raises(ValueError, match="multiple team:\\* tags on issue"):
        issue.resolve_team(leaf["id"])


def test_issue_resolve_team_requires_default_when_no_team_is_resolvable(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)
    leaf = issue.create("Leaf", tags=["node:agent"])

    with pytest.raises(ValueError, match="unable to resolve team"):
        issue.resolve_team(leaf["id"])


def test_issue_claim_ready_leaf_succeeds_only_once(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    leaf = issue.create(
        "Claim me once",
        tags=["node:agent", "granularity:atomic"],
    )

    first = issue.claim_ready_leaf(leaf["id"])
    second = issue.claim_ready_leaf(leaf["id"])

    assert first["claimed"] is True
    assert isinstance(first["claimed_at"], int)
    assert first["issue"]["status"] == "in_progress"
    assert second["claimed"] is False
    assert second["claimed_at"] is None
    assert second["issue"]["status"] == "in_progress"


def test_issue_claim_ready_leaf_requires_still_ready_leaf(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    blocker = issue.create("Open blocker")
    blocked = issue.create("Blocked candidate")
    issue.add_dep(blocker["id"], "blocks", blocked["id"])

    payload = issue.claim_ready_leaf(blocked["id"])

    assert payload["claimed"] is False
    assert payload["claimed_at"] is None
    assert payload["issue"]["status"] == "open"


def test_issue_resumable_orders_oldest_in_progress_first(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    oldest = issue.create("Oldest in progress", status="in_progress", priority=1)
    newest = issue.create("Newest in progress", status="in_progress", priority=1)
    lower_priority = issue.create(
        "Lower priority in progress",
        status="in_progress",
        priority=3,
    )

    rows = issue.resumable(limit=10)
    assert [row["id"] for row in rows] == [
        oldest["id"],
        newest["id"],
        lower_priority["id"],
    ]


def test_issue_outcome_persists_and_reopen_clears(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Resolve with explicit outcome")

    closed = issue.set_status(
        row["id"],
        "closed",
        outcome="failure",
        outcome_provided=True,
    )
    assert closed["status"] == "closed"
    assert closed["outcome"] == "failure"

    loaded = issue.show(row["id"])
    assert loaded is not None
    assert loaded["outcome"] == "failure"

    reopened = issue.set_status(row["id"], "open")
    assert reopened["status"] == "open"
    assert reopened["outcome"] is None


def test_issue_outcome_requires_terminal_status(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Non-terminal cannot have outcome")

    with pytest.raises(ValueError, match="terminal statuses"):
        issue.set_status(
            row["id"],
            "open",
            outcome="success",
            outcome_provided=True,
        )


def test_issue_control_flow_sequence_evaluates_failure_for_mixed_outcomes(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)
    parent = issue.create(
        "Sequence node",
        tags=["node:control", "cf:sequence"],
    )

    child_success = issue.create("Sequence child success")
    child_failure = issue.create("Sequence child failure")
    child_skipped = issue.create("Sequence child skipped")

    issue.add_dep(parent["id"], "parent", child_success["id"])
    issue.add_dep(parent["id"], "parent", child_failure["id"])
    issue.add_dep(parent["id"], "parent", child_skipped["id"])

    issue.set_status(
        child_success["id"],
        "closed",
        outcome="success",
        outcome_provided=True,
    )
    issue.set_status(
        child_failure["id"],
        "closed",
        outcome="failure",
        outcome_provided=True,
    )
    issue.set_status(
        child_skipped["id"],
        "duplicate",
        outcome="skipped",
        outcome_provided=True,
    )

    evaluated = issue.evaluate_control_flow(parent["id"])
    assert evaluated is not None
    assert evaluated["control_flow"] == "sequence"
    assert evaluated["outcome"] == "failure"
    assert evaluated["child_count"] == 3


def test_issue_control_flow_fallback_evaluates_success_when_any_child_succeeds(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)
    parent = issue.create(
        "Fallback node",
        tags=["node:control", "cf:fallback"],
    )

    child_failure = issue.create("Fallback child failure")
    child_success = issue.create("Fallback child success")
    child_skipped = issue.create("Fallback child skipped")

    issue.add_dep(parent["id"], "parent", child_failure["id"])
    issue.add_dep(parent["id"], "parent", child_success["id"])
    issue.add_dep(parent["id"], "parent", child_skipped["id"])

    issue.set_status(
        child_failure["id"],
        "closed",
        outcome="failure",
        outcome_provided=True,
    )
    issue.set_status(
        child_success["id"],
        "closed",
        outcome="success",
        outcome_provided=True,
    )
    issue.set_status(
        child_skipped["id"],
        "duplicate",
        outcome="skipped",
        outcome_provided=True,
    )

    evaluated = issue.evaluate_control_flow(parent["id"])
    assert evaluated is not None
    assert evaluated["control_flow"] == "fallback"
    assert evaluated["outcome"] == "success"


def test_issue_control_flow_parallel_uses_majority_voting(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)
    parent = issue.create(
        "Parallel node",
        tags=["node:control", "cf:parallel"],
    )

    outcomes = ["success", "success", "success", "failure", "skipped"]
    for index, outcome in enumerate(outcomes):
        child = issue.create(f"Parallel child {index}")
        issue.add_dep(parent["id"], "parent", child["id"])
        status = "closed" if outcome != "skipped" else "duplicate"
        issue.set_status(
            child["id"],
            status,
            outcome=outcome,
            outcome_provided=True,
        )

    evaluated = issue.evaluate_control_flow(parent["id"])
    assert evaluated is not None
    assert evaluated["control_flow"] == "parallel"
    assert evaluated["outcome"] == "success"
    assert evaluated["outcome_counts"]["success"] == 3


def test_issue_control_flow_helpers_only_return_terminal_children_nodes(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)

    evaluatable = issue.create(
        "Evaluatable control node",
        tags=["node:control", "cf:sequence"],
        priority=1,
    )
    done_a = issue.create("Done child A")
    done_b = issue.create("Done child B")
    issue.add_dep(evaluatable["id"], "parent", done_a["id"])
    issue.add_dep(evaluatable["id"], "parent", done_b["id"])
    issue.set_status(done_a["id"], "closed", outcome="success", outcome_provided=True)
    issue.set_status(done_b["id"], "closed", outcome="success", outcome_provided=True)

    not_done = issue.create(
        "Not yet evaluatable control node",
        tags=["node:control", "cf:fallback"],
        priority=2,
    )
    terminal_child = issue.create("Terminal fallback child")
    open_child = issue.create("Open fallback child")
    issue.add_dep(not_done["id"], "parent", terminal_child["id"])
    issue.add_dep(not_done["id"], "parent", open_child["id"])
    issue.set_status(
        terminal_child["id"],
        "closed",
        outcome="failure",
        outcome_provided=True,
    )

    plain_parent = issue.create("Plain parent without control-flow tag", priority=3)
    plain_child = issue.create("Plain child")
    issue.add_dep(plain_parent["id"], "parent", plain_child["id"])
    issue.set_status(
        plain_child["id"],
        "closed",
        outcome="success",
        outcome_provided=True,
    )

    assert issue.evaluate_control_flow(not_done["id"]) is None
    with pytest.raises(ValueError, match="not a control-flow"):
        issue.evaluate_control_flow(plain_parent["id"])

    rows = issue.evaluatable_control_flow_nodes(limit=10)
    assert [row["id"] for row in rows] == [evaluatable["id"]]
    assert rows[0]["outcome"] == "success"


def test_issue_control_flow_waits_for_expanded_child_to_resolve(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)

    sequence = issue.create(
        "Sequence control",
        tags=["node:control", "cf:sequence"],
    )
    expanded_branch = issue.create("Expanded branch")
    branch_leaf = issue.create("Branch leaf")

    issue.add_dep(sequence["id"], "parent", expanded_branch["id"])
    issue.add_dep(expanded_branch["id"], "parent", branch_leaf["id"])
    issue.set_status(
        expanded_branch["id"],
        "closed",
        outcome="expanded",
        outcome_provided=True,
    )

    assert issue.evaluate_control_flow(sequence["id"]) is None

    reconciled = issue.reconcile_control_flow(sequence["id"])
    assert reconciled["outcome"] is None
    assert reconciled["all_children_terminal"] is True
    assert reconciled["all_children_final"] is False


def test_issue_reconcile_sequence_prunes_remaining_open_siblings(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)

    sequence = issue.create(
        "Sequence control",
        tags=["node:control", "cf:sequence"],
    )
    step_a = issue.create("Sequence step A")
    step_b = issue.create("Sequence step B")
    step_c = issue.create("Sequence step C")

    issue.add_dep(sequence["id"], "parent", step_a["id"])
    issue.add_dep(sequence["id"], "parent", step_b["id"])
    issue.add_dep(sequence["id"], "parent", step_c["id"])
    issue.add_dep(step_a["id"], "blocks", step_b["id"])
    issue.add_dep(step_b["id"], "blocks", step_c["id"])

    issue.set_status(step_a["id"], "closed", outcome="success", outcome_provided=True)
    issue.set_status(step_b["id"], "closed", outcome="failure", outcome_provided=True)

    first = issue.reconcile_control_flow(sequence["id"])
    assert first["control_flow"] == "sequence"
    assert first["outcome"] == "failure"
    assert first["pruned_ids"] == [step_c["id"]]
    assert first["pruned_count"] == 1

    pruned_child = issue.show(step_c["id"])
    assert pruned_child is not None
    assert pruned_child["status"] == "duplicate"
    assert pruned_child["outcome"] == "skipped"
    assert "reason:upstream_failure" in pruned_child["tags"]

    closed_control = issue.show(sequence["id"])
    assert closed_control is not None
    assert closed_control["status"] == "closed"
    assert closed_control["outcome"] == "failure"

    second = issue.reconcile_control_flow(sequence["id"])
    assert second["pruned_count"] == 0


def test_issue_reconcile_fallback_prunes_remaining_open_alternatives(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)

    fallback = issue.create(
        "Fallback control",
        tags=["node:control", "cf:fallback"],
    )
    alt_fast = issue.create("Fallback fast path")
    alt_safe = issue.create("Fallback safe path")
    alt_manual = issue.create("Fallback manual path")

    issue.add_dep(fallback["id"], "parent", alt_fast["id"])
    issue.add_dep(fallback["id"], "parent", alt_safe["id"])
    issue.add_dep(fallback["id"], "parent", alt_manual["id"])
    issue.add_dep(alt_fast["id"], "blocks", alt_safe["id"])
    issue.add_dep(alt_safe["id"], "blocks", alt_manual["id"])

    issue.set_status(alt_fast["id"], "closed", outcome="failure", outcome_provided=True)
    issue.set_status(alt_safe["id"], "closed", outcome="success", outcome_provided=True)

    reconciled = issue.reconcile_control_flow(fallback["id"])
    assert reconciled["control_flow"] == "fallback"
    assert reconciled["outcome"] == "success"
    assert reconciled["pruned_ids"] == [alt_manual["id"]]
    assert reconciled["pruned_count"] == 1

    pruned_alt = issue.show(alt_manual["id"])
    assert pruned_alt is not None
    assert pruned_alt["status"] == "duplicate"
    assert pruned_alt["outcome"] == "skipped"
    assert "reason:pruned" in pruned_alt["tags"]

    closed_control = issue.show(fallback["id"])
    assert closed_control is not None
    assert closed_control["status"] == "closed"
    assert closed_control["outcome"] == "success"


def test_issue_reconcile_subtree_walks_control_nodes(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    root = issue.create("Root issue")
    sequence = issue.create(
        "Nested sequence",
        tags=["node:control", "cf:sequence"],
    )
    first = issue.create("First nested step")
    second = issue.create("Second nested step")

    issue.add_dep(root["id"], "parent", sequence["id"])
    issue.add_dep(sequence["id"], "parent", first["id"])
    issue.add_dep(sequence["id"], "parent", second["id"])
    issue.add_dep(first["id"], "blocks", second["id"])

    issue.set_status(first["id"], "closed", outcome="failure", outcome_provided=True)
    payload = issue.reconcile_control_flow_subtree(root["id"])

    assert payload["root_id"] == root["id"]
    assert payload["reconciled_count"] == 1
    assert payload["reconciled"][0]["id"] == sequence["id"]
    assert payload["reconciled"][0]["outcome"] == "failure"
    assert payload["validation"]["termination"]["reason"] == "root_not_terminal"
    assert payload["validation"]["errors"] == []

    skipped = issue.show(second["id"])
    assert skipped is not None
    assert skipped["status"] == "duplicate"
    assert skipped["outcome"] == "skipped"


def _build_incremental_reconcile_fixture(issue: Issue) -> dict[str, str]:
    root = issue.create("Root issue")
    sequence = issue.create(
        "Sequence parent",
        tags=["node:control", "cf:sequence"],
    )
    fallback = issue.create(
        "Fallback child",
        tags=["node:control", "cf:fallback"],
    )
    step_a = issue.create("Step A")
    alt_fast = issue.create("Fast option")
    alt_safe = issue.create("Safe option")
    alt_manual = issue.create("Manual option")

    issue.add_dep(root["id"], "parent", sequence["id"])
    issue.add_dep(sequence["id"], "parent", step_a["id"])
    issue.add_dep(sequence["id"], "parent", fallback["id"])
    issue.add_dep(step_a["id"], "blocks", fallback["id"])

    issue.add_dep(fallback["id"], "parent", alt_fast["id"])
    issue.add_dep(fallback["id"], "parent", alt_safe["id"])
    issue.add_dep(fallback["id"], "parent", alt_manual["id"])
    issue.add_dep(alt_fast["id"], "blocks", alt_safe["id"])
    issue.add_dep(alt_safe["id"], "blocks", alt_manual["id"])

    issue.set_status(step_a["id"], "closed", outcome="success", outcome_provided=True)
    issue.set_status(
        alt_fast["id"],
        "closed",
        outcome="failure",
        outcome_provided=True,
    )
    issue.set_status(
        alt_safe["id"],
        "closed",
        outcome="success",
        outcome_provided=True,
    )

    return {
        "root": root["id"],
        "sequence": sequence["id"],
        "fallback": fallback["id"],
        "step_a": step_a["id"],
        "fast": alt_fast["id"],
        "safe": alt_safe["id"],
        "manual": alt_manual["id"],
    }


def test_issue_affected_control_flow_ancestors_scopes_to_root_subtree(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)
    nodes = _build_incremental_reconcile_fixture(issue)

    outside = issue.create(
        "Outside control",
        tags=["node:control", "cf:sequence"],
    )
    issue.add_dep(outside["id"], "parent", nodes["safe"])

    targets = issue.affected_control_flow_ancestors(
        nodes["safe"],
        root_id=nodes["root"],
    )

    assert [row["id"] for row in targets] == [nodes["fallback"], nodes["sequence"]]
    assert [row["depth"] for row in targets] == [1, 2]


def test_issue_incremental_reconcile_matches_full_subtree_reconcile(
    tmp_path: Path,
) -> None:
    incremental_issue = Issue.from_workdir(tmp_path / "incremental")
    full_issue = Issue.from_workdir(tmp_path / "full")

    incremental_nodes = _build_incremental_reconcile_fixture(incremental_issue)
    full_nodes = _build_incremental_reconcile_fixture(full_issue)

    incremental_payload = incremental_issue.reconcile_control_flow_ancestors(
        incremental_nodes["safe"],
        root_issue_id=incremental_nodes["root"],
    )
    full_payload = full_issue.reconcile_control_flow_subtree(full_nodes["root"])

    assert incremental_payload["target_ids"] == [
        incremental_nodes["fallback"],
        incremental_nodes["sequence"],
    ]
    assert full_payload["reconciled_count"] == 2

    for name in ("sequence", "fallback", "step_a", "fast", "safe", "manual"):
        incremental_row = incremental_issue.show(incremental_nodes[name])
        full_row = full_issue.show(full_nodes[name])
        assert incremental_row is not None
        assert full_row is not None
        assert incremental_row["status"] == full_row["status"]
        assert incremental_row["outcome"] == full_row["outcome"]

    assert (
        incremental_payload["validation"]["termination"]["reason"]
        == full_payload["validation"]["termination"]["reason"]
    )
    assert (
        incremental_payload["validation"]["termination"]["is_final"]
        == full_payload["validation"]["termination"]["is_final"]
    )
    assert incremental_payload["validation"]["errors"] == full_payload["validation"]["errors"]


def test_issue_validate_orchestration_subtree_allows_expanded_root_with_active_descendants(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)

    root = issue.create("Root")
    child = issue.create("Child")
    issue.add_dep(root["id"], "parent", child["id"])
    issue.set_status(root["id"], "closed", outcome="expanded", outcome_provided=True)

    payload = issue.validate_orchestration_subtree(root["id"])
    assert payload["root_id"] == root["id"]
    assert payload["termination"]["is_final"] is False
    assert payload["termination"]["reason"] == "expanded_non_final"
    assert payload["termination"]["has_active_descendants"] is True
    assert payload["errors"] == []
    assert payload["warnings"] == []


def test_issue_validate_orchestration_subtree_does_not_require_team_resolution(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)

    root = issue.create("Root")
    leaf = issue.create("Leaf", tags=["node:agent"])
    issue.add_dep(root["id"], "parent", leaf["id"])

    payload = issue.validate_orchestration_subtree(root["id"])
    assert payload["warnings"] == []


def test_issue_validate_orchestration_subtree_bulk_team_resolution_single_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    issue = Issue.from_workdir(tmp_path)

    root = issue.create("Root", tags=["team:platform"])
    for index in range(220):
        leaf = issue.create(f"Leaf {index:03d}", tags=["node:agent"])
        issue.add_dep(root["id"], "parent", leaf["id"])

    original_connect = issue.store._connect
    connect_calls = 0

    def counting_connect() -> sqlite3.Connection:
        nonlocal connect_calls
        connect_calls += 1
        return original_connect()

    monkeypatch.setattr(issue.store, "_connect", counting_connect)

    payload = issue.validate_orchestration_subtree(root["id"])

    assert connect_calls == 1
    assert payload["errors"] == []
    assert not any(
        warning.get("code") == "node_team_unresolvable"
        for warning in payload["warnings"]
    )


def test_issue_validate_orchestration_subtree_flags_orphaned_expanded_nodes(
    tmp_path: Path,
) -> None:
    issue = Issue.from_workdir(tmp_path)

    root = issue.create("Root")
    child = issue.create("Child")
    issue.add_dep(root["id"], "parent", child["id"])
    issue.set_status(root["id"], "closed", outcome="expanded", outcome_provided=True)
    issue.set_status(child["id"], "closed", outcome="success", outcome_provided=True)

    payload = issue.validate_orchestration_subtree(root["id"])
    assert payload["termination"]["is_final"] is False
    assert payload["termination"]["reason"] == "expanded_non_final"
    assert payload["termination"]["has_active_descendants"] is False
    assert any(
        row["id"] == root["id"] for row in payload["orphaned_expanded_nodes"]
    )
    assert any(
        err["code"] == "orphaned_expanded_node" and err["id"] == root["id"]
        for err in payload["errors"]
    )
    assert any(
        warning["code"] == "root_expanded_without_active_descendants"
        for warning in payload["warnings"]
    )


def test_issue_validate_dag_detects_parent_cycle(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    root = issue.create("Root", tags=["node:agent"])
    alpha = issue.create("Alpha", tags=["node:agent"])
    beta = issue.create("Beta", tags=["node:agent"])

    issue.add_dep(root["id"], "parent", alpha["id"])
    issue.add_dep(alpha["id"], "parent", beta["id"])
    issue.add_dep(beta["id"], "parent", alpha["id"])

    payload = issue.validate_dag(root["id"])
    assert payload["root_id"] == root["id"]
    assert payload["checks"]["parent_acyclic"] is False
    assert any(err["code"] == "parent_cycle" for err in payload["errors"])


def test_issue_validate_dag_flags_terminal_node_missing_outcome(tmp_path: Path) -> None:
    issue = Issue.from_workdir(tmp_path)

    root = issue.create("Root")
    leaf = issue.create("Leaf", tags=["node:agent"])
    issue.add_dep(root["id"], "parent", leaf["id"])
    issue.set_status(leaf["id"], "closed")

    payload = issue.validate_dag(root["id"])
    assert payload["checks"]["terminal_outcomes"] is False
    assert any(
        err["code"] == "terminal_node_missing_outcome" and err["id"] == leaf["id"]
        for err in payload["errors"]
    )


def test_issue_validate_dag_flags_blocks_edges_for_non_siblings(tmp_path: Path) -> None:
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

    payload = issue.validate_dag(root["id"])
    assert payload["checks"]["blocks_sibling_wiring"] is False
    assert any(
        err["code"] == "blocks_not_siblings"
        and err["src_id"] == left["id"]
        and err["dst_id"] == right["id"]
        for err in payload["errors"]
    )


def test_issue_store_migrates_existing_db_to_outcome_column(tmp_path: Path) -> None:
    state_dir = tmp_path / ".loopfarm"
    state_dir.mkdir(parents=True, exist_ok=True)

    db_path = state_dir / "issue.sqlite3"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE issues (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL,
                priority INTEGER NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO issues(id, title, body, status, priority, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            ("loopfarm-legacy", "Legacy issue", "", "closed", 3, 1, 1),
        )

    issue = Issue.from_workdir(tmp_path)
    row = issue.edit("loopfarm-legacy", outcome="success", outcome_provided=True)
    assert row["outcome"] == "success"


def test_main_cli_dispatch_supports_issue_and_forum_subcommands(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["issue", "new", "Track migration"])
    issues = Issue.from_workdir(tmp_path).list(limit=10)
    assert len(issues) == 1

    cli.main(["forum", "post", "loopfarm:test", "-m", "hello"])
    messages = Forum.from_workdir(tmp_path).read("loopfarm:test", limit=5)
    assert len(messages) == 1
    assert messages[0]["body"] == "hello"
