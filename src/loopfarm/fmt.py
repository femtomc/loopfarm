"""Compact streaming formatters for Claude, Codex, OpenCode, pi, and Gemini output.

Design: show only tool calls (one line each) and the final summary message.
"""

from __future__ import annotations

import json
import re

from rich.console import Console
from rich.text import Text

_SHELL_WRAP_RE = re.compile(r"^/\S+\s+-lc\s+(.+)$", re.DOTALL)
_CD_PREFIX_RE = re.compile(r"^cd\s+\S+\s*&&\s*")

# Canonical tool name mapping per backend.
_TOOL_ALIASES: dict[str, str] = {
    # Claude (PascalCase → lowercase)
    "Read": "read",
    "Write": "write",
    "Edit": "edit",
    "Bash": "bash",
    "Glob": "glob",
    "Grep": "grep",
    "Task": "task",
    # Gemini
    "read_file": "read",
    "write_file": "write",
    "replace": "edit",
    "run_shell_command": "bash",
    "search_file_content": "grep",
    # Pi
    "find": "glob",
}

# Category → (tools, ok_style)
_TOOL_STYLES: dict[str, tuple[set[str], str]] = {
    "mutate": ({"edit", "write"}, "magenta"),
    "observe": ({"read", "glob", "grep"}, "blue"),
    "execute": ({"bash"}, "dim"),
    "delegate": ({"task"}, "cyan"),
}


def _normalize_tool(raw_name: str) -> str:
    """Map backend-specific tool name to a canonical lowercase name."""
    return _TOOL_ALIASES.get(raw_name, raw_name)


def _tool_style(canonical_name: str, *, ok: bool) -> str:
    """Return Rich style string for a tool category."""
    if not ok:
        return "red"
    for _cat, (tools, style) in _TOOL_STYLES.items():
        if canonical_name in tools:
            return style
    return "dim"


def _strip_shell(cmd: str) -> str:
    """Extract the inner command from /bin/zsh -lc '...' wrappers."""
    m = _SHELL_WRAP_RE.match(cmd)
    if m:
        inner = m.group(1).strip()
        if (inner.startswith("'") and inner.endswith("'")) or (
            inner.startswith('"') and inner.endswith('"')
        ):
            inner = inner[1:-1]
        cmd = inner
    return _CD_PREFIX_RE.sub("", cmd)


def _truncate(s: str, n: int = 100) -> str:
    return s[: n - 3] + "..." if len(s) > n else s


def _is_interactive(console: Console) -> bool:
    return bool(console.is_terminal and not console.is_dumb_terminal)


def _message_text(item: dict) -> str:
    text = item.get("text")
    if isinstance(text, str) and text:
        return text

    content = item.get("content")
    if isinstance(content, str):
        return content

    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, str):
                if part:
                    parts.append(part)
                continue
            if not isinstance(part, dict):
                continue
            ptext = part.get("text")
            if isinstance(ptext, str) and ptext:
                parts.append(ptext)
                continue
            pcontent = part.get("content")
            if isinstance(pcontent, str) and pcontent:
                parts.append(pcontent)
        return "\n".join(parts)

    return ""


class _BaseFormatter:
    def __init__(self, backend_name: str, console: Console | None = None) -> None:
        self.backend_name = backend_name
        self.console = console or Console()
        self.interactive = _is_interactive(self.console)
        self._summary_parts: list[str] = []
        self._pending_tool: tuple[str, str] | None = None  # (name, detail)

    @staticmethod
    def _extract_detail(canonical_name: str, params: dict) -> str:
        """Extract a human-readable detail string from tool parameters."""
        if not isinstance(params, dict):
            return ""
        if canonical_name in ("read", "glob", "grep"):
            for key in ("file_path", "filePath", "path", "pattern", "query"):
                v = params.get(key)
                if isinstance(v, str) and v:
                    return v
        elif canonical_name in ("edit", "write"):
            for key in ("file_path", "filePath", "path"):
                v = params.get(key)
                if isinstance(v, str) and v:
                    return v
        elif canonical_name == "bash":
            for key in ("command", "cmd"):
                v = params.get(key)
                if isinstance(v, str) and v:
                    return _truncate(_strip_shell(v), 80)
        elif canonical_name == "task":
            v = params.get("description")
            if isinstance(v, str) and v:
                return v
        else:
            for v in params.values():
                if isinstance(v, str) and v:
                    return _truncate(v, 60)
        return ""

    def _tool(self, name: str, detail: str = "", *, ok: bool = True) -> None:
        """Print a single-line tool invocation with success/failure indicator."""
        prefix = "\u2713" if ok else "\u2717"
        line = f"  {prefix} {name}"
        if detail:
            line += f" {detail}"
        style = _tool_style(name, ok=ok)
        if self.interactive:
            self.console.print(Text(line, style=style))
        else:
            self.console.print(line, markup=False)

    def _buffer_tool(self, name: str, detail: str = "") -> None:
        """Buffer a tool call; printed when result arrives."""
        self._flush_pending()
        self._pending_tool = (name, detail)

    def _resolve_tool(self, *, ok: bool = True) -> None:
        """Print the buffered tool call with its outcome."""
        if self._pending_tool is None:
            return
        name, detail = self._pending_tool
        self._pending_tool = None
        self._tool(name, detail, ok=ok)

    def _flush_pending(self) -> None:
        """Flush any buffered tool as success (safety net)."""
        if self._pending_tool is not None:
            name, detail = self._pending_tool
            self._pending_tool = None
            self._tool(name, detail, ok=True)

    def _error(self, msg: str) -> None:
        if self.interactive:
            self.console.print(Text(f"  error: {msg}", style="red"))
        else:
            self.console.print(f"  error: {msg}", markup=False)

    def _info(self, msg: str) -> None:
        if self.interactive:
            self.console.print(Text(f"  {msg}", style="dim"))
        else:
            self.console.print(f"  {msg}", markup=False)

    def _accumulate(self, text: str) -> None:
        """Buffer assistant text for final summary."""
        if text:
            self._summary_parts.append(text)

    def _print_summary(self) -> None:
        """Print the final accumulated assistant message."""
        text = "".join(self._summary_parts).strip()
        if not text:
            return
        self.console.print()
        if self.interactive:
            self.console.print(Text(text))
        else:
            self.console.print(text, markup=False)


