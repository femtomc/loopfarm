from __future__ import annotations

from dataclasses import dataclass

PhaseStep = tuple[str, int]


@dataclass(frozen=True)
class PhaseContract:
    name: str
    consumes: tuple[str, ...]
    produces: tuple[str, ...]
    tracker_writes: tuple[str, ...]
    forum_writes: tuple[str, ...]
    termination_gate: bool = False


@dataclass(frozen=True)
class LoopStateMachine:
    planning_once: bool
    loop_steps: tuple[PhaseStep, ...]
    termination_phase: str


PHASE_CONTRACTS: dict[str, PhaseContract] = {
    "planning": PhaseContract(
        name="planning",
        consumes=("prompt", "repo_state"),
        produces=("issue_plan",),
        tracker_writes=("epic", "leaf_issues"),
        forum_writes=("briefing",),
    ),
    "forward": PhaseContract(
        name="forward",
        consumes=("issue_plan", "repo_state"),
        produces=("code_changes", "phase_summary"),
        tracker_writes=("leaf_issues",),
        forum_writes=("briefing", "forward_report"),
    ),
    "research": PhaseContract(
        name="research",
        consumes=("research_objective", "repo_state"),
        produces=("findings",),
        tracker_writes=("candidate_issues",),
        forum_writes=("research_notes",),
    ),
    "curation": PhaseContract(
        name="curation",
        consumes=("findings",),
        produces=("prioritized_backlog",),
        tracker_writes=("epic", "leaf_issues", "dependencies"),
        forum_writes=("curation_summary",),
    ),
    "documentation": PhaseContract(
        name="documentation",
        consumes=("forward_report", "repo_state"),
        produces=("doc_updates", "phase_summary"),
        tracker_writes=("documentation_issues",),
        forum_writes=("briefing",),
    ),
    "architecture": PhaseContract(
        name="architecture",
        consumes=("forward_report", "repo_state"),
        produces=("architecture_findings",),
        tracker_writes=("implementation_epic",),
        forum_writes=("architecture_summary",),
    ),
    "backward": PhaseContract(
        name="backward",
        consumes=("phase_summaries", "forward_report", "repo_state"),
        produces=("decision", "phase_summary"),
        tracker_writes=("followup_issues",),
        forum_writes=("status", "briefing"),
        termination_gate=True,
    ),
}


def phase_contract(phase: str) -> PhaseContract:
    contract = PHASE_CONTRACTS.get(phase)
    if contract is None:
        raise ValueError(f"unknown phase contract: {phase!r}")
    return contract


def build_state_machine(
    *, planning_once: bool, loop_steps: tuple[PhaseStep, ...]
) -> LoopStateMachine:
    if not loop_steps:
        raise ValueError("loop_steps cannot be empty")
    for phase, repeat in loop_steps:
        phase_contract(phase)
        if repeat < 1:
            raise ValueError(f"repeat count must be >= 1 for phase {phase!r}")
    if "backward" not in {phase for phase, _ in loop_steps}:
        raise ValueError("loop_steps must include backward phase")
    return LoopStateMachine(
        planning_once=planning_once,
        loop_steps=loop_steps,
        termination_phase="backward",
    )


def is_termination_gate(phase: str) -> bool:
    return phase_contract(phase).termination_gate
