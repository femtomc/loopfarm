"""Compact streaming formatters for Claude, Codex, OpenCode, pi, and Gemini output.

Design: show only tool calls (one line each) and the final summary message.
"""

from __future__ import annotations

import json
import re

from rich.console import Console
from rich.markdown import Markdown
from rich.text import Text

_SHELL_WRAP_RE = re.compile(r"^/\S+\s+-lc\s+(.+)$", re.DOTALL)
_CD_PREFIX_RE = re.compile(r"^cd\s+\S+\s*&&\s*")

# Canonical tool name mapping per backend.
_TOOL_ALIASES: dict[str, str] = {
    # Claude / generic
    "read": "read",
    "write": "write",
    "edit": "edit",
    "bash": "bash",
    "glob": "glob",
    "grep": "grep",
    "task": "task",
    # Gemini
    "read_file": "read",
    "write_file": "write",
    "replace": "edit",
    "run_shell_command": "bash",
    "search_file_content": "grep",
    # Pi
    "find": "glob",
    # Local function tools
    "exec_command": "bash",
    "write_stdin": "bash",
    "parallel": "task",
    "apply_patch": "edit",
    "image_query": "search",
    "search_query": "search",
    "open": "read",
    "click": "read",
    "screenshot": "read",
}

# Category → (tools, ok_style)
_TOOL_STYLES: dict[str, tuple[set[str], str]] = {
    "mutate": ({"edit", "write"}, "magenta"),
    "observe": ({"read", "glob", "grep", "search"}, "blue"),
    "execute": ({"bash"}, "yellow"),
    "delegate": ({"task"}, "cyan"),
}


def _normalize_tool(raw_name: str) -> str:
    """Map backend-specific tool name to a canonical lowercase name."""
    if not raw_name:
        return "tool"
    name = raw_name.strip()
    if "." in name:
        name = name.rsplit(".", 1)[-1]
    if name.startswith("mcp__"):
        return "task"
    name = name.lower()
    return _TOOL_ALIASES.get(name, name)


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


