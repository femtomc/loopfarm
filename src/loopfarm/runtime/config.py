from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import tomllib


_PHASE_RE = re.compile(r"^([a-z_]+)(?:\*(\d+))?$")
_VALID_PHASES = {
    "planning",
    "forward",
    "research",
    "curation",
    "documentation",
    "architecture",
    "backward",
}
_INJECT_ALIASES = {
    "briefing": "phase_briefing",
    "phase_briefing": "phase_briefing",
    "forward_report": "forward_report",
    "report": "forward_report",
}


@dataclass(frozen=True)
class ProgramPhaseFileConfig:
    cli: str | None = None
    prompt: str | None = None
    model: str | None = None
    reasoning: str | None = None
    inject: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProgramFileConfig:
    name: str
    project: str | None
    loop_plan_once: bool
    loop_steps: tuple[tuple[str, int], ...]
    termination_phase: str
    report_source_phase: str | None
    report_target_phases: tuple[str, ...]
    phases: dict[str, ProgramPhaseFileConfig] = field(default_factory=dict)


@dataclass(frozen=True)
class LoopfarmFileConfig:
    repo_root: Path
    path: Path
    program: ProgramFileConfig | None = None


def _as_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _as_str_tuple(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    out: list[str] = []
    for item in value:
        text = _as_str(item)
        if text:
            out.append(text)
    return tuple(out)


def _parse_step_tokens(value: object) -> list[str]:
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    if isinstance(value, list):
        tokens: list[str] = []
        for item in value:
            text = _as_str(item)
            if text:
                tokens.append(text)
        return tokens
    return []


def _normalize_phase_name(name: str | None) -> str | None:
    if not name:
        return None
    lowered = name.strip().lower()
    if lowered in _VALID_PHASES:
        return lowered
    return None


def _parse_program_steps(value: object) -> tuple[bool, tuple[tuple[str, int], ...]] | None:
    tokens = _parse_step_tokens(value)
    if not tokens:
        return None

    parsed: list[tuple[str, int]] = []
    for token in tokens:
        match = _PHASE_RE.match(token.strip().lower())
        if not match:
            return None
        phase = _normalize_phase_name(match.group(1))
        if not phase:
            return None
        repeat = int(match.group(2)) if match.group(2) else 1
        if repeat < 1:
            return None
        parsed.append((phase, repeat))

    if not parsed:
        return None

    loop_plan_once = False
    if parsed[0][0] == "planning":
        if parsed[0][1] != 1:
            return None
        loop_plan_once = True
        parsed = parsed[1:]

    if not parsed:
        return None

    if any(phase == "planning" for phase, _ in parsed):
        return None

    return loop_plan_once, tuple(parsed)


def _parse_program_phases(raw: object) -> dict[str, ProgramPhaseFileConfig]:
    if not isinstance(raw, dict):
        return {}

    out: dict[str, ProgramPhaseFileConfig] = {}
    for key, value in raw.items():
        if not isinstance(value, dict):
            continue
        phase_name = _normalize_phase_name(str(key))
        if not phase_name:
            continue

        inject: list[str] = []
        for item in _as_str_tuple(value.get("inject")):
            normalized = _INJECT_ALIASES.get(item.strip().lower())
            if normalized and normalized not in inject:
                inject.append(normalized)

        out[phase_name] = ProgramPhaseFileConfig(
            cli=_as_str(value.get("cli")),
            prompt=_as_str(value.get("prompt")),
            model=_as_str(value.get("model")),
            reasoning=_as_str(value.get("reasoning")),
            inject=tuple(inject),
        )

    return out


def _parse_program(raw: object) -> ProgramFileConfig | None:
    if not isinstance(raw, dict):
        return None

    name = _as_str(raw.get("name"))
    if not name:
        return None

    parsed_steps = _parse_program_steps(raw.get("steps"))
    if parsed_steps is None:
        return None
    loop_plan_once, loop_steps = parsed_steps

    termination_phase = _normalize_phase_name(_as_str(raw.get("termination_phase")))
    if not termination_phase:
        return None
    if termination_phase not in {phase for phase, _ in loop_steps}:
        return None

    report_source_phase = _normalize_phase_name(_as_str(raw.get("report_source_phase")))
    if report_source_phase and report_source_phase not in {phase for phase, _ in loop_steps}:
        return None

    report_target_phases: list[str] = []
    loop_phase_names = {phase for phase, _ in loop_steps}
    for item in _as_str_tuple(raw.get("report_target_phases")):
        phase_name = _normalize_phase_name(item)
        if not phase_name:
            return None
        if phase_name not in loop_phase_names:
            return None
        if phase_name not in report_target_phases:
            report_target_phases.append(phase_name)

    return ProgramFileConfig(
        name=name,
        project=_as_str(raw.get("project")),
        loop_plan_once=loop_plan_once,
        loop_steps=loop_steps,
        termination_phase=termination_phase,
        report_source_phase=report_source_phase,
        report_target_phases=tuple(report_target_phases),
        phases=_parse_program_phases(raw.get("phase")),
    )


def load_config(repo_root: Path) -> LoopfarmFileConfig:
    path = repo_root / ".loopfarm" / "loopfarm.toml"
    if not path.exists():
        return LoopfarmFileConfig(repo_root=repo_root, path=path)

    raw: dict[str, Any]
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return LoopfarmFileConfig(repo_root=repo_root, path=path)

    return LoopfarmFileConfig(
        repo_root=repo_root,
        path=path,
        program=_parse_program(raw.get("program")),
    )