class ClaudeFormatter(_BaseFormatter):
    """Parses Claude stream-json events (including partial streaming)."""

    def __init__(self, console: Console | None = None) -> None:
        super().__init__("claude", console)
        self._thinking = False

    def _handle_stream_event(self, event: dict) -> None:
        """Handle stream_event (from --include-partial-messages)."""
        inner = event.get("event", {})
        if not isinstance(inner, dict):
            return
        inner_type = inner.get("type", "")

        if inner_type == "content_block_start":
            block = inner.get("content_block", {})
            if isinstance(block, dict) and block.get("type") == "thinking":
                if not self._thinking:
                    self._thinking = True
                    self._info("thinking...")
        elif inner_type == "content_block_stop":
            self._thinking = False

    def process_line(self, line: str) -> None:
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        etype = event.get("type", "")

        if etype == "stream_event":
            self._handle_stream_event(event)

        elif etype == "assistant":
            self._thinking = False
            self._accumulate(event.get("message", ""))

        elif etype == "result":
            cost = event.get("cost_usd")
            duration = event.get("duration_ms")
            parts = []
            if cost is not None:
                parts.append(f"${cost:.4f}")
            if duration is not None:
                parts.append(f"{duration / 1000:.1f}s")
            if parts:
                self._info(" ".join(parts))

        elif etype == "tool_use":
            self._thinking = False
            raw = event.get("tool", event.get("name", "?"))
            canonical = _normalize_tool(raw)
            inp = event.get("input", {})
            detail = self._extract_detail(canonical, inp)
            self._buffer_tool(canonical, detail)

        elif etype == "tool_result":
            is_error = event.get("is_error", False)
            self._resolve_tool(ok=not is_error)

        elif etype == "error":
            self._error(event.get("error", str(event)))

    def finish(self) -> None:
        self._flush_pending()
        self._print_summary()


class CodexFormatter(_BaseFormatter):
    """Parses Codex JSONL events."""

    def __init__(self, console: Console | None = None) -> None:
        super().__init__("codex", console)

    def process_line(self, line: str) -> None:
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        etype = event.get("type", "")
        item = event.get("item", {})
        item_type = item.get("type", "")

        if etype == "item.started" and item_type == "command_execution":
            cmd = _strip_shell(item.get("command", ""))
            self._buffer_tool("bash", _truncate(cmd, 120))

        elif etype == "item.completed":
            if item_type == "command_execution":
                exit_code = item.get("exit_code")
                self._resolve_tool(ok=(exit_code == 0))
            elif item_type in ("message", "agent_message"):
                content = _message_text(item)
                if content:
                    self._accumulate(content)

        elif etype == "error":
            self._error(event.get("error", str(event)))

    def finish(self) -> None:
        self._flush_pending()
        self._print_summary()


