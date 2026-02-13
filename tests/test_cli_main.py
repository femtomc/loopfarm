from __future__ import annotations

from pathlib import Path

import pytest

from loopfarm import cli
from loopfarm.issue import Issue


class _FakeRun:
    def __init__(self, *, stop_reason: str = "root_final") -> None:
        self.stop_reason = stop_reason
        self.steps = ()
        self.error = None
        self.termination = {
            "is_final": stop_reason == "root_final",
            "reason": "root_final_outcome" if stop_reason == "root_final" else "not_terminal",
        }


def test_main_without_command_prints_help(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main([])

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert raised.value.code == 0
    assert "loopfarm [OPTIONS] <prompt...>" in out


def test_main_prompt_mode_creates_root_issue_and_runs_orchestrator(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, int]] = []

    def fake_run(self, *, root_id: str, max_steps: int = 1, **kwargs):
        _ = kwargs
        calls.append((root_id, int(max_steps)))
        return _FakeRun()

    monkeypatch.setattr(
        "loopfarm.runtime.issue_dag_runner.IssueDagRunner.run",
        fake_run,
    )
    monkeypatch.chdir(tmp_path)

    cli.main(["--max-steps", "2", "Design sync engine"])

    out = capsys.readouterr().out
    assert "root=loopfarm-" in out
    assert "stop_reason=root_final" in out
    assert calls
    assert calls[0][1] == 2

    issue = Issue.from_workdir(tmp_path)
    rows = issue.list(limit=10)
    assert len(rows) == 1
    assert rows[0]["title"] == "Design sync engine"
    assert "node:agent" in (rows[0].get("tags") or [])


def test_main_prompt_mode_json_outputs_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_run(self, *, root_id: str, **kwargs):
        _ = self
        _ = root_id
        _ = kwargs
        return _FakeRun()

    monkeypatch.setattr(
        "loopfarm.runtime.issue_dag_runner.IssueDagRunner.run",
        fake_run,
    )
    monkeypatch.chdir(tmp_path)

    cli.main(["--json", "Break this down"])

    out = capsys.readouterr().out
    assert '"root_issue_id": "loopfarm-' in out
    assert '"stop_reason": "root_final"' in out


def test_main_rejects_unknown_option(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--bogus"])

    stderr = capsys.readouterr().err
    assert raised.value.code == 2
    assert "unrecognized arguments: --bogus" in stderr


def test_main_version_outputs_version(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as raised:
        cli.main(["--version"])

    captured = capsys.readouterr()
    assert raised.value.code == 0
    assert captured.out.strip()
