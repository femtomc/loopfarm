"""Tests for the main() entry point."""

from __future__ import annotations

import io
import json

import pytest

from loopfarm.format_stream import main


def _lines(*objs: dict) -> io.StringIO:
    return io.StringIO("\n".join(json.dumps(o) for o in objs) + "\n")


def _run_main(argv: list[str], stdin: io.StringIO, *, expect_code: int = 0) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(argv=argv, stdin=stdin)
    assert exc_info.value.code == expect_code


class TestAutoDetectClaude:
    def test_stream_event(self) -> None:
        inp = _lines(
            {"type": "stream_event", "event": {"type": "content_block_start", "content_block": {"type": "text"}}},
            {"type": "stream_event", "event": {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "hi"}}},
            {"type": "stream_event", "event": {"type": "content_block_stop"}},
        )
        _run_main([], inp)


class TestAutoDetectCodex:
    def test_thread_started(self) -> None:
        inp = _lines(
            {"type": "thread.started", "thread_id": "t1"},
            {"type": "turn.started"},
            {"type": "turn.completed"},
        )
        _run_main([], inp)


class TestAutoDetectKimi:
    def test_role_key(self) -> None:
        inp = _lines(
            {"role": "assistant", "content": [{"type": "text", "text": "hi"}]},
        )
        _run_main([], inp)


class TestForcedCli:
    def test_forced_claude(self) -> None:
        inp = _lines(
            {"type": "stream_event", "event": {"type": "message_stop"}},
        )
        _run_main(["--cli", "claude"], inp)

    def test_forced_codex(self) -> None:
        inp = _lines({"type": "thread.started", "thread_id": "x"})
        _run_main(["--cli", "codex"], inp)

    def test_forced_kimi(self) -> None:
        inp = _lines({"role": "assistant", "content": ["hi"]})
        _run_main(["--cli", "kimi"], inp)


class TestEmptyStdin:
    def test_empty_exits_1(self) -> None:
        _run_main([], io.StringIO(""), expect_code=1)
