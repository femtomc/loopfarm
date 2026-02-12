"""Tests for KimiJsonFormatter."""

from __future__ import annotations

import io
import json

from loopfarm.format_stream import KimiJsonFormatter


class TestKimiEmpty:
    def test_finish_returns_1(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = KimiJsonFormatter(stdout=stdout, stderr=stderr)
        assert f.finish() == 1
        assert "kimi" in stderr.getvalue()


class TestKimiAssistantText:
    def test_dict_block(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = KimiJsonFormatter(stdout=stdout, stderr=stderr)
        f.process_line(json.dumps({
            "role": "assistant",
            "content": [{"type": "text", "text": "Hello from kimi"}],
        }))
        assert "Hello from kimi" in stdout.getvalue()

    def test_plain_string_block(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        """The original bug: content blocks can be plain strings."""
        f = KimiJsonFormatter(stdout=stdout, stderr=stderr)
        f.process_line(json.dumps({
            "role": "assistant",
            "content": ["Plain text block"],
        }))
        assert "Plain text block" in stdout.getvalue()

    def test_mixed_blocks(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = KimiJsonFormatter(stdout=stdout, stderr=stderr)
        f.process_line(json.dumps({
            "role": "assistant",
            "content": [
                "first",
                {"type": "text", "text": "second"},
            ],
        }))
        out = stdout.getvalue()
        assert "first" in out
        assert "second" in out


class TestKimiToolCalls:
    def _assistant_with_tool(self, name: str, args: dict, stdout: io.StringIO, stderr: io.StringIO) -> str:
        f = KimiJsonFormatter(stdout=stdout, stderr=stderr)
        f.process_line(json.dumps({
            "role": "assistant",
            "content": [],
            "tool_calls": [{
                "function": {"name": name, "arguments": json.dumps(args)},
            }],
        }))
        return stdout.getvalue()

    def test_read_file(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        out = self._assistant_with_tool("ReadFile", {"path": "/foo/bar.py"}, stdout, stderr)
        assert "ReadFile" in out
        assert "bar.py" in out

    def test_shell(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        out = self._assistant_with_tool("Shell", {"command": "make test"}, stdout, stderr)
        assert "Shell" in out
        assert "make test" in out

    def test_grep(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        out = self._assistant_with_tool("Grep", {"pattern": "TODO"}, stdout, stderr)
        assert "Grep" in out

    def test_generic(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        out = self._assistant_with_tool("CustomTool", {"x": 1}, stdout, stderr)
        assert "CustomTool" in out


class TestKimiToolResult:
    def test_string_content_block(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        """The original bug: tool result content can be a plain string."""
        f = KimiJsonFormatter(stdout=stdout, stderr=stderr)
        f.process_line(json.dumps({
            "role": "tool",
            "content": ["file contents here"],
        }))
        assert "file contents here" in stdout.getvalue()

    def test_system_prefix_skipped(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = KimiJsonFormatter(stdout=stdout, stderr=stderr)
        f.process_line(json.dumps({
            "role": "tool",
            "content": ["<system>internal stuff</system>", "visible output"],
        }))
        out = stdout.getvalue()
        assert "internal stuff" not in out
        assert "visible output" in out


class TestKimiInvalidJson:
    def test_invalid_json_to_stderr(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        """After refactor, invalid JSON goes to stderr (new behavior from base class)."""
        f = KimiJsonFormatter(stdout=stdout, stderr=stderr)
        f.process_line("not json\n")
        assert "not json" in stderr.getvalue()
