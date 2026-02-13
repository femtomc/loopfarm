from __future__ import annotations

import pytest

from loopfarm import cli
from loopfarm.ui import OUTPUT_ENV_VAR


def test_main_help_rich_includes_quick_start_and_docs(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(OUTPUT_ENV_VAR, "rich")
    monkeypatch.setenv("COLUMNS", "200")

    with pytest.raises(SystemExit) as raised:
        cli.main(["--help"])

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert raised.value.code == 0
    assert "Quick Start" in out
    assert "Prompt Mode" in out
    assert "fallback rule" in out
    assert "loopfarm issue orchestrate-run --root <id>" in out
    assert "roles (internal)" in out


@pytest.mark.parametrize(
    ("argv", "needles"),
    [
        (
            ["issue", "--help"],
            ("loopfarm issue", "Quick Start", "loopfarm issue ready"),
        ),
        (
            ["docs", "--help"],
            ("loopfarm docs", "Topics", "issue-dag-orchestration"),
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
            ["roles", "--help"],
            (
                "loopfarm roles",
                "Quick Start",
                "loopfarm roles list",
                "assign",
            ),
        ),
        (
            ["init", "--help"],
            ("loopfarm init", "Generated Files", ".loopfarm/orchestrator.md"),
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
    monkeypatch.setenv("COLUMNS", "200")

    with pytest.raises(SystemExit) as raised:
        cli.main(argv)

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert raised.value.code == 0
    for needle in needles:
        assert needle in out


def test_issue_help_plain_has_sections_without_ansi(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv(OUTPUT_ENV_VAR, "plain")

    with pytest.raises(SystemExit) as raised:
        cli.main(["issue", "--help"])

    captured = capsys.readouterr()
    out = captured.out + captured.err
    assert raised.value.code == 0
    assert "loopfarm issue" in out
    assert "Quick Start" in out
    assert "orchestrate-run --root <id>" in out
    assert "\x1b[" not in out


@pytest.mark.parametrize(
    ("argv", "needles"),
    [
        (
            ["--help"],
            (
                "Primary Workflows",
                "prompt → root issue → orchestrate",
                'loopfarm "<prompt>"',
                "direct DAG operations",
            ),
        ),
        (
            ["issue", "--help"],
            (
                "Primary Workflow",
                "orchestrate-run --root <id>",
                "loopfarm issue ready",
            ),
        ),
        (
            ["init", "--help"],
            (
                "Generated Files",
                ".loopfarm/orchestrator.md",
                ".loopfarm/roles/worker.md",
            ),
        ),
        (
            ["roles", "--help"],
            (
                "Commands (Internal)",
                "loopfarm roles list",
                "node.team",
            ),
        ),
        (
            ["docs", "--help"],
            (
                "Topics",
                "issue-dag-orchestration",
                "loopfarm docs show dag",
            ),
        ),
    ],
)
def test_help_plain_and_rich_share_core_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
    needles: tuple[str, ...],
) -> None:
    monkeypatch.setenv(OUTPUT_ENV_VAR, "plain")
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    captured = capsys.readouterr()
    plain = captured.out + captured.err
    assert raised.value.code == 0
    assert "\x1b[" not in plain

    monkeypatch.setenv(OUTPUT_ENV_VAR, "rich")
    monkeypatch.setenv("COLUMNS", "200")
    with pytest.raises(SystemExit) as raised:
        cli.main(argv)
    captured = capsys.readouterr()
    rich = captured.out + captured.err
    assert raised.value.code == 0

    for needle in needles:
        assert needle in plain
        assert needle in rich
