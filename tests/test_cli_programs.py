from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopfarm import cli


def _write_program_file(tmp_path: Path, rel_path: str, *, body: str) -> None:
    path = tmp_path / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip() + "\n", encoding="utf-8")


def _write_legacy_program(tmp_path: Path, *, name: str = "impl") -> None:
    _write_program_file(
        tmp_path,
        ".loopfarm/loopfarm.toml",
        body=_minimal_program_toml(name=name),
    )


def _minimal_program_toml(*, name: str) -> str:
    return f"""
[program]
name = "{name}"
steps = ["planning", "forward"]
termination_phase = "forward"
"""


def _detailed_program_toml(*, name: str = "implementation") -> str:
    return f"""
[program]
name = "{name}"
project = "agent-core"
steps = ["planning", "forward*2", "documentation", "backward"]
termination_phase = "backward"
report_source_phase = "forward"
report_target_phases = ["documentation", "backward"]

[program.phase.planning]
cli = "codex"
prompt = ".loopfarm/prompts/planning.md"
model = "gpt-5"
reasoning = "high"

[program.phase.forward]
cli = "codex"
prompt = ".loopfarm/prompts/forward.md"
model = "gpt-5"
reasoning = "xhigh"
inject = ["phase_briefing", "forward_report"]

[program.phase.documentation]
cli = "claude"
prompt = ".loopfarm/prompts/documentation.md"
model = "claude-sonnet-4"
reasoning = "medium"
inject = ["report"]

[program.phase.research]
cli = "codex"
prompt = ".loopfarm/prompts/research.md"
model = "gpt-5-mini"
"""


