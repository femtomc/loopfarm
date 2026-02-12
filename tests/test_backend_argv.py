from __future__ import annotations

from pathlib import Path

import pytest

from loopfarm.backends.claude import ClaudeBackend
from loopfarm.backends.codex import CodexBackend
from loopfarm.backends.gemini import GeminiBackend
from loopfarm.backends.kimi import KimiBackend
from loopfarm.runner import CodexPhaseModel, LoopfarmConfig


def _cfg(tmp_path: Path, *, model_override: str | None = None) -> LoopfarmConfig:
    return LoopfarmConfig(
        repo_root=tmp_path,
        cli="codex",
        model_override=model_override,
        skip_plan=True,
        project="test",
        prompt="Example prompt",
        code_model=CodexPhaseModel(model="code-model", reasoning="high"),
        plan_model=CodexPhaseModel(model="plan-model", reasoning="xhigh"),
        review_model=CodexPhaseModel(model="review-model", reasoning="low"),
        architecture_model=CodexPhaseModel(model="arch-model", reasoning="xhigh"),
        documentation_model="gemini-3-pro-preview",
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
    assert argv[-1] == "Hello"


def test_claude_backend_build_argv_includes_model_override(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, model_override="claude-test")
    backend = ClaudeBackend()

    argv = backend.build_argv(
        phase="forward",
        prompt="Hi",
        last_message_path=tmp_path / "last.txt",
        cfg=cfg,
    )

    assert _flag_value(argv, "--model") == "claude-test"


@pytest.mark.parametrize(
    ("phase", "expected_model", "expected_reasoning"),
    [
        ("planning", "plan-model", "xhigh"),
        ("forward", "code-model", "high"),
        ("research", "plan-model", "xhigh"),
        ("curation", "plan-model", "xhigh"),
        ("documentation", "review-model", "low"),
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


@pytest.mark.parametrize(
    ("phase", "expected_reasoning"),
    [
        ("planning", "xhigh"),
        ("forward", "high"),
        ("research", "xhigh"),
        ("curation", "xhigh"),
        ("documentation", "low"),
        ("architecture", "xhigh"),
        ("backward", "low"),
    ],
)
def test_codex_backend_build_argv_respects_model_override(
    tmp_path: Path, phase: str, expected_reasoning: str
) -> None:
    cfg = _cfg(tmp_path, model_override="override-model")
    backend = CodexBackend()
    last_path = tmp_path / f"{phase}.last.txt"

    argv = backend.build_argv(
        phase=phase,
        prompt="Prompt",
        last_message_path=last_path,
        cfg=cfg,
    )

    assert _flag_value(argv, "-m") == "override-model"
    assert _flag_value(argv, "-c") == f"reasoning={expected_reasoning}"


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
    assert _flag_value(argv, "--model") == "gemini-3-pro-preview"
    assert _flag_value(argv, "--prompt") == "Update docs"


def test_gemini_backend_build_argv_respects_model_override(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path, model_override="gemini-3-pro")
    backend = GeminiBackend()

    argv = backend.build_argv(
        phase="documentation",
        prompt="Update docs",
        last_message_path=tmp_path / "last.txt",
        cfg=cfg,
    )

    assert _flag_value(argv, "--model") == "gemini-3-pro"
