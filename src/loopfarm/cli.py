from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .runtime.config import LoopfarmFileConfig, ProgramFileConfig, load_config
from .runner import CodexPhaseModel, LoopfarmConfig, run_loop
from .ui import (
    add_output_mode_argument,
    render_rich_help,
    resolve_output_mode,
)


def _print_help(*, output_mode: str) -> None:
    if output_mode == "rich":
        render_rich_help(
            command="loopfarm",
            summary="programmable loop runner",
            usage=(
                "loopfarm [OPTIONS] PROMPT",
                "loopfarm <command> [ARGS]",
            ),
            sections=(
                (
                    "Commands",
                    (
                        (
                            "init",
                            "scaffold .loopfarm config + prompts for a new workspace",
                        ),
                        (
                            "issue",
                            "create, update, and query issue tracker state",
                        ),
                        (
                            "forum",
                            "post/read/search loopfarm forum topics/messages",
                        ),
                        (
                            "programs",
                            "list discovered loop programs and source files",
                        ),
                        (
                            "docs",
                            "list/show built-in docs topics for loopfarm concepts",
                        ),
                        (
                            "sessions",
                            "list/show recent loop sessions and summaries",
                        ),
                        ("history", "alias for `sessions list`"),
                    ),
                ),
                (
                    "Required Config",
                    (
                        (
                            ".loopfarm/loopfarm.toml or .loopfarm/programs/*.toml",
                            "program configuration file(s)",
                        ),
                        (
                            "strict [program] block",
                            "one [program] section per file",
                        ),
                        (
                            "[program].steps",
                            "defines phase IDs and loop order",
                        ),
                        (
                            "phase IDs",
                            "user-defined; pattern: [a-z][a-z0-9_-]*",
                        ),
                    ),
                ),
                (
                    "Options",
                    (
                        (
                            "--program NAME",
                            "program name (required when multiple are configured)",
                        ),
                        ("--project NAME", "override [program].project"),
                        (
                            "--output MODE",
                            "auto|plain|rich (or LOOPFARM_OUTPUT)",
                        ),
                        ("--version", "print installed loopfarm version"),
                        ("-h, --help", "show this help"),
                    ),
                ),
                (
                    "Quick Start",
                    (
                        (
                            "bootstrap",
                            "loopfarm init [--force] [--project NAME]",
                        ),
                        (
                            "run a loop",
                            "loopfarm \"Implement feature X end-to-end\"",
                        ),
                        ("issue triage", "loopfarm issue ready"),
                        ("issue inspect", "loopfarm issue show <id>"),
                        (
                            "issue transition",
                            "loopfarm issue status <id> in_progress",
                        ),
                        ("forum post", "loopfarm forum post <topic> -m \"...\""),
                        ("forum read", "loopfarm forum read <topic>"),
                        ("forum search", "loopfarm forum search \"query\""),
                        ("session list", "loopfarm sessions list"),
                        ("session detail", "loopfarm sessions show <session-id>"),
                        ("docs index", "loopfarm docs list"),
                        ("docs topic", "loopfarm docs show steps-grammar"),
                    ),
                ),
            ),
            examples=(
                (
                    "loopfarm --program implementation \"Ship the CLI UX issue\"",
                    "run one loop pass with an explicit program",
                ),
                (
                    "loopfarm history show <session-id>",
                    "inspect prior session decision and briefings",
                ),
            ),
            docs_tip=(
                "Use `loopfarm docs list` to discover concepts, then "
                "`loopfarm docs show <topic> --output rich` for details."
            ),
            stderr=True,
        )
        return

    stream = sys.stderr
    print("loopfarm  programmable loop runner", file=stream)
    print(file=stream)
    print("usage: loopfarm [OPTIONS] PROMPT", file=stream)
    print("       loopfarm <command> [ARGS]", file=stream)
    print(file=stream)
    print("Commands", file=stream)
    print(
        "  init      scaffold .loopfarm config + prompts for a new workspace",
        file=stream,
    )
    print("  issue     create, update, and query issue tracker state", file=stream)
    print("  forum     post/read/search loopfarm forum topics/messages", file=stream)
    print("  programs  list discovered loop programs and source files", file=stream)
    print("  docs      list/show built-in docs topics for loopfarm concepts", file=stream)
    print("  sessions  list/show recent loop sessions and summaries", file=stream)
    print("  history   alias for `sessions list`", file=stream)
    print(file=stream)
    print("Required Config", file=stream)
    print("  .loopfarm/loopfarm.toml or .loopfarm/programs/*.toml", file=stream)
    print("  each TOML file defines one strict [program] block", file=stream)
    print("  [program].steps defines phase IDs and loop order", file=stream)
    print("  phase IDs are user-defined (pattern: [a-z][a-z0-9_-]*)", file=stream)
    print(file=stream)
    print("Options", file=stream)
    print(
        "  --program NAME   program name (required when multiple are configured)",
        file=stream,
    )
    print("  --project NAME   override [program].project", file=stream)
    print("  --output MODE    auto|plain|rich (or LOOPFARM_OUTPUT)", file=stream)
    print("  --version        print installed loopfarm version", file=stream)
    print("  -h, --help", file=stream)
    print(file=stream)
    print("Quick Start", file=stream)
    print("  bootstrap         loopfarm init [--force] [--project NAME]", file=stream)
    print("  run a loop        loopfarm \"Implement feature X end-to-end\"", file=stream)
    print("  issue triage      loopfarm issue ready", file=stream)
    print("  issue inspect     loopfarm issue show <id>", file=stream)
    print("  issue transition  loopfarm issue status <id> in_progress", file=stream)
    print("  forum post        loopfarm forum post <topic> -m \"...\"", file=stream)
    print("  forum read        loopfarm forum read <topic>", file=stream)
    print("  forum search      loopfarm forum search \"query\"", file=stream)
    print("  session list      loopfarm sessions list", file=stream)
    print("  session detail    loopfarm sessions show <session-id>", file=stream)
    print("  docs index        loopfarm docs list", file=stream)
    print("  docs topic        loopfarm docs show steps-grammar", file=stream)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loopfarm", add_help=False)
    p.add_argument("-h", "--help", action="store_true", default=False)
    p.add_argument("--version", action="store_true", default=False)
    p.add_argument("prompt", nargs=argparse.REMAINDER)
    p.add_argument("--program")
    p.add_argument("--project")
    add_output_mode_argument(p)
    return p


def _format_available_programs(programs: tuple[ProgramFileConfig, ...]) -> str:
    names = sorted({program.name for program in programs})
    return ", ".join(repr(name) for name in names)


def _select_program(
    args: argparse.Namespace, file_cfg: LoopfarmFileConfig
) -> ProgramFileConfig:
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
        if command == "programs":
            from .programs import main as programs_main

            programs_main(sub_argv)
            return
        if command == "docs":
            from .docs_cmd import main as docs_main

            docs_main(sub_argv)
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

    try:
        output_mode = resolve_output_mode(
            args.output,
            is_tty=getattr(sys.stderr, "isatty", lambda: False)(),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)

    if args.help:
        _print_help(output_mode=output_mode)
        raise SystemExit(0)
    if args.version:
        print(__version__)
        raise SystemExit(0)

    prompt = " ".join(args.prompt).strip()
    if not prompt:
        _print_help(output_mode=output_mode)
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
