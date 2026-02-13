from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..stores.session import SessionStore
from ..util import utc_now_iso


EmitFn = Callable[[str, dict[str, Any]], None]
PrintFn = Callable[[str], None]
SetContextFn = Callable[[str, str | None], None]
ClearContextFn = Callable[[str | None], None]
SleepFn = Callable[[int], None]


@dataclass(frozen=True)
class ControlCheckpointResult:
    paused: bool
    session_status: str
    last_signature: str
    stop_requested: bool


class ControlPlane:
    def __init__(self, session_store: SessionStore, *, poll_seconds: int = 5) -> None:
        self.session_store = session_store
        self.poll_seconds = max(1, int(poll_seconds))

    def load_session_context_override(self, session_id: str) -> str:
        meta = self.session_store.get_session_meta(session_id) or {}
        ctx = meta.get("session_context")
        if isinstance(ctx, str):
            return ctx
        return ""

    @staticmethod
    def control_signature(state: dict[str, Any]) -> str:
        parts = [
            str(state.get("timestamp") or ""),
            str(state.get("command") or ""),
            str(state.get("status") or ""),
            str(state.get("phase") or ""),
            str(state.get("iteration") or ""),
            str(state.get("author") or ""),
            str(state.get("content") or ""),
        ]
        return "|".join(parts)

    def read_control_state(
        self, session_id: str, *, last_signature: str
    ) -> tuple[dict[str, Any] | None, str]:
        state = self.session_store.get_control_state(session_id)
        if not state:
            return None, last_signature
        signature = self.control_signature(state)
        if not signature or signature == last_signature:
            return None, last_signature
        return state, signature

    def _post_session_state(
        self, *, session_id: str, phase: str, status: str, iteration: int | None
    ) -> None:
        payload: dict[str, Any] = {
            "status": status,
            "phase": phase,
            "timestamp": utc_now_iso(),
        }
        if iteration is not None:
            payload["iteration"] = iteration
        self.session_store.update_session_meta(session_id, payload, author="runner")

    def apply_control_state(
        self,
        *,
        state: dict[str, Any],
        session_id: str,
        phase: str,
        iteration: int | None,
        paused: bool,
        session_status: str,
        set_session_context: SetContextFn,
        clear_session_context: ClearContextFn,
        emit: EmitFn,
        print_line: PrintFn,
        pause_message: str,
        resume_message: str,
        stop_message: str,
    ) -> tuple[bool, str, bool]:
        command = str(state.get("command") or "").strip().lower()
        content = str(state.get("content") or "").strip()
        author = str(state.get("author") or "").strip() or None

        if command == "pause" and not paused:
            paused = True
            self._post_session_state(
                session_id=session_id,
                phase=phase,
                status="paused",
                iteration=iteration,
            )
            emit(
                "session.pause",
                {"command": "pause", "author": author, "content": content},
            )
            print_line(pause_message)
            return paused, session_status, False

        if command == "resume" and paused:
            paused = False
            self._post_session_state(
                session_id=session_id,
                phase=phase,
                status="running",
                iteration=iteration,
            )
            emit(
                "session.resume",
                {"command": "resume", "author": author, "content": content},
            )
            print_line(resume_message)
            return paused, session_status, False

        if command == "stop":
            session_status = "stopped"
            self._post_session_state(
                session_id=session_id,
                phase=phase,
                status="stopped",
                iteration=iteration,
            )
            emit(
                "session.stop",
                {"command": "stop", "author": author, "content": content},
            )
            print_line(stop_message)
            return paused, session_status, True

        if command == "context_set":
            if content:
                set_session_context(content, author)
            return paused, session_status, False

        if command == "context_clear":
            clear_session_context(author)
            return paused, session_status, False

        return paused, session_status, False

    def checkpoint(
        self,
        *,
        session_id: str,
        phase: str,
        iteration: int | None,
        paused: bool,
        session_status: str,
        last_signature: str,
        set_session_context: SetContextFn,
        clear_session_context: ClearContextFn,
        emit: EmitFn,
        print_line: PrintFn,
        sleep: SleepFn,
        pause_message: str,
        resume_message: str,
        stop_message: str,
    ) -> ControlCheckpointResult:
        state, current_signature = self.read_control_state(
            session_id, last_signature=last_signature
        )
        if state:
            paused, session_status, stop_requested = self.apply_control_state(
                state=state,
                session_id=session_id,
                phase=phase,
                iteration=iteration,
                paused=paused,
                session_status=session_status,
                set_session_context=set_session_context,
                clear_session_context=clear_session_context,
                emit=emit,
                print_line=print_line,
                pause_message=pause_message,
                resume_message=resume_message,
                stop_message=stop_message,
            )
            if stop_requested:
                return ControlCheckpointResult(
                    paused=paused,
                    session_status=session_status,
                    last_signature=current_signature,
                    stop_requested=True,
                )

        while paused:
            sleep(self.poll_seconds)
            state, current_signature = self.read_control_state(
                session_id, last_signature=current_signature
            )
            if not state:
                continue
            paused, session_status, stop_requested = self.apply_control_state(
                state=state,
                session_id=session_id,
                phase=phase,
                iteration=iteration,
                paused=paused,
                session_status=session_status,
                set_session_context=set_session_context,
                clear_session_context=clear_session_context,
                emit=emit,
                print_line=print_line,
                pause_message=pause_message,
                resume_message=resume_message,
                stop_message=stop_message,
            )
            if stop_requested:
                return ControlCheckpointResult(
                    paused=paused,
                    session_status=session_status,
                    last_signature=current_signature,
                    stop_requested=True,
                )

        return ControlCheckpointResult(
            paused=paused,
            session_status=session_status,
            last_signature=current_signature,
            stop_requested=False,
        )
