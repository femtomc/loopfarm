from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, TypedDict

from .jwz import Jwz
from .util import utc_now_iso

# Jwz topic schemas (append-only).
# loopfarm:session:<session_id> -> SessionMeta (schema loopfarm.session.meta.v1)
# loopfarm:control:<session_id> -> ControlState (schema loopfarm.session.control.v1)
# loopfarm:context:<session_id> -> SessionContext (schema loopfarm.session.context.v1)
# loopfarm:discord_cursor:<thread_id> -> DiscordCursor (schema loopfarm.discord.cursor.v1)
# loopfarm:chat:<session_id> -> ChatState (schema loopfarm.session.chat.v1)
# loopfarm:briefing:<session_id> -> PhaseSummary (schema loopfarm.session.briefing.v1)

SESSION_META_SCHEMA = "loopfarm.session.meta.v1"
CONTROL_STATE_SCHEMA = "loopfarm.session.control.v1"
SESSION_CONTEXT_SCHEMA = "loopfarm.session.context.v1"
DISCORD_CURSOR_SCHEMA = "loopfarm.discord.cursor.v1"
CHAT_STATE_SCHEMA = "loopfarm.session.chat.v1"
PHASE_SUMMARY_SCHEMA = "loopfarm.session.briefing.v1"


class SessionMeta(TypedDict, total=False):
    prompt: str
    started: str
    ended: str
    status: str
    phase: str
    iteration: int
    timestamp: str
    discord_context: str


class ControlState(TypedDict, total=False):
    command: str
    status: str
    phase: str
    iteration: int
    author: str
    content: str
    timestamp: str


class SessionContext(TypedDict, total=False):
    text: str
    author: str
    timestamp: str


class DiscordCursor(TypedDict, total=False):
    thread_id: str
    message_id: str
    timestamp: str


class ChatTurn(TypedDict, total=False):
    role: str
    content: str
    author: str
    timestamp: str


class ChatState(TypedDict, total=False):
    messages: list[ChatTurn]
    backend: str
    model: str
    timestamp: str


class PhaseSummary(TypedDict, total=False):
    phase: str
    iteration: int
    summary: str
    timestamp: str


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.isdigit():
            return int(stripped)
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


