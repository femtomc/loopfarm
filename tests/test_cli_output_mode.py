from __future__ import annotations

import pytest

from loopfarm.ui import resolve_output_mode


def test_resolve_output_mode_defaults_to_plain_without_tty() -> None:
    mode = resolve_output_mode(is_tty=False)
    assert mode == "plain"


def test_resolve_output_mode_auto_uses_tty_for_rich() -> None:
    mode = resolve_output_mode(is_tty=True)
    assert mode == "rich"


def test_resolve_output_mode_explicit_choice_applies() -> None:
    mode = resolve_output_mode("rich", is_tty=False)
    assert mode == "rich"


def test_resolve_output_mode_flag_uses_requested_value() -> None:
    mode = resolve_output_mode("plain", is_tty=True)
    assert mode == "plain"


def test_resolve_output_mode_rejects_invalid_flag_value() -> None:
    with pytest.raises(ValueError):
        resolve_output_mode("invalid", is_tty=True)
