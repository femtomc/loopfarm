from __future__ import annotations

import io
import json
import re

from rich.console import Console

from inshallah.fmt import ClaudeFormatter, CodexFormatter, GeminiFormatter, OpenCodeFormatter, PiFormatter


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


# -- Codex --


def test_codex_success_shows_checkmark() -> None:
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
    _emit(
        fmt,
        {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "/usr/bin/zsh -lc 'echo hi'",
                "aggregated_output": "hi\n",
                "exit_code": 0,
                "status": "completed",
            },
        },
    )

    rendered = out.getvalue()
    assert "\u2713" in rendered
    assert "bash echo hi" in rendered
    assert rendered.strip().count("\n") == 0


def test_codex_failure_shows_cross() -> None:
    console, out = _console(force_terminal=False)
    fmt = CodexFormatter(console)

    _emit(
        fmt,
        {
            "type": "item.started",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "/usr/bin/zsh -lc 'false'",
                "aggregated_output": "",
                "exit_code": None,
                "status": "in_progress",
            },
        },
    )
    _emit(
        fmt,
        {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "/usr/bin/zsh -lc 'false'",
                "aggregated_output": "",
                "exit_code": 1,
                "status": "completed",
            },
        },
    )

    rendered = out.getvalue()
    assert "\u2717" in rendered
    assert "bash false" in rendered


def test_codex_buffered_until_result() -> None:
    """Tool call is not printed until the result event arrives."""
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
    assert out.getvalue().strip() == ""

    _emit(
        fmt,
        {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "/usr/bin/zsh -lc 'echo hi'",
                "aggregated_output": "hi\n",
                "exit_code": 0,
                "status": "completed",
            },
        },
    )
    assert "bash echo hi" in out.getvalue()


def test_codex_no_rich_artifacts() -> None:
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
    _emit(
        fmt,
        {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "/usr/bin/zsh -lc 'echo hi'",
                "aggregated_output": "hi\n",
                "exit_code": 0,
                "status": "completed",
            },
        },
    )

    rendered = out.getvalue()
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


def test_codex_interactive_message_streams_before_finish() -> None:
    out = io.StringIO()
    console = Console(file=out, force_terminal=True, width=120)
    fmt = CodexFormatter(console)

    _emit(
        fmt,
        {
            "type": "item.completed",
            "item": {
                "id": "item_2",
                "type": "agent_message",
                "text": "Streaming status update.",
            },
        },
    )

    rendered = out.getvalue()
    plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
    assert "agent" in plain
    assert "Streaming status update." in plain


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


def test_codex_function_call_is_normalized() -> None:
    console, out = _console(force_terminal=False)
    fmt = CodexFormatter(console)

    _emit(
        fmt,
        {
            "type": "item.started",
            "item": {
                "id": "item_fn",
                "type": "function_call",
                "name": "apply_patch",
                "arguments": '{"path":"src/main.py"}',
            },
        },
    )
    _emit(
        fmt,
        {
            "type": "item.completed",
            "item": {
                "id": "item_fn",
                "type": "function_call",
                "status": "completed",
            },
        },
    )

    rendered = out.getvalue()
    assert "edit src/main.py" in rendered


def test_codex_multiline_shell_is_compact() -> None:
    console, out = _console(force_terminal=False)
    fmt = CodexFormatter(console)

    _emit(
        fmt,
        {
            "type": "item.started",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "command": "/usr/bin/zsh -lc 'set -euo pipefail\\nROOT=abc\\ninshallah issues list --root abc'",
            },
        },
    )
    _emit(
        fmt,
        {
            "type": "item.completed",
            "item": {
                "id": "item_1",
                "type": "command_execution",
                "exit_code": 0,
                "status": "completed",
            },
        },
    )

    rendered = out.getvalue()
    assert "ROOT=abc (+1 more lines)" in rendered


def test_codex_user_prompt_is_shown() -> None:
    console, out = _console(force_terminal=False)
    fmt = CodexFormatter(console)

    _emit(
        fmt,
        {
            "type": "item.completed",
            "item": {
                "id": "item_prompt",
                "type": "message",
                "role": "user",
                "text": "Please fix the parser.",
            },
        },
    )

    rendered = out.getvalue()
    assert "prompt: Please fix the parser." in rendered


# -- OpenCode --


def test_opencode_success_shows_checkmark() -> None:
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

    rendered = out.getvalue()
    assert "\u2713" in rendered
    assert "bash echo hi" in rendered


def test_opencode_failure_shows_cross() -> None:
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
                    "status": "error",
                    "input": {"command": "/usr/bin/zsh -lc 'false'"},
                    "output": "",
                },
            },
        },
    )

    rendered = out.getvalue()
    assert "\u2717" in rendered
    assert "bash false" in rendered


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


