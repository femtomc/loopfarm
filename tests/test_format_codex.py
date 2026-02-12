"""Tests for CodexJsonlFormatter."""

from __future__ import annotations

import io
import json

from loopfarm.format_stream import CodexJsonlFormatter


def _ev(data: dict) -> str:
    return json.dumps(data)


class TestCodexEmpty:
    def test_finish_returns_1(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = CodexJsonlFormatter(stdout=stdout, stderr=stderr)
        assert f.finish() == 1
        assert "No JSON events" in stderr.getvalue()


class TestCodexThreadStarted:
    def test_prints_thread_id(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = CodexJsonlFormatter(stdout=stdout, stderr=stderr)
        f.process_line(_ev({"type": "thread.started", "thread_id": "abc123"}))
        assert "abc123" in stdout.getvalue()


class TestCodexItemCompleted:
    def test_agent_message(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = CodexJsonlFormatter(stdout=stdout, stderr=stderr)
        f.process_line(_ev({
            "type": "item.completed",
            "item": {"type": "agent_message", "text": "Hello from codex"},
        }))
        assert "Hello from codex" in stdout.getvalue()

    def test_command_ok(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = CodexJsonlFormatter(stdout=stdout, stderr=stderr)
        f.process_line(_ev({
            "type": "item.completed",
            "item": {"type": "command_execution", "id": "c1", "command": "ls", "exit_code": 0, "aggregated_output": ""},
        }))
        out = stdout.getvalue()
        assert "Shell" in out

    def test_command_fail(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = CodexJsonlFormatter(stdout=stdout, stderr=stderr, show_command_output=True)
        f.process_line(_ev({
            "type": "item.completed",
            "item": {"type": "command_execution", "id": "c2", "command": "false", "exit_code": 1, "aggregated_output": "error output"},
        }))
        out = stdout.getvalue()
        assert "exit 1" in out

    def test_file_change(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = CodexJsonlFormatter(stdout=stdout, stderr=stderr)
        f.process_line(_ev({
            "type": "item.completed",
            "item": {
                "type": "file_change",
                "changes": [{"kind": "add", "path": "/foo/new.py"}],
            },
        }))
        out = stdout.getvalue()
        assert "Files" in out


class TestCodexReasoning:
    def test_hidden_by_default(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = CodexJsonlFormatter(stdout=stdout, stderr=stderr)
        f.process_line(_ev({
            "type": "item.completed",
            "item": {"type": "reasoning", "text": "thinking hard"},
        }))
        assert "thinking hard" not in stdout.getvalue()

    def test_shown_when_enabled(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = CodexJsonlFormatter(stdout=stdout, stderr=stderr, show_reasoning=True)
        f.process_line(_ev({
            "type": "item.completed",
            "item": {"type": "reasoning", "text": "thinking hard"},
        }))
        assert "thinking hard" in stdout.getvalue()


class TestCodexInvalidJson:
    def test_invalid_json_stderr(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = CodexJsonlFormatter(stdout=stdout, stderr=stderr)
        f.process_line("broken json!!!\n")
        assert "broken json" in stderr.getvalue()