def _parse_json_object(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def _summarize_shell(cmd: str, max_len: int = 80) -> str:
    raw = _strip_shell(cmd).strip()
    raw = raw.replace("\\n", "\n")
    if not raw:
        return ""
    lines = [ln.strip() for ln in raw.splitlines() if ln.strip()]
    if lines and lines[0].startswith("set -euo pipefail"):
        lines = lines[1:]
    if not lines:
        lines = [raw.replace("\n", " ").strip()]
    head = lines[0]
    if len(lines) > 1:
        head = f"{head} (+{len(lines) - 1} more lines)"
    return _truncate(head, max_len)


def _truncate(s: str, n: int = 100) -> str:
    return s[: n - 3] + "..." if len(s) > n else s


def _is_interactive(console: Console) -> bool:
    return bool(console.is_terminal and not console.is_dumb_terminal)


def _message_text(item: dict) -> str:
    text = item.get("text")
    if isinstance(text, str) and text:
        return text

    output_text = item.get("output_text")
    if isinstance(output_text, str) and output_text:
        return output_text

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
                continue
            pout = part.get("output_text")
            if isinstance(pout, str) and pout:
                parts.append(pout)
        return "\n".join(parts)

    message = item.get("message")
    if isinstance(message, dict):
        return _message_text(message)

    return ""


class _BaseFormatter:
    def __init__(self, backend_name: str, console: Console | None = None) -> None:
        self.backend_name = backend_name
        self.console = console or Console()
        self.interactive = _is_interactive(self.console)
        self._summary_parts: list[str] = []
        self._pending_tool: tuple[str, str] | None = None  # (name, detail)
        self._stats: dict[str, str] = {}
        self._live_delta_open = False
        self._saw_live_text = False

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
                    return _summarize_shell(v, 80)
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
        self._close_live_delta()
        prefix = "\u2713" if ok else "\u2717"
        line = f"  {prefix} {name}"
        if detail:
            line += f" {detail}"
        if self.interactive:
            tool_style = _tool_style(name, ok=ok)
            text = Text("  ")
            text.append(prefix, style="green" if ok else "red")
            text.append(" ")
            text.append(name, style=f"{tool_style} bold")
            if detail:
                text.append(" ")
                text.append(detail, style="dim" if ok else "red")
            self.console.print(text)
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
        self._close_live_delta()
        if self.interactive:
            self.console.print(Text(f"  error: {msg}", style="red"))
        else:
            self.console.print(f"  error: {msg}", markup=False)

    def _info(self, msg: str) -> None:
        self._close_live_delta()
        if self.interactive:
            self.console.print(Text(f"  {msg}", style="dim"))
        else:
            self.console.print(f"  {msg}", markup=False)

    def _set_stat(self, key: str, value: object) -> None:
        if value is None:
            return
        if isinstance(value, float):
            if key in ("duration", "cost"):
                text = f"{value:.1f}" if key == "duration" else f"{value:.4f}"
            else:
                text = str(value)
        else:
            text = str(value)
        if text:
            self._stats[key] = text

    def _print_stats(self) -> None:
        if not self._stats:
            return
        ordered = []
        for key in ("status", "duration", "cost", "tokens"):
            if key in self._stats:
                value = self._stats[key]
                if key == "duration":
                    ordered.append(f"duration={value}s")
                elif key == "cost":
                    ordered.append(f"cost=${value}")
                else:
                    ordered.append(f"{key}={value}")
        extras = [f"{k}={v}" for k, v in self._stats.items() if k not in {"status", "duration", "cost", "tokens"}]
        ordered.extend(extras)
        self._info("stats " + " ".join(ordered))

    def _print_live_text(self, text: str, *, delta: bool) -> None:
        if not self.interactive or not text:
            return
        self._saw_live_text = True

        if delta:
            if not self._live_delta_open:
                self.console.print()
                self.console.print(Text("  agent ", style="bold green"), end="")
                self._live_delta_open = True
            self.console.print(text, end="", markup=False, highlight=False)
            return

        self._close_live_delta()
        self.console.print()
        self.console.print(Text("agent", style="bold green"))
        self.console.print(Markdown(text.strip()))

    def _close_live_delta(self) -> None:
        if self.interactive and self._live_delta_open:
            self.console.print()
            self._live_delta_open = False

    def _accumulate(self, text: str, *, delta: bool = False) -> None:
        """Buffer assistant text for final summary."""
        if text:
            self._summary_parts.append(text)
            self._print_live_text(text, delta=delta)

    def _print_summary(self) -> None:
        """Print the final accumulated assistant message."""
        self._close_live_delta()
        if self.interactive and self._saw_live_text:
            return
        text = "".join(self._summary_parts).strip()
        if not text:
            return
        self.console.print()
        if self.interactive:
            self.console.print(Text("agent", style="bold green"))
            self.console.print(Markdown(text))
        else:
            self.console.print(text, markup=False)

    def _print_prompt(self, text: str) -> None:
        self._close_live_delta()
        if not text:
            return
        if self.interactive:
            self.console.print()
            self.console.print(Text("prompt", style="bold cyan"))
            self.console.print(Markdown(text))
        else:
            self.console.print(f"prompt: {text}", markup=False)


class ClaudeFormatter(_BaseFormatter):
    """Parses Claude stream-json events (including partial streaming)."""

    def __init__(self, console: Console | None = None) -> None:
        super().__init__("claude", console)
        self._thinking = False
        # Track active content block from stream_event for tool_use detection
        self._active_block_type: str | None = None
        self._active_tool_name: str | None = None
        self._active_tool_json_parts: list[str] = []
        # Track tool names already emitted via stream events to avoid duplicates
        self._stream_tool_ids: set[str] = set()

    def _handle_stream_event(self, event: dict) -> None:
        """Handle stream_event (from --include-partial-messages)."""
        inner = event.get("event", {})
        if not isinstance(inner, dict):
            return
        inner_type = inner.get("type", "")

        if inner_type == "content_block_start":
            block = inner.get("content_block", {})
            if not isinstance(block, dict):
                return
            btype = block.get("type", "")
            self._active_block_type = btype
            if btype == "thinking":
                if not self._thinking:
                    self._thinking = True
                    self._info("thinking...")
            elif btype == "tool_use":
                tool_id = block.get("id", "")
                self._active_tool_name = block.get("name", "?")
                self._active_tool_json_parts = []
                if tool_id:
                    self._stream_tool_ids.add(tool_id)

        elif inner_type == "content_block_delta":
            delta = inner.get("delta", {})
            if isinstance(delta, dict):
                if delta.get("type") == "input_json_delta":
                    part = delta.get("partial_json", "")
                    if isinstance(part, str) and part:
                        self._active_tool_json_parts.append(part)
                elif delta.get("type") == "text_delta":
                    part = delta.get("text", "")
                    if isinstance(part, str) and part:
                        self._accumulate(part, delta=True)

        elif inner_type == "content_block_stop":
            if self._active_block_type == "tool_use" and self._active_tool_name:
                canonical = _normalize_tool(self._active_tool_name)
                inp: dict = {}
                raw_json = "".join(self._active_tool_json_parts)
                if raw_json:
                    try:
                        inp = json.loads(raw_json)
                    except json.JSONDecodeError:
                        pass
                detail = self._extract_detail(canonical, inp)
                self._buffer_tool(canonical, detail)
            elif self._active_block_type == "text":
                self._close_live_delta()
            self._thinking = False
            self._active_block_type = None
            self._active_tool_name = None
            self._active_tool_json_parts = []

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
            # Replace (not append) to avoid duplicates from partial assistant events
            msg = _message_text({"message": event.get("message")})
            if isinstance(msg, str) and msg.strip():
                self._summary_parts = [msg]

        elif etype == "result":
            cost = event.get("cost_usd", event.get("total_cost_usd"))
            duration = event.get("duration_ms")
            if isinstance(duration, (int, float)):
                self._set_stat("duration", duration / 1000.0)
            if isinstance(cost, (int, float)):
                self._set_stat("cost", float(cost))

        elif etype == "tool_use":
            self._thinking = False
            # Skip if already emitted from stream_event
            tool_id = event.get("tool_use_id", "")
            if tool_id and tool_id in self._stream_tool_ids:
                return
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
        self._print_stats()
        self._print_summary()


class CodexFormatter(_BaseFormatter):
    """Parses Codex JSONL events."""

    def __init__(self, console: Console | None = None) -> None:
        super().__init__("codex", console)
        self._pending_by_id: dict[str, tuple[str, str]] = {}

    @staticmethod
    def _is_tool_item_type(item_type: str) -> bool:
        return item_type in {
            "command_execution",
            "tool_call",
            "function_call",
            "web_search_call",
            "file_search_call",
            "computer_call",
            "mcp_call",
        }

    def _codex_tool(self, item: dict) -> tuple[str, str] | None:
        item_type = item.get("type", "")
        if not isinstance(item_type, str):
            return None

        if item_type == "command_execution":
            cmd = item.get("command", "")
            if not isinstance(cmd, str):
                cmd = ""
            return "bash", _summarize_shell(cmd, 120)

        if not self._is_tool_item_type(item_type):
            return None

        raw_name = ""
        for key in ("tool_name", "tool", "name"):
            value = item.get(key)
            if isinstance(value, str) and value:
                raw_name = value
                break
        if not raw_name:
            raw_name = item_type.removesuffix("_call")
        canonical = _normalize_tool(raw_name)

        params: dict = {}
        for key in ("input", "parameters", "args", "arguments"):
            parsed = _parse_json_object(item.get(key))
            if parsed:
                params = parsed
                break

        detail = self._extract_detail(canonical, params)
        if not detail:
            for key in ("query", "prompt", "path"):
                value = item.get(key)
                if isinstance(value, str) and value:
                    detail = _truncate(value, 100)
                    break

        return canonical, detail

    def _buffer_tool_item(self, item: dict) -> None:
        tool = self._codex_tool(item)
        if tool is None:
            return
        item_id = item.get("id")
        if isinstance(item_id, str) and item_id:
            self._pending_by_id[item_id] = tool
            return
        name, detail = tool
        self._buffer_tool(name, detail)

    def _resolve_tool_item(self, item: dict) -> None:
        ok = True
        exit_code = item.get("exit_code")
        if isinstance(exit_code, int):
            ok = exit_code == 0
        status = item.get("status")
        if isinstance(status, str):
            status_text = status.lower()
            if status_text in {"error", "failed", "aborted"}:
                ok = False
            elif status_text in {"success", "completed", "ok"} and exit_code is None:
                ok = True

        item_id = item.get("id")
        if isinstance(item_id, str) and item_id and item_id in self._pending_by_id:
            name, detail = self._pending_by_id.pop(item_id)
            self._tool(name, detail, ok=ok)
            return

        self._resolve_tool(ok=ok)

    def process_line(self, line: str) -> None:
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        etype = event.get("type", "")
        raw_item = event.get("item", {})
        item = raw_item if isinstance(raw_item, dict) else {}
        item_type = item.get("type", "")

        if etype == "item.started" and isinstance(item, dict):
            if self._is_tool_item_type(item_type):
                self._buffer_tool_item(item)

        elif etype == "item.completed":
            if not isinstance(item, dict):
                return
            if self._is_tool_item_type(item_type):
                self._resolve_tool_item(item)
            elif item_type in ("message", "agent_message", "assistant_message"):
                content = _message_text(item)
                if content:
                    role = item.get("role")
                    if role == "user":
                        self._print_prompt(content)
                    else:
                        self._accumulate(content)
            elif item_type == "file_change":
                changes = item.get("changes", [])
                if isinstance(changes, list):
                    for change in changes:
                        if not isinstance(change, dict):
                            continue
                        path = change.get("path", "")
                        kind = change.get("kind", "update")
                        canonical = "write" if kind == "create" else "edit"
                        self._tool(canonical, path, ok=True)
            elif item_type == "usage":
                usage = item.get("usage")
                if isinstance(usage, dict):
                    total = usage.get("total_tokens")
                    if isinstance(total, int):
                        self._set_stat("tokens", total)

        elif etype == "response.completed":
            usage = event.get("usage")
            if isinstance(usage, dict):
                total = usage.get("total_tokens")
                if isinstance(total, int):
                    self._set_stat("tokens", total)
            status = event.get("status")
            if isinstance(status, str) and status:
                self._set_stat("status", status)

        elif etype == "error":
            self._error(event.get("error", str(event)))

    def finish(self) -> None:
        for name, detail in self._pending_by_id.values():
            self._tool(name, detail, ok=True)
        self._pending_by_id.clear()
        self._flush_pending()
        self._print_stats()
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
        self._print_stats()
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
            self._set_stat("status", status)
            duration = event.get("duration_ms")
            if isinstance(duration, (int, float)):
                self._set_stat("duration", duration / 1000.0)
            usage = event.get("usage")
            if isinstance(usage, dict):
                total_tokens = usage.get("totalTokens")
                if isinstance(total_tokens, int):
                    self._set_stat("tokens", total_tokens)

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
        self._print_stats()
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
                    self._accumulate(delta, delta=True)
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
            self._close_live_delta()
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
        self._print_stats()
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
