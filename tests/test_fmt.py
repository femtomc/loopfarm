from __future__ import annotations

import io
import json
import re

from rich.console import Console

from loopfarm.fmt import ClaudeFormatter, CodexFormatter, GeminiFormatter, OpenCodeFormatter, PiFormatter


def _console(force_terminal: bool) -> tuple[Console, io.StringIO]:
    out = io.StringIO()
    console = Console(
        file=out,
        force_terminal=force_terminal,
        color_system=None,
        width=120,
    )
    return console, out


def _emit(
    formatter: ClaudeFormatter | CodexFormatter | OpenCodeFormatter | PiFormatter | GeminiFormatter,
    event: dict,
) -> None:
    formatter.process_line(json.dumps(event))


def test_codex_tool_call_single_line() -> None:
    console, out = _console(force_terminal=True)
    fmt = CodexFormatter(console)

    _emit(
        fmt,
        {
            "type": "item.started",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "/usr/bin/zsh -lc 'echo hi'",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
    )

    rendered = out.getvalue()
    assert "bash echo hi" in rendered
    # Single line per tool call
    assert rendered.strip().count("\n") == 0


def test_codex_noninteractive_no_rich_artifacts() -> None:
    console, out = _console(force_terminal=False)
    fmt = CodexFormatter(console)

    _emit(
        fmt,
        {
            "type": "item.started",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "/usr/bin/zsh -lc 'echo hi'",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
    )

    rendered = out.getvalue()
    assert "bash echo hi" in rendered
    assert "\x1b[" not in rendered
    assert not re.search(r"[╭╮╰╯│─]", rendered)


def test_codex_summary_on_finish() -> None:
    console, out = _console(force_terminal=False)
    fmt = CodexFormatter(console)

    _emit(
        fmt,
        {
            "type": "item.completed",
            "item": {
                "id": "item_2",
                "type": "agent_message",
                "text": "Applying formatter updates.",
            },
        },
    )
    fmt.finish()

    rendered = out.getvalue()
    assert "Applying formatter updates." in rendered


def test_codex_reasoning_suppressed() -> None:
    console, out = _console(force_terminal=False)
    fmt = CodexFormatter(console)

    _emit(
        fmt,
        {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "reasoning",
                "text": "**Planning output changes**",
            },
        },
    )

    rendered = out.getvalue()
    assert "Planning" not in rendered


def test_opencode_tool_and_summary() -> None:
    console, out = _console(force_terminal=False)
    fmt = OpenCodeFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "part": {
                "id": "part_1",
                "type": "tool",
                "tool": "bash",
                "state": {
                    "status": "completed",
                    "input": {"command": "/usr/bin/zsh -lc 'echo hi'"},
                    "output": "hi\n",
                },
            },
        },
    )
    _emit(
        fmt,
        {
            "type": "text",
            "part": {
                "id": "part_2",
                "type": "text",
                "text": "Applied OpenCode backend updates.",
            },
        },
    )
    _emit(
        fmt,
        {
            "type": "error",
            "error": {
                "name": "RateLimitError",
                "data": {"message": "rate limited"},
            },
        },
    )
    fmt.finish()

    rendered = out.getvalue()
    assert "bash echo hi" in rendered
    assert "Applied OpenCode backend updates." in rendered
    assert "error: rate limited" in rendered
    assert "\x1b[" not in rendered
    assert not re.search(r"[╭╮╰╯│─]", rendered)


def test_opencode_reasoning_suppressed() -> None:
    console, out = _console(force_terminal=False)
    fmt = OpenCodeFormatter(console)

    _emit(
        fmt,
        {
            "type": "reasoning",
            "part": {
                "id": "part_3",
                "type": "reasoning",
                "text": "**Planning tests**",
            },
        },
    )

    rendered = out.getvalue()
    assert "Planning" not in rendered


def test_pi_tool_and_summary() -> None:
    console, out = _console(force_terminal=False)
    fmt = PiFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_execution_start",
            "toolCallId": "tool_1",
            "toolName": "bash",
            "args": {"command": "/usr/bin/zsh -lc 'echo hi'"},
        },
    )
    _emit(
        fmt,
        {
            "type": "message_update",
            "message": {"role": "assistant"},
            "assistantMessageEvent": {
                "type": "text_delta",
                "delta": "Applied pi backend updates.",
            },
        },
    )
    _emit(
        fmt,
        {
            "type": "message_end",
            "message": {
                "role": "assistant",
                "stopReason": "error",
                "errorMessage": "rate limited",
            },
        },
    )
    fmt.finish()

    rendered = out.getvalue()
    assert "bash echo hi" in rendered
    assert "Applied pi backend updates." in rendered
    assert "error: rate limited" in rendered
    assert "\x1b[" not in rendered
    assert not re.search(r"[╭╮╰╯│─]", rendered)


