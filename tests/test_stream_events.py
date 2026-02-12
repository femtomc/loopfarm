from __future__ import annotations

import io
import json

from loopfarm.format_stream import (
    ClaudeStreamJsonFormatter,
    CodexJsonlFormatter,
    KimiJsonFormatter,
)


def _claude_event(ev: dict) -> str:
    return json.dumps({"type": "stream_event", "event": ev})


def test_claude_emits_text_and_tool(stdout: io.StringIO, stderr: io.StringIO) -> None:
    events: list[tuple[str, dict]] = []
    f = ClaudeStreamJsonFormatter(
        stdout=stdout, stderr=stderr, event_sink=lambda t, p: events.append((t, p))
    )
    f.process_line(_claude_event({"type": "content_block_start", "content_block": {"type": "text"}}))
    f.process_line(_claude_event({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello"}}))
    f.process_line(_claude_event({"type": "content_block_stop"}))
    f.process_line(
        _claude_event(
            {
                "type": "content_block_start",
                "content_block": {"type": "tool_use", "name": "Read"},
            }
        )
    )
    f.process_line(
        _claude_event(
            {"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": "{\"file_path\": \"/tmp/x\"}"}}
        )
    )
    f.process_line(_claude_event({"type": "content_block_stop"}))
    types = [t for t, _ in events]
    assert "stream.text" in types
    assert "stream.tool" in types


def test_codex_emits_command_and_message(stdout: io.StringIO, stderr: io.StringIO) -> None:
    events: list[tuple[str, dict]] = []
    f = CodexJsonlFormatter(
        stdout=stdout, stderr=stderr, event_sink=lambda t, p: events.append((t, p))
    )
    f.process_line(json.dumps({"type": "item.started", "item": {"type": "command_execution", "id": "c1", "command": "ls"}}))
    f.process_line(
        json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "id": "c1",
                    "command": "ls",
                    "exit_code": 0,
                    "aggregated_output": "ok",
                },
            }
        )
    )
    f.process_line(
        json.dumps(
            {
                "type": "item.completed",
                "item": {"type": "agent_message", "text": "Done"},
            }
        )
    )
    types = [t for t, _ in events]
    assert "stream.command.start" in types
    assert "stream.command.end" in types
    assert "stream.text" in types


def test_kimi_emits_text_and_tool(stdout: io.StringIO, stderr: io.StringIO) -> None:
    events: list[tuple[str, dict]] = []
    f = KimiJsonFormatter(
        stdout=stdout, stderr=stderr, event_sink=lambda t, p: events.append((t, p))
    )
    f.process_line(
        json.dumps(
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "hi"}],
                "tool_calls": [
                    {"function": {"name": "ReadFile", "arguments": "{\"path\": \"/tmp/a\"}"}}
                ],
            }
        )
    )
    types = [t for t, _ in events]
    assert "stream.text" in types
    assert "stream.tool" in types
