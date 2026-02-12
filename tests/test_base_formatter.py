"""Tests for BaseFormatter."""

from __future__ import annotations

import io
import json

from loopfarm.format_stream import BaseFormatter


class ConcreteFormatter(BaseFormatter):
    """Minimal concrete subclass for testing."""

    def process_line(self, line: str) -> None:
        event = self._parse_json_line(line)
        if event is not None:
            self.processed_events += 1


class TestBaseFormatterInit:
    def test_consoles_created(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = ConcreteFormatter(stdout=stdout, stderr=stderr)
        assert f.console is not None
        assert f.err_console is not None

    def test_processed_events_default(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = ConcreteFormatter(stdout=stdout, stderr=stderr)
        assert f.processed_events == 0


class TestParseJsonLine:
    def test_valid_json(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = ConcreteFormatter(stdout=stdout, stderr=stderr)
        result = f._parse_json_line(json.dumps({"key": "val"}))
        assert result == {"key": "val"}

    def test_empty_string(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = ConcreteFormatter(stdout=stdout, stderr=stderr)
        assert f._parse_json_line("") is None
        assert f._parse_json_line("   \n") is None

    def test_invalid_json_stderr(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = ConcreteFormatter(stdout=stdout, stderr=stderr)
        result = f._parse_json_line("not json at all")
        assert result is None
        assert "not json at all" in stderr.getvalue()


class TestFinish:
    def test_zero_events_returns_1(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = ConcreteFormatter(stdout=stdout, stderr=stderr)
        assert f.finish() == 1
        assert "No events" in stderr.getvalue()

    def test_nonzero_events_returns_0(self, stdout: io.StringIO, stderr: io.StringIO) -> None:
        f = ConcreteFormatter(stdout=stdout, stderr=stderr)
        f.process_line(json.dumps({"x": 1}))
        assert f.finish() == 0
