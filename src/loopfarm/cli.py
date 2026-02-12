from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .backends import list_backends
from .loop_plan import parse_loop_plan
from .runner import CodexPhaseModel, LoopfarmConfig, run_loop

_PHASE_CLI_FIELDS = (
    "plan_cli",
    "forward_cli",
    "research_cli",
    "curation_cli",
    "documentation_cli",
    "architecture_cli",
    "backward_cli",
)


@dataclass(frozen=True)
class ModeSpec:
    summary: str
    cli_defaults: dict[str, str | None]
    loop_env: str | None = None
    loop_default: str | None = None
    loop_default_builder: Callable[[argparse.Namespace], str] | None = None
    report_source_phase: str | None = None
    report_target_phases: tuple[str, ...] = ()

    def supports_loop(self) -> bool:
        return self.loop_env is not None

    def default_loop_spec(self, args: argparse.Namespace) -> str | None:
        if self.loop_default_builder is not None:
            return self.loop_default_builder(args)
        return self.loop_default


def _implementation_default_loop(args: argparse.Namespace) -> str:
    default_forward_count = max(1, args.backward_interval)
    return (
        f"planning,forward*{default_forward_count},"
        "documentation,architecture,backward"
    )


_STANDARD_PHASE_DEFAULTS: dict[str, str | None] = {
    "plan_cli": "codex",
    "forward_cli": "codex",
    "research_cli": "codex",
    "curation_cli": "codex",
    "documentation_cli": "gemini",
    "architecture_cli": "codex",
    "backward_cli": "codex",
}


_MODE_SPECS: dict[str, ModeSpec] = {
    "implementation": ModeSpec(
        summary="forward + docs + architecture + backward [dim](main mode)[/dim]",
        cli_defaults=dict(_STANDARD_PHASE_DEFAULTS),
        loop_env="LOOPFARM_IMPLEMENTATION_LOOP",
        loop_default_builder=_implementation_default_loop,
        report_source_phase="forward",
        report_target_phases=("documentation", "architecture", "backward"),
    ),
    "research": ModeSpec(
        summary="research + curation + backward [dim](pre-implementation)[/dim]",
        cli_defaults=dict(_STANDARD_PHASE_DEFAULTS),
        loop_env="LOOPFARM_RESEARCH_LOOP",
        loop_default="planning,research,curation,backward",
    ),
    "writing": ModeSpec(
        summary="kimi forward + codex backward [dim](for prose/docs)[/dim]",
        cli_defaults={
            **_STANDARD_PHASE_DEFAULTS,
            "forward_cli": "kimi",
            "research_cli": None,
            "curation_cli": None,
            "documentation_cli": None,
            "architecture_cli": None,
            "backward_cli": "codex",
        },
    ),
}
_MODE_ORDER = ("implementation", "research", "writing")


def _env(*names: str) -> str | None:
    for name in names:
        v = os.environ.get(name)
        if v:
            return v
    return None


