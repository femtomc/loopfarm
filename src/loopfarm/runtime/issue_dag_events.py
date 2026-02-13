from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


NODE_PLAN = "node.plan"
NODE_MEMORY = "node.memory"
NODE_EXPAND = "node.expand"
NODE_EXECUTE = "node.execute"
NODE_RESULT = "node.result"
NODE_RECONCILE = "node.reconcile"

ISSUE_DAG_EVENT_KINDS = frozenset(
    {
        NODE_PLAN,
        NODE_MEMORY,
        NODE_EXPAND,
        NODE_EXECUTE,
        NODE_RESULT,
        NODE_RECONCILE,
    }
)

_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    NODE_PLAN: ("id", "root", "team", "role", "program", "summary"),
    NODE_MEMORY: ("id", "root", "summary"),
    NODE_EXPAND: ("id", "root", "team", "role", "program", "control", "children"),
    NODE_EXECUTE: (
        "id",
        "team",
        "role",
        "program",
        "mode",
        "claim_timestamp",
        "claim_timestamp_iso",
    ),
    NODE_RESULT: ("id", "root", "outcome"),
    NODE_RECONCILE: ("id", "root", "control_flow", "outcome"),
}

_EXECUTION_MODES = {"claim", "resume"}
_ISSUE_REFS_FIELD = "issue_refs"
_EVIDENCE_FIELD = "evidence"


def required_fields_for_kind(kind: str) -> tuple[str, ...]:
    normalized = _as_text(kind)
    if normalized is None:
        raise ValueError("event kind cannot be empty")
    fields = _REQUIRED_FIELDS.get(normalized)
    if fields is None:
        raise ValueError(f"unknown issue-dag event kind {normalized!r}")
    return fields


def validate_issue_dag_event(payload: Mapping[str, Any]) -> list[str]:
    kind = _as_text(payload.get("kind"))
    if kind is None:
        return ["missing kind"]
    if kind not in ISSUE_DAG_EVENT_KINDS:
        return [f"unknown kind {kind!r}"]

    errors: list[str] = []
    for field in _REQUIRED_FIELDS[kind]:
        if field not in payload:
            errors.append(f"missing {field}")
            continue

        value = payload.get(field)
        if field == "children":
            if not _normalize_children(value):
                errors.append("children must be a non-empty list of non-empty strings")
            continue

        if field == "claim_timestamp":
            if not isinstance(value, int):
                errors.append("claim_timestamp must be an integer")
            continue

        text = _as_text(value)
        if text is None:
            errors.append(f"{field} must be a non-empty string")
            continue

        if field == "mode" and text not in _EXECUTION_MODES:
            errors.append(f"mode must be one of {sorted(_EXECUTION_MODES)!r}")

    _validate_optional_issue_refs(payload, errors)
    _validate_optional_evidence(payload, errors)

    return errors


def ensure_issue_dag_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    event = dict(payload)
    errors = validate_issue_dag_event(event)
    if errors:
        joined = "; ".join(errors)
        raise ValueError(f"invalid issue-dag event: {joined}")
    return event


def build_node_plan_event(
    *,
    issue_id: str,
    root_id: str,
    team: str,
    role: str,
    program: str,
    summary: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "kind": NODE_PLAN,
        "id": _require_text(issue_id, "issue_id"),
        "root": _require_text(root_id, "root_id"),
        "team": _require_text(team, "team"),
        "role": _require_text(role, "role"),
        "program": _require_text(program, "program"),
        "summary": _require_text(summary, "summary"),
    }
    _merge_extra(payload, extra)
    return ensure_issue_dag_event(payload)


def build_node_memory_event(
    *,
    issue_id: str,
    root_id: str,
    summary: str,
    team: str | None = None,
    role: str | None = None,
    program: str | None = None,
    issue_refs: Iterable[str] | None = None,
    evidence: Iterable[Mapping[str, Any]] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": NODE_MEMORY,
        "id": _require_text(issue_id, "issue_id"),
        "root": _require_text(root_id, "root_id"),
        "summary": _require_text(summary, "summary"),
    }

    team_text = _as_text(team)
    if team_text:
        payload["team"] = team_text

    role_text = _as_text(role)
    if role_text:
        payload["role"] = role_text

    program_text = _as_text(program)
    if program_text:
        payload["program"] = program_text

    normalized_refs = _normalize_children(issue_refs)
    if issue_refs is not None and not normalized_refs:
        raise ValueError("issue_refs must contain at least one issue id")
    if normalized_refs:
        payload[_ISSUE_REFS_FIELD] = normalized_refs

    normalized_evidence = _normalize_evidence(evidence, strict=True)
    if evidence is not None and not normalized_evidence:
        raise ValueError("evidence must contain at least one entry")
    if normalized_evidence:
        payload[_EVIDENCE_FIELD] = normalized_evidence

    _merge_extra(payload, extra)
    return ensure_issue_dag_event(payload)