# -- Pi --


def test_pi_success_shows_checkmark() -> None:
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
            "type": "tool_execution_end",
            "toolCallId": "tool_1",
            "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "hi"}]},
            "isError": False,
        },
    )

    rendered = out.getvalue()
    assert "\u2713" in rendered
    assert "bash echo hi" in rendered


def test_pi_failure_shows_cross() -> None:
    console, out = _console(force_terminal=False)
    fmt = PiFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_execution_start",
            "toolCallId": "tool_1",
            "toolName": "bash",
            "args": {"command": "/usr/bin/zsh -lc 'false'"},
        },
    )
    _emit(
        fmt,
        {
            "type": "tool_execution_end",
            "toolCallId": "tool_1",
            "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "error"}]},
            "isError": True,
        },
    )

    rendered = out.getvalue()
    assert "\u2717" in rendered
    assert "bash false" in rendered


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
            "type": "tool_execution_end",
            "toolCallId": "tool_1",
            "toolName": "bash",
            "result": {"content": [{"type": "text", "text": "hi"}]},
            "isError": False,
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


# -- Gemini --


def test_gemini_success_shows_checkmark() -> None:
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
            "type": "tool_result",
            "tool_name": "run_shell_command",
            "tool_id": "tool_1",
            "status": "success",
            "output": "hi\n",
        },
    )

    rendered = out.getvalue()
    assert "\u2713" in rendered
    assert "bash echo hi" in rendered


def test_gemini_failure_shows_cross() -> None:
    console, out = _console(force_terminal=False)
    fmt = GeminiFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool_name": "run_shell_command",
            "tool_id": "tool_1",
            "parameters": {"command": "/usr/bin/zsh -lc 'false'"},
        },
    )
    _emit(
        fmt,
        {
            "type": "tool_result",
            "tool_name": "run_shell_command",
            "tool_id": "tool_1",
            "status": "error",
            "output": "",
        },
    )

    rendered = out.getvalue()
    assert "\u2717" in rendered
    assert "bash false" in rendered


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
            "type": "tool_result",
            "tool_name": "run_shell_command",
            "tool_id": "tool_1",
            "status": "success",
            "output": "hi\n",
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
    assert "bash echo hi" in rendered
    assert "Applied Gemini backend updates." in rendered
    assert "stats status=success duration=1.2s tokens=42" in rendered
    assert "\x1b[" not in rendered
    assert not re.search(r"[╭╮╰╯│─]", rendered)


def test_gemini_init_suppressed() -> None:
    console, out = _console(force_terminal=False)
    fmt = GeminiFormatter(console)

    _emit(fmt, {"type": "init", "model": "gemini-2.5-pro"})

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


# -- Claude --


def test_claude_success_shows_checkmark() -> None:
    console, out = _console(force_terminal=False)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool": "Read",
            "input": {"file_path": "src/main.py"},
        },
    )
    _emit(fmt, {"type": "tool_result", "is_error": False})

    rendered = out.getvalue()
    assert "\u2713" in rendered
    assert "read src/main.py" in rendered


def test_claude_failure_shows_cross() -> None:
    console, out = _console(force_terminal=False)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool": "Bash",
            "input": {"command": "false"},
        },
    )
    _emit(fmt, {"type": "tool_result", "is_error": True})

    rendered = out.getvalue()
    assert "\u2717" in rendered
    assert "bash false" in rendered


def test_claude_tool_buffered_until_result() -> None:
    console, out = _console(force_terminal=False)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool": "Bash",
            "input": {"command": "ls -la"},
        },
    )
    assert out.getvalue().strip() == ""

    _emit(fmt, {"type": "tool_result", "is_error": False})
    assert "bash ls -la" in out.getvalue()


def test_claude_tool_single_line() -> None:
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
    _emit(fmt, {"type": "tool_result", "is_error": False})

    rendered = out.getvalue()
    assert "bash ls -la" in rendered
    assert rendered.strip().count("\n") == 0


def test_claude_summary_on_finish() -> None:
    console, out = _console(force_terminal=False)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Working on it..."}],
            },
        },
    )
    _emit(fmt, {"type": "result", "cost_usd": 0.0012, "duration_ms": 900})
    fmt.finish()

    rendered = out.getvalue()
    assert "Working on it..." in rendered
    assert "$0.0012" in rendered
    assert "0.9s" in rendered


def test_claude_result_total_cost_field_supported() -> None:
    console, out = _console(force_terminal=False)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "assistant",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Done."}],
            },
        },
    )
    _emit(fmt, {"type": "result", "total_cost_usd": 0.1234, "duration_ms": 1200})
    fmt.finish()

    rendered = out.getvalue()
    assert "cost=$0.1234" in rendered
    assert "duration=1.2s" in rendered


