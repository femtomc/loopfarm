from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from .issue_dag_execution import (
    DEFAULT_RUN_TOPIC,
    IssueDagNodeExecutionAdapter,
    NodeExecutionRunResult,
    NodeExecutionSelection,
    ResumeMode,
)
from .issue_dag_orchestrator import (
    DEFAULT_EXECUTION_TAGS,
    IssueDagOrchestrator,
)
from .roles import RoleCatalog


IssueDagRunStopReason = Literal[
    "root_final",
    "no_executable_leaf",
    "max_steps_exhausted",
    "error",
]


class IssueDagRunnerIssueClient(Protocol):
    def validate_orchestration_subtree(self, root_issue_id: str) -> dict[str, Any]: ...

    def reconcile_control_flow_subtree(self, root_issue_id: str) -> dict[str, Any]: ...

    def reconcile_control_flow_ancestors(
        self,
        issue_id: str,
        *,
        root_issue_id: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class IssueDagRunStep:
    index: int
    selection: NodeExecutionSelection
    execution: NodeExecutionRunResult
    maintenance: dict[str, Any]
    termination_before: dict[str, Any]
    termination_after: dict[str, Any]


@dataclass(frozen=True)
class IssueDagRun:
    root_id: str
    required_tags: tuple[str, ...]
    resume_mode: ResumeMode
    max_steps: int
    stop_reason: IssueDagRunStopReason
    steps: tuple[IssueDagRunStep, ...]
    termination: dict[str, Any]
    validation: dict[str, Any]
    error: str | None = None


class IssueDagRunner:
    def __init__(
        self,
        *,
        repo_root: Path,
        issue: IssueDagRunnerIssueClient,
        forum,
        run_topic: str = DEFAULT_RUN_TOPIC,
        author: str = "orchestrator",
        scan_limit: int = 20,
        roles: RoleCatalog | None = None,
        orchestrator: IssueDagOrchestrator | None = None,
        executor: IssueDagNodeExecutionAdapter | None = None,
        show_reasoning: bool = False,
        show_command_output: bool = False,
        show_command_start: bool = False,
        show_small_output: bool = False,
        show_tokens: bool = False,
        max_output_lines: int = 60,
        max_output_chars: int = 2000,
        control_poll_seconds: int = 5,
        forward_report_max_lines: int = 20,
        forward_report_max_commits: int = 12,
        forward_report_max_summary_chars: int = 800,
    ) -> None:
        self.repo_root = repo_root
        self.issue = issue
        self._orchestrator = orchestrator or IssueDagOrchestrator(
            repo_root=repo_root,
            issue=issue,
            forum=forum,
            run_topic=run_topic,
            author=author,
            scan_limit=scan_limit,
            roles=roles,
        )
        self._executor = executor or IssueDagNodeExecutionAdapter(
            repo_root=repo_root,
            issue=issue,
            forum=forum,
            run_topic=run_topic,
            author=author,
            show_reasoning=show_reasoning,
            show_command_output=show_command_output,
            show_command_start=show_command_start,
            show_small_output=show_small_output,
            show_tokens=show_tokens,
            max_output_lines=max_output_lines,
            max_output_chars=max_output_chars,
            control_poll_seconds=control_poll_seconds,
            forward_report_max_lines=forward_report_max_lines,
            forward_report_max_commits=forward_report_max_commits,
            forward_report_max_summary_chars=forward_report_max_summary_chars,
        )

    def run(
        self,
        *,
        root_id: str,
        tags: list[str] | None = None,
        resume_mode: ResumeMode = "manual",
        max_steps: int = 1,
        full_maintenance: bool = False,
    ) -> IssueDagRun:
        resolved_root = root_id.strip()
        if not resolved_root:
            raise ValueError("root_id is required")

        step_budget = int(max_steps)
        if step_budget < 1:
            raise ValueError("max_steps must be >= 1")

        required_tags = sorted(
            {
                tag.strip()
                for tag in (
                    tags
                    if tags is not None
                    else list(DEFAULT_EXECUTION_TAGS)
                )
                if tag.strip()
            }
        )
        if not required_tags:
            required_tags = list(DEFAULT_EXECUTION_TAGS)

        steps: list[IssueDagRunStep] = []
        validation = self._validate_subtree(resolved_root)
        stop_reason: IssueDagRunStopReason = "max_steps_exhausted"
        error: str | None = None

        for index in range(1, step_budget + 1):
            termination_before = self._termination_payload(validation)
            if bool(termination_before.get("is_final")):
                stop_reason = "root_final"
                break

            selection = self._orchestrator.select_next_execution(
                root_id=resolved_root,
                tags=required_tags,
                resume_mode=resume_mode,
            )
            if selection is None:
                validation = self._validate_subtree(resolved_root)
                termination_after_none = self._termination_payload(validation)
                if bool(termination_after_none.get("is_final")):
                    stop_reason = "root_final"
                else:
                    stop_reason = "no_executable_leaf"
                break

            execution = self._executor.execute_selection(
                selection,
                root_id=resolved_root,
            )
            maintenance = self._run_maintenance(
                resolved_root,
                issue_id=selection.issue_id,
                full_maintenance=full_maintenance,
            )
            validation = dict(maintenance.get("validation") or {})
            termination_after = self._termination_payload(validation)
            steps.append(
                IssueDagRunStep(
                    index=index,
                    selection=selection,
                    execution=execution,
                    maintenance=maintenance,
                    termination_before=termination_before,
                    termination_after=termination_after,
                )
            )

            if not execution.success:
                stop_reason = "error"
                error = (
                    execution.error
                    or f"selection execution failed for issue {selection.issue_id}"
                )
                break
            if bool(termination_after.get("is_final")):
                stop_reason = "root_final"
                break
        else:
            termination_final = self._termination_payload(validation)
            if bool(termination_final.get("is_final")):
                stop_reason = "root_final"
            else:
                stop_reason = "max_steps_exhausted"

        return IssueDagRun(
            root_id=resolved_root,
            required_tags=tuple(required_tags),
            resume_mode=resume_mode,
            max_steps=step_budget,
            stop_reason=stop_reason,
            steps=tuple(steps),
            termination=self._termination_payload(validation),
            validation=dict(validation),
            error=error,
        )

    def _run_maintenance(
        self,
        root_id: str,
        *,
        issue_id: str,
        full_maintenance: bool,
    ) -> dict[str, Any]:
        if full_maintenance:
            reconciled = self.issue.reconcile_control_flow_subtree(root_id)
            validation = reconciled.get("validation")
            if not isinstance(validation, dict):
                validation = self._validate_subtree(root_id)
            return {
                "mode": "full",
                "root_id": root_id,
                "reconciled_count": int(reconciled.get("reconciled_count") or 0),
                "validation": dict(validation),
            }

        incremental = self.issue.reconcile_control_flow_ancestors(
            issue_id,
            root_issue_id=root_id,
        )
        validation = incremental.get("validation")
        if not isinstance(validation, dict):
            validation = self._validate_subtree(root_id)

        target_ids = [
            str(target_id) for target_id in list(incremental.get("target_ids") or [])
        ]
        return {
            "mode": "incremental",
            "root_id": root_id,
            "issue_id": issue_id,
            "target_count": int(incremental.get("target_count") or len(target_ids)),
            "target_ids": target_ids,
            "reconciled_count": int(incremental.get("reconciled_count") or 0),
            "reconciled": list(incremental.get("reconciled") or []),
            "validation": dict(validation),
        }

    def _validate_subtree(self, root_id: str) -> dict[str, Any]:
        validation = self.issue.validate_orchestration_subtree(root_id)
        if not isinstance(validation, dict):
            raise ValueError(
                f"validate_orchestration_subtree returned invalid payload for {root_id}"
            )
        return dict(validation)

    @staticmethod
    def _termination_payload(validation: dict[str, Any]) -> dict[str, Any]:
        termination = validation.get("termination")
        if not isinstance(termination, dict):
            return {}
        return dict(termination)
