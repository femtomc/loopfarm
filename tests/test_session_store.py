from __future__ import annotations

import json
from typing import Any

from loopfarm.stores.session import (
    CONTROL_STATE_SCHEMA,
    SESSION_META_SCHEMA,
    SessionStore,
)


class FakeForum:
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


def _envelope(schema: str, data: dict[str, Any]) -> str:
    return json.dumps({"schema": schema, "timestamp": "2026-02-12T00:00:00Z", "data": data})


def test_get_session_meta_missing_topic_returns_none() -> None:
    store = SessionStore(FakeForum())

    assert store.get_session_meta("sess") is None


def test_get_session_meta_skips_malformed_json() -> None:
    messages = {
        _session_topic("sess"): [
            {"id": 1, "body": "{"},
            {"id": 2, "body": _envelope(SESSION_META_SCHEMA, {"status": "running"})},
        ]
    }
    store = SessionStore(FakeForum(messages))

    meta = store.get_session_meta("sess")

    assert meta is not None
    assert meta.get("status") == "running"


def test_read_last_prefers_highest_id() -> None:
    messages = {
        _control_topic("sess"): [
            {
                "id": "5",
                "body": _envelope(CONTROL_STATE_SCHEMA, {"status": "paused", "command": "pause"}),
            },
            {
                "id": "9",
                "body": _envelope(CONTROL_STATE_SCHEMA, {"status": "running", "command": "resume"}),
            },
            {
                "id": "2",
                "body": _envelope(CONTROL_STATE_SCHEMA, {"status": "stopped", "command": "stop"}),
            },
        ]
    }
    store = SessionStore(FakeForum(messages))

    state = store.get_control_state("sess")

    assert state is not None
    assert state.get("command") == "resume"


def test_read_latest_prefers_created_at() -> None:
    messages = {
        _control_topic("sess"): [
            {
                "id": "01JH8TSQYH7J0C3C7P2T0K6X7A",
                "created_at": 1000,
                "body": _envelope(CONTROL_STATE_SCHEMA, {"status": "running", "command": "resume"}),
            },
            {
                "id": "01JH8TSR2T0HQD2M6KZ3BXY0Z2",
                "created_at": 2000,
                "body": _envelope(CONTROL_STATE_SCHEMA, {"status": "paused", "command": "pause"}),
            },
        ]
    }
    store = SessionStore(FakeForum(messages))

    state = store.get_control_state("sess")

    assert state is not None
    assert state.get("command") == "pause"


def test_read_latest_uses_newest_first_when_no_ids() -> None:
    messages = {
        _control_topic("sess"): [
            {
                "id": "01JH8TSR2T0HQD2M6KZ3BXY0Z2",
                "body": _envelope(CONTROL_STATE_SCHEMA, {"status": "paused", "command": "pause"}),
            },
            {
                "id": "01JH8TSQYH7J0C3C7P2T0K6X7A",
                "body": _envelope(CONTROL_STATE_SCHEMA, {"status": "running", "command": "resume"}),
            },
        ]
    }
    store = SessionStore(FakeForum(messages))

    state = store.get_control_state("sess")

    assert state is not None
    assert state.get("command") == "pause"


def test_update_session_meta_merges_and_posts_envelope() -> None:
    messages = {
        _session_topic("sess"): [
            {
                "id": 3,
                "body": _envelope(SESSION_META_SCHEMA, {"prompt": "hello", "status": "running"}),
            },
        ]
    }
    forum = FakeForum(messages)
    store = SessionStore(forum)

    merged = store.update_session_meta("sess", {"status": "paused"}, author="runner")

    assert merged["prompt"] == "hello"
    assert merged["status"] == "paused"
    assert forum.posted
    topic, payload = forum.posted[-1]
    assert topic == _session_topic("sess")
    assert payload.get("schema") == SESSION_META_SCHEMA
    assert payload.get("data", {}).get("status") == "paused"


def test_set_control_state_posts_envelope() -> None:
    forum = FakeForum()
    store = SessionStore(forum)

    store.set_control_state(
        "sess",
        status="paused",
        command="pause",
        phase="forward",
        iteration=2,
        author="operator",
        content="!pause",
    )

    assert forum.posted
    topic, payload = forum.posted[-1]
    assert topic == _control_topic("sess")
    assert payload.get("schema") == CONTROL_STATE_SCHEMA
    assert payload.get("data", {}).get("command") == "pause"
