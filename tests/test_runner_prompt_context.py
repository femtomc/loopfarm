from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from loopfarm.runtime.control import ControlCheckpointResult
from loopfarm.runner import CodexPhaseModel, LoopfarmConfig, LoopfarmRunner, StopRequested


def _write_prompts(
    tmp_path: Path,
    *,
    include_placeholder: bool = True,
    include_required_summary: bool = True,
) -> None:
    prompts_root = tmp_path / ".loopfarm" / "prompts"
    prompts_root.mkdir(parents=True)
    for phase in ("planning", "forward", "backward"):
        header = f"{phase.upper()} {{PROMPT}} {{SESSION}} {{PROJECT}}"
        header = (
            header.replace("{PROMPT}", "{{PROMPT}}")
            .replace("{SESSION}", "{{SESSION}}")
            .replace("{PROJECT}", "{{PROJECT}}")
        )
        lines = [header, ""]
        if include_placeholder:
            lines.append("{{DYNAMIC_CONTEXT}}")
            lines.append("")
        lines.append("## Workflow")
        lines.append("Do the thing.")
        if include_required_summary:
            lines.extend(["", "## Required Phase Summary", "Summary goes here.", ""])
        (prompts_root / f"{phase}.md").write_text("\n".join(lines), encoding="utf-8")


def _write_prompt_variants(
    tmp_path: Path,
    *,
    marker: str,
) -> None:
    prompts_root = tmp_path / ".loopfarm" / "prompts"
    prompts_root.mkdir(parents=True, exist_ok=True)
    for phase in ("planning", "forward", "backward"):
        header = f"{marker} {phase.upper()} {{PROMPT}} {{SESSION}} {{PROJECT}}"
        header = (
            header.replace("{PROMPT}", "{{PROMPT}}")
            .replace("{SESSION}", "{{SESSION}}")
            .replace("{PROJECT}", "{{PROJECT}}")
        )
        lines = [header, "", "## Required Phase Summary", "Summary goes here."]
        (prompts_root / f"{phase}.md").write_text("\n".join(lines), encoding="utf-8")


def _cfg(tmp_path: Path) -> LoopfarmConfig:
    prompts_root = tmp_path / ".loopfarm" / "prompts"
    model = CodexPhaseModel(model="test", reasoning="fast")
    return LoopfarmConfig(
        repo_root=tmp_path,
        project="test",
        prompt="Example prompt",
        loop_steps=(("forward", 1), ("backward", 1)),
        termination_phase="backward",
        phase_models=(
            ("planning", model),
            ("forward", model),
            ("backward", model),
        ),
        phase_cli_overrides=(
            ("planning", "claude"),
            ("forward", "claude"),
            ("backward", "claude"),
        ),
        phase_prompt_overrides=(
            ("planning", str(prompts_root / "planning.md")),
            ("forward", str(prompts_root / "forward.md")),
            ("backward", str(prompts_root / "backward.md")),
        ),
    )


def test_build_phase_prompt_injects_session_context(tmp_path: Path) -> None:
    _write_prompts(tmp_path)
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.session_context_override = "Pinned guidance"

    prompt = runner._build_phase_prompt("sess", "planning")

    assert "PLANNING Example prompt sess test" in prompt
    assert "## Session Context" in prompt
    assert "Pinned guidance" in prompt
    assert "## Operator Context" not in prompt
    assert "## Required Phase Summary" in prompt
    assert prompt.index("## Session Context") < prompt.index("## Required Phase Summary")


def test_session_context_persists_across_phases(tmp_path: Path) -> None:
    _write_prompts(tmp_path)
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.session_context_override = "Carry over"

    prompt_one = runner._build_phase_prompt("sess", "planning")
    prompt_two = runner._build_phase_prompt("sess", "forward")

    assert "Carry over" in prompt_one
    assert "Carry over" in prompt_two


def test_build_phase_prompt_without_context_returns_base(tmp_path: Path) -> None:
    _write_prompts(tmp_path)
    runner = LoopfarmRunner(_cfg(tmp_path))

    prompt = runner._build_phase_prompt("sess", "forward")

    assert "FORWARD Example prompt sess test" in prompt
    assert "## Session Context" not in prompt
    assert "## Operator Context" not in prompt
    assert "{{DYNAMIC_CONTEXT}}" not in prompt


def test_prompt_injects_context_before_summary_without_placeholder(
    tmp_path: Path,
) -> None:
    _write_prompts(tmp_path, include_placeholder=False)
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.session_context_override = "Pinned guidance"

    prompt = runner._build_phase_prompt("sess", "forward")

    assert "## Session Context" in prompt
    assert prompt.index("## Session Context") < prompt.index("## Required Phase Summary")


def test_control_checkpoint_pause_then_resume(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_prompts(tmp_path)
    runner = LoopfarmRunner(_cfg(tmp_path))

    monkeypatch.setattr(
        runner.control_plane,
        "checkpoint",
        lambda **_kwargs: ControlCheckpointResult(
            paused=False,
            session_status="running",
            last_signature="sig-1",
            stop_requested=False,
        ),
    )

    runner._control_checkpoint(session_id="sess", phase="forward", iteration=1)

    assert runner.paused is False
    assert runner.session_status == "running"


def test_control_checkpoint_stop_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_prompts(tmp_path)
    runner = LoopfarmRunner(_cfg(tmp_path))

    monkeypatch.setattr(
        runner.control_plane,
        "checkpoint",
        lambda **_kwargs: ControlCheckpointResult(
            paused=False,
            session_status="stopped",
            last_signature="sig-stop",
            stop_requested=True,
        ),
    )

    with pytest.raises(StopRequested):
        runner._control_checkpoint(session_id="sess", phase="forward", iteration=1)

    assert runner.session_status == "stopped"


def test_load_session_context_override_from_store(tmp_path: Path) -> None:
    _write_prompts(tmp_path)
    runner = LoopfarmRunner(_cfg(tmp_path))
    runner.session_store.update_session_meta(
        "sess",
        {"session_context": "Pinned guidance"},
        author="tester",
    )

    runner._load_session_context_override("sess")

    assert runner.session_context_override == "Pinned guidance"


def test_prompt_paths_use_explicit_phase_templates(tmp_path: Path) -> None:
    _write_prompt_variants(tmp_path, marker="BASE")

    cfg = replace(_cfg(tmp_path), phase_cli_overrides=(("planning", "codex"), ("forward", "codex"), ("backward", "codex")))
    runner = LoopfarmRunner(cfg)

    planning_prompt = runner._render_phase_prompt("sess", "planning")
    forward_prompt = runner._render_phase_prompt("sess", "forward")
    backward_prompt = runner._render_phase_prompt("sess", "backward")

    assert planning_prompt.startswith("BASE PLANNING")
    assert backward_prompt.startswith("BASE BACKWARD")
    assert forward_prompt.startswith("BASE FORWARD")


def test_injections_are_explicit_only(tmp_path: Path) -> None:
    _write_prompt_variants(tmp_path, marker="BASE")

    runner_no_injection = LoopfarmRunner(_cfg(tmp_path))
    no_injection = runner_no_injection._build_phase_prompt("sess", "forward")
    assert "## Phase Briefing" not in no_injection

    cfg = replace(_cfg(tmp_path), phase_injections=(("forward", ("phase_briefing",)),))
    runner_with_injection = LoopfarmRunner(cfg)
    runner_with_injection.session_store.store_phase_summary(
        "sess", "planning", 0, "plan summary"
    )

    injected = runner_with_injection._build_phase_prompt("sess", "forward")
    assert "## Phase Briefing" in injected
    assert "plan summary" in injected
