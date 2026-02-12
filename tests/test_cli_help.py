from __future__ import annotations

import pytest

from loopfarm import cli
from loopfarm.ui import OUTPUT_ENV_VAR


def test_main_help_rich_includes_quick_start_and_docs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(OUTPUT_ENV_VAR, "rich")

    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert raised.value.code == 0
    assert "Quick Start" in out
    assert "loopfarm issue ready" in out
    assert "loopfarm forum search" in out
    assert "loopfarm sessions show <session-id>" in out
    assert "loopfarm docs show steps-grammar" in out


@pytest.mark.parametrize(
    ("argv", "needles"),
    [
        (
            ["issue", "--help"],
            ("loopfarm issue", "Quick Start", "loopfarm issue ready"),
        ),
        (
            ["forum", "--help"],
            ("loopfarm forum", "Topic Patterns", "loopfarm forum read"),
        ),
        (
            ["sessions", "--help"],
            ("loopfarm sessions", "Quick Start", "show <session-id>"),
        ),
        (
            ["history", "--help"],
            ("loopfarm history", "Quick Start", "loopfarm history show <session-id>"),
        ),
        (
            ["programs", "--help"],
            (
                "loopfarm programs",
                "Quick Start",
                "loopfarm programs list --json",
                "show <name>",
            ),
        ),
        (
            ["init", "--help"],
            ("loopfarm init", "Generated Files", ".loopfarm/loopfarm.toml"),
        ),
    ],
)
def test_command_help_rich_has_consistent_sections(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    needles: tuple[str, ...],
) -> None:
    monkeypatch.setenv(OUTPUT_ENV_VAR, "rich")

    with pytest.raises(SystemExit) as raised:
        cli.main(argv)

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert raised.value.code == 0
    for needle in needles:
        assert needle in out


def test_issue_help_plain_uses_argparse_without_ansi(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.delenv(OUTPUT_ENV_VAR, raising=False)

    with pytest.raises(SystemExit) as raised:
        cli.main(["issue", "--help"])

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert raised.value.code == 0
    assert "usage: loopfarm issue" in out
    assert "\x1b[" not in out
