"""Tests for append-only JSONL event log emission."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from inshallah.dag import DagRunner
from inshallah.jsonl import read_jsonl
from inshallah.store import ForumStore, IssueStore


def _setup_store_dir(tmp_path: Path) -> Path:
    lf = tmp_path / ".inshallah"
    lf.mkdir(parents=True, exist_ok=True)
    (lf / "issues.jsonl").touch()
    (lf / "forum.jsonl").touch()
    (lf / "logs").mkdir(exist_ok=True)
    return lf


def _read_events(lf: Path) -> list[dict]:
    return read_jsonl(lf / "events.jsonl")


def _assert_envelope(ev: dict) -> None:
    assert isinstance(ev.get("v"), int)
    assert isinstance(ev.get("ts_ms"), int)
    assert isinstance(ev.get("type"), str)
    assert isinstance(ev.get("source"), str)
    assert isinstance(ev.get("payload"), dict)
    if "run_id" in ev:
        assert isinstance(ev["run_id"], str)
    if "issue_id" in ev:
        assert isinstance(ev["issue_id"], str)


def test_issue_store_emits_events(tmp_path: Path) -> None:
    lf = _setup_store_dir(tmp_path)
    store = IssueStore(lf / "issues.jsonl")

    a = store.create("a", tags=["node:agent"])
    b = store.create("b", tags=["node:agent"])

    store.update(a["id"], priority=1)
    store.claim(b["id"])
    store.close(b["id"], outcome="success")
    store.update(b["id"], status="open", outcome=None)

    store.add_dep(a["id"], "blocks", b["id"])
    store.remove_dep(a["id"], "blocks", b["id"])

    events = _read_events(lf)
    assert events, "expected events.jsonl to contain events"
    for ev in events:
        _assert_envelope(ev)

    types = {ev["type"] for ev in events}
    assert "issue.create" in types
    assert "issue.update" in types
    assert "issue.claim" in types
    assert "issue.close" in types
    assert "issue.open" in types
    assert "issue.dep.add" in types
    assert "issue.dep.remove" in types


def test_forum_post_emits_event_with_issue_id(tmp_path: Path) -> None:
    lf = _setup_store_dir(tmp_path)
    forum = ForumStore(lf / "forum.jsonl")

    forum.post("issue:inshallah-abc123", "hello", author="worker")
    events = _read_events(lf)
    for ev in events:
        _assert_envelope(ev)

    post_events = [ev for ev in events if ev["type"] == "forum.post"]
    assert len(post_events) == 1
    assert post_events[0].get("issue_id") == "inshallah-abc123"


def test_dag_runner_emits_correlated_events(tmp_path: Path) -> None:
    lf = _setup_store_dir(tmp_path)
    store = IssueStore(lf / "issues.jsonl")
    forum = ForumStore(lf / "forum.jsonl")

    root = store.create("root", tags=["node:agent", "node:root"])
    runner = DagRunner(store, forum, tmp_path)

    def backend_side_effect(prompt, model, reasoning, cwd, **kwargs):
        store.close(root["id"], outcome="success")
        return 0

    with patch("inshallah.dag.get_backend") as mock_backend, patch(
        "inshallah.dag.get_formatter"
    ) as mock_formatter:
        mock_proc = MagicMock()
        mock_proc.run.side_effect = backend_side_effect
        mock_backend.return_value = mock_proc
        mock_formatter.return_value = MagicMock()

        runner.run(root["id"], max_steps=2, review=False)

    events = _read_events(lf)
    for ev in events:
        _assert_envelope(ev)

    dag_starts = [ev for ev in events if ev["type"] == "dag.run.start"]
    assert len(dag_starts) == 1
    run_id = dag_starts[0].get("run_id")
    assert isinstance(run_id, str) and run_id

    correlated = [ev for ev in events if ev.get("run_id") == run_id]
    types = {ev["type"] for ev in correlated}
    assert "dag.step.start" in types
    assert "dag.step.end" in types
    assert "backend.run.start" in types
    assert "backend.run.end" in types

