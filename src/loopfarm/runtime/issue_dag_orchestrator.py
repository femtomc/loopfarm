from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .issue_dag_execution import (
    DEFAULT_RUN_TOPIC,
    IssueDagExecutionPlanner,
    NodeExecutionSelection,
    ResumeMode,
)
from .roles import ROLE_TAG_PREFIX, RoleCatalog


ATOMIC_TAG = "granularity:atomic"
TEAM_TAG_PREFIX = "team:"
DEFAULT_EXECUTION_TAGS = ("node:agent",)
DEFAULT_EXECUTION_ROLE = "worker"
DEFAULT_PLANNING_ROLE = "orchestrator"
DEFAULT_TEAM_LABEL = "dynamic"


@dataclass(frozen=True)
class IssueDagOrchestrationPass:
    index: int
    selection: NodeExecutionSelection | None
    termination_before: dict[str, Any]
    termination_after: dict[str, Any]


@dataclass(frozen=True)
class IssueDagOrchestrationRun:
    root_id: str
    required_tags: tuple[str, ...]
    resume_mode: ResumeMode
    max_passes: int
    stop_reason: str
    passes: tuple[IssueDagOrchestrationPass, ...]
    termination: dict[str, Any]
    validation: dict[str, Any]


class IssueDagOrchestrator:
    """
    Implements the hierarchical planning and execution loop for the issue DAG.

    This orchestrator serves as the "system 2" process that:
    1. Selects the next ready leaf issue from the DAG.
    2. Decides whether the issue is granular enough for execution:
       - If tagged `granularity:atomic`, routes to the worker role for execution.
       - If not atomic, routes to `.loopfarm/orchestrator.md` for decomposition.
    3. Assembles role-doc context for the selected route.
    4. Recursively repeats this process (via passes) to drive the DAG to completion.
    """

    def __init__(
        self,
        *,
        repo_root: Path,
        issue,
        forum,
        run_topic: str = DEFAULT_RUN_TOPIC,
        author: str = "orchestrator",
        scan_limit: int = 20,
        roles: RoleCatalog | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.issue = issue
        self._roles = roles or RoleCatalog.from_repo(repo_root)
        self.execution_planner = IssueDagExecutionPlanner(
            issue=issue,
            forum=forum,
            run_topic=run_topic,
            author=author,
            scan_limit=scan_limit,
        )

    def select_next_execution(
        self,
        *,
        root_id: str | None = None,
        tags: list[str] | None = None,
        resume_mode: ResumeMode = "manual",
    ) -> NodeExecutionSelection | None:
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

        candidate = self.execution_planner.select_next_candidate(
            root_id=root_id,
            tags=required_tags,
            resume_mode=resume_mode,
        )
        if candidate is None:
            return None

        issue_row = dict(candidate.issue)
        issue_id = str(issue_row.get("id") or "").strip()
        if not issue_id:
            return None

        team_name = self._resolve_team_label(issue_row)
        role, role_source, route = self._resolve_role(issue_row)
        selected_prompt_path: Path
        if route == "planning":
            selected_prompt_path = self.repo_root / ".loopfarm" / "orchestrator.md"
            if not selected_prompt_path.exists() or not selected_prompt_path.is_file():
                raise ValueError(
                    "missing orchestrator prompt: .loopfarm/orchestrator.md"
            )
            program = "orchestrator"
        else:
            role_doc = self._roles.require(role=role)
            selected_prompt_path = role_doc.source_path
            program = self._program_label(role_doc.role)
        team_assembly = self._assemble_team(
            team_name=team_name,
            selected_role=role,
            selected_program=program,
            selected_prompt_path=selected_prompt_path,
            route=route,
            role_source=role_source,
        )

        return self.execution_planner.build_selection(
            issue=issue_row,
            mode=candidate.mode,
            role=role,
            program=program,
            team=team_name,
            root_id=root_id,
            tags=required_tags,
            claim_timestamp=candidate.claim_timestamp,
            extra_payload={
                "route": route,
                "role_source": role_source,
                "team_assembly": team_assembly,
            },
        )

    def orchestrate(
        self,
        *,
        root_id: str,
        tags: list[str] | None = None,
        resume_mode: ResumeMode = "manual",
        max_passes: int = 1,
    ) -> IssueDagOrchestrationRun:
        resolved_root = root_id.strip()
        if not resolved_root:
            raise ValueError("root_id is required")

        pass_budget = int(max_passes)
        if pass_budget < 1:
            raise ValueError("max_passes must be >= 1")

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

        passes: list[IssueDagOrchestrationPass] = []
        validation = self._validate_subtree(resolved_root)
        stop_reason = "max_passes_exhausted"

        for index in range(1, pass_budget + 1):
            termination_before = self._termination_payload(validation)
            if bool(termination_before.get("is_final")):
                stop_reason = "root_final"
                break

            selection = self.select_next_execution(
                root_id=resolved_root,
                tags=required_tags,
                resume_mode=resume_mode,
            )

            validation = self._validate_subtree(resolved_root)
            termination_after = self._termination_payload(validation)
            passes.append(
                IssueDagOrchestrationPass(
                    index=index,
                    selection=selection,
                    termination_before=termination_before,
                    termination_after=termination_after,
                )
            )

            if selection is None:
                stop_reason = "no_executable_leaf"
                break
            if bool(termination_after.get("is_final")):
                stop_reason = "root_final"
                break
        else:
            termination_final = self._termination_payload(validation)
            if bool(termination_final.get("is_final")):
                stop_reason = "root_final"
            elif passes and passes[-1].selection is None:
                stop_reason = "no_executable_leaf"
            else:
                stop_reason = "max_passes_exhausted"

        return IssueDagOrchestrationRun(
            root_id=resolved_root,
            required_tags=tuple(required_tags),
            resume_mode=resume_mode,
            max_passes=pass_budget,
            stop_reason=stop_reason,
            passes=tuple(passes),
            termination=self._termination_payload(validation),
            validation=dict(validation),
        )

    def _resolve_role(
        self,
        issue_row: dict[str, Any],
    ) -> tuple[str, str, str]:
        tags = [
            str(tag).strip() for tag in issue_row.get("tags") or [] if str(tag).strip()
        ]
        issue_id = str(issue_row.get("id") or "").strip() or "<unknown>"
        role_tags = [
            tag
            for tag in tags
            if tag.startswith(ROLE_TAG_PREFIX) and tag[len(ROLE_TAG_PREFIX) :].strip()
        ]
        if len(role_tags) > 1:
            joined = ", ".join(role_tags)
            raise ValueError(f"multiple role:* tags on issue {issue_id}: {joined}")
        explicit_role = (
            role_tags[0][len(ROLE_TAG_PREFIX) :].strip().lower() if role_tags else ""
        )
        explicit_source = f"tag:{role_tags[0]}" if role_tags else ""

        is_atomic = ATOMIC_TAG in tags
        if not is_atomic:
            _ = explicit_role
            _ = explicit_source
            return (DEFAULT_PLANNING_ROLE, "orchestrator.prompt", "planning")

        if explicit_role:
            return (explicit_role, explicit_source, "execution")
        if self._roles.has_role(role=DEFAULT_EXECUTION_ROLE):
            return (DEFAULT_EXECUTION_ROLE, "role.default.worker", "execution")

        available_roles = self._roles.available_roles()
        if len(available_roles) == 1:
            return (available_roles[0], "role.only_available", "execution")
        if available_roles:
            joined = ", ".join(repr(role_name) for role_name in available_roles)
            raise ValueError(
                "unable to resolve execution role from available docs; "
                f"set role:<name> on issue (available roles: {joined})"
            )
        raise ValueError(
            "no role docs available; add files under .loopfarm/roles such as worker.md"
        )

    def _assemble_team(
        self,
        *,
        team_name: str,
        selected_role: str,
        selected_program: str,
        selected_prompt_path: Path,
        route: str,
        role_source: str,
    ) -> dict[str, Any]:
        roles_payload = []
        for doc in self._roles.available_docs():
            roles_payload.append(
                {
                    "role": doc.role,
                    "program": self._program_label(doc.role),
                    "role_doc": self._format_path(doc.source_path),
                }
            )
        roles_payload.sort(key=lambda item: str(item["role"]))

        roles_payload = [
            row for row in roles_payload if str(row["role"]) != selected_role
        ]
        return {
            "team": team_name,
            "route": route,
            "role_source": role_source,
            "selected": {
                "role": selected_role,
                "program": selected_program,
                "role_doc": self._format_path(selected_prompt_path),
            },
            "roles": [
                {
                    "role": selected_role,
                    "program": selected_program,
                    "role_doc": self._format_path(selected_prompt_path),
                },
                *roles_payload,
            ],
        }

    @staticmethod
    def _resolve_team_label(issue_row: dict[str, Any]) -> str:
        tags = [
            str(tag).strip() for tag in issue_row.get("tags") or [] if str(tag).strip()
        ]
        team_tags = [
            tag
            for tag in tags
            if tag.startswith(TEAM_TAG_PREFIX) and tag[len(TEAM_TAG_PREFIX) :].strip()
        ]
        issue_id = str(issue_row.get("id") or "").strip() or "<unknown>"
        if len(team_tags) > 1:
            joined = ", ".join(team_tags)
            raise ValueError(f"multiple team:* tags on issue {issue_id}: {joined}")
        if team_tags:
            team_name = team_tags[0][len(TEAM_TAG_PREFIX) :].strip()
            if team_name:
                return team_name
        return DEFAULT_TEAM_LABEL

    @staticmethod
    def _program_label(role: str) -> str:
        return f"role:{role.strip().lower()}"

    def _format_path(self, path: Path | None) -> str:
        if path is None:
            return ""
        try:
            return str(path.resolve().relative_to(self.repo_root.resolve()))
        except Exception:
            return str(path)

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
