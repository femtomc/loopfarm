from __future__ import annotations

import json
from pathlib import Path

import pytest

from loopfarm import cli
from loopfarm.forum import Forum
from loopfarm.issue import Issue
from loopfarm.runtime.issue_dag_execution import DEFAULT_RUN_TOPIC


def _write_role(tmp_path: Path, role: str, body: str = "") -> None:
    path = tmp_path / ".loopfarm" / "roles" / f"{role}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = body or f"# {role}\n"
    path.write_text(text, encoding="utf-8")


def test_roles_list_empty(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    cli.main(["roles", "list"])

    out = capsys.readouterr().out
    assert out.strip() == "(no roles)"


def test_roles_list_json_sorted(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_role(tmp_path, "worker")
    _write_role(tmp_path, "reviewer")
    monkeypatch.chdir(tmp_path)

    cli.main(["roles", "list", "--json"])

    payload = json.loads(capsys.readouterr().out)
    assert [row["role"] for row in payload] == ["reviewer", "worker"]
    assert payload[0]["path"] == ".loopfarm/roles/reviewer.md"


def test_roles_show_plain_outputs_markdown(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_role(tmp_path, "worker", body="# Worker\n\nDo work.\n")
    monkeypatch.chdir(tmp_path)

    cli.main(["roles", "show", "worker"])

    out = capsys.readouterr().out
    assert "ROLE\tworker" in out
    assert ".loopfarm/roles/worker.md" in out
    assert "Do work." in out


def test_roles_assign_updates_issue_tags_and_posts_event(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_role(tmp_path, "worker")
    _write_role(tmp_path, "reviewer")
    issue = Issue.from_workdir(tmp_path)
    row = issue.create("Team me")

    monkeypatch.chdir(tmp_path)
    cli.main(
        [
            "roles",
            "assign",
            row["id"],
            "--team",
            "platform",
            "--lead",
            "worker",
            "--role",
            "reviewer",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert payload["issue_id"] == row["id"]
    assert payload["team"] == "platform"
    assert payload["lead_role"] == "worker"
    assert payload["roles"] == ["worker", "reviewer"]

    updated = Issue.from_workdir(tmp_path).show(row["id"])
    assert updated is not None
    tags = set(str(tag) for tag in updated.get("tags") or [])
    assert "team:platform" in tags
    assert "role:worker" in tags

    forum = Forum.from_workdir(tmp_path)
    issue_events = [json.loads(str(row["body"])) for row in forum.read(f"issue:{row['id']}", limit=10)]
    assert any(event.get("kind") == "node.team" and event.get("id") == row["id"] for event in issue_events)

    run_events = [json.loads(str(row["body"])) for row in forum.read(DEFAULT_RUN_TOPIC, limit=10)]
    assert any(event.get("kind") == "node.team" and event.get("id") == row["id"] for event in run_events)
