"""Tests for top-level command dispatch behavior."""

from __future__ import annotations

import pytest

from inshallah.cli import main
from inshallah.dag import DagResult


def test_main_single_token_dispatches_as_run(capsys) -> None:
    """A single unknown token is treated as a run prompt, not an error."""
    # Don't execute real backends during unit tests.
    from unittest.mock import patch

    with patch(
        "inshallah.cli.DagRunner.run",
        return_value=DagResult(status="max_steps_exhausted", steps=0, error=""),
    ):
        with pytest.raises(SystemExit):
            main(["badcommand"])

    rendered = capsys.readouterr().out
    # Should dispatch to cmd_run (creates a root issue), not error recovery
    assert "Root Issue" in rendered
    assert "badcommand" in rendered
