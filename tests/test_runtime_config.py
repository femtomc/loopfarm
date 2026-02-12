from __future__ import annotations

from pathlib import Path

from loopfarm.runtime.config import load_config


def _write_config(tmp_path: Path, body: str) -> None:
    _write_program(tmp_path, ".loopfarm/loopfarm.toml", body)


def _write_program(tmp_path: Path, rel_path: str, body: str) -> None:
    path = tmp_path / rel_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip() + "\n", encoding="utf-8")


def test_load_config_reports_no_program_sources(tmp_path: Path) -> None:
    cfg = load_config(tmp_path)
    assert cfg.program is None
    assert cfg.programs == ()
    assert cfg.error is not None
    assert ".loopfarm/loopfarm.toml" in cfg.error
    assert ".loopfarm/programs/*.toml" in cfg.error


def test_load_config_reports_invalid_phase_in_steps(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
[program]
name = "impl"
steps = ["build!", "review"]
termination_phase = "review"
""",
    )

    cfg = load_config(tmp_path)
    assert cfg.program is None
    assert cfg.error is not None
    assert "invalid step token in [program].steps" in cfg.error


def test_load_config_accepts_user_defined_phase_ids(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
[program]
name = "impl"
steps = ["Discover", "implement_v2*2", "qa-check"]
termination_phase = "qa-check"
""",
    )

    cfg = load_config(tmp_path)
    assert cfg.error is None
    assert cfg.program is not None
    assert cfg.program.loop_steps == (
        ("discover", 1),
        ("implement_v2", 2),
        ("qa-check", 1),
    )
    assert cfg.program.termination_phase == "qa-check"


def test_load_config_reports_termination_not_in_steps(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
[program]
name = "impl"
steps = ["discover", "implement"]
termination_phase = "backward"
""",
    )

    cfg = load_config(tmp_path)
    assert cfg.program is None
    assert cfg.error is not None
    assert "termination_phase" in cfg.error
    assert "not present in [program].steps" in cfg.error


def test_load_config_reports_toml_parse_errors(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
[program
name = "impl"
""",
    )

    cfg = load_config(tmp_path)
    assert cfg.program is None
    assert cfg.error is not None
    assert "invalid TOML in .loopfarm/loopfarm.toml" in cfg.error


def test_load_config_discovers_programs_dir_sorted_and_tracks_source_paths(
    tmp_path: Path,
) -> None:
    _write_program(
        tmp_path,
        ".loopfarm/programs/zeta.toml",
        """
[program]
name = "zeta"
steps = ["planning", "forward"]
termination_phase = "forward"
""",
    )
    _write_program(
        tmp_path,
        ".loopfarm/programs/alpha.toml",
        """
[program]
name = "alpha"
steps = ["planning", "forward"]
termination_phase = "forward"
""",
    )

    cfg = load_config(tmp_path)
    assert cfg.error is None
    assert cfg.program is None
    assert [program.name for program in cfg.programs] == ["alpha", "zeta"]
    assert [program.source_path for program in cfg.programs] == [
        tmp_path / ".loopfarm" / "programs" / "alpha.toml",
        tmp_path / ".loopfarm" / "programs" / "zeta.toml",
    ]


def test_load_config_includes_legacy_and_programs_dir_sources(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
[program]
name = "legacy"
steps = ["planning", "forward"]
termination_phase = "forward"
""",
    )
    _write_program(
        tmp_path,
        ".loopfarm/programs/new.toml",
        """
[program]
name = "new"
steps = ["planning", "forward"]
termination_phase = "forward"
""",
    )

    cfg = load_config(tmp_path)
    assert cfg.error is None
    assert cfg.program is None
    assert {program.name for program in cfg.programs} == {"legacy", "new"}
    assert {program.source_path for program in cfg.programs} == {
        tmp_path / ".loopfarm" / "loopfarm.toml",
        tmp_path / ".loopfarm" / "programs" / "new.toml",
    }


def test_load_config_reports_duplicate_program_name_with_paths(tmp_path: Path) -> None:
    _write_config(
        tmp_path,
        """
[program]
name = "impl"
steps = ["planning", "forward"]
termination_phase = "forward"
""",
    )
    _write_program(
        tmp_path,
        ".loopfarm/programs/impl.toml",
        """
[program]
name = "impl"
steps = ["planning", "forward"]
termination_phase = "forward"
""",
    )

    cfg = load_config(tmp_path)
    assert cfg.program is None
    assert cfg.error is not None
    assert "duplicate [program].name 'impl'" in cfg.error
    assert ".loopfarm/loopfarm.toml" in cfg.error
    assert ".loopfarm/programs/impl.toml" in cfg.error
