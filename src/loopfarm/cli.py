from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .runtime.config import LoopfarmFileConfig, ProgramFileConfig, load_config
from .runner import CodexPhaseModel, LoopfarmConfig, run_loop


def _print_help() -> None:
    from rich.console import Console

    console = Console(stderr=True)
    console.print("[bold blue]loopfarm[/bold blue]  programmable loop runner")
    console.print()
    console.print("[dim]usage:[/dim] loopfarm [OPTIONS] PROMPT")
    console.print("[dim]       [/dim] loopfarm <command> [ARGS]")
    console.print()
    console.print("[bold]Commands[/bold]")
    console.print("  init      scaffold .loopfarm config + prompts for a new workspace")
    console.print("  issue     create, update, and query issue tracker state")
    console.print("  forum     post/read/search loopfarm forum topics/messages")
    console.print("  sessions  list/show recent loop sessions and summaries")
    console.print("  history   alias for `sessions list`")
    console.print()
    console.print("[bold]Required Config[/bold]")
    console.print(
        "  .loopfarm/loopfarm.toml or .loopfarm/programs/*.toml",
        markup=False,
    )
    console.print("  each TOML file defines one strict [program] block", markup=False)
    console.print("  [program].steps defines phase IDs and loop order", markup=False)
    console.print("  phase IDs are user-defined (pattern: [a-z][a-z0-9_-]*)", markup=False)
    console.print()
    console.print("[bold]Options[/bold]")
    console.print(
        "  --program NAME   program name (required when multiple are configured)",
        markup=False,
    )
    console.print("  --project NAME   override [program].project", markup=False)
    console.print("  --version        print installed loopfarm version")
    console.print("  -h, --help")
    console.print()
    console.print("[bold]Bootstrap[/bold]")
    console.print("  loopfarm init [--force] [--project NAME]")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loopfarm", add_help=False)
    p.add_argument("-h", "--help", action="store_true", default=False)
    p.add_argument("--version", action="store_true", default=False)
    p.add_argument("prompt", nargs=argparse.REMAINDER)
    p.add_argument("--program")
    p.add_argument("--project")
    return p


def _format_available_programs(programs: tuple[ProgramFileConfig, ...]) -> str:
    names = sorted({program.name for program in programs})
    return ", ".join(repr(name) for name in names)


def _select_program(args: argparse.Namespace, file_cfg: LoopfarmFileConfig) -> ProgramFileConfig:
    if file_cfg.error is not None:
        print(f"error: {file_cfg.error}", file=sys.stderr)
        raise SystemExit(2)

    programs: tuple[ProgramFileConfig, ...]
    if file_cfg.programs:
        programs = file_cfg.programs
    elif file_cfg.program is not None:
        programs = (file_cfg.program,)
    else:
        programs = ()

    if not programs:
        message = (
            "missing or invalid .loopfarm/loopfarm.toml or .loopfarm/programs/*.toml "
            "[program] configuration"
        )
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(2)

    requested = (args.program or "").strip()
    if requested:
        for program in programs:
            if requested == program.name:
                return program
        print(
            f"error: program {requested!r} not found (available: {_format_available_programs(programs)})",
            file=sys.stderr,
        )
        raise SystemExit(2)

    if len(programs) == 1:
        return programs[0]

    print(
        "error: multiple programs available; pass --program NAME "
        f"(available: {_format_available_programs(programs)})",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _required_phases(program: ProgramFileConfig) -> list[str]:
    phases: list[str] = []
    for phase, _ in program.loop_steps:
        if phase not in phases:
            phases.append(phase)
    return phases


def _resolve_phase_overrides(
    *,
    program: ProgramFileConfig,
    repo_root: Path,
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

        phase_cli = (phase_cfg.cli or "").strip()
        if not phase_cli:
            print(
                f"error: missing cli for phase {phase!r} in [program.phase.{phase}]",
                file=sys.stderr,
            )
            raise SystemExit(2)

        phase_model = (phase_cfg.model or "").strip()
        if phase_cli != "kimi" and not phase_model:
            print(
                f"error: missing model for phase {phase!r} in [program.phase.{phase}]",
                file=sys.stderr,
            )
            raise SystemExit(2)

        prompt_file = Path(prompt_path)
        if not prompt_file.is_absolute():
            prompt_file = repo_root / prompt_file
        if not prompt_file.exists() or not prompt_file.is_file():
            print(
                f"error: prompt file not found: {prompt_path} (phase: {phase})",
                file=sys.stderr,
            )
            raise SystemExit(2)
        phase_prompt_overrides.append((phase, prompt_path))
        phase_cli_overrides.append((phase, phase_cli))

        if phase_cfg.inject:
            phase_injections.append((phase, phase_cfg.inject))

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
        if command == "sessions":
            from .sessions import main as sessions_main

            sessions_main(sub_argv or ["list"], prog="loopfarm sessions")
            return
        if command == "history":
            from .sessions import main as sessions_main

            if sub_argv and sub_argv[0] in {"-h", "--help"}:
                sessions_main(["--help"], prog="loopfarm history")
                return
            if sub_argv and sub_argv[0] in {"list", "show"}:
                sessions_main(sub_argv, prog="loopfarm history")
            else:
                sessions_main(["list", *sub_argv], prog="loopfarm history")
            return

    args = _build_parser().parse_args(raw_argv)

    if args.help:
        _print_help()
        raise SystemExit(0)
    if args.version:
        print(__version__)
        raise SystemExit(0)

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        _print_help()
        raise SystemExit(0)

    repo_root = Path.cwd()
    file_cfg = load_config(repo_root)
    program = _select_program(args, file_cfg)

    (
        phase_cli_overrides,
        phase_prompt_overrides,
        phase_injections,
        phase_models,
    ) = _resolve_phase_overrides(program=program, repo_root=repo_root)

    project = args.project or program.project or repo_root.name

    cfg = LoopfarmConfig(
        repo_root=repo_root,
        project=str(project),
        prompt=prompt,
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
