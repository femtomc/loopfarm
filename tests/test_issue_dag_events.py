from __future__ import annotations

import pytest

from loopfarm.runtime.issue_dag_events import (
    NODE_EXECUTE,
    NODE_MEMORY,
    NODE_RECONCILE,
    build_node_execute_event,
    build_node_expand_event,
    build_node_memory_event,
    build_node_plan_event,
    build_node_reconcile_event,
    build_node_result_event,
    required_fields_for_kind,
    validate_issue_dag_event,
)


def test_required_fields_for_execute_kind_are_stable() -> None:
    assert required_fields_for_kind(NODE_EXECUTE) == (
        "id",
        "team",
        "role",
        "program",
        "mode",
        "claim_timestamp",
        "claim_timestamp_iso",
    )


def test_required_fields_for_memory_kind_are_stable() -> None:
    assert required_fields_for_kind(NODE_MEMORY) == (
        "id",
        "root",
        "summary",
    )


def test_validate_issue_dag_event_reports_missing_required_fields() -> None:
    errors = validate_issue_dag_event(
        {
            "kind": NODE_RECONCILE,
            "id": "loopfarm-control",
        }
    )
    assert errors == [
        "missing root",
        "missing control_flow",
        "missing outcome",
    ]


def test_build_node_execute_event_validates_and_normalizes_payload() -> None:
    payload = build_node_execute_event(
        issue_id="loopfarm-leaf",
        team="platform",
        role="worker",
        program="issue-dag-work",
        mode="claim",
        claim_timestamp=123,
        claim_timestamp_iso="2026-02-13T00:00:00Z",
        root_id="loopfarm-root",
        tags=["node:agent", " node:agent ", "", "granularity:atomic"],
        status="in_progress",
        team_source="issue_tag",
        team_source_issue_id="loopfarm-leaf",
        team_source_tag="team:platform",
        extra={"route": "spec_execution"},
    )
    assert payload["kind"] == NODE_EXECUTE
    assert payload["id"] == "loopfarm-leaf"
    assert payload["tags"] == ["node:agent", "granularity:atomic"]
    assert payload["route"] == "spec_execution"
    assert validate_issue_dag_event(payload) == []


def test_event_builders_emit_schema_valid_payloads() -> None:
    payloads = [
        build_node_plan_event(
            issue_id="loopfarm-plan",
            root_id="loopfarm-root",
            team="platform",
            role="planner",
            program="issue-dag-planning",
            summary="expanded into control-flow sequence",
        ),
        build_node_memory_event(
            issue_id="loopfarm-memory",
            root_id="loopfarm-root",
            summary="Selected fallback branch after worker failure",
            team="platform",
            role="replanner",
            program="issue-dag-replanning",
            issue_refs=["loopfarm-a", "loopfarm-control"],
            evidence=[
                {"kind": "forum", "ref": "issue:loopfarm-a#12"},
                {"kind": "log", "ref": "run:abc123", "note": "retry budget exceeded"},
            ],
        ),
        build_node_expand_event(
            issue_id="loopfarm-expand",
            root_id="loopfarm-root",
            team="platform",
            role="worker",
            program="issue-dag-work",
            control_id="loopfarm-control",
            children=["loopfarm-a", "loopfarm-b"],
        ),
        build_node_result_event(
            issue_id="loopfarm-a",
            root_id="loopfarm-root",
            outcome="success",
        ),
        build_node_reconcile_event(
            issue_id="loopfarm-control",
            root_id="loopfarm-root",
            control_flow="fallback",
            outcome="success",
        ),
    ]
    for payload in payloads:
        assert validate_issue_dag_event(payload) == []


def test_build_node_execute_event_rejects_invalid_mode() -> None:
    with pytest.raises(ValueError) as raised:
        build_node_execute_event(
            issue_id="loopfarm-leaf",
            team="platform",
            role="worker",
            program="issue-dag-work",
            mode="invalid",
            claim_timestamp=1,
            claim_timestamp_iso="2026-02-13T00:00:00Z",
        )
    assert "mode must be one of" in str(raised.value)


def test_validate_issue_dag_event_reports_invalid_issue_refs_and_evidence() -> None:
    errors = validate_issue_dag_event(
        {
            "kind": NODE_MEMORY,
            "id": "loopfarm-memory",
            "root": "loopfarm-root",
            "summary": "memo",
            "issue_refs": "loopfarm-a",
            "evidence": [{"kind": "", "ref": "issue:loopfarm-a#1"}],
        }
    )
    assert errors == [
        "issue_refs must be a non-empty list of non-empty strings",
        "evidence must be a non-empty list of objects",
    ]


def test_build_node_memory_event_rejects_invalid_evidence_shape() -> None:
    with pytest.raises(ValueError) as raised:
        build_node_memory_event(
            issue_id="loopfarm-memory",
            root_id="loopfarm-root",
            summary="memo",
            evidence=[{"kind": "forum"}],
        )
    assert "must include non-empty kind/ref" in str(raised.value)