def _print_help() -> None:
    from rich.console import Console
    from rich.table import Table
    from rich.text import Text

    backends = list_backends()
    backend_hint = "|".join(backends) if backends else "claude|codex|gemini|kimi"

    console = Console(stderr=True)

    # Header
    header = Text()
    header.append("loopfarm", style="bold blue")
    header.append("  Loop runner for multi-phase agentic work")
    console.print(header)
    console.print()

    # Usage
    console.print("[dim]usage:[/dim]  loopfarm [OPTIONS] PROMPT")
    console.print()

    # Phase diagram
    console.print("[bold]Phases[/bold]")
    console.print(
        "  [cyan]PLANNING[/cyan] [dim]->[/dim] [green]FORWARD[/green]/[cyan]RESEARCH[/cyan] "
        "[dim]->[/dim] [blue]CURATION[/blue]/[blue]DOCUMENTATION[/blue] "
        "[dim]->[/dim] [yellow]ARCHITECTURE[/yellow] "
        "[dim]->[/dim] [magenta]BACKWARD[/magenta] [dim]->[/dim] [dim](repeat)[/dim]"
    )
    console.print()

    # CLI backend
    t = Table(show_header=False, box=None, padding=(0, 2, 0, 2), expand=False)
    t.add_column(style="green", no_wrap=True)
    t.add_column()
    t.add_row("--claude", "use Claude Code [dim](default)[/dim]")
    t.add_row("--codex", "use Codex")
    t.add_row("--cli NAME", f"set CLI backend explicitly [dim]({backend_hint})[/dim]")
    t.add_row("--model NAME", "override model for all phases")
    console.print("[bold]CLI Backend[/bold]")
    console.print(t)
    console.print()

    # Mode & per-phase
    t = Table(show_header=False, box=None, padding=(0, 2, 0, 2), expand=False)
    t.add_column(style="green", no_wrap=True)
    t.add_column()
    for mode in _MODE_ORDER:
        t.add_row(f"--mode {mode}", _MODE_SPECS[mode].summary)
    t.add_row("--forward-cli NAME", f"CLI for forward phase [dim]({backend_hint})[/dim]")
    t.add_row("--research-cli NAME", f"CLI for research phase [dim]({backend_hint})[/dim]")
    t.add_row("--curation-cli NAME", f"CLI for curation phase [dim]({backend_hint})[/dim]")
    t.add_row(
        "--documentation-cli NAME",
        f"CLI for documentation phase [dim]({backend_hint})[/dim]",
    )
    t.add_row(
        "--architecture-cli NAME",
        f"CLI for architecture phase [dim]({backend_hint})[/dim]",
    )
    t.add_row("--backward-cli NAME", f"CLI for backward phase [dim]({backend_hint})[/dim]")
    console.print("[bold]Mode & Per-Phase Overrides[/bold]")
    console.print(
        "[dim]  Explicit per-phase --*-cli flags override mode defaults.[/dim]"
    )
    console.print(t)
    console.print()

    # Loop control
    t = Table(show_header=False, box=None, padding=(0, 2, 0, 2), expand=False)
    t.add_column(style="green", no_wrap=True)
    t.add_column()
    t.add_row("--skip-plan", "skip the planning phase")
    t.add_row("--backward-interval N", "run backward every N forward passes [dim](default: 1)[/dim]")
    t.add_row(
        "--phase-plan SPEC",
        "mode phase plan [dim](e.g. planning,forward*5,documentation,architecture,backward)[/dim]",
    )
    t.add_row("--loop SPEC", "[dim]legacy alias for --phase-plan[/dim]")
    t.add_row(
        "--project NAME",
        "project name for synth-forum/synth-issue context [dim](default: workshop)[/dim]",
    )
    console.print("[bold]Loop Control[/bold]")
    console.print(t)
    console.print()

    # Examples
    console.print("[bold]Examples[/bold]")
    examples = [
        ('loopfarm "Work on QED issues"', "default (implementation mode)"),
        ('loopfarm --codex "Refactor the allocator"', "codex for all phases"),
        ('loopfarm --mode writing "Document the 2LTT pipeline"', "kimi writes, codex reviews"),
        (
            'loopfarm --mode research --phase-plan "planning,research*3,curation,backward" "Survey runtime architectures"',
            "research + planning preparation loop",
        ),
        (
            'loopfarm --mode implementation --phase-plan "planning,forward*5,documentation,architecture,backward" "Improve QED"',
            "custom implementation loop",
        ),
        (
            'loopfarm --forward-cli codex --documentation-cli gemini --architecture-cli codex --backward-cli codex "Write API docs"',
            "explicit per-phase",
        ),
        ('loopfarm --skip-plan --codex "Fix the failing test"', "skip planning"),
    ]
    for cmd, desc in examples:
        console.print(f"  [white]{cmd}[/white]")
        console.print(f"    [dim]{desc}[/dim]")
    console.print()

    # Env vars
    t = Table(show_header=True, box=None, padding=(0, 2, 0, 2), expand=False)
    t.add_column("Variable", style="yellow", no_wrap=True)
    t.add_column("Description")
    t.add_row("LOOPFARM_CLI", f"default CLI [dim]({backend_hint})[/dim]")
    t.add_row("LOOPFARM_MODEL", "default model override")
    t.add_row("LOOPFARM_PROJECT", "default project name")
    t.add_row("LOOPFARM_BACKWARD_INTERVAL", "default backward interval")
    t.add_row("LOOPFARM_IMPLEMENTATION_LOOP", "default implementation loop spec")
    t.add_row("LOOPFARM_RESEARCH_LOOP", "default research loop spec")
    t.add_row("LOOPFARM_CODE_MODEL", "codex forward model [dim](gpt-5.3-codex)[/dim]")
    t.add_row("LOOPFARM_PLAN_MODEL", "codex planning model [dim](gpt-5.2)[/dim]")
    t.add_row("LOOPFARM_REVIEW_MODEL", "codex backward model [dim](gpt-5.2)[/dim]")
    t.add_row(
        "LOOPFARM_ARCHITECTURE_MODEL",
        "codex architecture model [dim](gpt-5.2)[/dim]",
    )
    t.add_row(
        "LOOPFARM_ARCHITECTURE_REASONING",
        "codex architecture reasoning [dim](xhigh)[/dim]",
    )
    t.add_row(
        "LOOPFARM_DOCUMENTATION_MODEL",
        "gemini documentation model [dim](gemini-3-pro-preview)[/dim]",
    )
    console.print("[bold]Environment Variables[/bold]")
    console.print("[dim]LOOPFARM_* env vars configure CLI defaults.[/dim]")
    console.print(t)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loopfarm", add_help=False)

    backend_choices = list_backends()

    p.add_argument("-h", "--help", action="store_true", default=False)
    p.add_argument("prompt", nargs=argparse.REMAINDER)

    p.add_argument("--claude", action="store_true")
    p.add_argument("--codex", action="store_true")
    p.add_argument("--cli", choices=backend_choices)
    p.add_argument("--model")

    p.add_argument("--mode", choices=list(_MODE_ORDER))
    p.add_argument("--implementation", action="store_true")
    p.add_argument("--research", action="store_true")
    p.add_argument("--plan-cli", choices=backend_choices)
    p.add_argument("--forward-cli", choices=backend_choices)
    p.add_argument("--research-cli", choices=backend_choices)
    p.add_argument("--curation-cli", choices=backend_choices)
    p.add_argument("--documentation-cli", choices=backend_choices)
    p.add_argument("--architecture-cli", choices=backend_choices)
    p.add_argument("--backward-cli", choices=backend_choices)

    p.add_argument("--skip-plan", action="store_true")
    p.add_argument(
        "--backward-interval",
        type=int,
        default=int(_env("LOOPFARM_BACKWARD_INTERVAL") or "1"),
    )
    p.add_argument("--phase-plan")
    p.add_argument("--loop")
    p.add_argument(
        "--project",
        default=_env("LOOPFARM_PROJECT") or "workshop",
    )

    return p


