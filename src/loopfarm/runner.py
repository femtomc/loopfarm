from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import IO, Any, Callable

from .backends import Backend, get_backend
from .discord import DiscordClient
from .discord_commands import (
    DiscordCommand,
    authorized_users_from_env,
    parse_discord_messages,
)
from .phase_contract import build_state_machine, is_termination_gate
from .jwz import Jwz
from .events import EventSink, LoopfarmEvent, StreamEventSink
from .prompting import assemble_prompt, render_prompt
from .session_store import SessionStore
from .templates import TemplateContext
from .util import (
    CommandError,
    env_flag,
    env_int,
    format_duration,
    new_session_id,
    run_capture,
    utc_now_iso,
)


BLUE = "\033[34m"
WHITE = "\033[37m"
GRAY = "\033[90m"
CYAN = "\033[36m"
GREEN = "\033[32m"
MAGENTA = "\033[35m"
RED = "\033[31m"
YELLOW = "\033[33m"
RESET = "\033[0m"


@dataclass(frozen=True)
class CodexPhaseModel:
    model: str
    reasoning: str


class StopRequested(Exception):
    pass


@dataclass(frozen=True)
class LoopfarmConfig:
    repo_root: Path
    cli: str  # backend name (claude|codex|gemini|kimi)
    model_override: str | None
    skip_plan: bool
    project: str
    prompt: str

    code_model: CodexPhaseModel
    plan_model: CodexPhaseModel
    review_model: CodexPhaseModel
    architecture_model: CodexPhaseModel | None = None
    documentation_model: str | None = None

    backward_interval: int = 1  # Run backward every N forward passes (1 = every pass)
    loop_plan_once: bool = False
    loop_steps: tuple[tuple[str, int], ...] | None = None
    loop_report_source_phase: str | None = None
    loop_report_target_phases: tuple[str, ...] = ()

    plan_cli: str | None = None  # per-phase CLI override (None = use cli)
    forward_cli: str | None = None  # per-phase CLI override (None = use cli)
    research_cli: str | None = None  # per-phase CLI override (None = use cli)
    curation_cli: str | None = None  # per-phase CLI override (None = use cli)
    documentation_cli: str | None = None  # per-phase CLI override (None = use cli)
    architecture_cli: str | None = None  # per-phase CLI override (None = use cli)
    backward_cli: str | None = None  # per-phase CLI override (None = use cli)
    mode: str | None = None  # "implementation" | "research" | "writing" | None


@dataclass(frozen=True)
class LoopfarmIO:
    stdout: IO[str] | None = None
    stderr: IO[str] | None = None


BackendProvider = Callable[[str, str, LoopfarmConfig], Backend]


