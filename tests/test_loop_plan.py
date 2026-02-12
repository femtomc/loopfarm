from __future__ import annotations

import pytest

from loopfarm.loop_plan import LoopPlan, parse_loop_plan


def test_parse_loop_plan_canonical_syntax() -> None:
    parsed = parse_loop_plan(
        "planning,forward*5,documentation,architecture,backward"
    )
    assert parsed == LoopPlan(
        plan_once=True,
        steps=(
            ("forward", 5),
            ("documentation", 1),
            ("architecture", 1),
            ("backward", 1),
        ),
    )


def test_parse_loop_plan_legacy_repeat_syntaxes() -> None:
    parsed = parse_loop_plan("plan,fwd5,docs,perf,review")
    assert parsed.plan_once is True
    assert parsed.steps == (
        ("forward", 5),
        ("documentation", 1),
        ("architecture", 1),
        ("backward", 1),
    )

    parsed = parse_loop_plan("plan,discovery:3,curate,replan")
    assert parsed.steps == (("research", 3), ("curation", 1), ("backward", 1))


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        ("", "phase plan cannot be empty"),
        ("planning", "phase plan must include at least one loop phase"),
        ("forward", "phase plan must include a backward phase"),
        ("forward,planning,backward", "planning may only appear at the start"),
        ("planning*2,forward,backward", "repeat counts are not supported for planning"),
        ("forward,backward*2", "repeat counts are not supported for backward"),
        ("unknown,backward", "unknown phase in plan"),
    ],
)
def test_parse_loop_plan_validation_errors(spec: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_loop_plan(spec)

