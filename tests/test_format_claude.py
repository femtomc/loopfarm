"""Tests for ClaudeStreamJsonFormatter."""

from __future__ import annotations

import io
import json

from loopfarm.format_stream import ClaudeStreamJsonFormatter


def _se(ev: dict) -> str:
    """Wrap an inner event dict as a stream_event JSON line."""
    return json.dumps({"type": "stream_event", "event": ev})


class TestClaudeEmpty:
    def test_finish_returns_1(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = ClaudeStreamJsonFormatter(stdout=stdout, stderr=stderr)
        assert f.finish() == 1
        assert "Claude" in stderr.getvalue()


class TestClaudeTextBlock:
    def test_text_renders_markdown(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = ClaudeStreamJsonFormatter(stdout=stdout, stderr=stderr)
        f.process_line(_se({"type": "content_block_start", "content_block": {"type": "text"}}))
        f.process_line(_se({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Hello "}}))
        f.process_line(_se({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "world"}}))
        f.process_line(_se({"type": "content_block_stop"}))
        output = stdout.getvalue()
        assert "Hello" in output
        assert "world" in output


class TestClaudeToolUse:
    def _tool_flow(self, name: str, input_json: dict, stdout: io.StringIO, stderr: io.StringIO) -> str:
        f = ClaudeStreamJsonFormatter(stdout=stdout, stderr=stderr)
        f.process_line(_se({"type": "content_block_start", "content_block": {"type": "tool_use", "name": name}}))
        raw = json.dumps(input_json)
        f.process_line(_se({"type": "content_block_delta", "delta": {"type": "input_json_delta", "partial_json": raw}}))
        f.process_line(_se({"type": "content_block_stop"}))
        return stdout.getvalue()

    def test_read(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        out = self._tool_flow("Read", {"file_path": "/foo/bar.py"}, stdout, stderr)
        assert "Read" in out
        assert "bar.py" in out

    def test_bash(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        out = self._tool_flow("Bash", {"command": "ls -la", "description": "list files"}, stdout, stderr)
        assert "Bash" in out
        assert "list files" in out

    def test_write(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        out = self._tool_flow("Write", {"file_path": "/foo/new.py"}, stdout, stderr)
        assert "Write" in out

    def test_grep(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        out = self._tool_flow("Grep", {"pattern": "TODO", "path": "/src"}, stdout, stderr)
        assert "Grep" in out
        assert "TODO" in out

    def test_edit(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        out = self._tool_flow("Edit", {"file_path": "/foo/edit.py"}, stdout, stderr)
        assert "Edit" in out

    def test_task(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        out = self._tool_flow("Task", {"subagent_type": "Explore", "description": "find stuff"}, stdout, stderr)
        assert "Task" in out
        assert "Explore" in out

    def test_generic(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        out = self._tool_flow("CustomTool", {"key": "val"}, stdout, stderr)
        assert "CustomTool" in out


class TestClaudeMessageStop:
    def test_message_stop_flushes(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = ClaudeStreamJsonFormatter(stdout=stdout, stderr=stderr)
        f.process_line(_se({"type": "content_block_start", "content_block": {"type": "text"}}))
        f.process_line(_se({"type": "content_block_delta", "delta": {"type": "text_delta", "text": "buffered"}}))
        f.process_line(_se({"type": "message_stop"}))
        assert "buffered" in stdout.getvalue()


class TestClaudeInvalidJson:
    def test_invalid_json_stderr(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = ClaudeStreamJsonFormatter(stdout=stdout, stderr=stderr)
        f.process_line("this is not json\n")
        assert "this is not json" in stderr.getvalue()