def build_node_expand_event(
    *,
    issue_id: str,
    root_id: str,
    team: str,
    role: str,
    program: str,
    control_id: str,
    children: Iterable[str],
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_children = _normalize_children(children)
    if not normalized_children:
        raise ValueError("children must contain at least one issue id")

    payload = {
        "kind": NODE_EXPAND,
        "id": _require_text(issue_id, "issue_id"),
        "root": _require_text(root_id, "root_id"),
        "team": _require_text(team, "team"),
        "role": _require_text(role, "role"),
        "program": _require_text(program, "program"),
        "control": _require_text(control_id, "control_id"),
        "children": normalized_children,
    }
    _merge_extra(payload, extra)
    return ensure_issue_dag_event(payload)


def build_node_execute_event(
    *,
    issue_id: str,
    team: str,
    role: str,
    program: str,
    mode: str,
    claim_timestamp: int,
    claim_timestamp_iso: str,
    root_id: str | None = None,
    tags: Iterable[str] | None = None,
    status: str | None = None,
    team_source: str | None = None,
    team_source_issue_id: str | None = None,
    team_source_tag: str | None = None,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "kind": NODE_EXECUTE,
        "id": _require_text(issue_id, "issue_id"),
        "team": _require_text(team, "team"),
        "role": _require_text(role, "role"),
        "program": _require_text(program, "program"),
        "mode": _require_text(mode, "mode"),
        "claim_timestamp": int(claim_timestamp),
        "claim_timestamp_iso": _require_text(claim_timestamp_iso, "claim_timestamp_iso"),
    }

    root_text = _as_text(root_id)
    if root_text:
        payload["root"] = root_text

    normalized_tags = _normalize_children(tags)
    if normalized_tags:
        payload["tags"] = normalized_tags

    status_text = _as_text(status)
    if status_text:
        payload["status"] = status_text

    source_text = _as_text(team_source)
    if source_text:
        payload["team_source"] = source_text

    source_issue = _as_text(team_source_issue_id)
    if source_issue:
        payload["team_source_issue_id"] = source_issue

    source_tag = _as_text(team_source_tag)
    if source_tag:
        payload["team_source_tag"] = source_tag

    _merge_extra(payload, extra)
    return ensure_issue_dag_event(payload)


def build_node_result_event(
    *,
    issue_id: str,
    root_id: str,
    outcome: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "kind": NODE_RESULT,
        "id": _require_text(issue_id, "issue_id"),
        "root": _require_text(root_id, "root_id"),
        "outcome": _require_text(outcome, "outcome"),
    }
    _merge_extra(payload, extra)
    return ensure_issue_dag_event(payload)


def build_node_reconcile_event(
    *,
    issue_id: str,
    root_id: str,
    control_flow: str,
    outcome: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "kind": NODE_RECONCILE,
        "id": _require_text(issue_id, "issue_id"),
        "root": _require_text(root_id, "root_id"),
        "control_flow": _require_text(control_flow, "control_flow"),
        "outcome": _require_text(outcome, "outcome"),
    }
    _merge_extra(payload, extra)
    return ensure_issue_dag_event(payload)


def _merge_extra(payload: dict[str, Any], extra: Mapping[str, Any] | None) -> None:
    if not extra:
        return
    for key, value in extra.items():
        if not isinstance(key, str):
            continue
        normalized = key.strip()
        if not normalized or normalized in payload:
            continue
        payload[normalized] = value


def _as_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    return text


def _require_text(value: object, field: str) -> str:
    text = _as_text(value)
    if text is None:
        raise ValueError(f"{field} is required")
    return text


def _normalize_children(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        normalized = _as_text(value)
        return [normalized] if normalized else []
    if not isinstance(value, Iterable):
        return []

    result: list[str] = []
    seen: set[str] = set()
    for entry in value:
        text = _as_text(entry)
        if text is None or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _validate_optional_issue_refs(
    payload: Mapping[str, Any],
    errors: list[str],
) -> None:
    if _ISSUE_REFS_FIELD not in payload:
        return
    value = payload.get(_ISSUE_REFS_FIELD)
    if (
        isinstance(value, str)
        or isinstance(value, Mapping)
        or not isinstance(value, Iterable)
    ):
        errors.append(
            "issue_refs must be a non-empty list of non-empty strings"
        )
        return

    normalized = _normalize_children(value)
    if not normalized:
        errors.append(
            "issue_refs must be a non-empty list of non-empty strings"
        )


def _validate_optional_evidence(
    payload: Mapping[str, Any],
    errors: list[str],
) -> None:
    if _EVIDENCE_FIELD not in payload:
        return
    value = payload.get(_EVIDENCE_FIELD)
    if (
        isinstance(value, str)
        or isinstance(value, Mapping)
        or not isinstance(value, Iterable)
    ):
        errors.append("evidence must be a non-empty list of objects")
        return

    normalized = _normalize_evidence(value)
    if not normalized:
        errors.append("evidence must be a non-empty list of objects")
        return

    if isinstance(value, list) and len(normalized) != len(value):
        errors.append("each evidence entry must include non-empty kind/ref")


def _normalize_evidence(
    value: object,
    *,
    strict: bool = False,
) -> list[dict[str, str]]:
    if value is None:
        return []
    if isinstance(value, str) or isinstance(value, Mapping):
        if strict:
            raise ValueError("evidence must be a list of objects")
        return []
    if not isinstance(value, Iterable):
        if strict:
            raise ValueError("evidence must be a list of objects")
        return []

    result: list[dict[str, str]] = []
    for index, entry in enumerate(value):
        if not isinstance(entry, Mapping):
            if strict:
                raise ValueError(
                    f"evidence[{index}] must be an object with kind/ref keys"
                )
            continue
        kind = _as_text(entry.get("kind"))
        ref = _as_text(entry.get("ref"))
        if kind is None or ref is None:
            if strict:
                raise ValueError(
                    f"evidence[{index}] must include non-empty kind/ref"
                )
            continue

        normalized: dict[str, str] = {
            "kind": kind,
            "ref": ref,
        }
        note = _as_text(entry.get("note"))
        if note is not None:
            normalized["note"] = note
        result.append(normalized)
    return result
