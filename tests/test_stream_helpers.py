from __future__ import annotations

from pathlib import Path

from loopfarm.backends import stream_helpers
from loopfarm.util import ExecResult


class DummyFormatter:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.finished = False

    def process_line(self, line: str) -> None:
        self.lines.append(line)

    def finish(self) -> None:
        self.finished = True


def test_run_stream_backend_calls_stream_process_and_finish(
    tmp_path: Path, monkeypatch
) -> None:
    calls: dict[str, object] = {}

    def fake_stream_process(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None,
        on_line: callable | None,
        tee_path: Path | None,
    ) -> ExecResult:
        calls["argv"] = argv
        calls["cwd"] = cwd
        calls["env"] = env
        calls["tee_path"] = tee_path
        if on_line:
            on_line("hello")
        return ExecResult(returncode=0)

    monkeypatch.setattr(stream_helpers, "stream_process", fake_stream_process)
    formatter = DummyFormatter()
    tee_path = tmp_path / "out.txt"

    ok = stream_helpers.run_stream_backend(
        argv=["demo", "--flag"],
        formatter=formatter,
        cwd=tmp_path,
        env={"X": "1"},
        tee_path=tee_path,
    )

    assert ok is True
    assert formatter.finished is True
    assert formatter.lines == ["hello"]
    assert calls["argv"] == ["demo", "--flag"]
    assert calls["cwd"] == tmp_path
    assert calls["env"] == {"X": "1"}
    assert calls["tee_path"] == tee_path


def test_run_stream_backend_false_on_error(tmp_path: Path, monkeypatch) -> None:
    def fake_stream_process(
        argv: list[str],
        *,
        cwd: Path,
        env: dict[str, str] | None,
        on_line: callable | None,
        tee_path: Path | None,
    ) -> ExecResult:
        return ExecResult(returncode=1)

    monkeypatch.setattr(stream_helpers, "stream_process", fake_stream_process)
    formatter = DummyFormatter()

    ok = stream_helpers.run_stream_backend(
        argv=["demo"],
        formatter=formatter,
        cwd=tmp_path,
        env=None,
        tee_path=None,
    )

    assert ok is False
    assert formatter.finished is True


def test_ensure_empty_last_message_overwrites_file(tmp_path: Path) -> None:
    path = tmp_path / "last_message.txt"
    path.write_text("not empty", encoding="utf-8")

    stream_helpers.ensure_empty_last_message(path)

    assert path.read_text(encoding="utf-8") == ""