def _truncate_lines(lines: list[str], max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []
    if len(lines) <= max_lines:
        return lines
    extra = len(lines) - max_lines
    return lines[:max_lines] + [f"... ({extra} more lines)"]


def _truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    suffix = " ... (truncated)"
    limit = max_chars - len(suffix)
    if limit <= 0:
        return suffix.strip()
    return text[:limit].rstrip() + suffix


def _chunk_text(text: str, max_chars: int) -> list[str]:
    if not text:
        return []
    if max_chars <= 0:
        return [text]
    return [text[i : i + max_chars] for i in range(0, len(text), max_chars)]


def _extract_claude_text(stream_json_path: Path) -> str:
    if not stream_json_path.exists() or stream_json_path.stat().st_size == 0:
        return ""

    text_parts: list[str] = []
    with stream_json_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if event.get("type") != "stream_event":
                continue
            ev = event.get("event", {})
            if ev.get("type") != "content_block_delta":
                continue
            delta = ev.get("delta", {})
            if delta.get("type") != "text_delta":
                continue
            text = delta.get("text") or ""
            if text:
                text_parts.append(text)
    return "".join(text_parts).strip()


def _extract_codex_text(jsonl_path: Path) -> str:
    if not jsonl_path.exists() or jsonl_path.stat().st_size == 0:
        return ""

    parts: list[str] = []
    with jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception:
                continue
            if event.get("type") != "item.completed":
                continue
            item = event.get("item")
            if not isinstance(item, dict):
                continue
            if item.get("type") != "agent_message":
                continue
            text = str(item.get("text") or "")
            if text.strip():
                parts.append(text)
    return "\n\n".join(parts).strip()


def _extract_kimi_text(jsonl_path: Path) -> str:
    if not jsonl_path.exists() or jsonl_path.stat().st_size == 0:
        return ""

    parts: list[str] = []
    with jsonl_path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except Exception:
                continue
            if msg.get("role") != "assistant":
                continue
            for block in msg.get("content") or []:
                if isinstance(block, str):
                    text = block
                elif isinstance(block, dict) and block.get("type") == "text":
                    text = block.get("text") or ""
                else:
                    text = ""
                if text.strip():
                    parts.append(text)
    return "\n".join(parts).strip()


class JwzPoller(threading.Thread):
    def __init__(
        self,
        *,
        jwz: Jwz,
        discord: DiscordClient,
        thread_id: str,
        topics: list[str],
        stop_event: threading.Event,
        seen_ids: set[str],
        debug: bool,
    ) -> None:
        super().__init__(daemon=True)
        self._jwz = jwz
        self._discord = discord
        self._thread_id = thread_id
        self._topics = topics
        self._stop_event = stop_event
        self._seen_ids = seen_ids
        self._debug = debug
        self._poll_limit = max(1, env_int("LOOPFARM_JWZ_POLL_LIMIT", 25))
        self._poll_max = max(self._poll_limit, env_int("LOOPFARM_JWZ_POLL_MAX", 200))

    def run(self) -> None:
        while not self._stop_event.is_set():
            for topic in self._topics:
                self._post_topic(topic)
            self._stop_event.wait(15)

    def _post_topic(self, topic: str) -> None:
        messages, truncated = self._read_topic_window(topic)
        for msg in messages:
            msg_id = msg.get("id")
            if not msg_id or msg_id in self._seen_ids:
                continue
            body = msg.get("body") or ""
            if not body:
                continue
            try:
                payload = json.loads(body)
            except Exception:
                continue
            formatted = ""
            if "decision" in payload:
                decision = payload.get("decision")
                summary = payload.get("summary") or "No summary"
                if decision == "COMPLETE":
                    formatted = f"✅ **Complete**: {summary}"
                else:
                    formatted = f"📋 **{decision}**: {summary}"
            elif "status" in payload:
                formatted = f"📊 Status: {payload.get('status')}"

            if formatted:
                if self._discord.post(formatted, thread_id=self._thread_id):
                    self._seen_ids.add(str(msg_id))
        if truncated:
            warning = (
                f"⚠️ **Discord status backlog**: `{topic}` has more than "
                f"{self._poll_max} unread messages. Some may be skipped."
            )
            self._discord.post(warning, thread_id=self._thread_id)

    def _read_topic_window(self, topic: str) -> tuple[list[dict[str, Any]], bool]:
        limit = self._poll_limit
        messages = self._jwz.read_json(topic, limit=limit)
        if not self._seen_ids:
            truncated = len(messages) >= limit and limit >= self._poll_max
            return messages, truncated

        while True:
            if len(messages) < limit or self._contains_seen_id(messages):
                return messages, False
            if limit >= self._poll_max:
                return messages, True
            limit = min(limit * 2, self._poll_max)
            messages = self._jwz.read_json(topic, limit=limit)

    def _contains_seen_id(self, messages: list[dict[str, Any]]) -> bool:
        for msg in messages:
            msg_id = msg.get("id")
            if msg_id and str(msg_id) in self._seen_ids:
                return True
        return False


class LoopfarmRunner:
    def __init__(
        self,
        cfg: LoopfarmConfig,
        *,
        event_sink: EventSink | None = None,
        io: LoopfarmIO | None = None,
        backend_provider: BackendProvider | None = None,
    ) -> None:
        self.cfg = cfg
        self.event_sink = event_sink
        self.backend_provider = backend_provider
        self.stdout = io.stdout if io and io.stdout else sys.stdout
        self.stderr = io.stderr if io and io.stderr else sys.stderr
        self.jwz = Jwz(cwd=cfg.repo_root)
        self.session_store = SessionStore(self.jwz)
        self.discord = DiscordClient.from_env()
        self.discord_thread_id = os.environ.get("DISCORD_THREAD_ID") or ""
        self.discord_last_seen_id = ""
        self.pending_discord_context: list[str] = []
        self.pending_discord_commands: list[DiscordCommand] = []
        self.discord_context_override = ""
        self.paused = False
        self.seen_jwz_ids: set[str] = set()
        self.last_phase = "startup"
        self.start_monotonic: float = 0.0
        self.session_status = "interrupted"
        self.last_forward_report: dict[str, Any] | None = None
        self.session_id: str | None = None

    def _print(self, *parts: object) -> None:
        print(*parts, file=self.stdout)

    def _emit(
        self,
        event_type: str,
        *,
        phase: str | None = None,
        iteration: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        if not self.event_sink:
            return
        full_payload = dict(payload or {})
        if self.session_id:
            full_payload.setdefault("session_id", self.session_id)
        event = LoopfarmEvent(
            type=event_type,
            timestamp=utc_now_iso(),
            phase=phase,
            iteration=iteration,
            payload=full_payload,
        )
        self.event_sink(event)

    def _stream_event_sink(
        self, *, phase: str, iteration: int | None
    ) -> StreamEventSink:
        def sink(event_type: str, payload: dict[str, Any]) -> None:
            self._emit(event_type, phase=phase, iteration=iteration, payload=payload)

        return sink

    def run(self, *, session_id: str) -> int:
        start_time = utc_now_iso()
        self.start_monotonic = time.monotonic()
        self.session_id = session_id

        os.environ["LOOPFARM_SESSION"] = session_id

        self.session_store.update_session_meta(
            session_id,
            {"prompt": self.cfg.prompt, "started": start_time, "status": "running"},
            author="runner",
        )
        self._emit(
            "session.start",
            payload={
                "started": start_time,
                "prompt": self.cfg.prompt,
                "project": self.cfg.project,
                "repo_root": str(self.cfg.repo_root),
                "cli": self.cfg.cli,
                "plan_cli": self.cfg.plan_cli,
                "forward_cli": self.cfg.forward_cli,
                "research_cli": self.cfg.research_cli,
                "curation_cli": self.cfg.curation_cli,
                "documentation_cli": self.cfg.documentation_cli,
                "architecture_cli": self.cfg.architecture_cli,
                "backward_cli": self.cfg.backward_cli,
                "model_override": self.cfg.model_override,
                "skip_plan": self.cfg.skip_plan,
                "mode": self.cfg.mode,
                "loop_plan_once": self.cfg.loop_plan_once,
                "loop_steps": list(self.cfg.loop_steps or ()),
                "loop_report_source_phase": self.cfg.loop_report_source_phase,
                "loop_report_target_phases": list(self.cfg.loop_report_target_phases),
            },
        )

        self._ensure_discord_thread(session_id, start_time)
        self._load_discord_cursor()
        self._load_discord_context_override(session_id)

        self._print(
            f"{BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}"
        )
        self._print(f"{WHITE}  LOOPFARM{RESET}  {GRAY}{session_id}{RESET}")
        self._print(f"  {GRAY}{self.cfg.prompt}{RESET}")
        self._print(
            f"{BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━{RESET}\n"
        )

        try:
            should_plan = not self.cfg.skip_plan
            if self.cfg.loop_steps is not None:
                should_plan = should_plan and self.cfg.loop_plan_once
            if should_plan:
                self._planning_phase(session_id)
            else:
                self._print(f"\n{GRAY}◆ PLANNING{RESET} {GRAY}(skipped){RESET}\n")
                self._discord_post("**◆ PLANNING** skipped")
                reason = "skip_plan"
                if self.cfg.loop_steps is not None and not self.cfg.loop_plan_once:
                    reason = "loop_spec"
                self._emit(
                    "phase.skip",
                    phase="planning",
                    payload={"reason": reason},
                )

            if self.cfg.loop_steps is not None:
                return self._configured_loop(session_id)
            return self._loop(session_id)
        except StopRequested:
            return 1
        except KeyboardInterrupt:
            self.session_status = "interrupted"
            return 1
        finally:
            self._finalize_session(session_id)

    def _finalize_session(self, session_id: str) -> None:
        end_time = utc_now_iso()
        duration = max(0, int(time.monotonic() - self.start_monotonic))
        duration_str = format_duration(duration)

        if self.session_status != "complete":
            self.session_store.update_session_meta(
                session_id,
                {"status": self.session_status, "ended": end_time},
                author="runner",
            )
            title = "Session Interrupted"
            if self.session_status == "stopped":
                title = "Session Stopped"
            self._discord_post(
                f"⚠️ **{title}**\n\n"
                f"**Duration:** {duration_str}\n"
                f"**Last Phase:** {self.last_phase}\n"
                f"**Ended:** {end_time}"
            )
            self._emit(
                "session.end",
                payload={
                    "status": self.session_status,
                    "ended": end_time,
                    "duration_seconds": duration,
                    "duration": duration_str,
                    "last_phase": self.last_phase,
                },
            )
            self._print(f"\n{RED}Stopped.{RESET}")
        else:
            self.session_store.update_session_meta(
                session_id,
                {"status": "complete", "ended": end_time},
                author="runner",
            )
            self._emit(
                "session.end",
                payload={
                    "status": "complete",
                    "ended": end_time,
                    "duration_seconds": duration,
                    "duration": duration_str,
                    "last_phase": self.last_phase,
                },
            )

    def _ensure_discord_thread(self, session_id: str, start_time: str) -> None:
        if self.discord_thread_id:
            return
        if not self.discord.webhook:
            return

        prompt = self.cfg.prompt
        thread_name = f"{session_id}: {prompt[:70]}"
        if len(prompt) > 70:
            thread_name += "..."

        bidir_hint = ""
        if self.discord.bot_token:
            bidir_hint = (
                "\n\n💬 **Interactive Mode:** Post messages to this thread to inject context into subsequent phases."
                "\n\n⏸️ **Loop Control:** `!pause`, `!resume`, `!stop`"
                "\n\n🧭 **Context:** `!context show`, `!context set …`, `!context clear`"
                "\n\n🗣️ **One-off Chat:** `!chat …` or `!ask …` (use `!chat reset` to clear history)"
            )

        initial_msg = (
            f"**Session Started** `{session_id}`\n\n"
            "**Prompt:**\n"
            "```\n"
            f"{prompt}\n"
            "```\n\n"
            f"**Started:** {start_time}{bidir_hint}"
        )

        thread_id = self.discord.create_thread(thread_name, initial_msg)
        if not thread_id:
            if not self.discord.webhook:
                self._print(
                    f"{YELLOW}⚠ Discord notifications disabled (LOOPFARM_DISCORD_WEBHOOK not set){RESET}"
                )
            else:
                self._print(
                    f"{YELLOW}⚠ Discord thread creation failed - set LOOPFARM_DISCORD_DEBUG=1 for details{RESET}"
                )
            return
        self.discord_thread_id = thread_id
        os.environ["DISCORD_THREAD_ID"] = thread_id

    def _discord_post(self, content: str) -> bool:
        if not self.discord_thread_id:
            return False
        return self.discord.post(content, thread_id=self.discord_thread_id)

    def _discord_post_chunks(self, content: str) -> None:
        if not content.strip():
            return
        max_chars = max(200, env_int("LOOPFARM_DISCORD_CHUNK_CHARS", 1900))
        for chunk in _chunk_text(content, max_chars):
            self._discord_post(chunk)

    def _post_jwz_status(self, topic: str) -> None:
        if not self.discord_thread_id:
            return
        messages = self.jwz.read_json(topic, limit=5)
        for msg in messages:
            msg_id = msg.get("id")
            if not msg_id or str(msg_id) in self.seen_jwz_ids:
                continue
            body = msg.get("body") or ""
            if not body:
                continue
            try:
                payload = json.loads(body)
            except Exception:
                continue
            formatted = ""
            if "decision" in payload:
                decision = payload.get("decision")
                summary = payload.get("summary") or "No summary"
                if decision == "COMPLETE":
                    formatted = f"✅ **Complete**: {summary}"
                else:
                    formatted = f"📋 **{decision}**: {summary}"
            elif "status" in payload:
                formatted = f"📊 Status: {payload.get('status')}"
            if formatted:
                if self._discord_post(formatted):
                    self.seen_jwz_ids.add(str(msg_id))

    def _collect_discord_messages(self) -> None:
        if not self.discord.bot_token or not self.discord_thread_id:
            return

        bot_id = self.discord.get_bot_user_id() or ""
        messages = self.discord.read_messages(
            self.discord_thread_id, after_id=self.discord_last_seen_id
        )
        if not messages:
            return

        result = parse_discord_messages(
            messages,
            bot_user_id=bot_id,
            authorized_users=authorized_users_from_env(),
        )

        if result.newest_id:
            self.discord_last_seen_id = str(result.newest_id)
            if self.session_id:
                self.session_store.set_discord_cursor(
                    self.discord_thread_id, self.discord_last_seen_id
                )

        context_count = 0
        for line, author in zip(result.context_lines, result.context_authors):
            self.pending_discord_context.append(line)
            if self.session_id:
                self.session_store.set_session_context(
                    self.session_id,
                    line,
                    author=author,
                )
            context_count += 1

        if result.commands:
            self.pending_discord_commands.extend(result.commands)

        if context_count:
            self._discord_post(
                f"📨 Received {context_count} message(s) from thread. "
                "Incorporating into next phase."
            )

    def _flush_discord_context(self) -> str:
        if not self.pending_discord_context:
            return ""
        ctx = "\n".join(self.pending_discord_context).strip()
        self.pending_discord_context = []
        return ctx

    def _set_discord_context_override(
        self, text: str, *, author: str | None
    ) -> None:
        self.discord_context_override = text
        if self.session_id:
            self.session_store.update_session_meta(
                self.session_id,
                {"discord_context": text},
                author=author,
            )

    def _clear_discord_context_override(self, *, author: str | None) -> None:
        self.discord_context_override = ""
        if self.session_id:
            self.session_store.update_session_meta(
                self.session_id,
                {"discord_context": ""},
                author=author,
            )

    def _discord_command_help(self) -> str:
        return (
            "🧭 **Loopfarm Commands**\n\n"
            "- `!pause` / `!resume` / `!stop`\n"
            "- `!context show` / `!context set …` / `!context clear`\n"
            "- `!chat …` / `!ask …` (one-off chat)\n"
            "- `!chat reset`\n"
            "- `!chat backend <name>` / `!chat model <name>`\n"
            "- Prefix with `!loopfarm` (or `!loopfarm`) if desired"
        )

    def _drain_discord_commands(self) -> list[DiscordCommand]:
        if not self.pending_discord_commands:
            return []
        commands = self.pending_discord_commands
        self.pending_discord_commands = []
        return commands

    def _chat_history_limit(self) -> int:
        return max(0, env_int("LOOPFARM_CHAT_HISTORY_LIMIT", 12))

    def _format_chat_history(self, history: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for turn in history:
            role = str(turn.get("role") or "user").lower()
            content = str(turn.get("content") or "").strip()
            if not content:
                continue
            label = "User" if role == "user" else "Assistant"
            lines.append(f"{label}: {content}")
        return "\n".join(lines).strip()

    def _build_chat_prompt(
        self,
        *,
        session_id: str,
        message: str,
        history: list[dict[str, Any]],
    ) -> str:
        lines = [
            "You are answering a one-off chat request from a human monitoring a Loopfarm loop.",
            "Do not advance the loop or modify files; respond conversationally and concisely.",
            "",
            f"Primary task:\n{self.cfg.prompt}",
        ]

        session_ctx = self.discord_context_override.strip()
        if session_ctx:
            lines.extend(
                [
                    "",
                    "Pinned session context:",
                    "```",
                    session_ctx,
                    "```",
                ]
            )

        history_text = self._format_chat_history(history)
        if history_text:
            lines.extend(["", "Chat history:", history_text])

        lines.extend(["", f"User: {message}", "Assistant:"])
        return "\n".join(lines).strip()

    def _extract_chat_response(
        self, backend: Backend, output_path: Path, last_message_path: Path
    ) -> str:
        if backend.name == "claude":
            return _extract_claude_text(output_path)
        if backend.name == "codex":
            return _extract_codex_text(output_path)
        if backend.name == "kimi":
            return _extract_kimi_text(output_path)
        return ""

    def _run_chat(
        self,
        *,
        session_id: str,
        message: str,
        author: str | None,
    ) -> None:
        chat_state = self.session_store.get_chat_state(session_id) or {}
        history = chat_state.get("messages") or []
        if not isinstance(history, list):
            history = []

        history_limit = self._chat_history_limit()
        if history_limit and len(history) > history_limit:
            history = history[-history_limit:]

        backend_name = str(
            chat_state.get("backend") or self._cli_for_phase("forward")
        ).strip()
        try:
            backend = get_backend(backend_name)
        except KeyError:
            self._discord_post(
                f"⚠️ **Chat backend** `{backend_name}` is not registered."
            )
            return

        cfg = self.cfg
        chat_model = str(chat_state.get("model") or "").strip()
        if chat_model:
            cfg = replace(cfg, model_override=chat_model)

        prompt = self._build_chat_prompt(
            session_id=session_id, message=message, history=history
        )

        user_turn = {
            "role": "user",
            "content": message,
            "author": author or "",
            "timestamp": utc_now_iso(),
        }
        self.session_store.append_chat_turn(
            session_id, user_turn, author=author, limit=history_limit
        )

        out_path = self._tmp_path(prefix="chat_", suffix=".log")
        last_path = self._tmp_path(prefix="chat_", suffix=".last.txt")
        try:
            self._discord_post("💬 **Chat** running…")
            ok = backend.run(
                phase="chat",
                prompt=prompt,
                output_path=out_path,
                last_message_path=last_path,
                cfg=cfg,
            )
            response = self._extract_chat_response(
                backend, out_path, last_path
            )
        finally:
            self._cleanup_paths(out_path, last_path)

        if not ok:
            error_msg = "⚠️ **Chat** failed. Check runner logs for details."
            self.session_store.append_chat_turn(
                session_id,
                {
                    "role": "assistant",
                    "content": error_msg,
                    "author": backend.name,
                    "timestamp": utc_now_iso(),
                },
                author=None,
                limit=history_limit,
            )
            self._discord_post(error_msg)
            return

        if not response.strip():
            response = "_(no response captured from agent output)_"

        self.session_store.append_chat_turn(
            session_id,
            {
                "role": "assistant",
                "content": response,
                "author": backend.name,
                "timestamp": utc_now_iso(),
            },
            author=None,
            limit=history_limit,
        )
        self._discord_post_chunks(response)

    def _post_control_event(
        self,
        *,
        session_id: str,
        phase: str,
        iteration: int | None,
        status: str,
        command: str,
        author: str | None,
        content: str | None,
    ) -> None:
        self.session_store.set_control_state(
            session_id,
            status=status,
            command=command,
            phase=phase,
            iteration=iteration,
            author=author,
            content=content,
        )

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

    def _handle_discord_commands(
        self, *, session_id: str, phase: str, iteration: int | None
    ) -> None:
        commands = self._drain_discord_commands()
        for cmd in commands:
            command = cmd.kind
            author = cmd.author or None
            content = cmd.content or None

            if command == "pause" and not self.paused:
                self.paused = True
                self._post_control_event(
                    session_id=session_id,
                    phase=phase,
                    iteration=iteration,
                    status="paused",
                    command="pause",
                    author=author,
                    content=content,
                )
                self._post_session_state(
                    session_id=session_id,
                    phase=phase,
                    status="paused",
                    iteration=iteration,
                )
                self._discord_post(
                    f"⏸️ **Paused** before {phase.upper()}."
                    " Send `!resume` to continue or `!stop` to end."
                )
                self._emit(
                    "session.pause",
                    phase=phase,
                    iteration=iteration,
                    payload={"command": "pause", "author": author, "content": content},
                )
                self._print(f"\n{YELLOW}⏸ Paused before {phase}.{RESET}")
                continue

            if command == "resume" and self.paused:
                self.paused = False
                self._post_control_event(
                    session_id=session_id,
                    phase=phase,
                    iteration=iteration,
                    status="resumed",
                    command="resume",
                    author=author,
                    content=content,
                )
                self._post_session_state(
                    session_id=session_id,
                    phase=phase,
                    status="running",
                    iteration=iteration,
                )
                self._discord_post(
                    f"▶️ **Resumed** - continuing {phase.upper()}."
                )
                self._emit(
                    "session.resume",
                    phase=phase,
                    iteration=iteration,
                    payload={"command": "resume", "author": author, "content": content},
                )
                self._print(f"{GREEN}▶ Resumed.{RESET}")
                continue

            if command == "stop":
                self.session_status = "stopped"
                self._post_control_event(
                    session_id=session_id,
                    phase=phase,
                    iteration=iteration,
                    status="stopped",
                    command="stop",
                    author=author,
                    content=content,
                )
                self._post_session_state(
                    session_id=session_id,
                    phase=phase,
                    status="stopped",
                    iteration=iteration,
                )
                self._discord_post("⛔ **Stop requested** - ending session.")
                self._emit(
                    "session.stop",
                    phase=phase,
                    iteration=iteration,
                    payload={"command": "stop", "author": author, "content": content},
                )
                self._print(f"\n{RED}⛔ Stop requested.{RESET}")
                raise StopRequested()

            if command == "context_show":
                ctx = self.discord_context_override.strip()
                if not ctx:
                    self._discord_post(
                        "🧭 **Context** is empty. Use `!context set …` to set it."
                    )
                    continue
                ctx = _truncate_text(ctx, 1700)
                self._discord_post(f"🧭 **Context**:\n```\n{ctx}\n```")
                continue

            if command == "context_set":
                new_ctx = (cmd.args or "").strip()
                if not new_ctx:
                    self._discord_post(
                        "⚠️ **Context set** needs text. Example: `!context set …`."
                    )
                    continue
                self._set_discord_context_override(new_ctx, author=author)
                self._discord_post(
                    f"🧭 **Context updated** ({len(new_ctx)} chars)."
                )
                continue

            if command == "context_clear":
                if self.discord_context_override.strip():
                    self._clear_discord_context_override(author=author)
                    self._discord_post("🧹 **Context cleared**.")
                else:
                    self._discord_post("🧹 **Context** already empty.")
                continue

            if command == "chat":
                message = (cmd.args or "").strip()
                if not message:
                    self._discord_post(
                        "⚠️ **Chat** needs a prompt. Example: `!chat How do we …?`."
                    )
                    continue

                lowered = message.lower()
                if lowered in {"reset", "clear"}:
                    self.session_store.update_chat_state(
                        session_id, {"messages": []}, author=author
                    )
                    self._discord_post("🧹 **Chat history cleared**.")
                    continue

                parts = message.split(None, 1)
                head = parts[0].lower()
                tail = parts[1].strip() if len(parts) > 1 else ""

                if head == "backend":
                    if not tail:
                        self._discord_post(
                            "⚠️ **Chat backend** needs a name. Example: `!chat backend codex`."
                        )
                        continue
                    try:
                        get_backend(tail)
                    except KeyError:
                        self._discord_post(
                            f"⚠️ **Chat backend** `{tail}` is not registered."
                        )
                        continue
                    self.session_store.update_chat_state(
                        session_id, {"backend": tail}, author=author
                    )
                    self._discord_post(f"✅ **Chat backend** set to `{tail}`.")
                    continue

                if head == "model":
                    if not tail:
                        self._discord_post(
                            "⚠️ **Chat model** needs a name. Example: `!chat model gpt-5.2`."
                        )
                        continue
                    if tail.lower() in {"clear", "reset", "default"}:
                        self.session_store.update_chat_state(
                            session_id, {"model": ""}, author=author
                        )
                        self._discord_post("✅ **Chat model** cleared.")
                        continue
                    self.session_store.update_chat_state(
                        session_id, {"model": tail}, author=author
                    )
                    self._discord_post(f"✅ **Chat model** set to `{tail}`.")
                    continue

                self._run_chat(session_id=session_id, message=message, author=author)
                continue

            if command == "help":
                self._discord_post(self._discord_command_help())

    def _control_checkpoint(
        self, *, session_id: str, phase: str, iteration: int | None
    ) -> None:
        self._collect_discord_messages()
        self._handle_discord_commands(
            session_id=session_id, phase=phase, iteration=iteration
        )

        poll_seconds = max(1, env_int("LOOPFARM_CONTROL_POLL_SECONDS", 5))
        while self.paused:
            self._sleep(poll_seconds)
            self._collect_discord_messages()
            self._handle_discord_commands(
                session_id=session_id, phase=phase, iteration=iteration
            )


    def _cli_for_phase(self, phase: str) -> str:
        if phase == "planning" and self.cfg.plan_cli:
            return self.cfg.plan_cli
        if phase == "forward" and self.cfg.forward_cli:
            return self.cfg.forward_cli
        if phase == "research":
            if self.cfg.research_cli:
                return self.cfg.research_cli
            if self.cfg.plan_cli:
                return self.cfg.plan_cli
        if phase == "curation":
            if self.cfg.curation_cli:
                return self.cfg.curation_cli
            if self.cfg.plan_cli:
                return self.cfg.plan_cli
        if phase == "documentation":
            if self.cfg.documentation_cli:
                return self.cfg.documentation_cli
            if self.cfg.forward_cli:
                return self.cfg.forward_cli
        if phase == "architecture":
            if self.cfg.architecture_cli:
                return self.cfg.architecture_cli
            if self.cfg.backward_cli:
                return self.cfg.backward_cli
        if phase == "backward" and self.cfg.backward_cli:
            return self.cfg.backward_cli
        return self.cfg.cli

    def _backend_for_phase(self, phase: str) -> Backend:
        name = self._cli_for_phase(phase)
        if self.backend_provider:
            return self.backend_provider(name, phase, self.cfg)
        try:
            return get_backend(name)
        except KeyError as exc:
            raise SystemExit(str(exc)) from exc

    def _prompt_path(self, phase: str) -> Path:
        # Prefer standalone layout first, then monorepo layout, then root fallback.
        prompts_root: Path | None = None
        for candidate in (
            self.cfg.repo_root / "prompts",
            self.cfg.repo_root / "loopfarm" / "prompts",
        ):
            if candidate.exists():
                prompts_root = candidate
                break
        if prompts_root is None:
            prompts_root = self.cfg.repo_root / "prompts"
        candidates: list[Path] = []
        mode = (self.cfg.mode or "").strip()
        if mode:
            candidates.append(prompts_root / mode / f"{phase}.md")
        implementation_path = prompts_root / "implementation" / f"{phase}.md"
        if implementation_path not in candidates:
            candidates.append(implementation_path)
        root_path = prompts_root / f"{phase}.md"
        if root_path not in candidates:
            candidates.append(root_path)

        for path in candidates:
            if path.exists():
                return path
        return root_path

    def _planning_phase(self, session_id: str) -> None:
        self.last_phase = "planning"
        self._control_checkpoint(session_id=session_id, phase="planning", iteration=None)
        phase_start = utc_now_iso()[11:19]
        self._print(f"\n{CYAN}◆ PLANNING{RESET} {GRAY}{phase_start}{RESET}")
        self._print(
            f"{GRAY}─────────────────────────────────────────────────────────{RESET}\n"
        )
        self._discord_post(f"**◆ PLANNING** started at {phase_start}")
        self._emit(
            "phase.start",
            phase="planning",
            payload={
                "started": phase_start,
                "prompt": self.cfg.prompt,
                "prompt_path": str(self._prompt_path("planning")),
            },
        )

        planning_prompt = self._build_phase_prompt(session_id, "planning")

        out_path = self._tmp_path(prefix="planning_", suffix=".jsonl")
        last_path = self._tmp_path(prefix="planning_", suffix=".last.txt")

        stop_event, poller = self._start_poller(session_id)
        try:
            ok = self._run_agent(
                "planning", planning_prompt, out_path, last_path, iteration=None
            )
        finally:
            self._stop_poller(stop_event, poller)

        if not ok:
            self._emit(
                "phase.error",
                phase="planning",
                payload={
                    "ok": False,
                    "output_path": str(out_path),
                    "last_message_path": str(last_path),
                },
            )
            self._print(f"{RED}✗ Planning failed{RESET}")
            self._discord_post("**◆ PLANNING** ❌ failed")
            raise SystemExit(1)

        summary = self._phase_summary("planning", out_path, last_path)
        self._emit(
            "phase.end",
            phase="planning",
            payload={
                "ok": True,
                "summary": summary,
                "output_path": str(out_path),
                "last_message_path": str(last_path),
            },
        )
        self._store_phase_summary(session_id, "planning", 0, summary)
        self._cleanup_paths(out_path, last_path)
        if summary:
            self._discord_post(f"**◆ PLANNING** Summary:\n{summary}")
        else:
            self._discord_post(f"**◆ PLANNING** ✅ completed at {utc_now_iso()[11:19]}")

    def _phase_presentation(self, phase: str) -> tuple[str, str, str]:
        if phase == "forward":
            return "▶ FORWARD", "**▶ FORWARD**", GREEN
        if phase == "research":
            return "◆ RESEARCH", "**◆ RESEARCH**", CYAN
        if phase == "curation":
            return "◆ CURATION", "**◆ CURATION**", WHITE
        if phase == "documentation":
            return "◆ DOCUMENTATION", "**◆ DOCUMENTATION**", BLUE
        if phase == "architecture":
            return "◆ ARCHITECTURE", "**◆ ARCHITECTURE**", YELLOW
        if phase == "backward":
            return "◀ BACKWARD", "**◀ BACKWARD**", MAGENTA
        return phase.upper(), f"**{phase.upper()}**", WHITE

    def _run_operational_phase(
        self,
        *,
        session_id: str,
        phase: str,
        iteration: int,
        forward_report: dict[str, Any] | None = None,
        run_index: int | None = None,
        run_total: int | None = None,
    ) -> str:
        fail_count = 0
        label, discord_label, color = self._phase_presentation(phase)
        run_suffix = ""
        if run_index is not None and run_total is not None:
            run_suffix = f" ({run_index}/{run_total})"

        while True:
            self.last_phase = phase
            self._control_checkpoint(
                session_id=session_id, phase=phase, iteration=iteration
            )
            phase_start = utc_now_iso()[11:19]
            self._print(f"\n{color}{label}{RESET}{run_suffix} {GRAY}{phase_start}{RESET}")
            self._print(
                f"{GRAY}─────────────────────────────────────────────────────────{RESET}\n"
            )
            self._discord_post(
                f"{discord_label} #{iteration}{run_suffix} started at {phase_start}"
            )
            payload: dict[str, Any] = {
                "started": phase_start,
                "prompt": self.cfg.prompt,
                "prompt_path": str(self._prompt_path(phase)),
            }
            if run_index is not None and run_total is not None:
                payload["run_index"] = run_index
                payload["run_total"] = run_total
            self._emit(
                "phase.start",
                phase=phase,
                iteration=iteration,
                payload=payload,
            )

            phase_prompt = self._build_phase_prompt(
                session_id, phase, forward_report=forward_report
            )
            out_path = self._tmp_path(prefix=f"{phase}_", suffix=".log")
            last_path = self._tmp_path(prefix=f"{phase}_", suffix=".last.txt")
            try:
                stop_event, poller = self._start_poller(session_id)
                try:
                    ok = self._run_agent(
                        phase,
                        phase_prompt,
                        out_path,
                        last_path,
                        iteration=iteration,
                    )
                finally:
                    self._stop_poller(stop_event, poller)

                if ok:
                    summary = self._phase_summary(phase, out_path, last_path)
                    self._emit(
                        "phase.end",
                        phase=phase,
                        iteration=iteration,
                        payload={
                            "ok": True,
                            "summary": summary,
                            "output_path": str(out_path),
                            "last_message_path": str(last_path),
                        },
                    )
                    self._store_phase_summary(session_id, phase, iteration, summary)
                    if summary:
                        self._discord_post(
                            f"{discord_label} #{iteration}{run_suffix} Summary:\n{summary}"
                        )
                    else:
                        self._discord_post(
                            f"{discord_label} #{iteration}{run_suffix} ✅ completed at {utc_now_iso()[11:19]}"
                        )
                    self._post_jwz_status(f"loopfarm:status:{session_id}")
                    return summary

                self._emit(
                    "phase.error",
                    phase=phase,
                    iteration=iteration,
                    payload={
                        "ok": False,
                        "output_path": str(out_path),
                        "last_message_path": str(last_path),
                        "fail_count": fail_count + 1,
                    },
                )
                fail_count += 1
                if fail_count >= 3:
                    self._print(
                        f"{RED}✗ Too many failures in {phase}, waiting 15 minutes...{RESET}"
                    )
                    self._discord_post(
                        f"{discord_label} #{iteration}{run_suffix} ⚠️ failed ({fail_count} consecutive), waiting 15 minutes before retry..."
                    )
                    self._sleep(900)
                    fail_count = 0
                else:
                    self._sleep(2)
            finally:
                self._cleanup_paths(out_path, last_path)

    def _mark_complete(self, *, iteration: int, summary: str) -> int:
        self.session_status = "complete"
        duration = max(0, int(time.monotonic() - self.start_monotonic))
        duration_str = format_duration(duration)
        self._discord_post(
            "✅ **Session Complete**\n\n"
            f"**Duration:** {duration_str}\n"
            f"**Iterations:** {iteration}\n"
            f"**Summary:** {summary or 'No summary provided'}\n"
            f"**Ended:** {utc_now_iso()}"
        )
        self._emit(
            "session.complete",
            payload={
                "iterations": iteration,
                "summary": summary,
                "ended": utc_now_iso(),
            },
        )
        self._print(f"\n{GREEN}✓ Complete.{RESET}")
        return 0

    def _configured_loop(self, session_id: str) -> int:
        if not self.cfg.loop_steps:
            raise SystemExit("loop configuration missing steps")
        machine = build_state_machine(
            planning_once=self.cfg.loop_plan_once,
            loop_steps=self.cfg.loop_steps,
        )
        loop_iteration = 0

        while True:
            loop_iteration += 1
            source_summaries: list[str] = []
            report_pre_head: str | None = None
            report_ready = False
            report_source = self.cfg.loop_report_source_phase
            report_targets = set(self.cfg.loop_report_target_phases)

            for phase, repeat in machine.loop_steps:
                for run_index in range(1, repeat + 1):
                    if report_source and phase == report_source and report_pre_head is None:
                        report_pre_head = self._git_head()

                    if (
                        report_source
                        and report_targets
                        and phase in report_targets
                        and not report_ready
                    ):
                        if report_pre_head is None:
                            report_pre_head = self._git_head()
                        report_post_head = self._git_head()
                        source_summary = "\n\n".join(
                            s for s in source_summaries if s.strip()
                        )
                        cycle_report = self._build_forward_report(
                            session_id=session_id,
                            pre_head=report_pre_head,
                            post_head=report_post_head,
                            summary=source_summary,
                        )
                        self.last_forward_report = cycle_report
                        self._post_forward_report(session_id, cycle_report)
                        self._emit(
                            "phase.forward_report",
                            phase=report_source,
                            iteration=loop_iteration,
                            payload=cycle_report,
                        )
                        report_ready = True

                    summary = self._run_operational_phase(
                        session_id=session_id,
                        phase=phase,
                        iteration=loop_iteration,
                        forward_report=(
                            self.last_forward_report
                            if phase in report_targets
                            else None
                        ),
                        run_index=run_index if repeat > 1 else None,
                        run_total=repeat if repeat > 1 else None,
                    )

                    if report_source and phase == report_source and summary.strip():
                        source_summaries.append(summary)

                    if is_termination_gate(phase):
                        decision, completion_summary = self._read_completion(session_id)
                        if decision == "COMPLETE":
                            return self._mark_complete(
                                iteration=loop_iteration,
                                summary=completion_summary,
                            )

    def _loop(self, session_id: str) -> int:
        loop_iteration = 0
        fail_count = 0

        while True:
            loop_iteration += 1

            # Forward
            pre_head = self._git_head()
            self.last_phase = "forward"
            self._control_checkpoint(
                session_id=session_id, phase="forward", iteration=loop_iteration
            )
            phase_start = utc_now_iso()[11:19]
            self._print(f"\n{GREEN}▶ FORWARD{RESET} {GRAY}{phase_start}{RESET}")
            self._print(
                f"{GRAY}─────────────────────────────────────────────────────────{RESET}\n"
            )
            self._discord_post(
                f"**▶ FORWARD** #{loop_iteration} started at {phase_start}"
            )
            self._emit(
                "phase.start",
                phase="forward",
                iteration=loop_iteration,
                payload={
                    "started": phase_start,
                    "prompt": self.cfg.prompt,
                    "prompt_path": str(self._prompt_path("forward")),
                },
            )

            forward_prompt = self._build_phase_prompt(session_id, "forward")

            forward_out = self._tmp_path(prefix="forward_", suffix=".log")
            forward_last = self._tmp_path(prefix="forward_", suffix=".last.txt")
            try:
                while True:
                    stop_event, poller = self._start_poller(session_id)
                    try:
                        ok = self._run_agent(
                            "forward",
                            forward_prompt,
                            forward_out,
                            forward_last,
                            iteration=loop_iteration,
                        )
                    finally:
                        self._stop_poller(stop_event, poller)

                    if ok:
                        fail_count = 0
                        break
                    self._emit(
                        "phase.error",
                        phase="forward",
                        iteration=loop_iteration,
                        payload={
                            "ok": False,
                            "output_path": str(forward_out),
                            "last_message_path": str(forward_last),
                            "fail_count": fail_count + 1,
                        },
                    )
                    fail_count += 1
                    if fail_count >= 3:
                        self._print(
                            f"{RED}✗ Too many failures, waiting 15 minutes...{RESET}"
                        )
                        self._discord_post(
                            f"**▶ FORWARD** #{loop_iteration} ⚠️ failed ({fail_count} consecutive), waiting 15 minutes before retry..."
                        )
                        self._sleep(900)
                        fail_count = 0
                    else:
                        self._sleep(2)

                forward_summary = self._phase_summary(
                    "forward", forward_out, forward_last
                )
                self._store_phase_summary(
                    session_id, "forward", loop_iteration, forward_summary
                )
                post_head = self._git_head()
                forward_report = self._build_forward_report(
                    session_id=session_id,
                    pre_head=pre_head,
                    post_head=post_head,
                    summary=forward_summary,
                )
                self.last_forward_report = forward_report
                self._post_forward_report(session_id, forward_report)
                self._emit(
                    "phase.forward_report",
                    phase="forward",
                    iteration=loop_iteration,
                    payload=forward_report,
                )
                self._emit(
                    "phase.end",
                    phase="forward",
                    iteration=loop_iteration,
                    payload={
                        "ok": True,
                        "summary": forward_summary,
                        "output_path": str(forward_out),
                        "last_message_path": str(forward_last),
                    },
                )
                if forward_summary:
                    self._discord_post(
                        f"**▶ FORWARD** #{loop_iteration} Summary:\n{forward_summary}"
                    )
                else:
                    self._discord_post(
                        f"**▶ FORWARD** #{loop_iteration} ✅ completed at {utc_now_iso()[11:19]}"
                    )
            finally:
                self._cleanup_paths(forward_out, forward_last)

            # Post statuses
            self._post_jwz_status(f"loopfarm:status:{session_id}")

            # Backward (runs every backward_interval iterations)
            run_backward = loop_iteration % self.cfg.backward_interval == 0
            if not run_backward:
                self._emit(
                    "phase.skip",
                    phase="backward",
                    iteration=loop_iteration,
                    payload={"backward_interval": self.cfg.backward_interval},
                )
                self._print(
                    f"\n{GRAY}◀ BACKWARD skipped (next at iteration "
                    f"{loop_iteration + (self.cfg.backward_interval - loop_iteration % self.cfg.backward_interval)}){RESET}"
                )
                continue

            self.last_phase = "backward"
            self._control_checkpoint(
                session_id=session_id, phase="backward", iteration=loop_iteration
            )
            phase_start = utc_now_iso()[11:19]
            self._print(f"\n{MAGENTA}◀ BACKWARD{RESET} {GRAY}{phase_start}{RESET}")
            self._print(
                f"{GRAY}─────────────────────────────────────────────────────────{RESET}\n"
            )
            self._discord_post(
                f"**◀ BACKWARD** #{loop_iteration} started at {phase_start}"
            )
            self._emit(
                "phase.start",
                phase="backward",
                iteration=loop_iteration,
                payload={
                    "started": phase_start,
                    "prompt": self.cfg.prompt,
                    "prompt_path": str(self._prompt_path("backward")),
                },
            )

            backward_prompt = self._build_phase_prompt(
                session_id, "backward", forward_report=self.last_forward_report
            )

            backward_out = self._tmp_path(prefix="backward_", suffix=".log")
            backward_last = self._tmp_path(prefix="backward_", suffix=".last.txt")
            try:
                while True:
                    stop_event, poller = self._start_poller(session_id)
                    try:
                        ok = self._run_agent(
                            "backward",
                            backward_prompt,
                            backward_out,
                            backward_last,
                            iteration=loop_iteration,
                        )
                    finally:
                        self._stop_poller(stop_event, poller)

                    if ok:
                        fail_count = 0
                        break
                    self._emit(
                        "phase.error",
                        phase="backward",
                        iteration=loop_iteration,
                        payload={
                            "ok": False,
                            "output_path": str(backward_out),
                            "last_message_path": str(backward_last),
                            "fail_count": fail_count + 1,
                        },
                    )
                    fail_count += 1
                    if fail_count >= 3:
                        self._print(
                            f"{RED}✗ Too many failures, waiting 15 minutes...{RESET}"
                        )
                        self._discord_post(
                            f"**◀ BACKWARD** #{loop_iteration} ⚠️ failed ({fail_count} consecutive), waiting 15 minutes before retry..."
                        )
                        self._sleep(900)
                        fail_count = 0
                    else:
                        self._sleep(2)

                backward_summary = self._phase_summary(
                    "backward", backward_out, backward_last
                )
                self._emit(
                    "phase.end",
                    phase="backward",
                    iteration=loop_iteration,
                    payload={
                        "ok": True,
                        "summary": backward_summary,
                        "output_path": str(backward_out),
                        "last_message_path": str(backward_last),
                    },
                )
                self._store_phase_summary(
                    session_id, "backward", loop_iteration, backward_summary
                )
                if backward_summary:
                    self._discord_post(
                        f"**◀ BACKWARD** #{loop_iteration} Summary:\n{backward_summary}"
                    )
                else:
                    self._discord_post(
                        f"**◀ BACKWARD** #{loop_iteration} ✅ completed at {utc_now_iso()[11:19]}"
                    )
            finally:
                self._cleanup_paths(backward_out, backward_last)

            # Post statuses
            self._post_jwz_status(f"loopfarm:status:{session_id}")

            # Completion check
            decision, summary = self._read_completion(session_id)
            if decision == "COMPLETE":
                return self._mark_complete(iteration=loop_iteration, summary=summary)

    def _render_phase_prompt(self, session_id: str, phase: str) -> str:
        ctx = TemplateContext(
            prompt=self.cfg.prompt, session=session_id, project=self.cfg.project
        )
        return render_prompt(self._prompt_path(phase), ctx)

    def _build_phase_prompt(
        self,
        session_id: str,
        phase: str,
        *,
        forward_report: dict[str, Any] | None = None,
    ) -> str:
        base = self._render_phase_prompt(session_id, phase)
        base = self._inject_writing_mode_guidance(base, phase)
        if phase == "forward":
            base = self._inject_phase_briefing(base, session_id)
        report_targets = set(self.cfg.loop_report_target_phases)
        if not report_targets and self.cfg.loop_steps is None:
            report_targets = {"backward"}
        if phase in report_targets:
            base = self._inject_forward_report(base, session_id, forward_report)
        prompt_suffix = self._backend_for_phase(phase).prompt_suffix(
            phase=phase, cfg=self.cfg
        )
        return assemble_prompt(
            base,
            session_context=self.discord_context_override,
            discord_context=self._flush_discord_context(),
            prompt_suffix=prompt_suffix,
        )

    def _inject_writing_mode_guidance(self, base: str, phase: str) -> str:
        if self.cfg.mode != "writing":
            return base

        lines = [
            "## Writing Mode",
            "",
            "This session is running with `--mode writing`.",
            "Read `prompts/writing.md` before starting and follow it.",
        ]
        if phase == "planning":
            lines.append(
                "In planning, file writing-focused issues and do not draft prose yet."
            )
        elif phase == "forward":
            lines.append(
                "In forward, edit documentation/prose files only and file issues for"
                " code changes instead of implementing them."
            )
        elif phase == "backward":
            lines.append(
                "In backward, audit docs for accuracy, clarity, and completeness."
            )
        elif phase == "documentation":
            lines.append(
                "In documentation, update prose/docs to match current behavior and do"
                " not change implementation code."
            )
        elif phase == "architecture":
            lines.append(
                "In architecture, evaluate modularity/performance and file issues;"
                " do not implement code changes directly."
            )

        section = "\n".join(lines)
        for anchor in ("## Workflow", "## Review Criteria", "## Required Phase Summary"):
            idx = base.find(anchor)
            if idx != -1:
                before = base[:idx].rstrip()
                after = base[idx:].lstrip()
                return f"{before}\n\n{section}\n\n{after}"
        return base.rstrip() + "\n\n" + section

    def _start_poller(
        self, session_id: str
    ) -> tuple[threading.Event, JwzPoller | None]:
        if not self.discord_thread_id:
            return threading.Event(), None

        stop_event = threading.Event()
        topics = [
            f"loopfarm:status:{session_id}",
            f"loopfarm:status:{session_id}",
        ]
        poller = JwzPoller(
            jwz=self.jwz,
            discord=self.discord,
            thread_id=self.discord_thread_id,
            topics=topics,
            stop_event=stop_event,
            seen_ids=self.seen_jwz_ids,
            debug=env_flag("LOOPFARM_DISCORD_DEBUG"),
        )
        poller.start()
        return stop_event, poller

    def _load_discord_cursor(self) -> None:
        if not self.discord_thread_id:
            return
        cursor = self.session_store.get_discord_cursor(self.discord_thread_id)
        if not cursor:
            return
        message_id = cursor.get("message_id")
        if message_id:
            self.discord_last_seen_id = str(message_id)

    def _load_discord_context_override(self, session_id: str) -> None:
        meta = self.session_store.get_session_meta(session_id) or {}
        ctx = meta.get("discord_context")
        if isinstance(ctx, str) and ctx.strip():
            self.discord_context_override = ctx

    def _stop_poller(
        self, stop_event: threading.Event, poller: JwzPoller | None
    ) -> None:
        stop_event.set()
        if poller:
            poller.join(timeout=2)

    def _phase_summary(
        self, phase: str, output_path: Path, last_message_path: Path
    ) -> str:
        backend = self._backend_for_phase(phase)
        return backend.extract_summary(
            phase=phase,
            output_path=output_path,
            last_message_path=last_message_path,
            cfg=self.cfg,
        )

    def _git_capture(self, argv: list[str]) -> str:
        try:
            return run_capture(argv, cwd=self.cfg.repo_root).strip()
        except CommandError:
            return ""

    def _git_lines(self, argv: list[str]) -> list[str]:
        out = self._git_capture(argv)
        if not out:
            return []
        return [line.rstrip() for line in out.splitlines() if line.strip()]

    def _git_head(self) -> str:
        return self._git_capture(["git", "rev-parse", "HEAD"])

    def _build_forward_report(
        self, *, session_id: str, pre_head: str, post_head: str, summary: str
    ) -> dict[str, Any]:
        max_lines = env_int("LOOPFARM_FORWARD_REPORT_MAX_LINES", 20)
        max_commits = env_int("LOOPFARM_FORWARD_REPORT_MAX_COMMITS", 12)
        max_summary_chars = env_int("LOOPFARM_FORWARD_REPORT_MAX_SUMMARY_CHARS", 800)

        head_changed = bool(pre_head and post_head and pre_head != post_head)
        commit_range = f"{pre_head}..{post_head}" if head_changed else ""

        commits = (
            self._git_lines(
                [
                    "git",
                    "--no-pager",
                    "log",
                    "--oneline",
                    f"--max-count={max_commits}",
                    commit_range,
                ]
            )
            if commit_range
            else []
        )
        diffstat = (
            self._git_lines(
                [
                    "git",
                    "--no-pager",
                    "diff",
                    "--stat",
                    "--submodule=short",
                    commit_range,
                ]
            )
            if commit_range
            else []
        )
        name_status = (
            self._git_lines(
                [
                    "git",
                    "--no-pager",
                    "diff",
                    "--name-status",
                    "--submodule=short",
                    commit_range,
                ]
            )
            if commit_range
            else []
        )

        status_lines = self._git_lines(["git", "status", "--porcelain=v1"])
        dirty = bool(status_lines)

        staged_diffstat = self._git_lines(
            ["git", "--no-pager", "diff", "--stat", "--cached", "--submodule=short"]
        )
        unstaged_diffstat = self._git_lines(
            ["git", "--no-pager", "diff", "--stat", "--submodule=short"]
        )
        staged_name_status = self._git_lines(
            [
                "git",
                "--no-pager",
                "diff",
                "--name-status",
                "--cached",
                "--submodule=short",
            ]
        )
        unstaged_name_status = self._git_lines(
            ["git", "--no-pager", "diff", "--name-status", "--submodule=short"]
        )

        return {
            "timestamp": utc_now_iso(),
            "session": session_id,
            "pre_head": pre_head,
            "post_head": post_head,
            "head_changed": head_changed,
            "commit_range": commit_range,
            "commits": _truncate_lines(commits, max_commits),
            "diffstat": _truncate_lines(diffstat, max_lines),
            "name_status": _truncate_lines(name_status, max_lines),
            "dirty": dirty,
            "status": _truncate_lines(status_lines, max_lines),
            "staged_diffstat": _truncate_lines(staged_diffstat, max_lines),
            "unstaged_diffstat": _truncate_lines(unstaged_diffstat, max_lines),
            "staged_name_status": _truncate_lines(staged_name_status, max_lines),
            "unstaged_name_status": _truncate_lines(unstaged_name_status, max_lines),
            "summary": _truncate_text(summary, max_summary_chars),
        }

    def _post_forward_report(self, session_id: str, payload: dict[str, Any]) -> None:
        self.jwz.post_json(f"loopfarm:forward:{session_id}", payload)

    def _read_forward_report(self, session_id: str) -> dict[str, Any] | None:
        msgs = self.jwz.read_json(f"loopfarm:forward:{session_id}", limit=1)
        if not msgs:
            msgs = self.jwz.read_json(f"loopfarm:forward:{session_id}", limit=1)
        if not msgs:
            return None
        body = msgs[0].get("body") or ""
        if not body:
            return None
        try:
            payload = json.loads(body)
        except Exception:
            return None
        if isinstance(payload, dict):
            return payload
        return None

    def _format_forward_report_for_prompt(self, payload: dict[str, Any] | None) -> str:
        if not payload:
            return ""

        def as_lines(key: str) -> list[str]:
            val = payload.get(key) or []
            if isinstance(val, list):
                return [str(x) for x in val if str(x).strip()]
            if isinstance(val, str):
                return [line for line in val.splitlines() if line.strip()]
            return []

        lines: list[str] = []
        summary = str(payload.get("summary") or "").strip()
        if summary:
            lines.append("Summary:")
            lines.append(summary)

        pre_head = str(payload.get("pre_head") or "").strip() or "unknown"
        post_head = str(payload.get("post_head") or "").strip() or "unknown"
        commit_range = str(payload.get("commit_range") or "").strip()

        lines.append(f"HEAD: {pre_head} -> {post_head}")
        if commit_range:
            lines.append(f"Commit range: {commit_range}")
        else:
            lines.append("Commit range: (none)")

        commits = as_lines("commits")
        if commits:
            lines.append("Commits:")
            lines.append("```")
            lines.extend(commits)
            lines.append("```")

        diffstat = as_lines("diffstat")
        if diffstat:
            lines.append("Diffstat (commits):")
            lines.append("```")
            lines.extend(diffstat)
            lines.append("```")

        name_status = as_lines("name_status")
        if name_status:
            lines.append("Name-status (commits):")
            lines.append("```")
            lines.extend(name_status)
            lines.append("```")

        dirty = bool(payload.get("dirty"))
        if dirty:
            lines.append("Working tree: dirty")
            status_lines = as_lines("status")
            if status_lines:
                lines.append("Status:")
                lines.append("```")
                lines.extend(status_lines)
                lines.append("```")

            staged_diffstat = as_lines("staged_diffstat")
            if staged_diffstat:
                lines.append("Diffstat (staged):")
                lines.append("```")
                lines.extend(staged_diffstat)
                lines.append("```")

            unstaged_diffstat = as_lines("unstaged_diffstat")
            if unstaged_diffstat:
                lines.append("Diffstat (unstaged):")
                lines.append("```")
                lines.extend(unstaged_diffstat)
                lines.append("```")

            staged_name_status = as_lines("staged_name_status")
            if staged_name_status:
                lines.append("Name-status (staged):")
                lines.append("```")
                lines.extend(staged_name_status)
                lines.append("```")

            unstaged_name_status = as_lines("unstaged_name_status")
            if unstaged_name_status:
                lines.append("Name-status (unstaged):")
                lines.append("```")
                lines.extend(unstaged_name_status)
                lines.append("```")
        else:
            lines.append("Working tree: clean")

        lines.append("Suggested commands:")
        lines.append("```bash")
        if commit_range:
            lines.append(f"git log --oneline {commit_range}")
            lines.append(f"git diff --stat {commit_range}")
            lines.append(f"git diff --name-status {commit_range}")
        lines.append("git status --porcelain=v1")
        if dirty:
            lines.append("git diff --stat")
            lines.append("git diff --stat --cached")
            lines.append("git diff --name-status")
            lines.append("git diff --name-status --cached")
        lines.append("```")

        return "\n".join(lines).strip()

    def _inject_forward_report(
        self,
        base: str,
        session_id: str,
        payload: dict[str, Any] | None,
    ) -> str:
        if payload is None:
            payload = self._read_forward_report(session_id)
        report = self._format_forward_report_for_prompt(payload)
        if not report:
            report = "_No forward report available._"
        placeholder = "{{FORWARD_REPORT}}"
        if placeholder in base:
            return base.replace(placeholder, report, 1)

        section = "---\n\n## Forward Pass Report\n\n" + report
        for anchor in ("## Workflow", "## Required Phase Summary"):
            idx = base.find(anchor)
            if idx != -1:
                before = base[:idx].rstrip()
                after = base[idx:].lstrip()
                return f"{before}\n\n{section}\n\n{after}"
        return base.rstrip() + "\n\n" + section

    def _store_phase_summary(
        self, session_id: str, phase: str, iteration: int, summary: str
    ) -> None:
        if not summary.strip():
            return
        self.session_store.store_phase_summary(session_id, phase, iteration, summary)

    def _build_phase_briefing(self, session_id: str) -> str:
        summaries = self.session_store.get_phase_summaries(session_id, limit=6)
        if not summaries:
            return ""

        lines = [
            "## Phase Briefing",
            "",
            "Recent activity in this session. Use this to maintain continuity with prior",
            "phases — especially backward review commentary and previous forward observations.",
        ]
        for s in summaries:
            phase = str(s.get("phase") or "unknown")
            iteration = s.get("iteration")
            text = str(s.get("summary") or "").strip()
            if not text:
                continue
            label = phase.capitalize()
            if iteration is not None and phase != "planning":
                label = f"{label} #{iteration}"
            lines.append("")
            lines.append(f"### {label}")
            lines.append(text)
        return "\n".join(lines)

    def _inject_phase_briefing(self, base: str, session_id: str) -> str:
        briefing = self._build_phase_briefing(session_id)
        if not briefing:
            return base
        placeholder = "{{PHASE_BRIEFING}}"
        if placeholder in base:
            return base.replace(placeholder, briefing, 1)
        for anchor in ("## Workflow", "## Guidelines"):
            idx = base.find(anchor)
            if idx != -1:
                before = base[:idx].rstrip()
                after = base[idx:].lstrip()
                return f"{before}\n\n{briefing}\n\n{after}"
        return base.rstrip() + "\n\n" + briefing

    def _run_agent(
        self,
        phase: str,
        prompt: str,
        output_path: Path,
        last_message_path: Path,
        *,
        iteration: int | None,
    ) -> bool:
        backend = self._backend_for_phase(phase)
        stream_sink = (
            self._stream_event_sink(phase=phase, iteration=iteration)
            if self.event_sink
            else None
        )
        return backend.run(
            phase=phase,
            prompt=prompt,
            output_path=output_path,
            last_message_path=last_message_path,
            cfg=self.cfg,
            event_sink=stream_sink,
            stdout=self.stdout,
            stderr=self.stderr,
        )

    def _read_completion(self, session_id: str) -> tuple[str, str]:
        msgs = self.jwz.read_json(f"loopfarm:status:{session_id}", limit=1)
        if not msgs:
            msgs = self.jwz.read_json(f"loopfarm:status:{session_id}", limit=1)
        if not msgs:
            return "", ""
        body = msgs[0].get("body") or ""
        if not body:
            return "", ""
        try:
            payload = json.loads(body)
        except Exception:
            return "", ""
        return str(payload.get("decision") or ""), str(payload.get("summary") or "")

    def _tmp_path(self, *, prefix: str = "loopfarm_", suffix: str = ".log") -> Path:
        fd, name = tempfile.mkstemp(prefix=prefix, suffix=suffix)
        os.close(fd)
        return Path(name)

    def _cleanup_paths(self, *paths: Path) -> None:
        for p in paths:
            try:
                p.unlink()
            except OSError:
                pass

    def _sleep(self, seconds: int) -> None:
        try:
            threading.Event().wait(seconds)
        except KeyboardInterrupt:
            raise


def run_loop(
    cfg: LoopfarmConfig,
    *,
    session_id: str | None = None,
    event_sink: EventSink | None = None,
    io: LoopfarmIO | None = None,
    backend_provider: BackendProvider | None = None,
) -> int:
    runner = LoopfarmRunner(
        cfg,
        event_sink=event_sink,
        io=io,
        backend_provider=backend_provider,
    )
    if session_id is None:
        session_id = new_session_id()
    return runner.run(session_id=session_id)

