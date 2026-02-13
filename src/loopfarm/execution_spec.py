from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


DEFAULT_SPEC_CLI = "codex"
DEFAULT_SPEC_MODEL = "gpt-5.2"
DEFAULT_SPEC_REASONING = "xhigh"
DEFAULT_SPEC_PHASE = "role"


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    if not text:
        raise ValueError(f"{field} cannot be empty")
    return text


def _normalize_optional_text(value: object, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string")
    text = value.strip()
    return text or None


def _normalize_repeat(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer >= 1")
    if isinstance(value, int):
        repeat = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field} cannot be empty")
        try:
            repeat = int(text)
        except ValueError as exc:
            raise ValueError(f"{field} must be an integer >= 1") from exc
    else:
        raise ValueError(f"{field} must be an integer >= 1")
    if repeat < 1:
        raise ValueError(f"{field} must be >= 1")
    return repeat


@dataclass(frozen=True)
class ExecutionLoopStep:
    phase: str
    repeat: int

    def to_tuple(self) -> tuple[str, int]:
        return (self.phase, self.repeat)

    def to_dict(self) -> dict[str, Any]:
        return {"phase": self.phase, "repeat": self.repeat}


@dataclass(frozen=True)
class ExecutionSpec:
    version: int
    role: str
    prompt_path: str
    team: str | None
    loop_steps: tuple[ExecutionLoopStep, ...]
    termination_phase: str
    default_cli: str
    default_model: str
    default_reasoning: str
    phase_cli: dict[str, str]
    phase_models: dict[str, dict[str, str]]
    phase_prompts: dict[str, str]
    control_flow: dict[str, Any]

    def loop_step_tuples(self) -> tuple[tuple[str, int], ...]:
        return tuple(step.to_tuple() for step in self.loop_steps)

    def cli_for_phase(self, phase: str) -> str:
        override = self.phase_cli.get(phase)
        if override:
            return override
        return self.default_cli

    def model_for_phase(self, phase: str) -> tuple[str, str]:
        phase_model = self.phase_models.get(phase) or {}
        model = str(phase_model.get("model") or "").strip() or self.default_model
        reasoning = (
            str(phase_model.get("reasoning") or "").strip() or self.default_reasoning
        )
        return (model, reasoning)

    def prompt_for_phase(self, phase: str) -> str | None:
        prompt = str(self.phase_prompts.get(phase) or "").strip()
        if prompt:
            return prompt
        if phase == DEFAULT_SPEC_PHASE:
            return self.prompt_path
        return None

    def resolved_prompt_path(self, *, repo_root: Path) -> Path:
        raw = self.prompt_path.strip()
        path = Path(raw)
        if path.is_absolute():
            return path
        return repo_root / path

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "role": self.role,
            "prompt_path": self.prompt_path,
            "team": self.team,
            "loop_steps": [step.to_dict() for step in self.loop_steps],
            "termination_phase": self.termination_phase,
            "default_cli": self.default_cli,
            "default_model": self.default_model,
            "default_reasoning": self.default_reasoning,
            "phase_cli": dict(self.phase_cli),
            "phase_models": {
                phase: {
                    "model": str(cfg.get("model") or ""),
                    "reasoning": str(cfg.get("reasoning") or ""),
                }
                for phase, cfg in self.phase_models.items()
            },
            "phase_prompts": dict(self.phase_prompts),
            "control_flow": dict(self.control_flow),
        }


