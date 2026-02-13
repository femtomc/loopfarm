from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .forum import Forum
from .runtime.issue_dag_execution import (
    DEFAULT_RUN_TOPIC,
    NodeExecutionRunResult,
    NodeExecutionSelection,
)
from .runtime.issue_dag_orchestrator import (
    DEFAULT_EXECUTION_TAGS,
    IssueDagOrchestrationRun,
    IssueDagOrchestrator,
)
from .runtime.issue_dag_runner import (
    IssueDagRun,
    IssueDagRunner,
)
from .stores.issue import ISSUE_OUTCOMES, ISSUE_STATUSES, RELATION_TYPES, IssueStore
from .ui import (
    add_output_mode_argument,
    make_console,
    render_panel,
    render_help,
    render_table,
    resolve_output_mode,
)

_RELATION_CHOICES = tuple(RELATION_TYPES) + ("blocked_by", "child")
_ISSUE_HEADERS = ("ID", "STATUS", "OUTCOME", "PR", "UPDATED", "TITLE", "TAGS")
_DEPENDENCY_HEADERS = ("SOURCE", "TYPE", "TARGET", "DIR", "ACTIVE", "CREATED")


@dataclass
class Issue:
    store: IssueStore

    @classmethod
    def from_workdir(
        cls,
        cwd: Path | None = None,
        *,
        create: bool = True,
        state_dir: Path | str | None = None,
    ) -> "Issue":
        return cls(IssueStore.from_workdir(cwd, create=create, state_dir=state_dir))

    def list(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.store.list(status=status, search=search, tag=tag, limit=limit)

    def ready(
        self,
        *,
        limit: int = 20,
        root: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return self.store.ready(limit=limit, root_id=root, tags=tags)

    def resumable(
        self,
        *,
        limit: int = 20,
        root: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return self.store.resumable(limit=limit, root_id=root, tags=tags)

    def claim_ready_leaf(
        self,
        issue_id: str,
        *,
        root: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.store.claim_ready_leaf(issue_id, root_id=root, tags=tags)

    def evaluate_control_flow(self, issue_id: str) -> dict[str, Any] | None:
        return self.store.evaluate_control_flow(issue_id)

    def evaluatable_control_flow_nodes(
        self, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        return self.store.evaluatable_control_flow_nodes(limit=limit)

    def reconcile_control_flow(self, issue_id: str) -> dict[str, Any]:
        return self.store.reconcile_control_flow(issue_id)

    def reconcile_control_flow_subtree(self, root_issue_id: str) -> dict[str, Any]:
        return self.store.reconcile_control_flow_subtree(root_issue_id)

    def affected_control_flow_ancestors(
        self,
        issue_id: str,
        *,
        root_id: str | None = None,
    ) -> list[dict[str, Any]]:
        return self.store.affected_control_flow_ancestors(
            issue_id,
            root_id=root_id,
        )

    def reconcile_control_flow_ancestors(
        self,
        issue_id: str,
        *,
        root_issue_id: str,
    ) -> dict[str, Any]:
        return self.store.reconcile_control_flow_ancestors(
            issue_id,
            root_issue_id=root_issue_id,
        )

    def validate_orchestration_subtree(self, root_issue_id: str) -> dict[str, Any]:
        return self.store.validate_orchestration_subtree(root_issue_id)

    def validate_dag(self, root_issue_id: str) -> dict[str, Any]:
        return self.store.validate_dag(root_issue_id)

    def resolve_team(
        self,
        issue_id: str,
        *,
        default_team: str | None = None,
    ) -> dict[str, Any]:
        return self.store.resolve_team(issue_id, default_team=default_team)

    def show(self, issue_id: str) -> dict[str, Any] | None:
        row = self.store.get(issue_id)
        if row is None:
            return None

        issue_key = str(row.get("id") or issue_id).strip()
        payload = dict(row)
        payload["comments"] = self.store.list_comments(issue_key, limit=100)
        payload["dependencies"] = self.store.dependencies(issue_key)
        return payload

    def comments(self, issue_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
        return self.store.list_comments(issue_id, limit=limit)

    def create(
        self,
        title: str,
        *,
        body: str = "",
        status: str = "open",
        priority: int = 3,
        tags: list[str] | None = None,
        execution_spec: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.store.create(
            title,
            body=body,
            status=status,
            priority=priority,
            tags=tags,
            execution_spec=execution_spec,
        )

    def set_status(
        self,
        issue_id: str,
        status: str,
        *,
        outcome: str | None = None,
        outcome_provided: bool = False,
    ) -> dict[str, Any]:
        return self.store.set_status(
            issue_id,
            status,
            outcome=outcome,
            outcome_provided=outcome_provided,
        )

    def set_priority(self, issue_id: str, priority: int) -> dict[str, Any]:
        return self.store.set_priority(issue_id, priority)

    def edit(
        self,
        issue_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        status: str | None = None,
        priority: int | None = None,
        outcome: str | None = None,
        outcome_provided: bool = False,
        execution_spec: dict[str, Any] | None = None,
        execution_spec_provided: bool = False,
    ) -> dict[str, Any]:
        return self.store.update(
            issue_id,
            title=title,
            body=body,
            status=status,
            priority=priority,
            outcome=outcome,
            outcome_provided=outcome_provided,
            execution_spec=execution_spec,
            execution_spec_provided=execution_spec_provided,
        )

    def delete(self, issue_id: str) -> dict[str, Any]:
        return self.store.delete(issue_id)

    def add_comment(
        self,
        issue_id: str,
        message: str,
        *,
        author: str | None = None,
    ) -> dict[str, Any]:
        return self.store.add_comment(issue_id, message, author=author)

    def deps(self, issue_id: str) -> list[dict[str, Any]]:
        return self.store.dependencies(issue_id)

    def add_dep(self, src_id: str, rel_type: str, dst_id: str) -> dict[str, Any]:
        return self.store.add_dependency(src_id, rel_type, dst_id)

    def add_tag(self, issue_id: str, tag: str) -> dict[str, Any]:
        return self.store.add_tag(issue_id, tag)

    def remove_tag(self, issue_id: str, tag: str) -> dict[str, Any]:
        return self.store.remove_tag(issue_id, tag)

    def get_execution_spec(self, issue_id: str) -> dict[str, Any] | None:
        row = self.store.get(issue_id)
        if row is None:
            raise ValueError(f"issue not found: {issue_id}")
        spec = row.get("execution_spec")
        if isinstance(spec, dict):
            return dict(spec)
        return None

    def set_execution_spec(
        self, issue_id: str, execution_spec: dict[str, Any]
    ) -> dict[str, Any]:
        return self.store.set_execution_spec(issue_id, execution_spec)

    def clear_execution_spec(self, issue_id: str) -> dict[str, Any]:
        return self.store.clear_execution_spec(issue_id)


def _to_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _iso_from_epoch_ms(value: object) -> str | None:
    ms = _to_int(value)
    if ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _with_iso_timestamps(payload: Any) -> Any:
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            out[key] = _with_iso_timestamps(value)
            if key.endswith("_at"):
                iso = _iso_from_epoch_ms(value)
                if iso:
                    out[f"{key}_iso"] = iso
        return out
    if isinstance(payload, list):
        return [_with_iso_timestamps(item) for item in payload]
    return payload


def _emit_json(payload: Any) -> None:
    print(json.dumps(_with_iso_timestamps(payload), ensure_ascii=False, indent=2))


def _format_time(value: object) -> str:
    return _iso_from_epoch_ms(value) or "-"


def _truncate(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _issue_columns(issue: dict[str, Any]) -> tuple[str, str, str, str, str, str, str]:
    return (
        str(issue.get("id") or ""),
        str(issue.get("status") or ""),
        str(issue.get("outcome") or "-"),
        f"P{issue.get('priority')}",
        _format_time(issue.get("updated_at")),
        _truncate(issue.get("title"), 56),
        _truncate(",".join(str(t) for t in issue.get("tags") or []), 28),
    )


def _print_issue(issue: dict[str, Any]) -> None:
    row = _issue_columns(issue)
    print(
        f"{row[0]}  {row[1]:<11}  {row[2]:<8}  {row[3]:<3}  "
        f"{row[4]}  {row[5]}  {row[6]}"
    )


def _print_issue_table(rows: list[dict[str, Any]]) -> None:
    values = [_issue_columns(row) for row in rows]

    widths = [len(item) for item in _ISSUE_HEADERS]
    for row in values:
        for idx, col in enumerate(row):
            widths[idx] = max(widths[idx], len(col))

    print(
        "  ".join(
            _ISSUE_HEADERS[idx].ljust(widths[idx]) for idx in range(len(_ISSUE_HEADERS))
        )
    )
    print("  ".join("-" * widths[idx] for idx in range(len(_ISSUE_HEADERS))))
    for row in values:
        print(
            "  ".join(row[idx].ljust(widths[idx]) for idx in range(len(_ISSUE_HEADERS)))
        )


def _print_issue_table_rich(rows: list[dict[str, Any]], *, title: str) -> None:
    console = make_console("rich")
    render_table(
        console,
        title=title,
        headers=_ISSUE_HEADERS,
        no_wrap_columns=(0, 1, 3),
        rows=[_issue_columns(row) for row in rows],
    )


def _selection_payload(selection: NodeExecutionSelection) -> dict[str, Any]:
    issue_payload = {
        "id": str(selection.issue.get("id") or selection.issue_id),
        "title": str(selection.issue.get("title") or ""),
        "status": str(selection.issue.get("status") or ""),
        "outcome": (
            str(selection.issue.get("outcome"))
            if selection.issue.get("outcome") is not None
            else None
        ),
        "priority": _to_int(selection.issue.get("priority")),
        "created_at": _to_int(selection.issue.get("created_at")),
        "updated_at": _to_int(selection.issue.get("updated_at")),
        "tags": [str(tag) for tag in selection.issue.get("tags") or []],
        "execution_spec": (
            selection.metadata.get("execution_spec")
            if selection.metadata.get("execution_spec") is not None
            else selection.issue.get("execution_spec")
        ),
    }
    return {
        "id": selection.issue_id,
        "team": selection.team,
        "role": selection.role,
        "program": selection.program,
        "mode": selection.mode,
        "claim_timestamp": selection.claim_timestamp,
        "claim_timestamp_iso": _iso_from_epoch_ms(selection.claim_timestamp),
        "metadata": dict(selection.metadata),
        "issue": issue_payload,
    }


def _orchestration_run_payload(run: IssueDagOrchestrationRun) -> dict[str, Any]:
    selection = next(
        (item.selection for item in reversed(run.passes) if item.selection is not None),
        None,
    )
    selections = [item for item in run.passes if item.selection is not None]
    return {
        "root_id": run.root_id,
        "resume_mode": run.resume_mode,
        "required_tags": list(run.required_tags),
        "max_passes": run.max_passes,
        "pass_count": len(run.passes),
        "executed_count": len(selections),
        "stop_reason": run.stop_reason,
        "selection": _selection_payload(selection) if selection is not None else None,
        "passes": [
            {
                "index": item.index,
                "selection": (
                    _selection_payload(item.selection)
                    if item.selection is not None
                    else None
                ),
                "termination_before": dict(item.termination_before),
                "termination_after": dict(item.termination_after),
            }
            for item in run.passes
        ],
        "termination": dict(run.termination),
        "validation": dict(run.validation),
    }


def _execution_result_payload(result: NodeExecutionRunResult) -> dict[str, Any]:
    return {
        "issue_id": result.issue_id,
        "root_id": result.root_id,
        "team": result.team,
        "role": result.role,
        "program": result.program,
        "mode": result.mode,
        "session_id": result.session_id,
        "started_at": result.started_at,
        "started_at_iso": result.started_at_iso,
        "ended_at": result.ended_at,
        "ended_at_iso": result.ended_at_iso,
        "exit_code": result.exit_code,
        "status": result.status,
        "outcome": result.outcome,
        "postconditions_met": result.postconditions_met,
        "success": result.success,
        "error": result.error,
    }


def _dag_run_payload(run: IssueDagRun) -> dict[str, Any]:
    return {
        "root_id": run.root_id,
        "resume_mode": run.resume_mode,
        "required_tags": list(run.required_tags),
        "max_steps": run.max_steps,
        "step_count": len(run.steps),
        "executed_count": len(run.steps),
        "stop_reason": run.stop_reason,
        "error": run.error,
        "steps": [
            {
                "index": item.index,
                "selection": _selection_payload(item.selection),
                "execution": _execution_result_payload(item.execution),
                "maintenance": dict(item.maintenance),
                "termination_before": dict(item.termination_before),
                "termination_after": dict(item.termination_after),
            }
            for item in run.steps
        ],
        "termination": dict(run.termination),
        "validation": dict(run.validation),
    }


def _print_orchestration_selection(selection: NodeExecutionSelection) -> None:
    claim_iso = _iso_from_epoch_ms(selection.claim_timestamp) or "-"
    issue_title = str(selection.issue.get("title") or "").strip()
    tags = ", ".join(str(tag) for tag in selection.issue.get("tags") or [])
    print(
        f"{selection.issue_id}  team={selection.team}  role={selection.role}  "
        f"program={selection.program}  mode={selection.mode}  claim={claim_iso}"
    )
    if issue_title:
        print(f"title: {issue_title}")
    if tags:
        print(f"tags: {tags}")


def _print_orchestration_selection_rich(selection: NodeExecutionSelection) -> None:
    payload = _selection_payload(selection)
    issue_payload = payload["issue"]
    console = make_console("rich")
    render_panel(
        console,
        "\n".join(
            [
                f"id: {payload['id']}",
                f"team: {payload['team']}",
                f"role: {payload['role']}",
                f"program: {payload['program']}",
                f"mode: {payload['mode']}",
                f"claim_timestamp: {payload['claim_timestamp_iso'] or '-'}",
            ]
        ),
        title="Orchestration Selection",
    )
    render_panel(
        console,
        "\n".join(
            [
                f"title: {issue_payload.get('title') or '-'}",
                f"status: {issue_payload.get('status') or '-'}",
                f"outcome: {issue_payload.get('outcome') or '-'}",
                "tags: "
                + (
                    ", ".join(str(tag) for tag in issue_payload.get("tags") or [])
                    or "-"
                ),
            ]
        ),
        title="Selected Issue",
    )


def _print_dag_run(payload: dict[str, Any]) -> None:
    print(
        "root="
        f"{payload.get('root_id') or '-'} "
        "steps="
        f"{int(payload.get('step_count') or 0)} "
        "stop_reason="
        f"{payload.get('stop_reason') or '-'}"
    )
    if payload.get("error"):
        print(f"error: {payload.get('error')}")
    for step in payload.get("steps") or []:
        selection = step.get("selection") or {}
        execution = step.get("execution") or {}
        maintenance = step.get("maintenance") or {}
        print(
            f"step {step.get('index')}: "
            f"{selection.get('id') or '-'} "
            f"{selection.get('role') or '-'} "
            f"program={selection.get('program') or '-'} "
            f"session={execution.get('session_id') or '-'} "
            f"success={bool(execution.get('success'))} "
            f"maintenance={maintenance.get('mode') or '-'}"
        )
    termination = payload.get("termination") or {}
    if termination:
        print(
            "root_final="
            f"{bool(termination.get('is_final'))} "
            f"reason={termination.get('reason') or '-'}"
        )


def _print_dag_run_rich(payload: dict[str, Any]) -> None:
    summary_lines = [
        f"root: {payload.get('root_id') or '-'}",
        f"steps: {int(payload.get('step_count') or 0)}",
        f"stop_reason: {payload.get('stop_reason') or '-'}",
    ]
    error = str(payload.get("error") or "").strip()
    if error:
        summary_lines.append(f"error: {error}")
    termination = payload.get("termination") or {}
    if termination:
        summary_lines.append(f"root_final: {bool(termination.get('is_final'))}")
        summary_lines.append(f"root_reason: {termination.get('reason') or '-'}")

    console = make_console("rich")
    render_panel(console, "\n".join(summary_lines), title="DAG Run")
    steps = payload.get("steps") or []
    if not steps:
        render_panel(console, "(no steps)", title="Execution Steps")
        return

    render_table(
        console,
        title="Execution Steps",
        headers=(
            "STEP",
            "ISSUE",
            "ROLE",
            "PROGRAM",
            "SESSION",
            "SUCCESS",
            "MAINT",
        ),
        no_wrap_columns=(0, 1, 2, 4, 5, 6),
        rows=[
            (
                str(step.get("index") or ""),
                str((step.get("selection") or {}).get("id") or ""),
                str((step.get("selection") or {}).get("role") or ""),
                str((step.get("selection") or {}).get("program") or ""),
                str((step.get("execution") or {}).get("session_id") or ""),
                (
                    "yes"
                    if bool((step.get("execution") or {}).get("success"))
                    else "no"
                ),
                str((step.get("maintenance") or {}).get("mode") or ""),
            )
            for step in steps
        ],
    )


def _print_issue_details(issue: dict[str, Any]) -> None:
    _print_issue(issue)
    print(f"created: {_format_time(issue.get('created_at'))}")
    print(f"updated: {_format_time(issue.get('updated_at'))}")
    print(f"outcome: {issue.get('outcome') or '-'}")
    print(
        "execution_spec: "
        + ("set" if isinstance(issue.get("execution_spec"), dict) else "-")
    )

    body = str(issue.get("body") or "").strip()
    if body:
        print()
        print(body)

    deps = issue.get("dependencies") or []
    print()
    print("dependencies:")
    if not deps:
        print("  (none)")
    else:
        for dep in deps:
            direction = str(dep.get("direction") or "?")
            active = "active" if dep.get("active") else "inactive"
            created = _format_time(dep.get("created_at"))
            print(
                f"  {dep.get('src_id')} {dep.get('type')} {dep.get('dst_id')} "
                f"({direction}, {active}, created={created})"
            )

    comments = issue.get("comments") or []
    print()
    print("comments:")
    if not comments:
        print("  (none)")
    else:
        for comment in comments:
            comment_id = comment.get("id")
            author = comment.get("author") or "unknown"
            created = _format_time(comment.get("created_at"))
            print(f"  [{comment_id}] {author} @ {created}")
            print(f"  {comment.get('body')}")


def _dependency_columns(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    active = "active" if row.get("active") else "inactive"
    return (
        str(row.get("src_id") or ""),
        str(row.get("type") or ""),
        str(row.get("dst_id") or ""),
        str(row.get("direction") or "?"),
        active,
        _format_time(row.get("created_at")),
    )


def _print_dependencies_rich(
    rows: list[dict[str, Any]],
    *,
    title: str,
    no_rows_message: str,
) -> None:
    console = make_console("rich")
    if not rows:
        render_panel(console, no_rows_message, title=title)
        return
    render_table(
        console,
        title=title,
        headers=_DEPENDENCY_HEADERS,
        no_wrap_columns=(0, 1, 2, 3, 4, 5),
        rows=[_dependency_columns(row) for row in rows],
    )


def _finding_sort_key(finding: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        str(finding.get("code") or ""),
        str(finding.get("id") or ""),
        str(finding.get("src_id") or ""),
        str(finding.get("dst_id") or ""),
        str(finding.get("message") or ""),
    )


def _finding_line(level: str, finding: dict[str, Any]) -> str:
    parts = [level, str(finding.get("code") or "-")]
    issue_id = str(finding.get("id") or "").strip()
    if issue_id:
        parts.append(f"id={issue_id}")
    src_id = str(finding.get("src_id") or "").strip()
    if src_id:
        parts.append(f"src={src_id}")
    dst_id = str(finding.get("dst_id") or "").strip()
    if dst_id:
        parts.append(f"dst={dst_id}")
    cycle = finding.get("cycle")
    if isinstance(cycle, list) and cycle:
        parts.append(f"cycle={' -> '.join(str(item) for item in cycle)}")
    message = str(finding.get("message") or "").strip()
    if message:
        parts.append(message)
    return " ".join(parts)


def _print_dag_validation(payload: dict[str, Any]) -> None:
    root_id = str(payload.get("root_id") or "-")
    node_count = int(payload.get("node_count") or 0)
    edges = payload.get("edges") or {}
    checks = payload.get("checks") or {}
    errors = sorted(list(payload.get("errors") or []), key=_finding_sort_key)
    warnings = sorted(list(payload.get("warnings") or []), key=_finding_sort_key)

    print(f"root: {root_id}")
    print(
        "nodes: "
        f"{node_count} parent_edges={int(edges.get('parent') or 0)} "
        f"blocks_edges={int(edges.get('blocks') or 0)}"
    )
    print("checks:")
    for key in sorted(checks):
        status = "ok" if bool(checks.get(key)) else "fail"
        print(f"  {key}: {status}")

    print(f"errors: {len(errors)}")
    for finding in errors:
        print(_finding_line("ERROR", finding))

    print(f"warnings: {len(warnings)}")
    for finding in warnings:
        print(_finding_line("WARN", finding))


def _print_dag_validation_rich(payload: dict[str, Any]) -> None:
    root_id = str(payload.get("root_id") or "-")
    node_count = int(payload.get("node_count") or 0)
    edges = payload.get("edges") or {}
    checks = payload.get("checks") or {}
    errors = sorted(list(payload.get("errors") or []), key=_finding_sort_key)
    warnings = sorted(list(payload.get("warnings") or []), key=_finding_sort_key)
    console = make_console("rich")

    summary = "\n".join(
        [
            f"root: {root_id}",
            (
                "nodes: "
                f"{node_count} parent_edges={int(edges.get('parent') or 0)} "
                f"blocks_edges={int(edges.get('blocks') or 0)}"
            ),
            "checks:",
            *[
                f"  {key}: {'ok' if bool(checks.get(key)) else 'fail'}"
                for key in sorted(checks)
            ],
        ]
    )
    render_panel(console, summary, title="DAG Validation")

    if errors:
        render_panel(
            console,
            "\n".join(_finding_line("ERROR", finding) for finding in errors),
            title=f"Errors ({len(errors)})",
        )
    else:
        render_panel(console, "(none)", title="Errors")

    if warnings:
        render_panel(
            console,
            "\n".join(_finding_line("WARN", finding) for finding in warnings),
            title=f"Warnings ({len(warnings)})",
        )
    else:
        render_panel(console, "(none)", title="Warnings")


def _print_comments_rich(
    rows: list[dict[str, Any]], *, title: str = "Comments"
) -> None:
    console = make_console("rich")
    if not rows:
        render_panel(console, "(no comments)", title=title)
        return
    for row in rows:
        comment_id = row.get("id")
        author = row.get("author") or "unknown"
        created = _format_time(row.get("created_at"))
        body = str(row.get("body") or "").rstrip() or "(empty)"
        render_panel(console, body, title=f"[{comment_id}] {author} @ {created}")


def _print_issue_details_rich(issue: dict[str, Any]) -> None:
    issue_id = str(issue.get("id") or "")
    priority = issue.get("priority")
    priority_label = f"P{priority}" if priority is not None else "-"
    tags = ", ".join(str(tag) for tag in issue.get("tags") or []) or "-"
    summary = "\n".join(
        [
            f"status: {issue.get('status') or '-'}",
            f"outcome: {issue.get('outcome') or '-'}",
            f"priority: {priority_label}",
            f"created: {_format_time(issue.get('created_at'))}",
            f"updated: {_format_time(issue.get('updated_at'))}",
            f"tags: {tags}",
            (
                "execution_spec: set"
                if isinstance(issue.get("execution_spec"), dict)
                else "execution_spec: -"
            ),
        ]
    )

    console = make_console("rich")
    render_panel(console, summary, title=f"Issue {issue_id}")

    body = str(issue.get("body") or "").strip()
    render_panel(console, body or "(no description)", title="Description")

    dependencies = issue.get("dependencies") or []
    if dependencies:
        render_table(
            console,
            title="Dependencies",
            headers=_DEPENDENCY_HEADERS,
            no_wrap_columns=(0, 1, 2, 3, 4, 5),
            rows=[_dependency_columns(dep) for dep in dependencies],
        )
    else:
        render_panel(console, "(none)", title="Dependencies")

    comments = issue.get("comments") or []
    if comments:
        for comment in comments:
            comment_id = comment.get("id")
            author = comment.get("author") or "unknown"
            created = _format_time(comment.get("created_at"))
            body_text = str(comment.get("body") or "").rstrip() or "(empty)"
            render_panel(
                console,
                body_text,
                title=f"Comment [{comment_id}] {author} @ {created}",
            )
    else:
        render_panel(console, "(none)", title="Comments")


def _print_comments(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        comment_id = row.get("id")
        author = row.get("author") or "unknown"
        created = _format_time(row.get("created_at"))
        print(f"[{comment_id}] {author} @ {created}")
        print(str(row.get("body") or ""))
        print()


def _print_help(*, output_mode: str) -> None:
    render_help(
        output_mode="rich" if output_mode == "rich" else "plain",
        command="loopfarm issue",
        summary="issue tracker + deterministic issue-DAG orchestration",
        usage=("loopfarm issue <command> [ARGS]",),
        sections=(
            (
                "Primary Workflow",
                (
                    (
                        "run orchestration",
                        "loopfarm issue orchestrate-run --root <id> [--max-steps N] [--json]",
                    ),
                    (
                        "inspect next work",
                        "loopfarm issue ready [--root <id>] [--tag <tag> ...]",
                    ),
                    ("inspect one node", "loopfarm issue show <id> [--json]"),
                    (
                        "edit DAG edges",
                        "loopfarm issue dep add <src> <type> <dst>",
                    ),
                    (
                        "edit metadata tags",
                        "loopfarm issue tag add/remove <id> <tag>",
                    ),
                    (
                        "set execution spec",
                        "loopfarm issue spec set <id> --file <path>.json",
                    ),
                ),
            ),
            (
                "Commands",
                (
                    ("list", "list issues with status/search/tag filters (stable)"),
                    ("ready", "show ready-to-work leaf issues (stable)"),
                    ("show <id>", "show issue details, dependencies, comments (stable)"),
                    ("comments <id>", "list comments for one issue (stable)"),
                    ("new <title>", "create issue with optional body/tags (stable)"),
                    (
                        "status <id> <value>",
                        "set issue status (+ optional outcome) (stable)",
                    ),
                    ('comment <id> -m "..."', "add a comment (stable)"),
                    ("close <id...>", "set one or more issues to closed (stable)"),
                    ("reopen <id...>", "set one or more issues to open (stable)"),
                    ("deps <id>", "show dependency relations around an issue (stable)"),
                    ("dep add <src> <type> <dst>", "create dependency relation (stable)"),
                    ("tag add/remove <id> <tag>", "manage issue tags (stable)"),
                    (
                        "spec show|set|clear <id>",
                        "manage issue execution specs (stable)",
                    ),
                    (
                        "orchestrate-run --root <id>",
                        "deterministic select→execute→maintain loop (stable)",
                    ),
                    (
                        "orchestrate --root <id> (internal)",
                        "selection-only: claim + emit node.execute events",
                    ),
                    (
                        "reconcile <id> [--root] (internal)",
                        "control-flow maintenance for cf:* nodes",
                    ),
                    (
                        "validate-dag --root <id> (internal)",
                        "validate parent/blocks/outcome invariants",
                    ),
                    ("priority <id> <1-5>", "set issue priority"),
                    ("edit <id> [flags]", "update title/body/status/priority/outcome"),
                    ("delete <id...> --yes (internal)", "delete issue(s)"),
                ),
            ),
            (
                "Options",
                (
                    ("--json", "emit machine-stable JSON payloads"),
                    (
                        "--output MODE",
                        "auto|plain|rich for read commands",
                    ),
                    ("--state-dir PATH", "explicit .loopfarm state directory"),
                    (
                        "orchestrate-run tuning",
                        "--control-poll-seconds/--forward-report-max-* / --max-output-*",
                    ),
                    ("-h, --help", "show this help"),
                ),
            ),
            (
                "Quick Start",
                (
                    ("pick next item", "loopfarm issue ready"),
                    (
                        "run one step",
                        "loopfarm issue orchestrate-run --root <id> --max-steps 1 --json",
                    ),
                    (
                        "run a few steps",
                        "loopfarm issue orchestrate-run --root <id> --max-steps 8 --json",
                    ),
                    ("inspect", "loopfarm issue show <id>"),
                    ("start work", "loopfarm issue status <id> in_progress"),
                    ("record progress", 'loopfarm issue comment <id> -m "..."'),
                    ("close", "loopfarm issue close <id> --outcome success"),
                ),
            ),
        ),
        examples=(
            (
                "loopfarm issue orchestrate-run --root loopfarm-123 --max-steps 8 --json",
                "run deterministic orchestration steps",
            ),
            (
                "loopfarm issue dep add loopfarm-a blocks loopfarm-b",
                "encode execution order",
            ),
            (
                "loopfarm issue show loopfarm-a --json",
                "export structured issue context for agents",
            ),
        ),
        docs_tip=(
            "Need the minimal-core contract? Run `loopfarm docs show issue-dag-orchestration`."
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="loopfarm issue",
        description="Manage loopfarm issues.",
    )
    p.add_argument(
        "--state-dir",
        help="Explicit .loopfarm state directory path",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    ls = sub.add_parser("list", help="List issues")
    ls.add_argument("--status", help=f"Filter by status ({', '.join(ISSUE_STATUSES)})")
    ls.add_argument("--search", help="Filter by text in id/title/body")
    ls.add_argument("--tag", help="Filter by tag")
    ls.add_argument("--limit", type=int, default=50, help="Max rows (default: 50)")
    ls.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(ls)

    ready = sub.add_parser("ready", help="List ready-to-work issues")
    ready.add_argument("--limit", type=int, default=20, help="Max rows (default: 20)")
    ready.add_argument(
        "--root",
        help="Scope to ready leaves under this root's parent-descendant subtree",
    )
    ready.add_argument(
        "--tag",
        action="append",
        default=[],
        help="Require tag on ready issues (repeatable)",
    )
    ready.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(ready)

    orchestrate = sub.add_parser(
        "orchestrate",
        help="Claim + route next issue-DAG leaf to team role/program",
    )
    orchestrate.add_argument(
        "--root",
        required=True,
        help="Root issue id for DAG-scoped selection",
    )
    orchestrate.add_argument(
        "--resume-mode",
        choices=("manual", "resume"),
        default="manual",
        help="manual: claim open leaves only; resume: adopt resumable in_progress first",
    )
    orchestrate.add_argument(
        "--tag",
        action="append",
        default=[],
        help=(
            "Require tag on candidates (repeatable); defaults to node:agent when omitted"
        ),
    )
    orchestrate.add_argument(
        "--scan-limit",
        type=int,
        default=20,
        help="Maximum frontier rows scanned per pass (default: 20)",
    )
    orchestrate.add_argument(
        "--max-passes",
        type=int,
        default=1,
        help=(
            "Recursive orchestration passes to run (default: 1). "
            "Each pass claims/routes at most one leaf."
        ),
    )
    orchestrate.add_argument(
        "--run-topic",
        default=DEFAULT_RUN_TOPIC,
        help=f"Run-level forum topic for node.execute events (default: {DEFAULT_RUN_TOPIC})",
    )
    orchestrate.add_argument(
        "--author",
        default="orchestrator",
        help="Forum author label for node.execute events (default: orchestrator)",
    )
    orchestrate.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(orchestrate)

    orchestrate_run = sub.add_parser(
        "orchestrate-run",
        help="Run deterministic issue-DAG loop (select -> execute -> maintain)",
    )
    orchestrate_run.add_argument(
        "--root",
        required=True,
        help="Root issue id for DAG-scoped execution",
    )
    orchestrate_run.add_argument(
        "--resume-mode",
        choices=("manual", "resume"),
        default="manual",
        help="manual: claim open leaves only; resume: adopt resumable in_progress first",
    )
    orchestrate_run.add_argument(
        "--tag",
        action="append",
        default=[],
        help=(
            "Require tag on candidates (repeatable); defaults to node:agent when omitted"
        ),
    )
    orchestrate_run.add_argument(
        "--scan-limit",
        type=int,
        default=20,
        help="Maximum frontier rows scanned per step (default: 20)",
    )
    orchestrate_run.add_argument(
        "--max-steps",
        type=int,
        default=1,
        help="Maximum execution steps before forced stop (default: 1)",
    )
    orchestrate_run.add_argument(
        "--full-maintenance",
        action="store_true",
        help=(
            "Run full reconcile+validate maintenance after each step "
            "(default: incremental affected-ancestor reconcile+validate)"
        ),
    )
    orchestrate_run.add_argument(
        "--run-topic",
        default=DEFAULT_RUN_TOPIC,
        help=f"Run-level forum topic for execution events (default: {DEFAULT_RUN_TOPIC})",
    )
    orchestrate_run.add_argument(
        "--author",
        default="orchestrator",
        help="Forum author label for execution events (default: orchestrator)",
    )
    orchestrate_run.add_argument(
        "--show-reasoning",
        action="store_true",
        help="Show reasoning items in streamed backend output",
    )
    orchestrate_run.add_argument(
        "--show-command-output",
        action="store_true",
        help="Always show command output in streamed backend output",
    )
    orchestrate_run.add_argument(
        "--show-command-start",
        action="store_true",
        help="Show command start events in streamed backend output",
    )
    orchestrate_run.add_argument(
        "--show-small-output",
        action="store_true",
        help="Show output when it fits truncation limits",
    )
    orchestrate_run.add_argument(
        "--show-tokens",
        action="store_true",
        help="Show token usage events",
    )
    orchestrate_run.add_argument(
        "--max-output-lines",
        type=int,
        default=60,
        help="Maximum command output lines to render per command (default: 60)",
    )
    orchestrate_run.add_argument(
        "--max-output-chars",
        type=int,
        default=2000,
        help="Maximum command output chars to render per command (default: 2000)",
    )
    orchestrate_run.add_argument(
        "--control-poll-seconds",
        type=int,
        default=5,
        help="Control checkpoint polling interval in seconds (default: 5)",
    )
    orchestrate_run.add_argument(
        "--forward-report-max-lines",
        type=int,
        default=20,
        help="Maximum forward-report lines for diff/status sections (default: 20)",
    )
    orchestrate_run.add_argument(
        "--forward-report-max-commits",
        type=int,
        default=12,
        help="Maximum forward-report commit lines (default: 12)",
    )
    orchestrate_run.add_argument(
        "--forward-report-max-summary-chars",
        type=int,
        default=800,
        help="Maximum forward-report summary characters (default: 800)",
    )
    orchestrate_run.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(orchestrate_run)

    show = sub.add_parser("show", help="Show one issue with details")
    show.add_argument("id", help="Issue id")
    show.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(show)

    comments = sub.add_parser("comments", help="List comments for an issue")
    comments.add_argument("id", help="Issue id")
    comments.add_argument(
        "--limit", type=int, default=25, help="Max rows (default: 25)"
    )
    comments.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(comments)

    new = sub.add_parser("new", help="Create a new issue")
    new.add_argument("title", help="Issue title")
    new.add_argument("-b", "--body", default="", help="Issue description/body")
    new.add_argument(
        "-s",
        "--status",
        default="open",
        choices=ISSUE_STATUSES,
        help=f"Initial status ({', '.join(ISSUE_STATUSES)})",
    )
    new.add_argument("-p", "--priority", type=int, default=3, help="Priority 1-5")
    new.add_argument(
        "-t", "--tag", action="append", default=[], help="Tag (repeatable)"
    )
    new.add_argument("--json", action="store_true", help="Output JSON")

    status = sub.add_parser("status", help="Set issue status")
    status.add_argument("id", help="Issue id")
    status.add_argument(
        "value",
        choices=ISSUE_STATUSES,
        help=f"New status ({', '.join(ISSUE_STATUSES)})",
    )
    status.add_argument(
        "--outcome",
        choices=ISSUE_OUTCOMES,
        help=f"Outcome when transitioning terminal status ({', '.join(ISSUE_OUTCOMES)})",
    )
    status.add_argument("--json", action="store_true", help="Output JSON")

    reconcile = sub.add_parser(
        "reconcile",
        help="Reconcile control-flow node(s): prune + close when outcome is determinable",
    )
    reconcile.add_argument(
        "id",
        help="Control-flow issue id, or root issue id when using --root",
    )
    reconcile.add_argument(
        "--root",
        action="store_true",
        help="Treat id as root and reconcile all cf:sequence/cf:fallback descendants",
    )
    reconcile.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(reconcile)

    validate_dag = sub.add_parser(
        "validate-dag",
        help="Validate issue-DAG consistency invariants under a root issue",
    )
    validate_dag.add_argument(
        "--root",
        required=True,
        help="Root issue id for DAG-scoped validation",
    )
    validate_dag.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(validate_dag)

    close = sub.add_parser("close", help="Set issue status to closed")
    close.add_argument("id", nargs="+", help="Issue id(s)")
    close.add_argument(
        "--outcome",
        choices=ISSUE_OUTCOMES,
        help=f"Outcome for closed issue ({', '.join(ISSUE_OUTCOMES)})",
    )
    close.add_argument("--json", action="store_true", help="Output JSON")

    reopen = sub.add_parser("reopen", help="Set issue status to open")
    reopen.add_argument("id", nargs="+", help="Issue id(s)")
    reopen.add_argument("--json", action="store_true", help="Output JSON")

    delete = sub.add_parser("delete", help="Delete issue(s)")
    delete.add_argument("id", nargs="+", help="Issue id(s)")
    delete.add_argument(
        "--yes",
        action="store_true",
        help="Confirm delete operation",
    )
    delete.add_argument("--json", action="store_true", help="Output JSON")

    priority = sub.add_parser("priority", help="Set issue priority")
    priority.add_argument("id", help="Issue id")
    priority.add_argument("value", type=int, help="Priority 1-5")
    priority.add_argument("--json", action="store_true", help="Output JSON")

    edit = sub.add_parser("edit", help="Edit issue fields")
    edit.add_argument("id", help="Issue id")
    edit.add_argument("--title", help="New title")
    edit.add_argument("-b", "--body", help="New body")
    edit.add_argument("-s", "--status", choices=ISSUE_STATUSES, help="New status")
    edit.add_argument("-p", "--priority", type=int, help="New priority 1-5")
    edit.add_argument(
        "--outcome",
        choices=ISSUE_OUTCOMES,
        help=f"Set terminal outcome ({', '.join(ISSUE_OUTCOMES)})",
    )
    edit.add_argument(
        "--clear-outcome",
        action="store_true",
        help="Clear outcome value",
    )
    edit.add_argument("--json", action="store_true", help="Output JSON")

    comment = sub.add_parser("comment", help="Add a comment to an issue")
    comment.add_argument("id", help="Issue id")
    comment.add_argument("-m", "--message", required=True, help="Comment body")
    comment.add_argument("--author", help="Author label")
    comment.add_argument("--json", action="store_true", help="Output JSON")

    deps = sub.add_parser("deps", help="List dependencies connected to an issue")
    deps.add_argument("id", help="Issue id")
    deps.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(deps)

    dep = sub.add_parser("dep", help="Dependency operations")
    dep_sub = dep.add_subparsers(dest="dep_cmd", required=True, metavar="dep_cmd")
    dep_add = dep_sub.add_parser("add", help="Add a dependency relation")
    dep_add.add_argument("src_id", help="Source issue id")
    dep_add.add_argument(
        "type",
        choices=_RELATION_CHOICES,
        help="Relation type (blocks, parent, related, blocked_by, child)",
    )
    dep_add.add_argument("dst_id", help="Destination issue id")
    dep_add.add_argument("--json", action="store_true", help="Output JSON")

    tag = sub.add_parser("tag", help="Tag operations")
    tag_sub = tag.add_subparsers(dest="tag_cmd", required=True, metavar="tag_cmd")
    tag_add = tag_sub.add_parser("add", help="Add a tag")
    tag_add.add_argument("id", help="Issue id")
    tag_add.add_argument("tag", help="Tag value")
    tag_add.add_argument("--json", action="store_true", help="Output JSON")
    tag_rm = tag_sub.add_parser("remove", help="Remove a tag")
    tag_rm.add_argument("id", help="Issue id")
    tag_rm.add_argument("tag", help="Tag value")
    tag_rm.add_argument("--json", action="store_true", help="Output JSON")

    spec = sub.add_parser("spec", help="Execution spec operations")
    spec_sub = spec.add_subparsers(dest="spec_cmd", required=True, metavar="spec_cmd")
    spec_show = spec_sub.add_parser("show", help="Show execution spec for one issue")
    spec_show.add_argument("id", help="Issue id")
    spec_show.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(spec_show)

    spec_set = spec_sub.add_parser("set", help="Set execution spec for one issue")
    spec_set.add_argument("id", help="Issue id")
    spec_set.add_argument(
        "--value",
        help="JSON object literal for execution spec",
    )
    spec_set.add_argument(
        "--file",
        help="Path to JSON file containing execution spec",
    )
    spec_set.add_argument("--json", action="store_true", help="Output JSON")

    spec_clear = spec_sub.add_parser(
        "clear", help="Clear execution spec for one issue"
    )
    spec_clear.add_argument("id", help="Issue id")
    spec_clear.add_argument("--json", action="store_true", help="Output JSON")

    return p


def main(argv: list[str] | None = None) -> None:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if raw_argv and raw_argv[0] in {"-h", "--help"}:
        help_parser = argparse.ArgumentParser(add_help=False)
        help_parser.add_argument("--state-dir")
        add_output_mode_argument(help_parser)
        help_args, _unknown = help_parser.parse_known_args(raw_argv[1:])
        try:
            help_output_mode = resolve_output_mode(
                getattr(help_args, "output", None),
                is_tty=getattr(sys.stdout, "isatty", lambda: False)(),
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        _print_help(output_mode=help_output_mode)
        raise SystemExit(0)

    args = _build_parser().parse_args(raw_argv)

    create = args.command not in {
        "list",
        "ready",
        "show",
        "deps",
        "comments",
        "validate-dag",
    }
    if args.command == "spec" and getattr(args, "spec_cmd", None) == "show":
        create = False
    state_dir = str(getattr(args, "state_dir", "") or "").strip() or None
    issue = Issue.from_workdir(Path.cwd(), create=create, state_dir=state_dir)
    output_mode = "plain"
    if hasattr(args, "output"):
        try:
            output_mode = resolve_output_mode(getattr(args, "output", None))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(2)

    try:
        if args.command == "list":
            rows = issue.list(
                status=args.status,
                search=args.search,
                tag=args.tag,
                limit=max(1, int(args.limit)),
            )
            if args.json:
                _emit_json(rows)
            else:
                if not rows:
                    if args.status or args.search or args.tag:
                        if output_mode == "rich":
                            render_panel(
                                make_console("rich"),
                                "(no matching issues)",
                                title="Issues",
                            )
                        else:
                            print("(no matching issues)")
                    else:
                        if output_mode == "rich":
                            render_panel(
                                make_console("rich"), "(no issues)", title="Issues"
                            )
                        else:
                            print("(no issues)")
                elif output_mode == "rich":
                    _print_issue_table_rich(rows, title="Issues")
                else:
                    _print_issue_table(rows)
            return

        if args.command == "ready":
            rows = issue.ready(
                limit=max(1, int(args.limit)),
                root=args.root,
                tags=list(args.tag or []),
            )
            if args.json:
                _emit_json(rows)
            else:
                if not rows:
                    if output_mode == "rich":
                        render_panel(
                            make_console("rich"),
                            "(no ready issues)",
                            title="Ready Issues",
                        )
                    else:
                        print("(no ready issues)")
                elif output_mode == "rich":
                    _print_issue_table_rich(rows, title="Ready Issues")
                else:
                    _print_issue_table(rows)
            return

        if args.command == "orchestrate":
            run_tags = [tag.strip() for tag in list(args.tag or []) if tag.strip()]
            if not run_tags:
                run_tags = list(DEFAULT_EXECUTION_TAGS)

            max_passes = max(1, int(args.max_passes))
            orchestrator = IssueDagOrchestrator(
                repo_root=Path.cwd(),
                issue=issue,
                forum=Forum.from_workdir(Path.cwd(), state_dir=state_dir),
                run_topic=args.run_topic,
                author=args.author,
                scan_limit=max(1, int(args.scan_limit)),
            )
            run = orchestrator.orchestrate(
                root_id=args.root,
                tags=run_tags,
                resume_mode=args.resume_mode,
                max_passes=max_passes,
            )
            payload = _orchestration_run_payload(run)
            selection_payload = payload.get("selection")
            selection: NodeExecutionSelection | None = None
            if selection_payload is not None:
                selection = next(
                    (
                        item.selection
                        for item in reversed(run.passes)
                        if item.selection is not None
                    ),
                    None,
                )

            if args.json:
                _emit_json(payload)
            else:
                if selection is None:
                    reason = str(payload.get("termination", {}).get("reason") or "-")
                    if output_mode == "rich":
                        render_panel(
                            make_console("rich"),
                            (
                                "(no executable issues)\n"
                                f"root_final_reason: {reason}\n"
                                f"stop_reason: {payload.get('stop_reason') or '-'}"
                            ),
                            title="Orchestrate",
                        )
                    else:
                        print("(no executable issues)")
                        print(f"root_final_reason: {reason}")
                        print(f"stop_reason: {payload.get('stop_reason') or '-'}")
                elif output_mode == "rich":
                    _print_orchestration_selection_rich(selection)
                else:
                    _print_orchestration_selection(selection)
                if max_passes > 1:
                    print(
                        "passes="
                        f"{payload.get('pass_count', 0)} "
                        "executed="
                        f"{payload.get('executed_count', 0)} "
                        "stop_reason="
                        f"{payload.get('stop_reason') or '-'}"
                    )
            return

        if args.command == "orchestrate-run":
            run_tags = [tag.strip() for tag in list(args.tag or []) if tag.strip()]
            if not run_tags:
                run_tags = list(DEFAULT_EXECUTION_TAGS)

            runner = IssueDagRunner(
                repo_root=Path.cwd(),
                issue=issue,
                forum=Forum.from_workdir(Path.cwd(), state_dir=state_dir),
                run_topic=args.run_topic,
                author=args.author,
                scan_limit=max(1, int(args.scan_limit)),
                show_reasoning=bool(args.show_reasoning),
                show_command_output=bool(args.show_command_output),
                show_command_start=bool(args.show_command_start),
                show_small_output=bool(args.show_small_output),
                show_tokens=bool(args.show_tokens),
                max_output_lines=max(1, int(args.max_output_lines)),
                max_output_chars=max(1, int(args.max_output_chars)),
                control_poll_seconds=max(1, int(args.control_poll_seconds)),
                forward_report_max_lines=max(
                    1, int(args.forward_report_max_lines)
                ),
                forward_report_max_commits=max(
                    1, int(args.forward_report_max_commits)
                ),
                forward_report_max_summary_chars=max(
                    1, int(args.forward_report_max_summary_chars)
                ),
            )
            dag_run = runner.run(
                root_id=args.root,
                tags=run_tags,
                resume_mode=args.resume_mode,
                max_steps=max(1, int(args.max_steps)),
                full_maintenance=bool(args.full_maintenance),
            )
            payload = _dag_run_payload(dag_run)

            if args.json:
                _emit_json(payload)
            elif output_mode == "rich":
                _print_dag_run_rich(payload)
            else:
                _print_dag_run(payload)

            if dag_run.stop_reason == "error":
                raise SystemExit(1)
            return

        if args.command == "show":
            row = issue.show(args.id)
            if row is None:
                print(f"error: issue not found: {args.id}", file=sys.stderr)
                raise SystemExit(1)
            if args.json:
                _emit_json(row)
            elif output_mode == "rich":
                _print_issue_details_rich(row)
            else:
                _print_issue_details(row)
            return

        if args.command == "comments":
            rows = issue.comments(args.id, limit=max(1, int(args.limit)))
            if args.json:
                _emit_json(rows)
            else:
                if not rows:
                    if output_mode == "rich":
                        _print_comments_rich(rows)
                    else:
                        print("(no comments)")
                elif output_mode == "rich":
                    _print_comments_rich(rows)
                else:
                    _print_comments(rows)
            return

        if args.command == "new":
            row = issue.create(
                args.title,
                body=args.body,
                status=args.status,
                priority=args.priority,
                tags=list(args.tag or []),
            )
            if args.json:
                _emit_json(row)
            else:
                print(row["id"])
            return

        if args.command == "status":
            row = issue.set_status(
                args.id,
                args.value,
                outcome=args.outcome,
                outcome_provided=args.outcome is not None,
            )
            if args.json:
                _emit_json(row)
            else:
                _print_issue(row)
            return

        if args.command == "reconcile":
            if args.root:
                row = issue.reconcile_control_flow_subtree(args.id)
            else:
                row = issue.reconcile_control_flow(args.id)
            if args.json:
                _emit_json(row)
            else:
                if args.root:
                    reconciled = row.get("reconciled") or []
                    print(
                        f"reconciled {len(reconciled)} control nodes under {row.get('root_id')}"
                    )
                    for entry in reconciled:
                        print(
                            f"{entry.get('id')} {entry.get('control_flow')} "
                            f"outcome={entry.get('outcome') or '-'} "
                            f"pruned={entry.get('pruned_count')}"
                        )
                    validation = row.get("validation") or {}
                    errors = validation.get("errors") or []
                    warnings = validation.get("warnings") or []
                    termination = validation.get("termination") or {}
                    is_final = bool(termination.get("is_final"))
                    reason = str(termination.get("reason") or "-")
                    print(f"root_final={is_final} reason={reason}")
                    if errors:
                        print(f"validation errors: {len(errors)}")
                        for err in errors:
                            print(
                                f"ERROR {err.get('code')}: "
                                f"{err.get('message')}"
                            )
                    if warnings:
                        print(f"validation warnings: {len(warnings)}")
                        for warning in warnings:
                            print(
                                f"WARN {warning.get('code')}: "
                                f"{warning.get('message')}"
                            )
                else:
                    print(
                        f"{row.get('id')} {row.get('control_flow')} "
                        f"outcome={row.get('outcome') or '-'} "
                        f"pruned={row.get('pruned_count')} "
                        f"closed={bool(row.get('closed'))}"
                    )
            return

        if args.command == "validate-dag":
            payload = issue.validate_dag(args.root)
            if args.json:
                _emit_json(payload)
            elif output_mode == "rich":
                _print_dag_validation_rich(payload)
            else:
                _print_dag_validation(payload)

            if payload.get("errors"):
                raise SystemExit(1)
            return

        if args.command == "close":
            rows = [
                issue.set_status(
                    issue_id,
                    "closed",
                    outcome=args.outcome,
                    outcome_provided=args.outcome is not None,
                )
                for issue_id in args.id
            ]
            if args.json:
                _emit_json(rows)
            else:
                for row in rows:
                    _print_issue(row)
            return

        if args.command == "reopen":
            rows = [issue.set_status(issue_id, "open") for issue_id in args.id]
            if args.json:
                _emit_json(rows)
            else:
                for row in rows:
                    _print_issue(row)
            return

        if args.command == "delete":
            if not args.yes:
                print("error: refusing to delete without --yes", file=sys.stderr)
                raise SystemExit(1)
            rows = [issue.delete(issue_id) for issue_id in args.id]
            if args.json:
                _emit_json(rows)
            else:
                for row in rows:
                    print(f"deleted: {row['id']}")
            return

        if args.command == "priority":
            row = issue.set_priority(args.id, int(args.value))
            if args.json:
                _emit_json(row)
            else:
                _print_issue(row)
            return

        if args.command == "edit":
            if args.outcome is not None and args.clear_outcome:
                raise ValueError("cannot combine --outcome and --clear-outcome")
            outcome_provided = args.outcome is not None or bool(args.clear_outcome)
            outcome_value = None if args.clear_outcome else args.outcome
            row = issue.edit(
                args.id,
                title=args.title,
                body=args.body,
                status=args.status,
                priority=args.priority,
                outcome=outcome_value,
                outcome_provided=outcome_provided,
            )
            if args.json:
                _emit_json(row)
            else:
                _print_issue(row)
            return

        if args.command == "comment":
            row = issue.add_comment(args.id, args.message, author=args.author)
            if args.json:
                _emit_json(row)
            else:
                print(row["id"])
            return

        if args.command == "spec" and args.spec_cmd == "show":
            payload = {
                "id": args.id,
                "execution_spec": issue.get_execution_spec(args.id),
            }
            if args.json:
                _emit_json(payload)
            else:
                spec_payload = payload["execution_spec"]
                if output_mode == "rich":
                    console = make_console("rich")
                    if spec_payload is None:
                        render_panel(console, "(none)", title=f"Execution Spec: {args.id}")
                    else:
                        render_panel(
                            console,
                            json.dumps(spec_payload, ensure_ascii=False, indent=2),
                            title=f"Execution Spec: {args.id}",
                        )
                else:
                    if spec_payload is None:
                        print("(none)")
                    else:
                        print(json.dumps(spec_payload, ensure_ascii=False, indent=2))
            return

        if args.command == "spec" and args.spec_cmd == "set":
            value_text = str(args.value or "").strip()
            file_text = str(args.file or "").strip()
            if bool(value_text) == bool(file_text):
                raise ValueError("provide exactly one of --value or --file")
            if file_text:
                value_text = Path(file_text).read_text(encoding="utf-8")
            try:
                payload = json.loads(value_text)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid execution spec JSON: {exc}") from exc

            row = issue.set_execution_spec(args.id, payload)
            out = {
                "id": str(row.get("id") or args.id),
                "execution_spec": row.get("execution_spec"),
            }
            if args.json:
                _emit_json(out)
            else:
                print(f"set execution_spec for {out['id']}")
            return

        if args.command == "spec" and args.spec_cmd == "clear":
            row = issue.clear_execution_spec(args.id)
            out = {
                "id": str(row.get("id") or args.id),
                "execution_spec": row.get("execution_spec"),
            }
            if args.json:
                _emit_json(out)
            else:
                print(f"cleared execution_spec for {out['id']}")
            return

        if args.command == "deps":
            rows = issue.deps(args.id)
            if args.json:
                _emit_json(rows)
            else:
                if output_mode == "rich":
                    _print_dependencies_rich(
                        rows,
                        title=f"Dependencies: {args.id}",
                        no_rows_message="(no dependencies)",
                    )
                else:
                    if not rows:
                        print("(no dependencies)")
                    for row in rows:
                        print(
                            f"{row['src_id']} {row['type']} {row['dst_id']}\t"
                            f"active={row['active']}"
                        )
            return

        if args.command == "dep" and args.dep_cmd == "add":
            row = issue.add_dep(args.src_id, args.type, args.dst_id)
            if args.json:
                _emit_json(row)
            else:
                print(f"{row['src_id']} {row['type']} {row['dst_id']}")
            return

        if args.command == "tag" and args.tag_cmd == "add":
            row = issue.add_tag(args.id, args.tag)
            if args.json:
                _emit_json(row)
            else:
                _print_issue(row)
            return

        if args.command == "tag" and args.tag_cmd == "remove":
            row = issue.remove_tag(args.id, args.tag)
            if args.json:
                _emit_json(row)
            else:
                _print_issue(row)
            return
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
