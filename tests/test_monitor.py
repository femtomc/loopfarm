from __future__ import annotations

import json
from pathlib import Path

from loopfarm.monitor import MonitorCollector, _decode_message_body


def _envelope(schema: str, data: dict[str, object]) -> str:
    return json.dumps({"schema": schema, "data": data}, ensure_ascii=False)


class FakeCollector(MonitorCollector):
    def __init__(self, repo_root: Path) -> None:
        super().__init__(repo_root)

    def _run_json(self, argv: list[str]):
        if argv == ["synth-forum", "topic", "list", "--json"]:
            return [
                {
                    "name": "loopfarm:session:loopfarm-a1b2c3d4",
                    "created_at": 3000,
                },
                {
                    "name": "loopfarm:session:loopfarm-deadbeef",
                    "created_at": 2500,
                },
                {
                    "name": "research:qed:kernel",
                    "created_at": 3100,
                },
            ]

        if argv[:3] == ["synth-forum", "read", "loopfarm:session:loopfarm-a1b2c3d4"]:
            return [
                {
                    "id": "2",
                    "created_at": 3010,
                    "body": _envelope(
                        "loopfarm.session.meta.v1",
                        {
                            "prompt": "Improve incremental loop execution",
                            "status": "running",
                            "phase": "forward",
                            "iteration": 2,
                            "started": "2026-02-12T10:00:00Z",
                        },
                    ),
                }
            ]

        if argv[:3] == ["synth-forum", "read", "loopfarm:status:loopfarm-a1b2c3d4"]:
            return [
                {
                    "id": "3",
                    "created_at": 3020,
                    "body": json.dumps(
                        {
                            "decision": "CONTINUE",
                            "summary": "need one more forward pass",
                        }
                    ),
                }
            ]

        if argv[:3] == ["synth-forum", "read", "loopfarm:briefing:loopfarm-a1b2c3d4"]:
            return [
                {
                    "id": "4",
                    "created_at": 3030,
                    "body": _envelope(
                        "loopfarm.session.briefing.v1",
                        {
                            "phase": "forward",
                            "iteration": 2,
                            "summary": "Implemented parser + tests",
                        },
                    ),
                }
            ]

        if argv[:3] == ["synth-forum", "read", "loopfarm:forward:loopfarm-a1b2c3d4"]:
            return [
                {
                    "id": "5",
                    "created_at": 3040,
                    "body": json.dumps(
                        {
                            "summary": "Touched cli.py and runner.py",
                            "post_head": "abc123",
                        }
                    ),
                }
            ]

        if argv[:3] == ["synth-forum", "read", "loopfarm:session:loopfarm-deadbeef"]:
            return [
                {
                    "id": "6",
                    "created_at": 2510,
                    "body": _envelope(
                        "loopfarm.session.meta.v1",
                        {
                            "prompt": "Legacy run",
                            "status": "complete",
                            "started": "2026-02-11T10:00:00Z",
                            "ended": "2026-02-11T11:00:00Z",
                        },
                    ),
                }
            ]

        if argv[:3] == ["synth-forum", "read", "loopfarm:status:loopfarm-deadbeef"]:
            return []

        if argv[:3] == ["synth-forum", "read", "loopfarm:briefing:loopfarm-deadbeef"]:
            return []

        if argv[:3] == ["synth-forum", "read", "loopfarm:forward:loopfarm-deadbeef"]:
            return []

        if argv[:3] == ["synth-forum", "read", "research:qed:kernel"]:
            return [
                {
                    "id": "7",
                    "created_at": 3110,
                    "body": json.dumps({"summary": "paper notes"}),
                }
            ]

        if argv[:4] == ["synth-issue", "list", "--status", "in_progress"]:
            return [
                {
                    "id": "workshop-aaaa",
                    "title": "Implement monitor API",
                    "priority": 1,
                    "updated_at": 4000,
                }
            ]

        if argv[:4] == ["synth-issue", "list", "--status", "open"]:
            return [
                {
                    "id": "workshop-bbbb",
                    "title": "Add monitor UI details",
                    "priority": 2,
                    "updated_at": 3900,
                }
            ]

        if argv[:4] == ["synth-issue", "list", "--status", "paused"]:
            return []

        return []


def test_decode_message_body_understands_envelopes() -> None:
    schema, payload = _decode_message_body(
        _envelope("loopfarm.session.meta.v1", {"status": "running"})
    )
    assert schema == "loopfarm.session.meta.v1"
    assert payload == {"status": "running"}


def test_collect_overview_merges_loops_issues_forum(tmp_path: Path) -> None:
    collector = FakeCollector(tmp_path)

    overview = collector.collect_overview(max_sessions=5, max_issues=10, max_topics=10)

    assert overview["health"]["synth_forum"] in {True, False}
    assert overview["issue_counts"] == {"in_progress": 1, "open": 1, "paused": 0}

    sessions = overview["sessions"]
    assert len(sessions) == 2
    assert sessions[0]["session_id"] == "loopfarm-a1b2c3d4"
    assert sessions[0]["status"] == "running"
    assert sessions[0]["decision"] == "CONTINUE"
    assert sessions[0]["latest_summary"] == "Implemented parser + tests"

    issues = overview["issues"]
    assert [issue["id"] for issue in issues] == ["workshop-aaaa", "workshop-bbbb"]

    topic_names = [topic["name"] for topic in overview["forum_topics"]]
    assert "research:qed:kernel" in topic_names
    assert "loopfarm:session:loopfarm-a1b2c3d4" in topic_names


def test_collect_overview_returns_all_loopfarm_sessions(tmp_path: Path) -> None:
    collector = FakeCollector(tmp_path)

    overview = collector.collect_overview(max_sessions=5, max_issues=10, max_topics=10)

    sessions = overview["sessions"]
    assert len(sessions) == 2
    assert {session["session_id"] for session in sessions} == {
        "loopfarm-a1b2c3d4",
        "loopfarm-deadbeef",
    }
