from __future__ import annotations

import re
from dataclasses import dataclass

TOKEN_RE = re.compile(r"^([a-z_/-]+?)(?:(?:\*|:)?(\d+))?$")

PHASE_ALIASES: dict[str, str] = {
    "plan": "planning",
    "planning": "planning",
    "forward": "forward",
    "fwd": "forward",
    "research": "research",
    "investigate": "research",
    "discovery": "research",
    "curation": "curation",
    "curate": "curation",
    "triage": "curation",
    "documentation": "documentation",
    "docs": "documentation",
    "doc": "documentation",
    "architecture": "architecture",
    "arch": "architecture",
    "performance": "architecture",
    "perf": "architecture",
    "backward": "backward",
    "review": "backward",
    "replan": "backward",
    "replanning": "backward",
}


@dataclass(frozen=True)
class LoopPlan:
    plan_once: bool
    steps: tuple[tuple[str, int], ...]


def parse_loop_plan(spec: str) -> LoopPlan:
    tokens = [part.strip().lower() for part in spec.split(",") if part.strip()]
    if not tokens:
        raise ValueError("phase plan cannot be empty")

    parsed: list[tuple[str, int]] = []
    for token in tokens:
        match = TOKEN_RE.match(token)
        if not match:
            raise ValueError(f"invalid phase token: {token!r}")
        raw_name = match.group(1) or ""
        repeat_raw = match.group(2)
        phase = PHASE_ALIASES.get(raw_name)
        if phase is None:
            raise ValueError(f"unknown phase in plan: {raw_name!r}")
        repeat = int(repeat_raw) if repeat_raw else 1
        if repeat < 1:
            raise ValueError(f"repeat count must be >= 1 for token: {token!r}")
        if phase in {"planning", "backward"} and repeat != 1:
            raise ValueError(
                f"repeat counts are not supported for {phase} (token: {token!r})"
            )
        parsed.append((phase, repeat))

    plan_once = False
    if parsed and parsed[0][0] == "planning":
        plan_once = True
        parsed = parsed[1:]
    if any(name == "planning" for name, _ in parsed):
        raise ValueError("planning may only appear at the start of the phase plan")
    if not parsed:
        raise ValueError("phase plan must include at least one loop phase")
    if not any(name == "backward" for name, _ in parsed):
        raise ValueError(
            "phase plan must include a backward phase for completion checks"
        )

    return LoopPlan(plan_once=plan_once, steps=tuple(parsed))
