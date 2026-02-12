from __future__ import annotations

import json
from typing import Any

from loopfarm.session_store import (
    CONTROL_STATE_SCHEMA,
    SESSION_META_SCHEMA,
    SessionStore,
)


class FakeJwz:
    def __init__(self, messages: dict[str, list[dict[str, Any]]] | None = None) -> None:
        self._messages = messages or {}
        self.posted: list[tuple[str, dict[str, Any]]] = []

    def post_json(self, topic: str, payload: Any) -> None:
        self.posted.append((topic, payload))

    def read_json(self, topic: str, *, limit: int) -> list[dict[str, Any]]:
        return list(self._messages.get(topic, []))[:limit]


def _session_topic(session_id: str) -> str:
    return f"loopfarm:session:{session_id}"


def _control_topic(session_id: str) -> str:
    return f"loopfarm:control:{session_id}"


def test_get_session_meta_missing_topic_returns_none() -> None:
    store = SessionStore(FakeJwz())

    assert store.get_session_meta("sess") is None


def test_get_session_meta_skips_malformed_json() -> None:
    messages = {
        _session_topic("sess"): [
            {"id": 1, "body": "{"},
            {"id": 2, "body": json.dumps({"status": "running"})},
        ]
    }
    store = SessionStore(FakeJwz(messages))

    meta = store.get_session_meta("sess")

    assert meta is not None
    assert meta.get("status") == "running"


def test_read_last_prefers_highest_id() -> None:
    messages = {
        _control_topic("sess"): [
            {"id": "5", "body": json.dumps({"status": "paused", "command": "pause"})},
            {"id": "9", "body": json.dumps({"status": "running", "command": "resume"})},
            {"id": "2", "body": json.dumps({"status": "stopped", "command": "stop"})},
        ]
    }
    store = SessionStore(FakeJwz(messages))

    state = store.get_control_state("sess")

    assert state is not None
    assert state.get("command") == "resume"


def test_read_latest_prefers_created_at() -> None:
    messages = {
        _control_topic("sess"): [
            {
                "id": "01JH8TSQYH7J0C3C7P2T0K6X7A",
                "created_at": 1000,
                "body": json.dumps({"status": "running", "command": "resume"}),
            },
            {
                "id": "01JH8TSR2T0HQD2M6KZ3BXY0Z2",
                "created_at": 2000,
                "body": json.dumps({"status": "paused", "command": "pause"}),
            },
        ]
    }
    store = SessionStore(FakeJwz(messages))

    state = store.get_control_state("sess")

    assert state is not None
    assert state.get("command") == "pause"


def test_read_latest_uses_newest_first_when_no_ids() -> None:
    messages = {
        _control_topic("sess"): [
            {
                "id": "01JH8TSR2T0HQD2M6KZ3BXY0Z2",
                "body": json.dumps({"status": "paused", "command": "pause"}),
            },
            {
                "id": "01JH8TSQYH7J0C3C7P2T0K6X7A",
                "body": json.dumps({"status": "running", "command": "resume"}),
            },
        ]
    }
    store = SessionStore(FakeJwz(messages))

    state = store.get_control_state("sess")

    assert state is not None
    assert state.get("command") == "pause"


def test_update_session_meta_merges_and_posts_envelope() -> None:
    messages = {
        _session_topic("sess"): [
            {"id": 3, "body": json.dumps({"prompt": "hello", "status": "running"})},
        ]
    }
    jwz = FakeJwz(messages)
    store = SessionStore(jwz)

    merged = store.update_session_meta("sess", {"status": "paused"}, author="runner")

    assert merged["prompt"] == "hello"
    assert merged["status"] == "paused"
    assert jwz.posted
    topic, payload = jwz.posted[-1]
    assert topic == _session_topic("sess")
    assert payload.get("schema") == SESSION_META_SCHEMA
    assert payload.get("data", {}).get("status") == "paused"


def test_set_control_state_posts_envelope() -> None:
    jwz = FakeJwz()
    store = SessionStore(jwz)

    store.set_control_state(
        "sess",
        status="paused",
        command="pause",
        phase="forward",
        iteration=2,
        author="operator",
        content="!pause",
    )

    assert jwz.posted
    topic, payload = jwz.posted[-1]
    assert topic == _control_topic("sess")
    assert payload.get("schema") == CONTROL_STATE_SCHEMA
    assert payload.get("data", {}).get("command") == "pause"
