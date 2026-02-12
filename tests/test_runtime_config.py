from __future__ import annotations

from pathlib import Path

from loopfarm.runtime.config import load_config


def _write_config(tmp_path: Path, body: str) -> None:
    path = tmp_path / ".loopfarm" / "loopfarm.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip() + "\n", encoding="utf-8")


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
