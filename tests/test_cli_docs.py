from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopfarm import cli


def test_docs_defaults_to_list_topics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["docs"])

    out = capsys.readouterr().out
    assert "TOPIC" in out
    assert "steps-grammar" in out
    assert "implementation-state-machine" in out
    assert "source-layout" in out
    assert "Program Step Grammar" in out
    assert "Source Layout" in out


def test_docs_list_json_outputs_stable_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["docs", "list", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 3
    assert {row["topic"] for row in payload} == {
        "steps-grammar",
        "implementation-state-machine",
        "source-layout",
    }
    assert all(set(row.keys()) == {"topic", "title", "description"} for row in payload)


def test_docs_show_plain_outputs_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["docs", "show", "steps-grammar"])

    out = capsys.readouterr().out
    assert "# Program Step Grammar" in out
    assert "`[program].steps` defines loop structure." in out
    assert "planning,forward*5,documentation,architecture,backward" in out


def test_docs_show_rich_renders_panel_and_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")

    cli.main(["docs", "show", "source-layout", "--output", "rich"])

    out = capsys.readouterr().out
    assert "Topic: source-layout" in out
    assert "Source Layout" in out
    assert "src/loopfarm/" in out


def test_docs_show_json_outputs_stable_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["docs", "show", "implementation-state-machine", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {"topic", "title", "markdown"}
    assert payload["topic"] == "implementation-state-machine"
    assert payload["title"] == "Implementation Program State Machine"
    assert "termination_phase" in payload["markdown"]


def test_docs_show_unknown_topic_prints_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["docs", "show", "unknown-topic"])

    stderr = capsys.readouterr().err
    assert raised.value.code == 2
    assert "error: unknown docs topic 'unknown-topic'" in stderr
    assert "steps-grammar" in stderr