def test_programs_defaults_to_list_for_legacy_program(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_legacy_program(tmp_path, name="legacy")
    monkeypatch.chdir(tmp_path)

    cli.main(["programs"])

    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["legacy\t.loopfarm/loopfarm.toml"]


def test_programs_list_sorts_by_program_name_for_programs_dir_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_program_file(
        tmp_path,
        ".loopfarm/programs/a.toml",
        body=_minimal_program_toml(name="zeta"),
    )
    _write_program_file(
        tmp_path,
        ".loopfarm/programs/b.toml",
        body=_minimal_program_toml(name="alpha"),
    )
    monkeypatch.chdir(tmp_path)

    cli.main(["programs", "list"])

    out = capsys.readouterr().out.strip().splitlines()
    assert out == [
        "alpha\t.loopfarm/programs/b.toml",
        "zeta\t.loopfarm/programs/a.toml",
    ]


def test_programs_list_handles_mixed_legacy_and_directory_sources(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_legacy_program(tmp_path, name="legacy")
    _write_program_file(
        tmp_path,
        ".loopfarm/programs/a.toml",
        body=_minimal_program_toml(name="alpha"),
    )
    monkeypatch.chdir(tmp_path)

    cli.main(["programs", "list"])

    out = capsys.readouterr().out.strip().splitlines()
    assert out == [
        "alpha\t.loopfarm/programs/a.toml",
        "legacy\t.loopfarm/loopfarm.toml",
    ]


def test_programs_list_json_outputs_stable_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_legacy_program(tmp_path, name="legacy")
    _write_program_file(
        tmp_path,
        ".loopfarm/programs/b.toml",
        body=_minimal_program_toml(name="alpha"),
    )
    monkeypatch.chdir(tmp_path)

    cli.main(["programs", "list", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert payload == [
        {"name": "alpha", "path": ".loopfarm/programs/b.toml"},
        {"name": "legacy", "path": ".loopfarm/loopfarm.toml"},
    ]
    assert all(set(row.keys()) == {"name", "path"} for row in payload)


def test_programs_list_rich_output_renders_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_legacy_program(tmp_path, name="legacy")
    monkeypatch.chdir(tmp_path)

    cli.main(["programs", "list", "--output", "rich"])

    out = capsys.readouterr().out
    assert "Loop Programs" in out
    assert "Program" in out
    assert "legacy" in out
    assert ".loopfarm/loopfarm.toml" in out
    assert "loopfarm programs show <name>" in out


def test_programs_show_plain_outputs_effective_program_context(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_program_file(
        tmp_path,
        ".loopfarm/programs/implementation.toml",
        body=_detailed_program_toml(),
    )
    monkeypatch.chdir(tmp_path)

    cli.main(["programs", "show", "implementation"])

    out = capsys.readouterr().out
    assert "PROGRAM\timplementation" in out
    assert "PROJECT\tagent-core" in out
    assert "REPORT_SOURCE_PHASE\tforward" in out
    assert "REPORT_TARGET_PHASES\tdocumentation, backward" in out
    assert "STEP\tPHASE\tREPEAT" in out
    assert "2\tforward\t2" in out
    assert "PHASE\tIN_STEPS\tCONFIGURED\tCLI\tMODEL\tREASONING\tINJECT\tPROMPT" in out
    assert (
        "documentation\tyes\tyes\tclaude\tclaude-sonnet-4\tmedium\tforward_report\t"
        ".loopfarm/prompts/documentation.md"
    ) in out
    assert "backward\tyes\tno\t-\t-\t-\t-\t-" in out
    assert (
        "research\tno\tyes\tcodex\tgpt-5-mini\t-\t-\t.loopfarm/prompts/research.md"
    ) in out
    assert "MISSING_PHASE_CONFIGS\tbackward" in out
    assert "EXTRA_PHASE_CONFIGS\tresearch" in out


def test_programs_show_json_outputs_stable_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_program_file(
        tmp_path,
        ".loopfarm/programs/implementation.toml",
        body=_detailed_program_toml(),
    )
    monkeypatch.chdir(tmp_path)

    cli.main(["programs", "show", "implementation", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {
        "name",
        "path",
        "project",
        "steps",
        "loop_steps",
        "termination_phase",
        "report_source_phase",
        "report_target_phases",
        "phases",
        "missing_phase_configs",
        "extra_phase_configs",
    }
    assert payload["name"] == "implementation"
    assert payload["path"] == ".loopfarm/programs/implementation.toml"
    assert payload["project"] == "agent-core"
    assert payload["termination_phase"] == "backward"
    assert payload["report_source_phase"] == "forward"
    assert payload["report_target_phases"] == ["documentation", "backward"]
    assert payload["loop_steps"] == [
        {"index": 1, "phase": "planning", "repeat": 1},
        {"index": 2, "phase": "forward", "repeat": 2},
        {"index": 3, "phase": "documentation", "repeat": 1},
        {"index": 4, "phase": "backward", "repeat": 1},
    ]
    assert payload["missing_phase_configs"] == ["backward"]
    assert payload["extra_phase_configs"] == ["research"]

    backward = next(
        row for row in payload["phases"] if row["phase"] == "backward"
    )
    assert backward == {
        "phase": "backward",
        "in_steps": True,
        "configured": False,
        "cli": None,
        "model": None,
        "reasoning": None,
        "inject": [],
        "prompt": None,
    }
    assert all(
        set(row.keys())
        == {
            "phase",
            "in_steps",
            "configured",
            "cli",
            "model",
            "reasoning",
            "inject",
            "prompt",
        }
        for row in payload["phases"]
    )


def test_programs_show_rich_renders_steps_and_phase_tables(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_program_file(
        tmp_path,
        ".loopfarm/programs/implementation.toml",
        body=_detailed_program_toml(),
    )
    monkeypatch.chdir(tmp_path)

    cli.main(["programs", "show", "implementation", "--output", "rich"])

    out = capsys.readouterr().out
    assert "Program implementation" in out
    assert "Loop Steps" in out
    assert "Phase Config" in out
    assert "Validation Hints" in out
    assert "backward" in out
    assert "research" in out


def test_programs_show_reports_unknown_program(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_program_file(
        tmp_path,
        ".loopfarm/programs/implementation.toml",
        body=_detailed_program_toml(),
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["programs", "show", "missing"])

    stderr = capsys.readouterr().err
    assert raised.value.code == 2
    assert "error: program 'missing' not found (available: 'implementation')" in stderr


def test_programs_list_output_flag_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_legacy_program(tmp_path, name="legacy")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("LOOPFARM_OUTPUT", "rich")

    cli.main(["programs", "list", "--output", "plain"])

    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["legacy\t.loopfarm/loopfarm.toml"]


def test_programs_list_reports_missing_config_using_cli_error_conventions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["programs", "list"])

    stderr = capsys.readouterr().err
    assert raised.value.code == 2
    assert "error: no program config found" in stderr
    assert ".loopfarm/loopfarm.toml" in stderr
    assert ".loopfarm/programs/*.toml" in stderr


def test_programs_list_reports_invalid_config_using_cli_error_conventions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_program_file(
        tmp_path,
        ".loopfarm/loopfarm.toml",
        body="""
[program
name = "broken"
""",
    )
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["programs", "list"])

    stderr = capsys.readouterr().err
    assert raised.value.code == 2
    assert "error: invalid TOML in .loopfarm/loopfarm.toml" in stderr


def test_main_help_mentions_programs_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])

    stderr = capsys.readouterr().err
    assert raised.value.code == 0
    assert "programs  list discovered loop programs and source files" in stderr
