from __future__ import annotations

from pathlib import Path

from loopfarm import cli


def test_init_creates_scaffold(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["init"])

    config = tmp_path / ".loopfarm" / "loopfarm.toml"
    impl_forward = tmp_path / ".loopfarm" / "prompts" / "implementation" / "forward.md"
    research_backward = tmp_path / ".loopfarm" / "prompts" / "research" / "backward.md"

    assert config.exists()
    assert impl_forward.exists()
    assert research_backward.exists()
    text = config.read_text(encoding="utf-8")
    assert "[program]" in text
    assert f'project = "{tmp_path.name}"' in text
    assert "steps = [\"forward*5\", \"documentation\", \"architecture\", \"backward\"]" in text


def test_init_skips_existing_files_without_force(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / ".loopfarm" / "loopfarm.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("custom\n", encoding="utf-8")

    cli.main(["init"])

    assert config.read_text(encoding="utf-8") == "custom\n"


def test_init_force_overwrites_existing_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    config = tmp_path / ".loopfarm" / "loopfarm.toml"
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text("custom\n", encoding="utf-8")

    cli.main(["init", "--force", "--project", "custom-project"])

    text = config.read_text(encoding="utf-8")
    assert "custom\n" not in text
    assert 'project = "custom-project"' in text