def test_pi_thinking_suppressed() -> None:
    console, out = _console(force_terminal=False)
    fmt = PiFormatter(console)

    _emit(
        fmt,
        {
            "type": "message_update",
            "message": {"role": "assistant"},
            "assistantMessageEvent": {
                "type": "thinking_delta",
                "delta": "**Planning tests**",
            },
        },
    )

    rendered = out.getvalue()
    assert "Planning" not in rendered


def test_pi_tool_result_suppressed() -> None:
    console, out = _console(force_terminal=False)
    fmt = PiFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_execution_end",
            "toolCallId": "tool_1",
            "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "hi"}]},
            "isError": False,
        },
    )

    rendered = out.getvalue()
    assert rendered.strip() == ""


def test_gemini_tool_and_summary() -> None:
    console, out = _console(force_terminal=False)
    fmt = GeminiFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool_name": "run_shell_command",
            "tool_id": "tool_1",
            "parameters": {"command": "/usr/bin/zsh -lc 'echo hi'"},
        },
    )
    _emit(
        fmt,
        {
            "type": "message",
            "role": "assistant",
            "content": "Applied Gemini backend updates.",
            "delta": False,
        },
    )
    _emit(
        fmt,
        {
            "type": "result",
            "status": "success",
            "duration_ms": 1200,
            "usage": {"totalTokens": 42},
        },
    )
    fmt.finish()

    rendered = out.getvalue()
    assert "run_shell_command echo hi" in rendered
    assert "Applied Gemini backend updates." in rendered
    assert "success 1.2s tokens=42" in rendered
    assert "\x1b[" not in rendered
    assert not re.search(r"[╭╮╰╯│─]", rendered)


def test_gemini_init_suppressed() -> None:
    console, out = _console(force_terminal=False)
    fmt = GeminiFormatter(console)

    _emit(fmt, {"type": "init", "model": "gemini-2.5-pro"})

    rendered = out.getvalue()
    assert rendered.strip() == ""


def test_gemini_tool_result_suppressed() -> None:
    console, out = _console(force_terminal=False)
    fmt = GeminiFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_result",
            "tool_name": "run_shell_command",
            "tool_id": "tool_1",
            "status": "success",
            "output": "hi\n",
        },
    )

    rendered = out.getvalue()
    assert rendered.strip() == ""


def test_gemini_renders_error() -> None:
    console, out = _console(force_terminal=False)
    fmt = GeminiFormatter(console)

    _emit(
        fmt,
        {
            "type": "error",
            "error": {"message": "rate limited"},
        },
    )

    rendered = out.getvalue()
    assert "error: rate limited" in rendered


def test_claude_tool_call_single_line() -> None:
    console, out = _console(force_terminal=True)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool": "Bash",
            "input": {"command": "ls -la"},
        },
    )

    rendered = out.getvalue()
    assert "Bash ls -la" in rendered
    assert rendered.strip().count("\n") == 0


def test_claude_summary_on_finish() -> None:
    console, out = _console(force_terminal=False)
    fmt = ClaudeFormatter(console)

    _emit(fmt, {"type": "assistant", "message": "Working on it..."})
    _emit(fmt, {"type": "result", "cost_usd": 0.0012, "duration_ms": 900})
    fmt.finish()

    rendered = out.getvalue()
    assert "Working on it..." in rendered
    assert "$0.0012" in rendered
    assert "0.9s" in rendered


def test_claude_noninteractive_no_rich_artifacts() -> None:
    console, out = _console(force_terminal=False)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool": "Read",
            "input": {"file_path": "src/loopfarm/fmt.py"},
        },
    )
    _emit(fmt, {"type": "error", "error": "boom"})

    rendered = out.getvalue()
    assert "Read src/loopfarm/fmt.py" in rendered
    assert "error: boom" in rendered
    assert "\x1b[" not in rendered
    assert not re.search(r"[╭╮╰╯│─]", rendered)