class OpenCodeFormatter(_BaseFormatter):
    """Parses OpenCode run --format json events."""

    def __init__(self, console: Console | None = None) -> None:
        super().__init__("opencode", console)

    def process_line(self, line: str) -> None:
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        etype = event.get("type", "")

        if etype == "tool_use":
            part = event.get("part", {})
            raw = part.get("tool", "?")
            canonical = _normalize_tool(raw)
            state = part.get("state", {})
            tool_input = state.get("input", {}) if isinstance(state, dict) else {}
            if not isinstance(tool_input, dict):
                tool_input = {}
            detail = self._extract_detail(canonical, tool_input)
            status = state.get("status", "") if isinstance(state, dict) else ""
            self._tool(canonical, detail, ok=(status != "error"))

        elif etype == "text":
            part = event.get("part", {})
            text = part.get("text", "")
            if isinstance(text, str) and text.strip():
                self._accumulate(text)

        elif etype == "error":
            err = event.get("error", line)
            if isinstance(err, dict):
                data = err.get("data", {})
                if isinstance(data, dict) and isinstance(data.get("message"), str):
                    msg = data["message"]
                elif isinstance(err.get("message"), str):
                    msg = err["message"]
                elif isinstance(err.get("name"), str):
                    msg = err["name"]
                else:
                    msg = json.dumps(err)
            else:
                msg = str(err)
            self._error(msg)

    def finish(self) -> None:
        self._print_summary()


class GeminiFormatter(_BaseFormatter):
    """Parses Gemini --output-format stream-json events."""

    def __init__(self, console: Console | None = None) -> None:
        super().__init__("gemini", console)

    def process_line(self, line: str) -> None:
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        etype = event.get("type", "")

        if etype == "tool_use":
            raw = event.get("tool_name", "?")
            if not isinstance(raw, str):
                raw = "?"
            canonical = _normalize_tool(raw)
            detail = self._extract_detail(canonical, event.get("parameters", {}))
            self._buffer_tool(canonical, detail)

        elif etype == "tool_result":
            status = event.get("status")
            status_text = status.lower() if isinstance(status, str) else ""
            self._resolve_tool(ok=(status_text in ("success", "ok", "")))

        elif etype == "message":
            if event.get("role") == "assistant":
                content = event.get("content")
                if isinstance(content, str) and content:
                    self._accumulate(content)

        elif etype == "result":
            status = event.get("status")
            if not isinstance(status, str):
                status = "unknown"
            parts = [status]
            duration = event.get("duration_ms")
            if isinstance(duration, (int, float)):
                parts.append(f"{duration / 1000:.1f}s")
            usage = event.get("usage")
            if isinstance(usage, dict):
                total_tokens = usage.get("totalTokens")
                if isinstance(total_tokens, int):
                    parts.append(f"tokens={total_tokens}")
            self._info(" ".join(parts))

        elif etype == "error":
            err = event.get("error")
            if isinstance(err, dict):
                msg = str(err.get("message") or err.get("details") or err)
            elif isinstance(err, str) and err:
                msg = err
            else:
                msg = str(event.get("message") or line)
            self._error(msg)

    def finish(self) -> None:
        self._flush_pending()
        self._print_summary()


class PiFormatter(_BaseFormatter):
    """Parses pi --mode json events."""

    def __init__(self, console: Console | None = None) -> None:
        super().__init__("pi", console)

    def process_line(self, line: str) -> None:
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        etype = event.get("type", "")

        if etype == "tool_execution_start":
            raw = event.get("toolName", "?")
            if not isinstance(raw, str):
                raw = "?"
            canonical = _normalize_tool(raw)
            detail = self._extract_detail(canonical, event.get("args", {}))
            self._buffer_tool(canonical, detail)

        elif etype == "tool_execution_end":
            is_error = bool(event.get("isError"))
            self._resolve_tool(ok=not is_error)

        elif etype == "message_update":
            assistant_event = event.get("assistantMessageEvent", {})
            if not isinstance(assistant_event, dict):
                return
            if assistant_event.get("type") == "text_delta":
                delta = assistant_event.get("delta", "")
                if isinstance(delta, str) and delta:
                    self._accumulate(delta)
            elif assistant_event.get("type") == "error":
                error_value = assistant_event.get("error", {})
                message = "assistant error"
                if isinstance(error_value, dict):
                    for key in ("errorMessage", "message"):
                        value = error_value.get(key)
                        if isinstance(value, str) and value:
                            message = value
                            break
                self._error(message)

        elif etype == "message_end":
            message = event.get("message", {})
            if isinstance(message, dict) and message.get("role") == "assistant":
                stop_reason = message.get("stopReason")
                if stop_reason in ("error", "aborted"):
                    error_message = message.get("errorMessage")
                    if not isinstance(error_message, str) or not error_message:
                        error_message = f"assistant {stop_reason}"
                    self._error(error_message)

        elif etype == "error":
            self._error(event.get("error", str(event)))

    def finish(self) -> None:
        self._flush_pending()
        self._print_summary()


def get_formatter(backend_name: str, console: Console | None = None):
    if backend_name == "claude":
        return ClaudeFormatter(console)
    if backend_name == "opencode":
        return OpenCodeFormatter(console)
    if backend_name == "gemini":
        return GeminiFormatter(console)
    if backend_name == "pi":
        return PiFormatter(console)
    return CodexFormatter(console)
