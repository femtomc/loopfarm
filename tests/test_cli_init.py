from __future__ import annotations

from pathlib import Path

from loopfarm import cli


def test_init_creates_minimal_orchestration_scaffold(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["init"])

    orchestrator = tmp_path / ".loopfarm" / "orchestrator.md"
    worker = tmp_path / ".loopfarm" / "roles" / "worker.md"

    assert orchestrator.exists()
    assert worker.exists()
    assert (tmp_path / ".loopfarm" / "loopfarm.toml").exists() is False
    assert (tmp_path / ".loopfarm" / "programs").exists() is False

    orchestrator_text = orchestrator.read_text(encoding="utf-8")
    assert orchestrator_text.startswith("---\n")
    assert "cli: codex" in orchestrator_text
    assert "hierarchical orchestrator" in orchestrator_text
    assert "outcome=expanded" in orchestrator_text

    worker_text = worker.read_text(encoding="utf-8")
    assert worker_text.startswith("---\n")
    assert "cli: codex" in worker_text
    assert "atomic issue" in worker_text
    assert "success" in worker_text


def test_init_skips_existing_files_without_force(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    orchestrator = tmp_path / ".loopfarm" / "orchestrator.md"
    orchestrator.parent.mkdir(parents=True, exist_ok=True)
    orchestrator.write_text("custom\n", encoding="utf-8")

    cli.main(["init"])

    assert orchestrator.read_text(encoding="utf-8") == "custom\n"


def test_init_force_overwrites_existing_files(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    worker = tmp_path / ".loopfarm" / "roles" / "worker.md"
    worker.parent.mkdir(parents=True, exist_ok=True)
    worker.write_text("custom\n", encoding="utf-8")

    cli.main(["init", "--force"])

    text = worker.read_text(encoding="utf-8")
    assert "custom\n" not in text
    assert "atomic issue" in text
