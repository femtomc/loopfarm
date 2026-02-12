from __future__ import annotations

import pytest

from loopfarm.ui import OUTPUT_ENV_VAR, resolve_output_mode


def test_resolve_output_mode_defaults_to_plain_without_tty() -> None:
    mode = resolve_output_mode(env={}, is_tty=False)
    assert mode == "plain"


def test_resolve_output_mode_auto_uses_tty_for_rich() -> None:
    mode = resolve_output_mode(env={}, is_tty=True)
    assert mode == "rich"


def test_resolve_output_mode_uses_env_when_flag_missing() -> None:
    mode = resolve_output_mode(env={OUTPUT_ENV_VAR: "rich"}, is_tty=False)
    assert mode == "rich"


def test_resolve_output_mode_flag_overrides_env() -> None:
    mode = resolve_output_mode(
        "plain",
        env={OUTPUT_ENV_VAR: "rich"},
        is_tty=True,
    )
    assert mode == "plain"


def test_resolve_output_mode_rejects_invalid_env_value() -> None:
    with pytest.raises(ValueError):
        resolve_output_mode(env={OUTPUT_ENV_VAR: "invalid"}, is_tty=True)
