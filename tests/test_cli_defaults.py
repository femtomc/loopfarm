from __future__ import annotations

import pytest

from loopfarm import cli


def test_main_defaults_codex_forward_model_and_reasoning(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    captured = {}

    def fake_run_loop(cfg):
        captured["cfg"] = cfg
        return 0

    monkeypatch.setattr(cli, "run_loop", fake_run_loop)
    monkeypatch.chdir(tmp_path)

    for name in (
        "LOOPFARM_MODEL",
        "LOOPFARM_CODE_MODEL",
        "LOOPFARM_CODE_REASONING",
        "LOOPFARM_PLAN_MODEL",
        "LOOPFARM_PLAN_REASONING",
        "LOOPFARM_REVIEW_MODEL",
        "LOOPFARM_REVIEW_REASONING",
        "LOOPFARM_ARCHITECTURE_MODEL",
        "LOOPFARM_ARCHITECTURE_REASONING",
        "LOOPFARM_DOCUMENTATION_MODEL",
        "LOOPFARM_IMPLEMENTATION_LOOP",
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(SystemExit) as raised:
        cli.main(["--codex", "Implement feature"])

    assert raised.value.code == 0

    cfg = captured["cfg"]
    assert cfg.code_model.model == "gpt-5.3-codex"
    assert cfg.code_model.reasoning == "xhigh"
    assert cfg.mode == "implementation"
    assert cfg.loop_plan_once is True
    assert cfg.loop_steps == (
        ("forward", 1),
        ("documentation", 1),
        ("architecture", 1),
        ("backward", 1),
    )
    assert cfg.loop_report_source_phase == "forward"
    assert cfg.loop_report_target_phases == ("documentation", "architecture", "backward")
    assert cfg.documentation_cli == "gemini"
    assert cfg.architecture_cli == "codex"
    assert cfg.backward_cli == "codex"


def test_main_implementation_loop_parses_repeats(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    captured = {}

    def fake_run_loop(cfg):
        captured["cfg"] = cfg
        return 0

    monkeypatch.setattr(cli, "run_loop", fake_run_loop)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(
            [
                "--mode",
                "implementation",
                "--loop",
                "planning,forward5,documentation,architecture,backward",
                "Improve architecture",
            ]
        )

    assert raised.value.code == 0
    cfg = captured["cfg"]
    assert cfg.loop_plan_once is True
    assert cfg.loop_steps == (
        ("forward", 5),
        ("documentation", 1),
        ("architecture", 1),
        ("backward", 1),
    )


def test_main_implementation_loop_supports_aliases(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    captured = {}

    def fake_run_loop(cfg):
        captured["cfg"] = cfg
        return 0

    monkeypatch.setattr(cli, "run_loop", fake_run_loop)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(
            [
                "--mode",
                "implementation",
                "--loop",
                "plan,fwd:3,docs,perf,review",
                "Improve architecture",
            ]
        )

    assert raised.value.code == 0
    cfg = captured["cfg"]
    assert cfg.loop_plan_once is True
    assert cfg.loop_steps == (
        ("forward", 3),
        ("documentation", 1),
        ("architecture", 1),
        ("backward", 1),
    )


def test_main_rejects_invalid_loop_for_non_implementation_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["--mode", "writing", "--loop", "forward,backward", "Write docs"])

    assert raised.value.code == 2


def test_main_rejects_implementation_flag_with_writing_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["--implementation", "--mode", "writing", "Write docs"])

    assert raised.value.code == 2


def test_main_rejects_research_flag_with_writing_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["--research", "--mode", "writing", "Write docs"])

    assert raised.value.code == 2


def test_main_rejects_conflicting_mode_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["--implementation", "--research", "Investigate runtimes"])

    assert raised.value.code == 2


def test_main_research_mode_defaults_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    captured = {}

    def fake_run_loop(cfg):
        captured["cfg"] = cfg
        return 0

    monkeypatch.setattr(cli, "run_loop", fake_run_loop)
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("LOOPFARM_RESEARCH_LOOP", raising=False)

    with pytest.raises(SystemExit) as raised:
        cli.main(["--mode", "research", "Study actor runtimes"])

    assert raised.value.code == 0
    cfg = captured["cfg"]
    assert cfg.mode == "research"
    assert cfg.loop_plan_once is True
    assert cfg.loop_steps == (("research", 1), ("curation", 1), ("backward", 1))
    assert cfg.loop_report_source_phase is None
    assert cfg.loop_report_target_phases == ()
    assert cfg.research_cli == "codex"
    assert cfg.curation_cli == "codex"


def test_main_research_mode_custom_loop_parses_aliases_and_repeats(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    captured = {}

    def fake_run_loop(cfg):
        captured["cfg"] = cfg
        return 0

    monkeypatch.setattr(cli, "run_loop", fake_run_loop)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(
            [
                "--mode",
                "research",
                "--loop",
                "plan,discovery3,curate,replan",
                "Investigate runtime architecture tradeoffs",
            ]
        )

    assert raised.value.code == 0
    cfg = captured["cfg"]
    assert cfg.mode == "research"
    assert cfg.loop_plan_once is True
    assert cfg.loop_steps == (("research", 3), ("curation", 1), ("backward", 1))


def test_main_phase_plan_flag_uses_canonical_repeat_syntax(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    captured = {}

    def fake_run_loop(cfg):
        captured["cfg"] = cfg
        return 0

    monkeypatch.setattr(cli, "run_loop", fake_run_loop)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(
            [
                "--mode",
                "research",
                "--phase-plan",
                "planning,research*2,curation,backward",
                "Investigate runtime architecture tradeoffs",
            ]
        )

    assert raised.value.code == 0
    cfg = captured["cfg"]
    assert cfg.mode == "research"
    assert cfg.loop_plan_once is True
    assert cfg.loop_steps == (("research", 2), ("curation", 1), ("backward", 1))


def test_main_research_flag_selects_research_mode(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    captured = {}

    def fake_run_loop(cfg):
        captured["cfg"] = cfg
        return 0

    monkeypatch.setattr(cli, "run_loop", fake_run_loop)
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["--research", "Investigate runtimes"])

    assert raised.value.code == 0
    assert captured["cfg"].mode == "research"