@dataclass
class SessionStore:
    jwz: Jwz
    read_limit: int = 25

    def get_session_meta(self, session_id: str) -> SessionMeta | None:
        return self._read_latest(
            self._session_topic(session_id), SESSION_META_SCHEMA, allow_legacy=True
        )

    def update_session_meta(
        self,
        session_id: str,
        patch: SessionMeta,
        *,
        author: str | None = None,
    ) -> SessionMeta:
        current = self.get_session_meta(session_id) or {}
        merged: SessionMeta = {**current, **patch}
        self._post(
            self._session_topic(session_id),
            SESSION_META_SCHEMA,
            merged,
            author=author,
        )
        return merged

    def get_control_state(self, session_id: str) -> ControlState | None:
        return self._read_latest(
            self._control_topic(session_id), CONTROL_STATE_SCHEMA, allow_legacy=True
        )

    def set_control_state(
        self,
        session_id: str,
        *,
        status: str,
        command: str,
        phase: str | None,
        iteration: int | None,
        author: str | None,
        content: str | None,
    ) -> ControlState:
        payload: ControlState = {
            "timestamp": utc_now_iso(),
            "status": status,
            "command": command,
        }
        if phase:
            payload["phase"] = phase
        if iteration is not None:
            payload["iteration"] = iteration
        if author:
            payload["author"] = author
        if content:
            payload["content"] = content
        self._post(
            self._control_topic(session_id),
            CONTROL_STATE_SCHEMA,
            payload,
            author=author,
        )
        return payload

    def get_session_context(self, session_id: str) -> SessionContext | None:
        return self._read_latest(
            self._context_topic(session_id), SESSION_CONTEXT_SCHEMA, allow_legacy=True
        )

    def set_session_context(
        self,
        session_id: str,
        text: str,
        *,
        author: str | None = None,
    ) -> SessionContext:
        payload: SessionContext = {"text": text, "timestamp": utc_now_iso()}
        if author:
            payload["author"] = author
        self._post(
            self._context_topic(session_id),
            SESSION_CONTEXT_SCHEMA,
            payload,
            author=author,
        )
        return payload

    def get_discord_cursor(self, thread_id: str) -> DiscordCursor | None:
        return self._read_latest(
            self._discord_cursor_topic(thread_id),
            DISCORD_CURSOR_SCHEMA,
            allow_legacy=True,
        )

    def set_discord_cursor(self, thread_id: str, message_id: str) -> DiscordCursor:
        payload: DiscordCursor = {
            "thread_id": thread_id,
            "message_id": message_id,
            "timestamp": utc_now_iso(),
        }
        self._post(
            self._discord_cursor_topic(thread_id),
            DISCORD_CURSOR_SCHEMA,
            payload,
            author=None,
        )
        return payload

    def get_chat_state(self, session_id: str) -> ChatState | None:
        return self._read_latest(
            self._chat_topic(session_id), CHAT_STATE_SCHEMA, allow_legacy=True
        )

    def update_chat_state(
        self,
        session_id: str,
        patch: ChatState,
        *,
        author: str | None = None,
    ) -> ChatState:
        current = self.get_chat_state(session_id) or {}
        merged: ChatState = {**current, **patch, "timestamp": utc_now_iso()}
        self._post(
            self._chat_topic(session_id),
            CHAT_STATE_SCHEMA,
            merged,
            author=author,
        )
        return merged

    def store_phase_summary(
        self,
        session_id: str,
        phase: str,
        iteration: int,
        summary: str,
    ) -> None:
        payload: PhaseSummary = {
            "phase": phase,
            "iteration": iteration,
            "summary": summary,
            "timestamp": utc_now_iso(),
        }
        self._post(
            self._briefing_topic(session_id),
            PHASE_SUMMARY_SCHEMA,
            payload,
            author="runner",
        )

    def get_phase_summaries(
        self, session_id: str, limit: int = 6
    ) -> list[PhaseSummary]:
        messages = self.jwz.read_json(
            self._briefing_topic(session_id), limit=max(limit, self.read_limit)
        )
        summaries: list[tuple[int | None, int | None, PhaseSummary]] = []
        for msg in messages:
            body = msg.get("body")
            if not isinstance(body, str) or not body.strip():
                continue
            try:
                payload = json.loads(body)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            data = self._unwrap(payload, PHASE_SUMMARY_SCHEMA, allow_legacy=False)
            if data is None:
                continue
            created_at = _as_int(msg.get("created_at"))
            msg_id = _as_int(msg.get("id"))
            summaries.append((created_at, msg_id, data))

        if not summaries:
            return []

        # Sort oldest-first.
        with_created = [s for s in summaries if s[0] is not None]
        if with_created:
            with_created.sort(key=lambda s: s[0])
            ordered = [s[2] for s in with_created]
        else:
            with_ids = [s for s in summaries if s[1] is not None]
            if with_ids:
                with_ids.sort(key=lambda s: s[1])
                ordered = [s[2] for s in with_ids]
            else:
                # jwz returns newest-first; reverse for oldest-first.
                ordered = [s[2] for s in reversed(summaries)]

        return ordered[-limit:]

    def append_chat_turn(
        self,
        session_id: str,
        turn: ChatTurn,
        *,
        author: str | None = None,
        limit: int | None = None,
    ) -> ChatState:
        state = self.get_chat_state(session_id) or {}
        messages = list(state.get("messages") or [])
        messages.append(turn)
        if limit is not None and limit > 0:
            messages = messages[-limit:]
        return self.update_chat_state(
            session_id,
            {"messages": messages},
            author=author,
        )

    def _post(
        self,
        topic: str,
        schema: str,
        data: dict[str, Any],
        *,
        author: str | None,
    ) -> None:
        payload: dict[str, Any] = {
            "schema": schema,
            "timestamp": utc_now_iso(),
            "data": data,
        }
        if author:
            payload["author"] = author
        self.jwz.post_json(topic, payload)

    def _read_latest(
        self,
        topic: str,
        schema: str,
        *,
        allow_legacy: bool,
    ) -> dict[str, Any] | None:
        messages = self.jwz.read_json(topic, limit=self.read_limit)
        candidates: list[tuple[int | None, int | None, dict[str, Any]]] = []
        for msg in messages:
            body = msg.get("body")
            if not isinstance(body, str) or not body.strip():
                continue
            try:
                payload = json.loads(body)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            data = self._unwrap(payload, schema, allow_legacy=allow_legacy)
            if data is None:
                continue
            created_at = _as_int(msg.get("created_at"))
            msg_id = _as_int(msg.get("id"))
            candidates.append((created_at, msg_id, data))

        if not candidates:
            return None
        with_created = [item for item in candidates if item[0] is not None]
        if with_created:
            with_created.sort(key=lambda item: item[0])
            return with_created[-1][2]
        with_ids = [item for item in candidates if item[1] is not None]
        if with_ids:
            with_ids.sort(key=lambda item: item[1])
            return with_ids[-1][2]
        # jwz read returns newest-first, so the first valid candidate is newest.
        return candidates[0][2]

    def _unwrap(
        self, payload: dict[str, Any], schema: str, *, allow_legacy: bool
    ) -> dict[str, Any] | None:
        if "schema" in payload and "data" in payload:
            if payload.get("schema") != schema:
                return None
            data = payload.get("data")
            if isinstance(data, dict):
                return data
            return None
        if allow_legacy:
            return payload
        return None

    @staticmethod
    def _session_topic(session_id: str) -> str:
        return f"loopfarm:session:{session_id}"

    @staticmethod
    def _control_topic(session_id: str) -> str:
        return f"loopfarm:control:{session_id}"

    @staticmethod
    def _context_topic(session_id: str) -> str:
        return f"loopfarm:context:{session_id}"

    @staticmethod
    def _discord_cursor_topic(thread_id: str) -> str:
        return f"loopfarm:discord_cursor:{thread_id}"

    @staticmethod
    def _chat_topic(session_id: str) -> str:
        return f"loopfarm:chat:{session_id}"

    @staticmethod
    def _briefing_topic(session_id: str) -> str:
        return f"loopfarm:briefing:{session_id}"