def parse_execution_spec(value: object) -> ExecutionSpec:
    if not isinstance(value, Mapping):
        raise ValueError("execution_spec must be a JSON object")

    raw_version = value.get("version", 1)
    if isinstance(raw_version, bool):
        raise ValueError("execution_spec.version must be an integer")
    if isinstance(raw_version, int):
        version = raw_version
    elif isinstance(raw_version, str):
        text = raw_version.strip()
        if not text:
            raise ValueError("execution_spec.version cannot be empty")
        try:
            version = int(text)
        except ValueError as exc:
            raise ValueError("execution_spec.version must be an integer") from exc
    else:
        raise ValueError("execution_spec.version must be an integer")
    if version < 1:
        raise ValueError("execution_spec.version must be >= 1")

    role = _require_text(value.get("role"), "execution_spec.role")
    prompt_path = _normalize_optional_text(
        value.get("prompt_path"), "execution_spec.prompt_path"
    ) or f".loopfarm/roles/{role}.md"
    team = _normalize_optional_text(value.get("team"), "execution_spec.team")

    default_cli = (
        _normalize_optional_text(value.get("default_cli"), "execution_spec.default_cli")
        or _normalize_optional_text(value.get("cli"), "execution_spec.cli")
        or DEFAULT_SPEC_CLI
    )
    default_model = (
        _normalize_optional_text(
            value.get("default_model"), "execution_spec.default_model"
        )
        or _normalize_optional_text(value.get("model"), "execution_spec.model")
        or DEFAULT_SPEC_MODEL
    )
    default_reasoning = (
        _normalize_optional_text(
            value.get("default_reasoning"), "execution_spec.default_reasoning"
        )
        or _normalize_optional_text(
            value.get("reasoning"), "execution_spec.reasoning"
        )
        or DEFAULT_SPEC_REASONING
    )

    loop_steps = _parse_loop_steps(value.get("loop_steps"))
    if not loop_steps:
        loop_steps = (ExecutionLoopStep(phase=DEFAULT_SPEC_PHASE, repeat=1),)
    phase_names = {step.phase for step in loop_steps}

    termination_phase = (
        _normalize_optional_text(
            value.get("termination_phase"), "execution_spec.termination_phase"
        )
        or loop_steps[-1].phase
    )
    if termination_phase not in phase_names:
        raise ValueError(
            "execution_spec.termination_phase must reference a phase in loop_steps"
        )

    phase_cli = _parse_phase_cli(value.get("phase_cli"), known_phases=phase_names)
    phase_models = _parse_phase_models(
        value.get("phase_models"),
        known_phases=phase_names,
    )
    phase_prompts = _parse_phase_prompts(
        value.get("phase_prompts"),
        known_phases=phase_names,
    )

    raw_control_flow = value.get("control_flow")
    control_flow: dict[str, Any]
    if raw_control_flow is None:
        control_flow = {}
    elif isinstance(raw_control_flow, Mapping):
        control_flow = {
            str(key): raw_control_flow[key] for key in raw_control_flow
        }
    else:
        raise ValueError("execution_spec.control_flow must be an object")

    return ExecutionSpec(
        version=version,
        role=role,
        prompt_path=prompt_path,
        team=team,
        loop_steps=loop_steps,
        termination_phase=termination_phase,
        default_cli=default_cli,
        default_model=default_model,
        default_reasoning=default_reasoning,
        phase_cli=phase_cli,
        phase_models=phase_models,
        phase_prompts=phase_prompts,
        control_flow=control_flow,
    )


def normalize_execution_spec_payload(value: object) -> dict[str, Any]:
    return parse_execution_spec(value).to_dict()


def _parse_loop_steps(value: object) -> tuple[ExecutionLoopStep, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("execution_spec.loop_steps must be a list")

    out: list[ExecutionLoopStep] = []
    for idx, item in enumerate(value):
        field = f"execution_spec.loop_steps[{idx}]"
        if isinstance(item, Mapping):
            phase = _require_text(item.get("phase"), f"{field}.phase")
            repeat = _normalize_repeat(item.get("repeat", 1), f"{field}.repeat")
            out.append(ExecutionLoopStep(phase=phase, repeat=repeat))
            continue
        if isinstance(item, list) and len(item) == 2:
            phase = _require_text(item[0], f"{field}[0]")
            repeat = _normalize_repeat(item[1], f"{field}[1]")
            out.append(ExecutionLoopStep(phase=phase, repeat=repeat))
            continue
        raise ValueError(
            f"{field} must be {{phase, repeat}} or [phase, repeat]"
        )
    return tuple(out)


def _parse_phase_cli(
    value: object,
    *,
    known_phases: set[str],
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("execution_spec.phase_cli must be an object")

    out: dict[str, str] = {}
    for key, raw in value.items():
        phase = _require_text(key, "execution_spec.phase_cli phase")
        if phase not in known_phases:
            raise ValueError(
                f"execution_spec.phase_cli references unknown phase {phase!r}"
            )
        out[phase] = _require_text(raw, f"execution_spec.phase_cli[{phase}]")
    return out


def _parse_phase_models(
    value: object,
    *,
    known_phases: set[str],
) -> dict[str, dict[str, str]]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("execution_spec.phase_models must be an object")

    out: dict[str, dict[str, str]] = {}
    for key, raw_cfg in value.items():
        phase = _require_text(key, "execution_spec.phase_models phase")
        if phase not in known_phases:
            raise ValueError(
                f"execution_spec.phase_models references unknown phase {phase!r}"
            )
        if not isinstance(raw_cfg, Mapping):
            raise ValueError(
                f"execution_spec.phase_models[{phase}] must be an object"
            )
        model = _normalize_optional_text(
            raw_cfg.get("model"),
            f"execution_spec.phase_models[{phase}].model",
        )
        reasoning = _normalize_optional_text(
            raw_cfg.get("reasoning"),
            f"execution_spec.phase_models[{phase}].reasoning",
        )
        if model is None and reasoning is None:
            continue
        out[phase] = {
            "model": model or DEFAULT_SPEC_MODEL,
            "reasoning": reasoning or DEFAULT_SPEC_REASONING,
        }
    return out


def _parse_phase_prompts(
    value: object,
    *,
    known_phases: set[str],
) -> dict[str, str]:
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError("execution_spec.phase_prompts must be an object")

    out: dict[str, str] = {}
    for key, raw_prompt in value.items():
        phase = _require_text(key, "execution_spec.phase_prompts phase")
        if phase not in known_phases:
            raise ValueError(
                f"execution_spec.phase_prompts references unknown phase {phase!r}"
            )
        out[phase] = _require_text(
            raw_prompt,
            f"execution_spec.phase_prompts[{phase}]",
        )
    return out
