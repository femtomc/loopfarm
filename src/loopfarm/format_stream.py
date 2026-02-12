#!/usr/bin/env python3
"""Format Claude stream-json, Codex JSONL, and Kimi JSON output for loopfarm."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .runtime.events import StreamEventSink
from .util import env_flag, env_int


def _shorten_path(path: str, repo_root: Path | None) -> str:
    try:
        p = Path(path)
        if repo_root:
            try:
                rel = p.resolve().relative_to(repo_root.resolve())
                return str(rel)
            except Exception:
                pass
        return str(p)
    except Exception:
        return path


_ZSH_LC_RE = re.compile(r'^(?:.*/)?zsh\s+-lc\s+"(?P<body>.*)"$')
_BASH_LC_RE = re.compile(r'^(?:.*/)?bash\s+-lc\s+"(?P<body>.*)"$')

_TOOL_SUMMARY_MAX = 200
_TOOL_VALUE_MAX = 80
_TOOL_ITEMS_MAX = 6
_BULKY_TOOL_KEYS = {
    "body",
    "content",
    "data",
    "diff",
    "input",
    "message",
    "messages",
    "patch",
    "payload",
    "prompt",
    "text",
}


def _truncate_text(text: str, max_len: int) -> str:
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len == 1:
        return "…"
    return text[: max_len - 1] + "…"


def _inline_text(text: str, max_len: int) -> str:
    cleaned = text.replace("\r", "").replace("\n", "\\n").strip()
    return _truncate_text(cleaned, max_len)


def _shorten_shell_command(cmd: str) -> str:
    cmd = cmd.strip()
    if not cmd:
        return cmd

    m = _ZSH_LC_RE.match(cmd) or _BASH_LC_RE.match(cmd)
    if m:
        cmd = m.group("body")

    cmd = cmd.replace("\r", "")
    cmd = cmd.replace("\n", "\\n")

    # Common: cd <dir> && <rest>
    if "&&" in cmd:
        parts = [p.strip() for p in cmd.split("&&", 1)]
        if parts and parts[0].startswith("cd "):
            cmd = parts[1].strip()

    return cmd.strip()


def _summarize_value(value: Any, *, key: str | None, max_len: int) -> str:
    if isinstance(value, str):
        if key in _BULKY_TOOL_KEYS:
            return f"<{len(value)} chars>"
        return _inline_text(value, max_len)
    if isinstance(value, dict):
        return f"{{{len(value)} keys}}"
    if isinstance(value, list):
        return f"[{len(value)} items]"
    if value is None:
        return "null"
    return _truncate_text(str(value), max_len)


def _summarize_tool_data(data: Any) -> str:
    if isinstance(data, dict):
        parts: list[str] = []
        for idx, (key, value) in enumerate(data.items()):
            if idx >= _TOOL_ITEMS_MAX:
                parts.append("…")
                break
            key_str = str(key)
            parts.append(
                f"{key_str}={_summarize_value(value, key=key_str, max_len=_TOOL_VALUE_MAX)}"
            )
        summary = " ".join(parts)
    else:
        summary = _summarize_value(data, key=None, max_len=_TOOL_VALUE_MAX)
    return _truncate_text(summary, _TOOL_SUMMARY_MAX)


def _trim_lines(text: str, *, max_lines: int, tail: bool) -> tuple[str, bool]:
    lines = text.splitlines()
    if len(lines) <= max_lines:
        return text, False
    if tail:
        kept = lines[-max_lines:]
    else:
        kept = lines[:max_lines]
    return "\n".join(kept) + "\n…", True


def _trim_text(
    text: str, *, max_lines: int, max_chars: int | None, tail: bool
) -> tuple[str, bool]:
    trimmed, was_trimmed = _trim_lines(text, max_lines=max_lines, tail=tail)
    if max_chars is not None and len(trimmed) > max_chars:
        trimmed = _truncate_text(trimmed, max_chars)
        return trimmed, True
    return trimmed, was_trimmed


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


@dataclass
class BaseFormatter:
    stdout: IO[str]
    stderr: IO[str]
    repo_root: Path | None = None
    processed_events: int = 0
    event_sink: StreamEventSink | None = None

    console: Console = field(init=False)
    err_console: Console = field(init=False)

    def __post_init__(self) -> None:
        self.console = Console(file=self.stdout, highlight=False, markup=True)
        self.err_console = Console(
            file=self.stderr, highlight=False, markup=True, stderr=True
        )

    def _parse_json_line(self, line: str) -> dict[str, Any] | None:
        raw = line.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            self.err_console.print(f"[yellow][stderr][/yellow] {raw}")
            return None

    def process_line(self, line: str) -> None:
        raise NotImplementedError

    def finish(self) -> int:
        if self.processed_events == 0:
            self.err_console.print(self._empty_stream_warning())
            return 1
        return 0

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_sink:
            self.event_sink(event_type, payload)

    def _empty_stream_warning(self) -> str:
        return "[yellow]⚠ No events received[/yellow]"


# ---------------------------------------------------------------------------
# Claude
# ---------------------------------------------------------------------------


@dataclass
class ClaudeStreamJsonFormatter(BaseFormatter):
    current_tool: str | None = None
    tool_json: str = ""
    text_buffer: str = ""
    _progress_dots: int = 0

    def _empty_stream_warning(self) -> str:
        return "[yellow]⚠ No valid stream events received - Claude may have failed to start[/yellow]"

    def _clear_progress(self) -> None:
        if self._progress_dots <= 0:
            return
        try:
            self.stdout.write("\r" + (" " * self._progress_dots) + "\r")
            self.stdout.flush()
        except Exception:
            pass
        self._progress_dots = 0

    def _flush_markdown(self) -> None:
        if not self.text_buffer.strip():
            self.text_buffer = ""
            return
        self._clear_progress()
        self.console.print(Markdown(self.text_buffer))
        self.text_buffer = ""

    def _format_tool(self, name: str, json_str: str) -> None:
        try:
            data = json.loads(json_str) if json_str.strip() else {}
        except Exception:
            data = {"_raw": json_str}

        self._emit("stream.tool", {"name": name, "input": data})

        title = f"⚡ {name}"

        if name == "Read":
            path = str(data.get("file_path", ""))
            disp = (
                _inline_text(_shorten_path(path, self.repo_root), 140) if path else ""
            )
            if disp:
                self.console.print(f"[cyan]{title}[/cyan] [dim]{disp}[/dim]")
            else:
                self.console.print(f"[cyan]{title}[/cyan]")
            return

        if name == "Write":
            path = str(data.get("file_path", ""))
            disp = (
                _inline_text(_shorten_path(path, self.repo_root), 140) if path else ""
            )
            if disp:
                self.console.print(f"[cyan]{title}[/cyan] [dim]{disp}[/dim]")
            else:
                self.console.print(f"[cyan]{title}[/cyan]")
            return

        if name == "Glob":
            pattern = _inline_text(str(data.get("pattern", "")), 160)
            self.console.print(f"[cyan]{title}[/cyan] [dim]{pattern}[/dim]")
            return

        if name == "Grep":
            pattern = _inline_text(str(data.get("pattern", "")), 120)
            raw_path = str(data.get("path", ""))
            disp_path = (
                _inline_text(_shorten_path(raw_path, self.repo_root), 80)
                if raw_path
                else ""
            )
            suffix = f" in {disp_path}" if disp_path else ""
            self.console.print(f"[cyan]{title}[/cyan] [dim]/{pattern}/{suffix}[/dim]")
            return

        if name == "Bash":
            cmd = _shorten_shell_command(str(data.get("command", "")).strip())
            desc = _inline_text(str(data.get("description", "")).strip(), 120)
            cmd_first = _inline_text(cmd.splitlines()[0] if cmd else "", 160)
            line = f"[cyan]{title}[/cyan]"
            if desc:
                line += f" [yellow]{desc}[/yellow]"
            if cmd_first:
                line += f" [dim]$ {cmd_first}[/dim]"
            self.console.print(line)
            return

        if name == "Edit":
            path = str(data.get("file_path", ""))
            disp = (
                _inline_text(_shorten_path(path, self.repo_root), 140) if path else ""
            )
            if disp:
                self.console.print(f"[cyan]{title}[/cyan] [dim]{disp}[/dim]")
            else:
                self.console.print(f"[cyan]{title}[/cyan]")
            return

        if name == "Task":
            subagent = _inline_text(str(data.get("subagent_type", "unknown")), 60)
            desc = _inline_text(str(data.get("description", "")).strip(), 140)
            line = f"[cyan]{title}[/cyan] [yellow]{subagent}[/yellow]"
            if desc:
                line += f" [dim]{desc}[/dim]"
            self.console.print(line)
            return

        summary = _summarize_tool_data(data)
        if summary:
            self.console.print(f"[cyan]{title}[/cyan] [dim]{summary}[/dim]")
        else:
            self.console.print(f"[cyan]{title}[/cyan]")

    def process_line(self, line: str) -> None:
        event = self._parse_json_line(line)
        if event is None:
            return

        self.processed_events += 1

        if event.get("type") != "stream_event":
            return

        ev = event.get("event", {})
        ev_type = ev.get("type", "")

        if ev_type == "content_block_start":
            cb = ev.get("content_block", {})
            if cb.get("type") == "tool_use":
                self._flush_markdown()
                self.current_tool = cb.get("name", "unknown")
                self.tool_json = ""
            return

        if ev_type == "content_block_delta":
            delta = ev.get("delta", {})
            delta_type = delta.get("type", "")
            if delta_type == "text_delta":
                text = str(delta.get("text", ""))
                if text:
                    self._emit("stream.text", {"text": text, "delta": True})
                self.text_buffer += text
                if (
                    len(self.text_buffer) // 200
                    > (len(self.text_buffer) - len(text)) // 200
                ):
                    try:
                        self.stdout.write(".")
                        self.stdout.flush()
                        self._progress_dots += 1
                    except Exception:
                        pass
            elif delta_type == "input_json_delta":
                self.tool_json += str(delta.get("partial_json", ""))
            return

        if ev_type == "content_block_stop":
            if self.current_tool:
                self._clear_progress()
                self._format_tool(self.current_tool, self.tool_json)
                self.current_tool = None
                self.tool_json = ""
                return
            self._flush_markdown()
            return

        if ev_type == "message_stop":
            self._flush_markdown()
            return


# ---------------------------------------------------------------------------
# Codex
# ---------------------------------------------------------------------------


@dataclass
class CodexJsonlFormatter(BaseFormatter):
    show_reasoning: bool = False
    show_command_output: bool = False
    show_command_start: bool = False
    show_small_output: bool = False
    show_tokens: bool = False
    max_output_lines: int = 60
    max_output_chars: int = 2000

    _cmd_started_at: dict[str, float] = field(default_factory=dict)

    def _empty_stream_warning(self) -> str:
        return "[yellow]⚠ No JSON events received[/yellow]"

    def _print_usage(self, usage: dict[str, Any]) -> None:
        inp = usage.get("input_tokens")
        cached = usage.get("cached_input_tokens")
        out = usage.get("output_tokens")
        parts: list[str] = []
        if inp is not None:
            parts.append(f"in {inp}")
        if cached is not None:
            parts.append(f"cached {cached}")
        if out is not None:
            parts.append(f"out {out}")
        if parts:
            self.console.print(f"[dim]tokens: {', '.join(parts)}[/dim]")

    def _print_file_change(self, item: dict[str, Any]) -> None:
        changes = item.get("changes") or []
        if not isinstance(changes, list) or not changes:
            self.console.print("[cyan]⚡ Files[/cyan] [dim](no details)[/dim]")
            return

        table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
        table.add_column("kind", style="cyan", no_wrap=True)
        table.add_column("path", style="white")

        for ch in changes:
            if not isinstance(ch, dict):
                continue
            kind = str(ch.get("kind") or "")
            path = str(ch.get("path") or "")
            disp = _shorten_path(path, self.repo_root)
            style = {"add": "green", "update": "yellow", "delete": "red"}.get(
                kind, "cyan"
            )
            table.add_row(f"[{style}]{kind}[/{style}]", disp)

        self.console.print(Panel(table, title="⚡ Files", border_style="cyan"))

    def _output_stats(self, output: str) -> tuple[int, int]:
        lines = output.splitlines()
        return len(lines), len(output)

    def _is_small_output(self, output: str) -> bool:
        lines, chars = self._output_stats(output)
        return lines <= self.max_output_lines and chars <= self.max_output_chars

    def _print_command(self, item: dict[str, Any], *, started: bool) -> None:
        item_id = str(item.get("id") or "")
        cmd_raw = str(item.get("command") or "")
        cmd = _shorten_shell_command(cmd_raw)
        shown = _inline_text(cmd if cmd else cmd_raw, 160)

        if started:
            self._cmd_started_at[item_id] = time.monotonic()
            self._emit(
                "stream.command.start",
                {"id": item_id, "command": cmd_raw, "display": shown},
            )
            if not self.show_command_start:
                return
            if shown:
                self.console.print(f"[cyan]⚙ Shell[/cyan] [dim]$ {shown}[/dim]")
            else:
                self.console.print("[cyan]⚙ Shell[/cyan]")
            return

        started_at = self._cmd_started_at.pop(item_id, None)
        dur = ""
        dur_s: float | None = None
        if started_at is not None:
            dur_s = time.monotonic() - started_at
            dur = f"{dur_s:.1f}s"

        exit_code = item.get("exit_code")
        ok = exit_code == 0
        exit_label = "?" if exit_code is None else exit_code
        status = "[green]✓ ok[/green]" if ok else f"[red]✗ exit {exit_label}[/red]"
        dur_note = f" [dim]({dur})[/dim]" if dur else ""
        subtitle = f"{status}{dur_note}"
        if shown:
            subtitle += f" [dim]$ {shown}[/dim]"

        out = str(item.get("aggregated_output") or "")
        out = out.rstrip("\n")
        out_trimmed = ""
        output_truncated = False
        if out:
            out_trimmed, output_truncated = _trim_text(
                out,
                max_lines=self.max_output_lines,
                max_chars=self.max_output_chars,
                tail=not ok,
            )
        lines, chars = self._output_stats(out) if out else (0, 0)

        self._emit(
            "stream.command.end",
            {
                "id": item_id,
                "command": cmd_raw,
                "display": shown,
                "exit_code": exit_code,
                "ok": ok,
                "duration_seconds": dur_s,
                "output": out_trimmed,
                "output_truncated": output_truncated,
                "output_lines": lines,
                "output_chars": chars,
            },
        )
        if not out:
            line = f"[cyan]⚙ Shell[/cyan] {status}{dur_note}"
            if shown:
                line += f" [dim]$ {shown}[/dim]"
            self.console.print(line)
            return

        show_output = (
            self.show_command_output
            or not ok
            or (self.show_small_output and self._is_small_output(out))
        )
        if show_output:
            body = Text(out_trimmed)
            self.console.print(
                Panel(body, title="⚙ Shell", subtitle=subtitle, border_style="cyan")
            )
            return

        stats: list[str] = []
        if lines:
            stats.append(f"{lines} lines")
        if chars:
            stats.append(f"{chars} chars")
        stats_note = f" [dim]({', '.join(stats)} suppressed)[/dim]" if stats else ""
        line = f"[cyan]⚙ Shell[/cyan] {status}{dur_note}"
        if shown:
            line += f" [dim]$ {shown}[/dim]"
        line += stats_note
        self.console.print(line)

    def _print_message(self, item: dict[str, Any]) -> None:
        text = str(item.get("text") or "")
        if not text.strip():
            return
        self._emit("stream.text", {"text": text})
        self.console.print(Markdown(text))

    def _print_reasoning(self, item: dict[str, Any]) -> None:
        text = str(item.get("text") or "")
        if not text.strip():
            return
        self._emit("stream.reasoning", {"text": text})
        if not self.show_reasoning:
            return
        self.console.print(
            Panel(Markdown(text), title="🧠 Reasoning", border_style="dim")
        )

    def process_line(self, line: str) -> None:
        event = self._parse_json_line(line)
        if event is None:
            return

        self.processed_events += 1

        ev_type = str(event.get("type") or "")

        if ev_type == "thread.started":
            thread_id = str(event.get("thread_id") or "")
            if thread_id:
                self._emit("stream.thread", {"thread_id": thread_id})
            if thread_id:
                self.console.print(f"[dim]codex thread {thread_id}[/dim]")
            return

        if ev_type == "turn.started":
            return

        if ev_type == "turn.completed":
            usage = event.get("usage") or {}
            if isinstance(usage, dict) and usage:
                self._emit("stream.usage", {"usage": usage})
            if self.show_tokens:
                if isinstance(usage, dict):
                    self._print_usage(usage)
            return

        if ev_type == "item.started":
            item = event.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "command_execution":
                self._print_command(item, started=True)
            return

        if ev_type == "item.completed":
            item = event.get("item") or {}
            if not isinstance(item, dict):
                return
            item_type = str(item.get("type") or "")
            if item_type == "agent_message":
                self._print_message(item)
            elif item_type == "command_execution":
                self._print_command(item, started=False)
            elif item_type == "file_change":
                changes = item.get("changes") or []
                if isinstance(changes, list):
                    self._emit("stream.file_change", {"changes": changes})
                self._print_file_change(item)
            elif item_type == "reasoning":
                self._print_reasoning(item)
            else:
                summary = _summarize_tool_data(item)
                label = f"item {item_type}" if item_type else "item"
                if summary:
                    self._emit("stream.item", {"item_type": item_type, "summary": summary})
                else:
                    self._emit("stream.item", {"item_type": item_type})
                if summary:
                    self.console.print(f"[dim]{label}: {summary}[/dim]")
                else:
                    self.console.print(f"[dim]{label}[/dim]")
            return

        # Unknown: keep out of the way but don't drop entirely.
        summary = _summarize_tool_data(event)
        if summary:
            self._emit("stream.event", {"summary": summary})
        else:
            self._emit("stream.event", {})
        if summary:
            self.console.print(f"[dim]{summary}[/dim]")
        else:
            self.console.print("[dim](event)[/dim]")


# ---------------------------------------------------------------------------
# Kimi
# ---------------------------------------------------------------------------


@dataclass
class KimiJsonFormatter(BaseFormatter):
    """Format Kimi stream-json output (one JSON object per message turn)."""

    def _empty_stream_warning(self) -> str:
        return "[yellow]⚠ No JSON messages received - kimi may have failed to start[/yellow]"

    def process_line(self, line: str) -> None:
        msg = self._parse_json_line(line)
        if msg is None:
            return

        role = msg.get("role")
        if role == "assistant":
            self._handle_assistant(msg)
        elif role == "tool":
            self._handle_tool(msg)
        self.processed_events += 1

    def _handle_assistant(self, msg: dict[str, Any]) -> None:
        for block in msg.get("content") or []:
            if isinstance(block, str):
                if block.strip():
                    self._emit("stream.text", {"text": block})
                    self.console.print(Markdown(block))
                continue
            btype = block.get("type")
            if btype == "text":
                text = block.get("text") or ""
                if text.strip():
                    self._emit("stream.text", {"text": text})
                    self.console.print(Markdown(text))
            # thinking is omitted (not useful in loopfarm output)

        for tc in msg.get("tool_calls") or []:
            fn = (tc.get("function") or {})
            name = fn.get("name") or "?"
            args_raw = fn.get("arguments") or ""
            try:
                args = json.loads(args_raw) if args_raw else {}
            except Exception:
                args = {}
            self._emit("stream.tool", {"name": name, "input": args})
            self._print_tool_call(name, args)

    def _handle_tool(self, msg: dict[str, Any]) -> None:
        # tool results — show abbreviated output
        parts: list[str] = []
        for block in msg.get("content") or []:
            if isinstance(block, str):
                text = block
            else:
                text = block.get("text") or ""
            if text.startswith("<system>"):
                continue  # skip kimi system wrappers
            if text.strip():
                parts.append(text.strip())
        if parts:
            combined = "\n".join(parts)
            trimmed, _ = _trim_text(combined, max_lines=20, max_chars=1000, tail=True)
            self._emit("stream.tool.result", {"text": trimmed})
            self.console.print(f"[dim]{trimmed}[/dim]")

    def _print_tool_call(self, name: str, args: dict[str, Any]) -> None:
        title = f"⚡ {name}"

        if name in ("ReadFile", "Read"):
            path = str(args.get("path") or args.get("file_path") or "")
            disp = _inline_text(_shorten_path(path, self.repo_root), 140) if path else ""
            self.console.print(f"[cyan]{title}[/cyan] [dim]{disp}[/dim]")
            return

        if name in ("WriteFile", "Write"):
            path = str(args.get("path") or args.get("file_path") or "")
            disp = _inline_text(_shorten_path(path, self.repo_root), 140) if path else ""
            self.console.print(f"[cyan]{title}[/cyan] [dim]{disp}[/dim]")
            return

        if name == "Shell":
            cmd = str(args.get("command") or "")
            short = _shorten_shell_command(cmd)
            disp = _inline_text(short, 140) if short else ""
            self.console.print(f"[cyan]{title}[/cyan] [dim]{disp}[/dim]")
            return

        if name == "Grep":
            pattern = str(args.get("pattern") or args.get("regex") or "")
            path = str(args.get("path") or "")
            disp = pattern
            if path:
                disp = f"{pattern} in {_shorten_path(path, self.repo_root)}"
            self.console.print(f"[cyan]{title}[/cyan] [dim]{_inline_text(disp, 140)}[/dim]")
            return

        # generic tool
        summary = _summarize_tool_data(args)
        if summary:
            self.console.print(f"[cyan]{title}[/cyan] [dim]{summary}[/dim]")
        else:
            self.console.print(f"[cyan]{title}[/cyan]")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None, stdin: IO[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="loopfarm format")
    p.add_argument("--cli", choices=["auto", "claude", "codex", "kimi"], default="auto")
    p.add_argument("--repo-root", help="Repo root for shortening absolute paths")
    p.add_argument(
        "--show-reasoning", action="store_true", help="Show Codex reasoning items"
    )
    p.add_argument(
        "--show-command-output",
        action="store_true",
        help="Always show Codex command output",
    )
    p.add_argument(
        "--show-command-start",
        action="store_true",
        help="Show Codex command start lines",
    )
    p.add_argument(
        "--show-small-output",
        action="store_true",
        help="Show Codex output when it is below truncation limits",
    )
    p.add_argument(
        "--show-tokens",
        action="store_true",
        help="Show Codex token usage on turn completion",
    )
    p.add_argument(
        "--max-output-lines", type=int, help="Max lines of Codex command output to show"
    )
    p.add_argument(
        "--max-output-chars", type=int, help="Max chars of Codex command output to show"
    )
    args = p.parse_args(argv)

    repo_root: Path | None = Path(args.repo_root) if args.repo_root else Path.cwd()

    show_reasoning = bool(args.show_reasoning) or bool(
        env_flag("LOOPFARM_SHOW_REASONING")
    )
    show_command_output = bool(args.show_command_output) or env_flag(
        "LOOPFARM_SHOW_COMMAND_OUTPUT"
    )
    show_command_start = bool(args.show_command_start) or env_flag(
        "LOOPFARM_SHOW_COMMAND_START"
    )
    show_small_output = bool(args.show_small_output) or env_flag(
        "LOOPFARM_SHOW_SMALL_OUTPUT"
    )
    show_tokens = bool(args.show_tokens) or env_flag("LOOPFARM_SHOW_TOKENS")
    max_output_lines = (
        args.max_output_lines
        if args.max_output_lines is not None
        else env_int("LOOPFARM_MAX_OUTPUT_LINES", 60)
    )
    max_output_chars = (
        args.max_output_chars
        if args.max_output_chars is not None
        else env_int("LOOPFARM_MAX_OUTPUT_CHARS", 2000)
    )

    inp = sys.stdin if stdin is None else stdin

    def _make_codex() -> CodexJsonlFormatter:
        return CodexJsonlFormatter(
            stdout=sys.stdout,
            stderr=sys.stderr,
            repo_root=repo_root,
            show_reasoning=show_reasoning,
            show_command_output=show_command_output,
            show_command_start=show_command_start,
            show_small_output=show_small_output,
            show_tokens=show_tokens,
            max_output_lines=max_output_lines,
            max_output_chars=max_output_chars,
        )

    formatter: BaseFormatter | None = None
    forced = args.cli != "auto"

    for line in inp:
        if not formatter:
            raw = line.strip()
            if not raw:
                continue
            try:
                obj = json.loads(raw)
            except Exception:
                sys.stdout.write(line)
                sys.stdout.flush()
                continue

            if args.cli == "claude" or (
                not forced and obj.get("type") == "stream_event"
            ):
                formatter = ClaudeStreamJsonFormatter(
                    stdout=sys.stdout, stderr=sys.stderr, repo_root=repo_root
                )
            elif args.cli == "codex" or (
                not forced
                and str(obj.get("type") or "").startswith(("thread.", "turn.", "item."))
            ):
                formatter = _make_codex()
            elif args.cli == "kimi" or (not forced and "role" in obj):
                formatter = KimiJsonFormatter(
                    stdout=sys.stdout, stderr=sys.stderr, repo_root=repo_root
                )
            else:
                formatter = _make_codex()

            formatter.process_line(line)
            continue

        formatter.process_line(line)

    if not formatter:
        raise SystemExit(1)
    raise SystemExit(formatter.finish())


if __name__ == "__main__":
    main()
