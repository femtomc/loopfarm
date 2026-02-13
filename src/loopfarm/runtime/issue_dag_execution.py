from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal, Protocol

from ..runner import CodexPhaseModel, LoopfarmConfig, run_loop
from ..stores.session import SessionStore
from ..stores.state import now_ms
from ..util import env_value, new_session_id
from .issue_dag_events import build_node_execute_event, build_node_result_event
from .roles import RoleCatalog


DEFAULT_RUN_TOPIC = "loopfarm:feature:issue-dag-orchestration"
ResumeMode = Literal["manual", "resume"]
ExecutionMode = Literal["claim", "resume"]
ROLE_PHASE = "role"
DEFAULT_ROLE_CLI = "codex"
DEFAULT_ROLE_MODEL = "gpt-5.2"
DEFAULT_ROLE_REASONING = "xhigh"
DEFAULT_SELECTION_TEAM = "dynamic"
_TERMINAL_STATUSES = frozenset({"closed", "duplicate"})
_TERMINAL_OUTCOMES = frozenset({"success", "failure", "expanded", "skipped"})


class IssueDagIssueClient(Protocol):
    def ready(
        self,
        *,
        limit: int = 20,
        root: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...

    def resumable(
        self,
        *,
        limit: int = 20,
        root: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...

    def claim_ready_leaf(
        self,
        issue_id: str,
        *,
        root: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]: ...


class IssueDagForumClient(Protocol):
    def post_json(self, topic: str, payload: Any, *, author: str | None = None) -> None: ...


class IssueDagSessionForumClient(IssueDagForumClient, Protocol):
    def read_json(self, topic: str, *, limit: int) -> list[dict[str, Any]]: ...


class IssueDagExecutionStateClient(Protocol):
    def show(self, issue_id: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class NodeExecutionRunResult:
    issue_id: str
    root_id: str | None
    team: str
    role: str
    program: str
    mode: ExecutionMode
    session_id: str
    started_at: int
    started_at_iso: str
    ended_at: int
    ended_at_iso: str
    exit_code: int
    status: str
    outcome: str | None
    postconditions_met: bool
    success: bool
    error: str | None


@dataclass(frozen=True)
class NodeExecutionSelection:
    issue_id: str
    team: str
    role: str
    program: str
    mode: ExecutionMode
    claim_timestamp: int
    issue: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class NodeExecutionCandidate:
    issue: dict[str, Any]
    mode: ExecutionMode
    claim_timestamp: int


RunSelectionSessionFn = Callable[[LoopfarmConfig, str], int]


class IssueDagNodeExecutionAdapter:
    def __init__(
        self,
        *,
        repo_root: Path,
        issue: IssueDagExecutionStateClient,
        forum: IssueDagSessionForumClient,
        run_topic: str = DEFAULT_RUN_TOPIC,
        author: str = "orchestrator",
        roles: RoleCatalog | None = None,
        run_session: RunSelectionSessionFn | None = None,
        session_id_factory: Callable[[], str] = new_session_id,
    ) -> None:
        self.repo_root = repo_root
        self.issue = issue
        self.forum = forum
        self.run_topic = run_topic
        self.author = author
        self._roles = roles or RoleCatalog.from_repo(repo_root)
        self._run_session = run_session or self._default_run_session
        self._session_id_factory = session_id_factory
        self._session_store = SessionStore(forum)

    def execute_selection(
        self,
        selection: NodeExecutionSelection,
        *,
        root_id: str | None = None,
    ) -> NodeExecutionRunResult:
        issue_id = (
            str(selection.issue_id).strip()
            or str(selection.issue.get("id") or "").strip()
        )
        if not issue_id:
            raise ValueError("selection.issue_id is required")

        resolved_root_id = self._resolve_root_id(root_id, selection=selection)
        issue_payload = self._normalize_issue_payload(selection.issue, fallback_id=issue_id)
        prompt_path = self._prompt_path_for_selection(selection)
        cfg = self._build_loop_config(
            team=selection.team,
            prompt_path=prompt_path,
            prompt=self._build_issue_prompt(issue_payload),
        )

        session_id = self._session_id_factory().strip()
        if not session_id:
            raise ValueError("session_id_factory returned an empty session id")

        started_at = now_ms()
        # Force one-pass execution for role docs by satisfying the runner's
        # termination check at the single role phase.
        self.forum.post_json(
            f"loopfarm:status:{session_id}",
            {
                "decision": "COMPLETE",
                "summary": f"Role phase {selection.role!r} finished",
            },
            author=self.author,
        )
        self._session_store.update_session_meta(
            session_id,
            {
                "session_context": self._dynamic_context(
                    issue=issue_payload,
                    root_id=resolved_root_id,
                    selection=selection,
                )
            },
            author=self.author,
        )

        error_parts: list[str] = []
        try:
            exit_code = int(self._run_session(cfg, session_id))
        except Exception as exc:
            exit_code = 1
            error_parts.append(f"session execution failed: {exc}")

        final_issue = self.issue.show(issue_id)
        status = str((final_issue or {}).get("status") or "").strip()
        raw_outcome = (final_issue or {}).get("outcome")
        outcome = (
            str(raw_outcome).strip()
            if raw_outcome is not None and str(raw_outcome).strip()
            else None
        )

        postcondition_error = self._postcondition_error(
            issue_id=issue_id,
            status=status,
            outcome=outcome,
            route=self._selection_route(selection),
        )
        if postcondition_error is not None:
            error_parts.append(postcondition_error)
        if exit_code != 0:
            error_parts.append(f"session exited with code {exit_code}")

        postconditions_met = postcondition_error is None
        error = "; ".join(error_parts) if error_parts else None

        ended_at = now_ms()
        result = NodeExecutionRunResult(
            issue_id=issue_id,
            root_id=resolved_root_id,
            team=selection.team,
            role=selection.role,
            program=selection.program,
            mode=selection.mode,
            session_id=session_id,
            started_at=started_at,
            started_at_iso=self._iso_ms(started_at),
            ended_at=ended_at,
            ended_at_iso=self._iso_ms(ended_at),
            exit_code=exit_code,
            status=status,
            outcome=outcome,
            postconditions_met=postconditions_met,
            success=bool(exit_code == 0 and postconditions_met),
            error=error,
        )

        self._post_result(selection=selection, result=result)
        if error is not None:
            self._post_diagnostic(selection=selection, result=result)

        return result

    def _post_result(
        self,
        *,
        selection: NodeExecutionSelection,
        result: NodeExecutionRunResult,
    ) -> None:
        root_id = (result.root_id or "").strip()
        status = result.status.strip()
        outcome = (result.outcome or "").strip()

        if not root_id or status not in _TERMINAL_STATUSES:
            return
        if not outcome or outcome not in _TERMINAL_OUTCOMES:
            return

        payload = build_node_result_event(
            issue_id=result.issue_id,
            root_id=root_id,
            outcome=outcome,
            extra={
                "team": result.team,
                "role": result.role,
                "program": result.program,
                "mode": result.mode,
                "session_id": result.session_id,
                "status": status,
                "exit_code": result.exit_code,
                "postconditions_met": result.postconditions_met,
                "success": result.success,
                "started_at": result.started_at,
                "started_at_iso": result.started_at_iso,
                "ended_at": result.ended_at,
                "ended_at_iso": result.ended_at_iso,
            },
        )
        if selection.metadata:
            payload["metadata"] = dict(selection.metadata)

        self.forum.post_json(
            self.run_topic,
            payload,
            author=self.author,
        )
        self.forum.post_json(
            f"issue:{result.issue_id}",
            payload,
            author=self.author,
        )

    def _post_diagnostic(
        self,
        *,
        selection: NodeExecutionSelection,
        result: NodeExecutionRunResult,
    ) -> None:
        payload: dict[str, Any] = {
            "kind": "node.execution_diagnostic",
            "id": result.issue_id,
            "team": result.team,
            "role": result.role,
            "program": result.program,
            "mode": result.mode,
            "session_id": result.session_id,
            "claim_timestamp": selection.claim_timestamp,
            "claim_timestamp_iso": self._iso_ms(selection.claim_timestamp),
            "postconditions_met": result.postconditions_met,
            "success": result.success,
            "status": result.status,
            "outcome": result.outcome,
            "exit_code": result.exit_code,
            "error": result.error,
            "started_at": result.started_at,
            "started_at_iso": result.started_at_iso,
            "ended_at": result.ended_at,
            "ended_at_iso": result.ended_at_iso,
        }
        if result.root_id:
            payload["root"] = result.root_id
        if selection.metadata:
            payload["metadata"] = dict(selection.metadata)

        self.forum.post_json(
            self.run_topic,
            payload,
            author=self.author,
        )
        self.forum.post_json(
            f"issue:{result.issue_id}",
            payload,
            author=self.author,
        )

    def _prompt_path_for_selection(self, selection: NodeExecutionSelection) -> Path:
        route = self._selection_route(selection)
        if route == "planning":
            orchestrator_prompt = self.repo_root / ".loopfarm" / "orchestrator.md"
            if not orchestrator_prompt.exists() or not orchestrator_prompt.is_file():
                raise ValueError(
                    "missing orchestrator prompt: .loopfarm/orchestrator.md"
                )
            return orchestrator_prompt

        role_name = str(selection.role or "").strip().lower()
        if not role_name:
            raise ValueError("selection.role is required")
        role_doc = self._roles.require(role=role_name)
        return role_doc.source_path

    def _build_loop_config(
        self,
        *,
        team: str,
        prompt_path: Path,
        prompt: str,
    ) -> LoopfarmConfig:
        cli = self._role_cli()
        model = self._role_model()
        reasoning = self._role_reasoning()
        phase_models: tuple[tuple[str, CodexPhaseModel], ...]
        if cli == "kimi":
            phase_models = ()
        else:
            phase_models = ((ROLE_PHASE, CodexPhaseModel(model, reasoning)),)

        project = (team or self.repo_root.name or "loopfarm").strip() or "loopfarm"
        return LoopfarmConfig(
            repo_root=self.repo_root,
            project=project,
            prompt=prompt,
            loop_steps=((ROLE_PHASE, 1),),
            termination_phase=ROLE_PHASE,
            phase_models=phase_models,
            phase_cli_overrides=((ROLE_PHASE, cli),),
            phase_prompt_overrides=((ROLE_PHASE, str(prompt_path)),),
        )

    @staticmethod
    def _role_cli() -> str:
        raw = env_value("LOOPFARM_ROLE_CLI")
        if raw is None:
            return DEFAULT_ROLE_CLI
        value = raw.strip().lower()
        return value or DEFAULT_ROLE_CLI

    @staticmethod
    def _role_model() -> str:
        raw = env_value("LOOPFARM_ROLE_MODEL")
        if raw is None:
            return DEFAULT_ROLE_MODEL
        value = raw.strip()
        return value or DEFAULT_ROLE_MODEL

    @staticmethod
    def _role_reasoning() -> str:
        raw = env_value("LOOPFARM_ROLE_REASONING")
        if raw is None:
            return DEFAULT_ROLE_REASONING
        value = raw.strip()
        return value or DEFAULT_ROLE_REASONING

    def _build_issue_prompt(self, issue: dict[str, Any]) -> str:
        issue_id = str(issue.get("id") or "").strip() or "unknown"
        title = str(issue.get("title") or "").strip()
        body = str(issue.get("body") or "").strip()

        lines = [f"Issue ID: {issue_id}"]
        if title:
            lines.append(f"Issue Title: {title}")
        if body:
            lines.extend(("", body))
        return "\n".join(lines).strip() or issue_id

    def _dynamic_context(
        self,
        *,
        issue: dict[str, Any],
        root_id: str | None,
        selection: NodeExecutionSelection,
    ) -> str:
        payload: dict[str, Any] = {
            "issue": issue,
            "selection": {
                "team": selection.team,
                "role": selection.role,
                "program": selection.program,
                "mode": selection.mode,
                "claim_timestamp": selection.claim_timestamp,
                "claim_timestamp_iso": self._iso_ms(selection.claim_timestamp),
                "metadata": dict(selection.metadata),
            },
        }
        if root_id:
            payload["root_id"] = root_id
        return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)

    @staticmethod
    def _normalize_issue_payload(
        issue: dict[str, Any] | None,
        *,
        fallback_id: str,
    ) -> dict[str, Any]:
        payload = dict(issue) if isinstance(issue, dict) else {}
        issue_id = str(payload.get("id") or fallback_id).strip() or fallback_id
        tags = sorted(
            {
                str(tag).strip()
                for tag in payload.get("tags") or []
                if str(tag).strip()
            }
        )
        raw_outcome = payload.get("outcome")
        outcome = (
            str(raw_outcome).strip()
            if raw_outcome is not None and str(raw_outcome).strip()
            else None
        )
        return {
            "id": issue_id,
            "title": str(payload.get("title") or "").strip(),
            "body": str(payload.get("body") or "").strip(),
            "tags": tags,
            "status": str(payload.get("status") or "").strip(),
            "outcome": outcome,
        }

    @staticmethod
    def _postcondition_error(
        *,
        issue_id: str,
        status: str,
        outcome: str | None,
        route: str | None = None,
    ) -> str | None:
        if status not in _TERMINAL_STATUSES:
            return (
                f"issue {issue_id} must end in a terminal status "
                "(closed|duplicate) after execution"
            )
        if outcome not in _TERMINAL_OUTCOMES:
            allowed = ",".join(sorted(_TERMINAL_OUTCOMES))
            return (
                f"issue {issue_id} must end with an allowed terminal outcome "
                f"({allowed})"
            )

        if route == "planning" and outcome != "expanded":
            return (
                f"issue {issue_id} routed via planning must end with "
                "outcome=expanded"
            )
        if route == "execution" and outcome == "expanded":
            return (
                f"issue {issue_id} routed via execution must not end with "
                "outcome=expanded"
            )
        return None

    @staticmethod
    def _selection_route(selection: NodeExecutionSelection) -> str | None:
        route = str(selection.metadata.get("route") or "").strip()
        return route or None

    def _resolve_root_id(
        self,
        root_id: str | None,
        *,
        selection: NodeExecutionSelection,
    ) -> str | None:
        explicit = (root_id or "").strip()
        if explicit:
            return explicit
        metadata_root = str(selection.metadata.get("root_id") or "").strip()
        if metadata_root:
            return metadata_root
        return None

    @staticmethod
    def _iso_ms(value: int) -> str:
        dt = datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _default_run_session(cfg: LoopfarmConfig, session_id: str) -> int:
        return int(run_loop(cfg, session_id=session_id))


class IssueDagExecutionPlanner:
    def __init__(
        self,
        *,
        issue: IssueDagIssueClient,
        forum: IssueDagForumClient,
        run_topic: str = DEFAULT_RUN_TOPIC,
        author: str = "orchestrator",
        scan_limit: int = 20,
    ) -> None:
        self.issue = issue
        self.forum = forum
        self.run_topic = run_topic
        self.author = author
        self.scan_limit = max(1, int(scan_limit))

    def select_next_execution(
        self,
        *,
        role: str,
        program: str,
        root_id: str | None = None,
        tags: list[str] | None = None,
        resume_mode: ResumeMode = "manual",
    ) -> NodeExecutionSelection | None:
        role_name = role.strip()
        if not role_name:
            raise ValueError("role is required")
        program_name = program.strip()
        if not program_name:
            raise ValueError("program is required")
        required_tags = sorted({tag.strip() for tag in (tags or []) if tag.strip()})

        candidate = self.select_next_candidate(
            root_id=root_id,
            tags=required_tags,
            resume_mode=resume_mode,
        )
        if candidate is None:
            return None

        return self.build_selection(
            issue=candidate.issue,
            mode=candidate.mode,
            role=role_name,
            program=program_name,
            root_id=root_id,
            tags=required_tags,
            claim_timestamp=candidate.claim_timestamp,
        )

    def select_next_candidate(
        self,
        *,
        root_id: str | None = None,
        tags: list[str] | None = None,
        resume_mode: ResumeMode = "manual",
    ) -> NodeExecutionCandidate | None:
        normalized_mode = resume_mode.strip().lower()
        if normalized_mode not in ("manual", "resume"):
            raise ValueError("resume_mode must be 'manual' or 'resume'")

        required_tags = sorted({tag.strip() for tag in (tags or []) if tag.strip()})

        if normalized_mode == "resume":
            in_progress = self.issue.resumable(
                limit=self.scan_limit,
                root=root_id,
                tags=required_tags,
            )
            for candidate in self._sort_candidates(in_progress, resume=True):
                issue_payload = dict(candidate)
                issue_id = str(issue_payload.get("id") or "").strip()
                if not issue_id:
                    continue
                return NodeExecutionCandidate(
                    issue=issue_payload,
                    mode="resume",
                    claim_timestamp=self._to_claim_timestamp(
                        candidate.get("updated_at"),
                    ),
                )

        attempted: set[str] = set()
        while True:
            ready_rows = self.issue.ready(
                limit=self.scan_limit,
                root=root_id,
                tags=required_tags,
            )
            pending = [
                row
                for row in self._sort_candidates(ready_rows, resume=False)
                if str(row.get("id") or "").strip()
                and str(row.get("id") or "").strip() not in attempted
            ]
            if not pending:
                return None

            for candidate in pending:
                issue_id = str(candidate.get("id") or "").strip()
                if not issue_id:
                    continue
                attempted.add(issue_id)
                claim = self.issue.claim_ready_leaf(
                    issue_id,
                    root=root_id,
                    tags=required_tags,
                )
                if not bool(claim.get("claimed")):
                    continue

                issue_payload = claim.get("issue")
                if not isinstance(issue_payload, dict):
                    issue_payload = dict(candidate)
                issue_row = dict(issue_payload)
                issue_row_id = str(issue_row.get("id") or "").strip()
                if not issue_row_id:
                    continue
                return NodeExecutionCandidate(
                    issue=issue_row,
                    mode="claim",
                    claim_timestamp=self._to_claim_timestamp(
                        claim.get("claimed_at"),
                    ),
                )

    def build_selection(
        self,
        *,
        issue: dict[str, Any],
        mode: ExecutionMode,
        role: str,
        program: str,
        team: str | None = None,
        root_id: str | None,
        tags: list[str],
        claim_timestamp: int,
        extra_payload: dict[str, Any] | None = None,
    ) -> NodeExecutionSelection | None:
        issue_id = str(issue.get("id") or "").strip()
        if not issue_id:
            return None

        team_name = (team or "").strip() or DEFAULT_SELECTION_TEAM
        status = str(issue.get("status") or "").strip()
        metadata = dict(extra_payload) if isinstance(extra_payload, dict) else {}
        payload = build_node_execute_event(
            issue_id=issue_id,
            team=team_name,
            role=role,
            program=program,
            mode=mode,
            claim_timestamp=claim_timestamp,
            claim_timestamp_iso=self._iso_ms(claim_timestamp),
            root_id=root_id,
            tags=tags,
            status=status or None,
            extra=metadata or None,
        )

        self.forum.post_json(
            f"issue:{issue_id}",
            payload,
            author=self.author,
        )
        self.forum.post_json(
            self.run_topic,
            payload,
            author=self.author,
        )

        return NodeExecutionSelection(
            issue_id=issue_id,
            team=team_name,
            role=role,
            program=program,
            mode=mode,
            claim_timestamp=claim_timestamp,
            issue=issue,
            metadata=metadata,
        )

    def _sort_candidates(
        self,
        rows: list[dict[str, Any]],
        *,
        resume: bool,
    ) -> list[dict[str, Any]]:
        def sort_key(row: dict[str, Any]) -> tuple[int, int, str]:
            priority = self._to_int(row.get("priority"), default=99)
            updated = self._to_int(row.get("updated_at"), default=0)
            issue_id = str(row.get("id") or "")
            if resume:
                return (priority, updated, issue_id)
            return (priority, -updated, issue_id)

        return sorted(rows, key=sort_key)

    @staticmethod
    def _to_int(value: object, *, default: int) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text:
                try:
                    return int(text)
                except ValueError:
                    return default
        return default

    @staticmethod
    def _to_claim_timestamp(value: object) -> int:
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            text = value.strip()
            if text:
                try:
                    return int(text)
                except ValueError:
                    return now_ms()
        return now_ms()

    @staticmethod
    def _iso_ms(value: int) -> str:
        dt = datetime.fromtimestamp(value / 1000.0, tz=timezone.utc)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
