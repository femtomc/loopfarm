"""Tests for utility / pure functions in format_stream."""

from __future__ import annotations

from pathlib import Path

from loopfarm.format_stream import (
    _inline_text,
    _shorten_path,
    _shorten_shell_command,
    _summarize_tool_data,
    _summarize_value,
    _trim_lines,
    _trim_text,
    _truncate_text,
)


# -- _shorten_path -----------------------------------------------------------


class TestShortenPath:
    def test_relative_to_root(self, tmp_path: Path) -> None:
        f = tmp_path / "a" / "b.txt"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.touch()
        assert _shorten_path(str(f), tmp_path) == "a/b.txt"

    def test_no_root(self) -> None:
        assert _shorten_path("/foo/bar.txt", None) == "/foo/bar.txt"

    def test_unresolvable(self, tmp_path: Path) -> None:
        result = _shorten_path("/nonexistent/xyz.txt", tmp_path)
        assert "xyz.txt" in result


# -- _truncate_text ----------------------------------------------------------


class TestTruncateText:
    def test_within_limit(self) -> None:
        assert _truncate_text("hello", 10) == "hello"

    def test_over_limit(self) -> None:
        result = _truncate_text("hello world", 6)
        assert len(result) == 6
        assert result.endswith("…")

    def test_zero(self) -> None:
        assert _truncate_text("hello", 0) == ""

    def test_one(self) -> None:
        assert _truncate_text("hello", 1) == "…"


# -- _inline_text ------------------------------------------------------------


class TestInlineText:
    def test_newlines_stripped(self) -> None:
        assert "\\n" in _inline_text("a\nb", 100)

    def test_truncated(self) -> None:
        result = _inline_text("a" * 200, 10)
        assert len(result) == 10


# -- _shorten_shell_command --------------------------------------------------


class TestShortenShellCommand:
    def test_zsh_lc(self) -> None:
        result = _shorten_shell_command('zsh -lc "echo hello"')
        assert result == "echo hello"

    def test_bash_lc(self) -> None:
        result = _shorten_shell_command('bash -lc "ls -la"')
        assert result == "ls -la"

    def test_cd_strip(self) -> None:
        result = _shorten_shell_command("cd /tmp && make build")
        assert result == "make build"

    def test_empty(self) -> None:
        assert _shorten_shell_command("") == ""


# -- _summarize_value --------------------------------------------------------


class TestSummarizeValue:
    def test_string(self) -> None:
        result = _summarize_value("hello", key="name", max_len=80)
        assert result == "hello"

    def test_dict(self) -> None:
        result = _summarize_value({"a": 1, "b": 2}, key=None, max_len=80)
        assert result == "{2 keys}"

    def test_list(self) -> None:
        result = _summarize_value([1, 2, 3], key=None, max_len=80)
        assert result == "[3 items]"

    def test_none(self) -> None:
        assert _summarize_value(None, key=None, max_len=80) == "null"

    def test_bulky_key(self) -> None:
        result = _summarize_value("x" * 1000, key="content", max_len=80)
        assert "1000 chars" in result


# -- _summarize_tool_data ----------------------------------------------------


class TestSummarizeToolData:
    def test_dict(self) -> None:
        result = _summarize_tool_data({"a": "b"})
        assert "a=" in result

    def test_non_dict(self) -> None:
        result = _summarize_tool_data("hello")
        assert result == "hello"


# -- _trim_lines -------------------------------------------------------------


class TestTrimLines:
    def test_under_limit(self) -> None:
        text = "a\nb\nc"
        result, trimmed = _trim_lines(text, max_lines=5, tail=False)
        assert result == text
        assert trimmed is False

    def test_over_limit_head(self) -> None:
        text = "a\nb\nc\nd\ne"
        result, trimmed = _trim_lines(text, max_lines=2, tail=False)
        assert trimmed is True
        assert result.startswith("a\nb")

    def test_over_limit_tail(self) -> None:
        text = "a\nb\nc\nd\ne"
        result, trimmed = _trim_lines(text, max_lines=2, tail=True)
        assert trimmed is True
        assert "d\ne" in result


# -- _trim_text --------------------------------------------------------------


class TestTrimText:
    def test_by_chars(self) -> None:
        text = "a" * 100
        result, trimmed = _trim_text(text, max_lines=1000, max_chars=10, tail=False)
        assert trimmed is True
        assert len(result) <= 10

    def test_by_lines(self) -> None:
        text = "\n".join(str(i) for i in range(100))
        result, trimmed = _trim_text(text, max_lines=5, max_chars=None, tail=False)
        assert trimmed is True
