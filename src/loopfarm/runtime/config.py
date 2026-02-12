from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import tomllib


_STEP_RE = re.compile(r"^([a-zA-Z][a-zA-Z0-9_-]*)(?:\*(\d+))?$")
_PHASE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
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
    error: str | None = None


class ConfigValidationError(ValueError):
    pass


def _as_str(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _as_str_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConfigValidationError(f"{field} must be an array of strings")

    out: list[str] = []
    for idx, item in enumerate(value):
        text = _as_str(item)
        if text is None:
            raise ConfigValidationError(f"{field}[{idx}] must be a non-empty string")
        out.append(text)
    return tuple(out)


def _phase_name_help() -> str:
    return "phase names must match [a-z][a-z0-9_-]*"


def _parse_step_tokens(value: object) -> list[str]:
    field = "[program].steps"
    if value is None:
        raise ConfigValidationError("missing [program].steps")

    if isinstance(value, str):
        tokens = [part.strip() for part in value.split(",") if part.strip()]
        if not tokens:
            raise ConfigValidationError("missing or empty [program].steps")
        return tokens

    if isinstance(value, list):
        tokens: list[str] = []
        for idx, item in enumerate(value):
            text = _as_str(item)
            if text is None:
                raise ConfigValidationError(f"{field}[{idx}] must be a non-empty string")
            tokens.append(text)
        if not tokens:
            raise ConfigValidationError("missing or empty [program].steps")
        return tokens

    raise ConfigValidationError(
        f"{field} must be a comma-separated string or an array of strings"
    )


def _normalize_phase_name(name: str | None) -> str | None:
    if not name:
        return None
    lowered = name.strip().lower()
    if _PHASE_NAME_RE.match(lowered):
        return lowered
    return None


def _parse_program_steps(value: object) -> tuple[tuple[str, int], ...]:
    tokens = _parse_step_tokens(value)

    parsed: list[tuple[str, int]] = []
    for token in tokens:
        match = _STEP_RE.match(token.strip())
        if not match:
            raise ConfigValidationError(
                f"invalid step token in [program].steps: {token!r}"
            )
        phase = _normalize_phase_name(match.group(1))
        if not phase:
            raise ConfigValidationError(
                f"invalid phase in [program].steps: {match.group(1)!r} "
                f"({_phase_name_help()})"
            )
        repeat = int(match.group(2)) if match.group(2) else 1
        if repeat < 1:
            raise ConfigValidationError(
                f"invalid repeat count in [program].steps: {token!r}"
            )
        parsed.append((phase, repeat))

    if not parsed:
        raise ConfigValidationError("[program].steps must include at least one phase")

    return tuple(parsed)


def _parse_program_phases(raw: object) -> dict[str, ProgramPhaseFileConfig]:
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigValidationError("[program.phase] must be a table")

    out: dict[str, ProgramPhaseFileConfig] = {}
    for key, value in raw.items():
        phase_name = _normalize_phase_name(str(key))
        if not phase_name:
            raise ConfigValidationError(
                f"invalid [program.phase] entry: {key!r} is not a valid phase "
                f"({_phase_name_help()})"
            )
        if not isinstance(value, dict):
            raise ConfigValidationError(
                f"[program.phase.{phase_name}] must be a table"
            )
        if phase_name in out:
            raise ConfigValidationError(
                f"duplicate phase config for [program.phase.{phase_name}]"
            )

        inject: list[str] = []
        for item in _as_str_tuple(
            value.get("inject"),
            field=f"[program.phase.{phase_name}].inject",
        ):
            normalized = _INJECT_ALIASES.get(item.strip().lower())
            if not normalized:
                raise ConfigValidationError(
                    f"invalid inject value in [program.phase.{phase_name}].inject: {item!r}"
                )
            if normalized not in inject:
                inject.append(normalized)

        out[phase_name] = ProgramPhaseFileConfig(
            cli=_as_str(value.get("cli")),
            prompt=_as_str(value.get("prompt")),
            model=_as_str(value.get("model")),
            reasoning=_as_str(value.get("reasoning")),
            inject=tuple(inject),
        )

    return out


def _parse_program(raw: object) -> ProgramFileConfig:
    if raw is None:
        raise ConfigValidationError("missing [program] section")
    if not isinstance(raw, dict):
        raise ConfigValidationError("[program] must be a table")

    name = _as_str(raw.get("name"))
    if not name:
        raise ConfigValidationError("missing [program].name")

    loop_steps = _parse_program_steps(raw.get("steps"))
    loop_phase_names = {phase for phase, _ in loop_steps}

    termination_raw = _as_str(raw.get("termination_phase"))
    if not termination_raw:
        raise ConfigValidationError("missing [program].termination_phase")
    termination_phase = _normalize_phase_name(termination_raw)
    if not termination_phase:
        raise ConfigValidationError(
            f"invalid [program].termination_phase: {termination_raw!r} "
            f"({_phase_name_help()})"
        )
    if termination_phase not in loop_phase_names:
        raise ConfigValidationError(
            f"[program].termination_phase {termination_phase!r} is not present in [program].steps"
        )

    report_source_phase: str | None = None
    report_source_raw = raw.get("report_source_phase")
    if report_source_raw is not None:
        report_source_text = _as_str(report_source_raw)
        if not report_source_text:
            raise ConfigValidationError(
                "[program].report_source_phase must be a non-empty string when set"
            )
        report_source_phase = _normalize_phase_name(report_source_text)
        if not report_source_phase:
            raise ConfigValidationError(
                f"invalid [program].report_source_phase: {report_source_text!r} "
                f"({_phase_name_help()})"
            )
        if report_source_phase not in loop_phase_names:
            raise ConfigValidationError(
                f"[program].report_source_phase {report_source_phase!r} is not present in [program].steps"
            )

    report_target_phases: list[str] = []
    for item in _as_str_tuple(
        raw.get("report_target_phases"),
        field="[program].report_target_phases",
    ):
        phase_name = _normalize_phase_name(item)
        if not phase_name:
            raise ConfigValidationError(
                f"invalid [program].report_target_phases entry: {item!r} "
                f"({_phase_name_help()})"
            )
        if phase_name not in loop_phase_names:
            raise ConfigValidationError(
                f"[program].report_target_phases entry {phase_name!r} is not present in [program].steps"
            )
        if phase_name not in report_target_phases:
            report_target_phases.append(phase_name)

    return ProgramFileConfig(
        name=name,
        project=_as_str(raw.get("project")),
        loop_steps=loop_steps,
        termination_phase=termination_phase,
        report_source_phase=report_source_phase,
        report_target_phases=tuple(report_target_phases),
        phases=_parse_program_phases(raw.get("phase")),
    )


def _format_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except Exception:
        return str(path)


def load_config(repo_root: Path) -> LoopfarmFileConfig:
    path = repo_root / ".loopfarm" / "loopfarm.toml"
    if not path.exists():
        return LoopfarmFileConfig(
            repo_root=repo_root,
            path=path,
            error=f"config file not found: {_format_path(path, repo_root)}",
        )

    raw: dict[str, Any]
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return LoopfarmFileConfig(
            repo_root=repo_root,
            path=path,
            error=f"invalid TOML in {_format_path(path, repo_root)}: {exc}",
        )

    try:
        program = _parse_program(raw.get("program"))
    except ConfigValidationError as exc:
        return LoopfarmFileConfig(
            repo_root=repo_root,
            path=path,
            error=str(exc),
        )

    return LoopfarmFileConfig(
        repo_root=repo_root,
        path=path,
        program=program,
    )