def _resolve_mode(args: argparse.Namespace) -> str:
    flag_mode: str | None = None
    if args.implementation:
        flag_mode = "implementation"
    if args.research:
        if flag_mode and flag_mode != "research":
            print(
                "error: --implementation and --research cannot be used together",
                file=sys.stderr,
            )
            raise SystemExit(2)
        flag_mode = "research"

    if args.mode and flag_mode and args.mode != flag_mode:
        print(
            f"error: --{flag_mode} cannot be combined with --mode {args.mode}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    return args.mode or flag_mode or "implementation"


def _resolve_loop_settings(
    args: argparse.Namespace, mode: str
) -> tuple[bool, tuple[tuple[str, int], ...] | None, str | None, tuple[str, ...]]:
    loop_plan_once = False
    loop_steps: tuple[tuple[str, int], ...] | None = None
    loop_report_source_phase: str | None = None
    loop_report_target_phases: tuple[str, ...] = ()

    mode_spec = _MODE_SPECS[mode]
    if mode_spec.supports_loop():
        default_loop = mode_spec.default_loop_spec(args)
        if not default_loop:
            raise SystemExit(f"missing default loop spec for mode: {mode}")
        loop_env = mode_spec.loop_env
        if loop_env is None:
            raise SystemExit(f"missing loop env for mode: {mode}")
        phase_plan_arg = args.phase_plan or args.loop
        loop_spec = phase_plan_arg or _env(loop_env) or default_loop
        try:
            parsed = parse_loop_plan(loop_spec)
            loop_plan_once, loop_steps = parsed.plan_once, parsed.steps
        except ValueError as exc:
            print(f"error: invalid phase plan: {exc}", file=sys.stderr)
            raise SystemExit(2)
        loop_report_source_phase = mode_spec.report_source_phase
        loop_report_target_phases = mode_spec.report_target_phases
    elif args.loop or args.phase_plan:
        loop_modes = ", ".join(
            f"--mode {name}"
            for name in _MODE_ORDER
            if _MODE_SPECS[name].supports_loop()
        )
        print(
            f"error: --phase-plan/--loop is only valid with {loop_modes}",
            file=sys.stderr,
        )
        raise SystemExit(2)

    return (
        loop_plan_once,
        loop_steps,
        loop_report_source_phase,
        loop_report_target_phases,
    )


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    if args.help:
        _print_help()
        raise SystemExit(0)

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        _print_help()
        raise SystemExit(1)

    cli = _env("LOOPFARM_CLI") or "claude"
    if args.claude:
        cli = "claude"
    if args.codex:
        cli = "codex"
    if args.cli:
        cli = args.cli

    model_override = args.model or _env("LOOPFARM_MODEL")

    mode = _resolve_mode(args)

    phase_clis = dict(_MODE_SPECS[mode].cli_defaults)
    for field in _PHASE_CLI_FIELDS:
        value = getattr(args, field)
        if value is not None:
            phase_clis[field] = value

    (
        loop_plan_once,
        loop_steps,
        loop_report_source_phase,
        loop_report_target_phases,
    ) = _resolve_loop_settings(args, mode)

    code_model = CodexPhaseModel(
        model=_env("LOOPFARM_CODE_MODEL") or "gpt-5.3-codex",
        reasoning=_env("LOOPFARM_CODE_REASONING") or "xhigh",
    )
    plan_model = CodexPhaseModel(
        model=_env("LOOPFARM_PLAN_MODEL") or "gpt-5.2",
        reasoning=_env("LOOPFARM_PLAN_REASONING") or "xhigh",
    )
    review_model = CodexPhaseModel(
        model=_env("LOOPFARM_REVIEW_MODEL") or "gpt-5.2",
        reasoning=_env("LOOPFARM_REVIEW_REASONING") or "xhigh",
    )
    architecture_model = CodexPhaseModel(
        model=_env("LOOPFARM_ARCHITECTURE_MODEL")
        or _env("LOOPFARM_REVIEW_MODEL")
        or "gpt-5.2",
        reasoning=_env(
            "LOOPFARM_ARCHITECTURE_REASONING",
        )
        or _env("LOOPFARM_REVIEW_REASONING")
        or "xhigh",
    )
    documentation_model = (
        _env("LOOPFARM_DOCUMENTATION_MODEL")
        or "gemini-3-pro-preview"
    )

    cfg = LoopfarmConfig(
        repo_root=Path.cwd(),
        cli=cli,
        model_override=model_override,
        skip_plan=bool(args.skip_plan),
        project=str(args.project),
        prompt=prompt,
        code_model=code_model,
        plan_model=plan_model,
        review_model=review_model,
        architecture_model=architecture_model,
        documentation_model=documentation_model,
        backward_interval=max(1, args.backward_interval),
        loop_plan_once=loop_plan_once,
        loop_steps=loop_steps,
        loop_report_source_phase=loop_report_source_phase,
        loop_report_target_phases=loop_report_target_phases,
        plan_cli=phase_clis["plan_cli"],
        forward_cli=phase_clis["forward_cli"],
        research_cli=phase_clis["research_cli"],
        curation_cli=phase_clis["curation_cli"],
        documentation_cli=phase_clis["documentation_cli"],
        architecture_cli=phase_clis["architecture_cli"],
        backward_cli=phase_clis["backward_cli"],
        mode=mode,
    )

    raise SystemExit(run_loop(cfg))


if __name__ == "__main__":
    main()
