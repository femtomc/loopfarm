from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopfarm import cli
from loopfarm.forum import Forum
from loopfarm.issue import Issue


def test_issue_list_empty_prints_message_and_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["issue", "list"])

    out = capsys.readouterr().out
    assert "(no issues)" in out
    assert not (tmp_path / ".loopfarm").exists()


def test_issue_show_missing_prints_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["issue", "show", "loopfarm-missing"])

    stderr = capsys.readouterr().err
    assert raised.value.code == 1
    assert "error: issue not found: loopfarm-missing" in stderr


def test_issue_show_json_includes_comments_and_dependencies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    src = issue.create("Parent")
    dst = issue.create("Child")
    issue.add_dep(src["id"], "blocks", dst["id"])
    issue.add_comment(dst["id"], "Needs docs", author="reviewer")

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "show", dst["id"], "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert payload["id"] == dst["id"]
    assert "comments" in payload
    assert len(payload["comments"]) == 1
    assert payload["comments"][0]["body"] == "Needs docs"
    assert "dependencies" in payload
    assert len(payload["dependencies"]) == 1
    assert payload["created_at_iso"].endswith("Z")
    assert payload["updated_at_iso"].endswith("Z")


def test_issue_list_non_json_uses_table_columns(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    issue.create("Implement parser", tags=["feature"])

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "list"])

    out = capsys.readouterr().out
    assert "ID" in out
    assert "STATUS" in out
    assert "TITLE" in out
    assert "Implement parser" in out


def test_issue_list_rich_output_renders_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    issue.create("Implement parser", tags=["feature"])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    cli.main(["issue", "list", "--output", "rich"])

    out = capsys.readouterr().out
    assert "Issues" in out
    assert "ID" in out
    assert "Implement" in out or "parser" in out


def test_issue_ready_rich_output_renders_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Ready task")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    cli.main(["issue", "ready", "--output", "rich"])

    out = capsys.readouterr().out
    assert "Ready Issues" in out
    assert row["id"] in out
    assert "Ready task" in out


def test_issue_close_reopen_and_delete(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Close me")

    monkeypatch.chdir(tmp_path)

    cli.main(["issue", "close", row["id"]])
    closed = Issue.from_workdir(tmp_path).show(row["id"])
    assert closed is not None
    assert closed["status"] == "closed"

    cli.main(["issue", "reopen", row["id"]])
    reopened = Issue.from_workdir(tmp_path).show(row["id"])
    assert reopened is not None
    assert reopened["status"] == "open"

    with pytest.raises(SystemExit) as raised:
        cli.main(["issue", "delete", row["id"]])
    assert raised.value.code == 1
    assert "refusing to delete without --yes" in capsys.readouterr().err

    cli.main(["issue", "delete", row["id"], "--yes"])
    assert Issue.from_workdir(tmp_path).show(row["id"]) is None


def test_issue_comments_subcommand(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Needs follow-up")
    issue.add_comment(row["id"], "Ship it", author="reviewer")

    monkeypatch.chdir(tmp_path)
    cli.main(["issue", "comments", row["id"]])

    out = capsys.readouterr().out
    assert "reviewer" in out
    assert "Ship it" in out


def test_issue_show_rich_output_renders_sections(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    src = issue.create("Parent")
    dst = issue.create("Child", body="Needs docs")
    issue.add_dep(src["id"], "blocks", dst["id"])
    issue.add_comment(dst["id"], "Ship it", author="reviewer")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    cli.main(["issue", "show", dst["id"], "--output", "rich"])

    out = capsys.readouterr().out
    assert f"Issue {dst['id']}" in out
    assert "Description" in out
    assert "Dependencies" in out
    assert "SOURCE" in out
    assert "TARGET" in out
    assert "Comment [" in out
    assert "Ship it" in out


def test_issue_comments_rich_output_renders_panels(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Needs follow-up")
    issue.add_comment(row["id"], "Ship it", author="reviewer")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    cli.main(["issue", "comments", row["id"], "--output", "rich"])

    out = capsys.readouterr().out
    assert "reviewer" in out
    assert "Ship it" in out


def test_issue_deps_rich_output_renders_table(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    issue = Issue.from_workdir(tmp_path)
    src = issue.create("Parent")
    dst = issue.create("Child")
    issue.add_dep(src["id"], "blocks", dst["id"])

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COLUMNS", "200")
    cli.main(["issue", "deps", dst["id"], "--output", "rich"])

    out = capsys.readouterr().out
    assert f"Dependencies: {dst['id']}" in out
    assert "SOURCE" in out
    assert "TYPE" in out
    assert "TARGET" in out


def test_forum_read_empty_prints_message_and_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["forum", "read", "unknown-topic"])

    out = capsys.readouterr().out
    assert "(no messages)" in out
    assert not (tmp_path / ".loopfarm").exists()


def test_forum_show_missing_prints_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["forum", "show", "12345"])

    stderr = capsys.readouterr().err
    assert raised.value.code == 1
    assert "error: message not found: 12345" in stderr


def test_forum_topic_list_empty_prints_message(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["forum", "topic", "list"])

    out = capsys.readouterr().out
    assert "(no topics)" in out


def test_forum_read_non_json_uses_human_timestamps(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    forum = Forum.from_workdir(tmp_path)
    forum.post("loopfarm:test", "hello", author="agent")

    monkeypatch.chdir(tmp_path)
    cli.main(["forum", "read", "loopfarm:test", "--limit", "1"])

    out = capsys.readouterr().out
    assert "@20" in out
    assert "T" in out
    assert "Z" in out


def test_sessions_list_empty_prints_message_and_has_no_side_effects(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["sessions"])

    out = capsys.readouterr().out
    assert "(no sessions)" in out
    assert not (tmp_path / ".loopfarm").exists()


def test_sessions_and_history_commands_show_session_data(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    session_id = "loopfarm-a1b2c3d4"
    forum = Forum.from_workdir(tmp_path)
    forum.post_json(
        f"loopfarm:session:{session_id}",
        {
            "prompt": "Improve cli ergonomics",
            "status": "running",
            "phase": "forward",
            "iteration": 2,
            "started": "2026-02-12T10:00:00Z",
        },
    )
    forum.post_json(
        f"loopfarm:status:{session_id}",
        {
            "decision": "CONTINUE",
            "summary": "one more forward pass",
        },
    )
    forum.post_json(
        f"loopfarm:briefing:{session_id}",
        {
            "phase": "forward",
            "iteration": 2,
            "summary": "Added lifecycle commands",
        },
    )

    monkeypatch.chdir(tmp_path)

    cli.main(["sessions", "list"])
    sessions_list_out = capsys.readouterr().out
    assert session_id in sessions_list_out
    assert "CONTINUE" in sessions_list_out

    cli.main(["history"])
    history_out = capsys.readouterr().out
    assert session_id in history_out

    cli.main(["sessions", "show", session_id, "--json"])
    payload = json.loads(capsys.readouterr().out)
    assert payload["session_id"] == session_id
    assert payload["status"] == "running"
    assert payload["decision"] == "CONTINUE"
    assert len(payload["briefings"]) == 1


def test_history_help_uses_history_prog_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        cli.main(["history", "--help"])

    captured = capsys.readouterr()
    assert raised.value.code == 0
    assert "usage: loopfarm history" in (captured.out + captured.err)
