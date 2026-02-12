from __future__ import annotations

from pathlib import Path

import pytest

from loopfarm.backends.claude import ClaudeBackend
from loopfarm.backends.codex import CodexBackend
from loopfarm.backends.gemini import GeminiBackend
from loopfarm.backends.kimi import KimiBackend
from loopfarm.runner import CodexPhaseModel, LoopfarmConfig


def _cfg(tmp_path: Path) -> LoopfarmConfig:
    return LoopfarmConfig(
        repo_root=tmp_path,
        project="test",
        prompt="Example prompt",
        loop_steps=(("forward", 1), ("backward", 1)),
        termination_phase="backward",
        phase_models=(
            ("planning", CodexPhaseModel(model="plan-model", reasoning="xhigh")),
            ("forward", CodexPhaseModel(model="code-model", reasoning="high")),
            ("research", CodexPhaseModel(model="research-model", reasoning="xhigh")),
            ("curation", CodexPhaseModel(model="curation-model", reasoning="high")),
            (
                "documentation",
                CodexPhaseModel(model="docs-model", reasoning="medium"),
            ),
            ("architecture", CodexPhaseModel(model="arch-model", reasoning="xhigh")),
            ("backward", CodexPhaseModel(model="review-model", reasoning="low")),
        ),
        phase_cli_overrides=(
            ("planning", "codex"),
            ("forward", "codex"),
            ("research", "codex"),
            ("curation", "codex"),
            ("documentation", "gemini"),
            ("architecture", "codex"),
            ("backward", "codex"),
        ),
        phase_prompt_overrides=(
            ("planning", "planning.md"),
            ("forward", "forward.md"),
            ("research", "research.md"),
            ("curation", "curation.md"),
            ("documentation", "documentation.md"),
            ("architecture", "architecture.md"),
            ("backward", "backward.md"),
        ),
    )


def _flag_value(argv: list[str], flag: str) -> str:
    idx = argv.index(flag)
    return argv[idx + 1]


def test_claude_backend_build_argv_appends_prompt(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    backend = ClaudeBackend()

    argv = backend.build_argv(
        phase="forward",
        prompt="Hello",
        last_message_path=tmp_path / "last.txt",
        cfg=cfg,
    )

    assert argv[0] == "claude"
    assert "--output-format" in argv
    assert "stream-json" in argv
    assert _flag_value(argv, "--model") == "code-model"
    assert argv[-1] == "Hello"


@pytest.mark.parametrize(
    ("phase", "expected_model", "expected_reasoning"),
    [
        ("planning", "plan-model", "xhigh"),
        ("forward", "code-model", "high"),
        ("research", "research-model", "xhigh"),
        ("curation", "curation-model", "high"),
        ("documentation", "docs-model", "medium"),
        ("architecture", "arch-model", "xhigh"),
        ("backward", "review-model", "low"),
    ],
)
def test_codex_backend_build_argv_uses_phase_models(
    tmp_path: Path, phase: str, expected_model: str, expected_reasoning: str
) -> None:
    cfg = _cfg(tmp_path)
    backend = CodexBackend()
    last_path = tmp_path / f"{phase}.last.txt"

    argv = backend.build_argv(
        phase=phase,
        prompt="Prompt",
        last_message_path=last_path,
        cfg=cfg,
    )

    assert argv[:2] == ["codex", "exec"]
    assert "--json" in argv
    assert _flag_value(argv, "-C") == str(tmp_path)
    assert _flag_value(argv, "-m") == expected_model
    assert _flag_value(argv, "-c") == f"reasoning={expected_reasoning}"
    assert _flag_value(argv, "--output-last-message") == str(last_path)


def test_kimi_backend_build_argv_includes_workdir_and_prompt(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    backend = KimiBackend()

    argv = backend.build_argv(
        phase="forward",
        prompt="Draft",
        last_message_path=tmp_path / "last.txt",
        cfg=cfg,
    )

    assert argv[0] == "kimi"
    assert _flag_value(argv, "--work-dir") == str(tmp_path)
    assert _flag_value(argv, "-p") == "Draft"


def test_gemini_backend_build_argv_includes_model_and_prompt(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    backend = GeminiBackend()

    argv = backend.build_argv(
        phase="documentation",
        prompt="Update docs",
        last_message_path=tmp_path / "last.txt",
        cfg=cfg,
    )

    assert argv[0] == "gemini"
    assert _flag_value(argv, "--approval-mode") == "yolo"
    assert _flag_value(argv, "--output-format") == "text"
    assert _flag_value(argv, "--model") == "docs-model"
    assert _flag_value(argv, "--prompt") == "Update docs"
