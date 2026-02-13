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

    def _tool(self, name: str, detail: str = "") -> None:
        """Print a single-line tool invocation."""
        line = f"  {name}"
        if detail:
            line += f" {detail}"
        if self.interactive:
            self.console.print(Text(line, style="dim"))
        else:
            self.console.print(line, markup=False)

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
    """Parses Claude stream-json events."""

    def __init__(self, console: Console | None = None) -> None:
        super().__init__("claude", console)

    def process_line(self, line: str) -> None:
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        etype = event.get("type", "")

        if etype == "assistant":
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
            name = event.get("tool", event.get("name", "?"))
            inp = event.get("input", {})
            detail = ""
            if name in ("Read", "Glob", "Grep"):
                detail = inp.get("file_path") or inp.get("pattern") or inp.get("path", "")
            elif name in ("Edit", "Write"):
                detail = inp.get("file_path", "")
            elif name == "Bash":
                detail = _truncate(_strip_shell(inp.get("command", "")), 80)
            elif name == "Task":
                detail = inp.get("description", "")
            else:
                for v in inp.values():
                    if isinstance(v, str) and v:
                        detail = _truncate(v, 60)
                        break
            self._tool(name, detail)

        elif etype == "error":
            self._error(event.get("error", str(event)))

    def finish(self) -> None:
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
            self._tool("bash", _truncate(cmd, 120))

        elif etype == "item.completed":
            if item_type in ("message", "agent_message"):
                content = _message_text(item)
                if content:
                    self._accumulate(content)

        elif etype == "error":
            self._error(event.get("error", str(event)))

    def finish(self) -> None:
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
            tool = part.get("tool", "?")
            state = part.get("state", {})
            tool_input = state.get("input", {}) if isinstance(state, dict) else {}
            if not isinstance(tool_input, dict):
                tool_input = {}

            detail = ""
            if tool in ("read", "write", "edit"):
                detail = tool_input.get("filePath", "")
            elif tool in ("glob", "grep"):
                detail = tool_input.get("pattern", "")
            elif tool == "bash":
                detail = _truncate(_strip_shell(tool_input.get("command", "")), 80)
            elif tool == "task":
                detail = tool_input.get("description", "")
            elif isinstance(tool_input, dict):
                for value in tool_input.values():
                    if isinstance(value, str) and value:
                        detail = _truncate(value, 60)
                        break
            self._tool(tool, detail)

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

    def _tool_detail(self, tool_name: str, params: object) -> str:
        if not isinstance(params, dict):
            return ""

        if tool_name in ("read_file", "write_file", "replace"):
            for key in ("path", "file_path"):
                value = params.get(key)
                if isinstance(value, str) and value:
                    return value

        if tool_name in ("glob", "grep", "search_file_content"):
            for key in ("pattern", "path", "query"):
                value = params.get(key)
                if isinstance(value, str) and value:
                    return value

        if tool_name in ("run_shell_command", "bash"):
            for key in ("command", "cmd"):
                command = params.get(key)
                if isinstance(command, str) and command:
                    return _truncate(_strip_shell(command), 80)

        for value in params.values():
            if isinstance(value, str) and value:
                return _truncate(value, 60)
        return ""

    def process_line(self, line: str) -> None:
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        etype = event.get("type", "")

        if etype == "tool_use":
            tool_name = event.get("tool_name", "?")
            if not isinstance(tool_name, str):
                tool_name = "?"
            detail = self._tool_detail(tool_name, event.get("parameters", {}))
            self._tool(tool_name, detail)

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
        self._print_summary()


class PiFormatter(_BaseFormatter):
    """Parses pi --mode json events."""

    def __init__(self, console: Console | None = None) -> None:
        super().__init__("pi", console)

    def _tool_detail(self, tool_name: str, args: object) -> str:
        if not isinstance(args, dict):
            return ""

        if tool_name in ("read", "write", "edit"):
            for key in ("path", "filePath", "targetPath"):
                value = args.get(key)
                if isinstance(value, str) and value:
                    return value

        if tool_name in ("grep", "find"):
            for key in ("pattern", "path"):
                value = args.get(key)
                if isinstance(value, str) and value:
                    return value

        if tool_name == "bash":
            command = args.get("command")
            if isinstance(command, str) and command:
                return _truncate(_strip_shell(command), 80)

        for value in args.values():
            if isinstance(value, str) and value:
                return _truncate(value, 60)
        return ""

    def process_line(self, line: str) -> None:
        if not line.strip():
            return
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return

        etype = event.get("type", "")

        if etype == "tool_execution_start":
            tool_name = event.get("toolName", "?")
            if not isinstance(tool_name, str):
                tool_name = "?"
            detail = self._tool_detail(tool_name, event.get("args", {}))
            self._tool(tool_name, detail)

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
