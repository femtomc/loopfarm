from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopfarm import cli, docs_cmd


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
    assert "issue-dag-orchestration" in out
    assert "Issue-DAG Step Routing Grammar" in out
    assert "Source Layout" in out


def test_docs_list_json_outputs_stable_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["docs", "list", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 4
    assert {row["topic"] for row in payload} == {
        "steps-grammar",
        "implementation-state-machine",
        "source-layout",
        "issue-dag-orchestration",
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
    assert "# Issue-DAG Step Routing Grammar" in out
    assert "execution_spec" in out
    assert ".loopfarm/orchestrator.md" in out
    assert "route: spec_execution" in out


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
    assert payload["title"] == "Issue-DAG Runner State Machine"
    assert "root_final" in payload["markdown"]


def test_docs_show_issue_dag_topic_in_plain_and_rich(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")

    cli.main(["docs", "show", "issue-dag-orchestration"])
    plain = capsys.readouterr().out
    assert "# Issue-DAG Orchestration" in plain
    assert "cf:sequence" in plain
    assert "role:<name>" in plain
    assert "execution_spec" in plain
    assert ".loopfarm/orchestrator.md" in plain
    assert ".loopfarm/roles/<role>.md" in plain
    assert "def orchestrate(root_id):" in plain
    assert "node.memory" in plain
    assert "issue_refs" in plain
    assert "evidence" in plain
    assert "MVP Non-Goals" in plain
    assert "steps-grammar" in plain
    assert "implementation-state-machine" in plain

    cli.main(["docs", "show", "dag", "--output", "rich"])
    rich = capsys.readouterr().out
    assert "Topic: issue-dag-orchestration" in rich
    assert "Issue-DAG Orchestration" in rich
    assert "node.plan" in rich
    assert "node.memory" in rich
    assert "node.reconcile" in rich


def test_docs_search_plain_outputs_snippet_and_next_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["docs", "search", "granularity atomic"])

    out = capsys.readouterr().out
    assert "TOPIC" in out
    assert "SNIPPET" in out
    assert "NEXT" in out
    assert "issue-dag-orchestration" in out
    assert "loopfarm docs show issue-dag-orchestration" in out


def test_docs_search_plain_miss_outputs_no_results(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["docs", "search", "this-query-should-not-match-any-doc-topic-xyz"])

    out = capsys.readouterr().out
    assert out.strip() == "(no results)"


def test_docs_search_json_outputs_stable_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["docs", "search", "state machine", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert set(payload.keys()) == {"query", "results"}
    assert payload["query"] == "state machine"
    assert isinstance(payload["results"], list)
    assert payload["results"]
    first = payload["results"][0]
    assert set(first.keys()) == {
        "topic",
        "title",
        "match_count",
        "snippet",
        "show_command",
    }
    assert isinstance(first["match_count"], int)
    assert first["show_command"].startswith("loopfarm docs show ")


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


def test_docs_do_not_depend_on_repo_relative_file_layout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)
    fake_module_path = tmp_path / "site-packages" / "loopfarm" / "docs_cmd.py"
    fake_module_path.parent.mkdir(parents=True, exist_ok=True)
    fake_module_path.write_text("# installed placeholder\n", encoding="utf-8")
    monkeypatch.setattr(docs_cmd, "__file__", str(fake_module_path))

    cli.main(["docs", "show", "steps-grammar"])

    out = capsys.readouterr().out
    assert "# Issue-DAG Step Routing Grammar" in out
    assert ".loopfarm/roles/<role>.md" in out
