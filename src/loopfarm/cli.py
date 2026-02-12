from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .runtime.config import LoopfarmFileConfig, ProgramFileConfig, load_config
from .runner import CodexPhaseModel, LoopfarmConfig, run_loop


def _print_help() -> None:
    from rich.console import Console

    console = Console(stderr=True)
    console.print("[bold blue]loopfarm[/bold blue]  programmable loop runner")
    console.print()
    console.print("[dim]usage:[/dim] loopfarm [OPTIONS] PROMPT")
    console.print("[dim]       [/dim] loopfarm init|forum|issue|monitor ...")
    console.print()
    console.print("[bold]Required Config[/bold]")
    console.print("  .loopfarm/loopfarm.toml with a strict [program] block")
    console.print()
    console.print("[bold]Options[/bold]")
    console.print("  --program NAME   program name (must match [program].name)")
    console.print("  --project NAME   override [program].project")
    console.print("  -h, --help")
    console.print()
    console.print("[bold]Bootstrap[/bold]")
    console.print("  loopfarm init [--force] [--project NAME]")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loopfarm", add_help=False)
    p.add_argument("-h", "--help", action="store_true", default=False)
    p.add_argument("prompt", nargs=argparse.REMAINDER)
    p.add_argument("--program")
    p.add_argument("--project")
    return p


def _select_program(args: argparse.Namespace, file_cfg: LoopfarmFileConfig) -> ProgramFileConfig:
    program = file_cfg.program
    if program is None:
        print(
            "error: missing or invalid .loopfarm/loopfarm.toml [program] configuration",
            file=sys.stderr,
        )
        raise SystemExit(2)

    requested = (args.program or "").strip()
    if requested and requested != program.name:
        print(
            f"error: program {requested!r} not found (configured: {program.name!r})",
            file=sys.stderr,
        )
        raise SystemExit(2)

    return program


def _required_phases(program: ProgramFileConfig) -> list[str]:
    phases: list[str] = []
    if program.loop_plan_once:
        phases.append("planning")
    for phase, _ in program.loop_steps:
        if phase not in phases:
            phases.append(phase)
    return phases


def _resolve_phase_overrides(
    *,
    program: ProgramFileConfig,
) -> tuple[
    tuple[tuple[str, str], ...],
    tuple[tuple[str, str], ...],
    tuple[tuple[str, tuple[str, ...]], ...],
    tuple[tuple[str, CodexPhaseModel], ...],
]:
    required_phases = _required_phases(program)

    phase_cli_overrides: list[tuple[str, str]] = []
    phase_prompt_overrides: list[tuple[str, str]] = []
    phase_injections: list[tuple[str, tuple[str, ...]]] = []
    phase_models: list[tuple[str, CodexPhaseModel]] = []

    for phase in required_phases:
        phase_cfg = program.phases.get(phase)
        if phase_cfg is None:
            print(
                f"error: missing [program.phase.{phase}] configuration",
                file=sys.stderr,
            )
            raise SystemExit(2)

        prompt_path = (phase_cfg.prompt or "").strip()
        if not prompt_path:
            print(
                f"error: missing prompt for phase {phase!r} in [program.phase.{phase}]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        phase_prompt_overrides.append((phase, prompt_path))

        phase_cli = (phase_cfg.cli or "").strip()
        if not phase_cli:
            print(
                f"error: missing cli for phase {phase!r} in [program.phase.{phase}]",
                file=sys.stderr,
            )
            raise SystemExit(2)
        phase_cli_overrides.append((phase, phase_cli))

        if phase_cfg.inject:
            phase_injections.append((phase, phase_cfg.inject))

        phase_model = (phase_cfg.model or "").strip()
        if phase_cli != "kimi" and not phase_model:
            print(
                f"error: missing model for phase {phase!r} in [program.phase.{phase}]",
                file=sys.stderr,
            )
            raise SystemExit(2)

        if phase_model:
            reasoning = (phase_cfg.reasoning or "xhigh").strip() or "xhigh"
            phase_models.append((phase, CodexPhaseModel(phase_model, reasoning)))

    return (
        tuple(phase_cli_overrides),
        tuple(phase_prompt_overrides),
        tuple(phase_injections),
        tuple(phase_models),
    )


def main(argv: list[str] | None = None) -> None:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]

    if raw_argv:
        command = raw_argv[0]
        sub_argv = raw_argv[1:]
        if command == "forum":
            from .forum import main as forum_main

            forum_main(sub_argv)
            return
        if command == "init":
            from .init_cmd import main as init_main

            init_main(sub_argv)
            return
        if command == "issue":
            from .issue import main as issue_main

            issue_main(sub_argv)
            return
        if command == "monitor":
            from .monitor import main as monitor_main

            monitor_main(sub_argv)
            return

    args = _build_parser().parse_args(raw_argv)

    if args.help:
        _print_help()
        raise SystemExit(0)

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        _print_help()
        raise SystemExit(1)

    repo_root = Path.cwd()
    file_cfg = load_config(repo_root)
    program = _select_program(args, file_cfg)

    (
        phase_cli_overrides,
        phase_prompt_overrides,
        phase_injections,
        phase_models,
    ) = _resolve_phase_overrides(program=program)

    project = args.project or program.project or repo_root.name

    cfg = LoopfarmConfig(
        repo_root=repo_root,
        project=str(project),
        prompt=prompt,
        loop_plan_once=program.loop_plan_once,
        loop_steps=program.loop_steps,
        termination_phase=program.termination_phase,
        loop_report_source_phase=program.report_source_phase,
        loop_report_target_phases=program.report_target_phases,
        phase_models=phase_models,
        phase_cli_overrides=phase_cli_overrides,
        phase_prompt_overrides=phase_prompt_overrides,
        phase_injections=phase_injections,
    )

    raise SystemExit(run_loop(cfg))


if __name__ == "__main__":
    main()