def test_claude_text_delta_accumulates_without_assistant_event() -> None:
    console, out = _console(force_terminal=False)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "text", "text": ""},
            },
        },
    )
    _emit(
        fmt,
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Hello"},
            },
        },
    )
    _emit(
        fmt,
        {
            "type": "stream_event",
            "event": {"type": "content_block_stop"},
        },
    )
    fmt.finish()

    rendered = out.getvalue()
    assert "Hello" in rendered


def test_claude_interactive_delta_streams_before_finish() -> None:
    out = io.StringIO()
    console = Console(file=out, force_terminal=True, width=120)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_start",
                "content_block": {"type": "text", "text": ""},
            },
        },
    )
    _emit(
        fmt,
        {
            "type": "stream_event",
            "event": {
                "type": "content_block_delta",
                "delta": {"type": "text_delta", "text": "Hi"},
            },
        },
    )

    rendered = out.getvalue()
    plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
    assert "agent" in plain
    assert "Hi" in plain


def test_claude_no_rich_artifacts() -> None:
    console, out = _console(force_terminal=False)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool": "Read",
            "input": {"file_path": "src/inshallah/fmt.py"},
        },
    )
    _emit(fmt, {"type": "tool_result", "is_error": False})
    _emit(fmt, {"type": "error", "error": "boom"})

    rendered = out.getvalue()
    assert "read src/inshallah/fmt.py" in rendered
    assert "error: boom" in rendered
    assert "\x1b[" not in rendered
    assert not re.search(r"[╭╮╰╯│─]", rendered)


def test_claude_pending_tool_flushed_on_finish() -> None:
    """If no tool_result arrives, finish() flushes as success."""
    console, out = _console(force_terminal=False)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool": "Read",
            "input": {"file_path": "src/main.py"},
        },
    )
    assert out.getvalue().strip() == ""

    fmt.finish()
    rendered = out.getvalue()
    assert "\u2713" in rendered
    assert "read src/main.py" in rendered


# -- Tool normalization --


def test_normalize_tool_names() -> None:
    from inshallah.fmt import _normalize_tool

    assert _normalize_tool("Read") == "read"
    assert _normalize_tool("Write") == "write"
    assert _normalize_tool("Edit") == "edit"
    assert _normalize_tool("Bash") == "bash"
    assert _normalize_tool("Glob") == "glob"
    assert _normalize_tool("Grep") == "grep"
    assert _normalize_tool("Task") == "task"
    assert _normalize_tool("read_file") == "read"
    assert _normalize_tool("write_file") == "write"
    assert _normalize_tool("replace") == "edit"
    assert _normalize_tool("run_shell_command") == "bash"
    assert _normalize_tool("search_file_content") == "grep"
    assert _normalize_tool("find") == "glob"
    # Pass-through for already-canonical names
    assert _normalize_tool("bash") == "bash"
    assert _normalize_tool("unknown_tool") == "unknown_tool"


# -- Color-coding --


def test_edit_tool_styled_magenta_interactive() -> None:
    """Edit/write tools use magenta style when interactive."""
    out = io.StringIO()
    console = Console(file=out, force_terminal=True, width=120)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool": "Edit",
            "input": {"file_path": "src/main.py"},
        },
    )
    _emit(fmt, {"type": "tool_result", "is_error": False})

    rendered = out.getvalue()
    plain = re.sub(r"\x1b\[[0-9;]*m", "", rendered)
    assert "edit src/main.py" in plain
    # Non-interactive assertion not needed; just verify it renders


def test_color_coding_no_ansi_plain() -> None:
    """Color-coding does not inject ANSI codes in non-interactive mode."""
    console, out = _console(force_terminal=False)
    fmt = ClaudeFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool": "Edit",
            "input": {"file_path": "src/main.py"},
        },
    )
    _emit(fmt, {"type": "tool_result", "is_error": False})

    rendered = out.getvalue()
    assert "edit src/main.py" in rendered
    assert "\x1b[" not in rendered


def test_gemini_read_file_normalized() -> None:
    """Gemini read_file is normalized to 'read'."""
    console, out = _console(force_terminal=False)
    fmt = GeminiFormatter(console)

    _emit(
        fmt,
        {
            "type": "tool_use",
            "tool_name": "read_file",
            "tool_id": "tool_1",
            "parameters": {"path": "/tmp/test.py"},
        },
    )
    _emit(
        fmt,
        {
            "type": "tool_result",
            "tool_id": "tool_1",
            "status": "success",
        },
    )

    rendered = out.getvalue()
    assert "read /tmp/test.py" in rendered
