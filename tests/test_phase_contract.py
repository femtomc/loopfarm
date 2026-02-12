from __future__ import annotations

import pytest

from loopfarm.phase_contract import (
    build_state_machine,
    is_termination_gate,
    phase_contract,
)


def test_build_state_machine_validates_basic_shape() -> None:
    machine = build_state_machine(
        planning_once=True,
        loop_steps=(
            ("forward", 2),
            ("documentation", 1),
            ("architecture", 1),
            ("backward", 1),
        ),
    )
    assert machine.planning_once is True
    assert machine.termination_phase == "backward"
    assert machine.loop_steps[0] == ("forward", 2)


def test_build_state_machine_requires_backward_phase() -> None:
    with pytest.raises(ValueError, match="must include backward"):
        build_state_machine(
            planning_once=True,
            loop_steps=(("forward", 1), ("documentation", 1)),
        )


def test_phase_contract_unknown_phase_errors() -> None:
    with pytest.raises(ValueError, match="unknown phase contract"):
        phase_contract("unknown")


def test_backward_is_sole_termination_gate() -> None:
    assert is_termination_gate("backward") is True
    assert is_termination_gate("forward") is False
    assert is_termination_gate("documentation") is False
    assert is_termination_gate("architecture") is False

