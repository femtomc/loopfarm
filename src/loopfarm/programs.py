from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .runtime.config import (
    LoopfarmFileConfig,
    ProgramFileConfig,
    ProgramPhaseFileConfig,
    load_config,
)
from .ui import (
    add_output_mode_argument,
    make_console,
    render_panel,
    render_rich_help,
    render_table,
    resolve_output_mode,
)

_MISSING_CONFIG_MESSAGE = (
    "missing or invalid .loopfarm/loopfarm.toml or .loopfarm/programs/*.toml "
    "[program] configuration"
)


def _configured_programs(file_cfg: LoopfarmFileConfig) -> tuple[ProgramFileConfig, ...]:
    if file_cfg.programs:
        return file_cfg.programs
    if file_cfg.program is not None:
        return (file_cfg.program,)
    return ()


@dataclass(frozen=True)
class ProgramRow:
    name: str
    path: str
    project: str
    steps: str
    termination_phase: str


@dataclass(frozen=True)
class LoopStepRow:
    index: int
    phase: str
    repeat: int


@dataclass(frozen=True)
class ProgramPhaseRow:
    phase: str
    in_steps: bool
    configured: bool
    cli: str | None
    model: str | None
    reasoning: str | None
    prompt: str | None
    inject: tuple[str, ...]


@dataclass(frozen=True)
class ProgramDetail:
    name: str
    path: str
    project: str
    steps: str
    loop_steps: tuple[LoopStepRow, ...]
    termination_phase: str
    report_source_phase: str | None
    report_target_phases: tuple[str, ...]
    phases: tuple[ProgramPhaseRow, ...]
    missing_phase_configs: tuple[str, ...]
    extra_phase_configs: tuple[str, ...]


def _format_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except Exception:
        return str(path)


def _format_steps(program: ProgramFileConfig) -> str:
    tokens: list[str] = []
    for phase, repeat in program.loop_steps:
        if repeat == 1:
            tokens.append(phase)
        else:
            tokens.append(f"{phase}*{repeat}")
    return " -> ".join(tokens)


def _program_rows(file_cfg: LoopfarmFileConfig) -> list[ProgramRow]:
    rows: list[ProgramRow] = []
    for program in _configured_programs(file_cfg):
        source_path = program.source_path or file_cfg.path
        rows.append(
            ProgramRow(
                name=program.name,
                path=_format_path(source_path, file_cfg.repo_root),
                project=str(program.project or "-"),
                steps=_format_steps(program),
                termination_phase=program.termination_phase,
            )
        )
    rows.sort(key=lambda row: row.name)
    return rows


def _load_config_or_exit(repo_root: Path) -> LoopfarmFileConfig:
    file_cfg = load_config(repo_root)
    if file_cfg.error is not None:
        print(f"error: {file_cfg.error}", file=sys.stderr)
        raise SystemExit(2)
    if not _configured_programs(file_cfg):
        print(f"error: {_MISSING_CONFIG_MESSAGE}", file=sys.stderr)
        raise SystemExit(2)
    return file_cfg


def _load_program_rows(repo_root: Path) -> list[ProgramRow]:
    file_cfg = _load_config_or_exit(repo_root)
    return _program_rows(file_cfg)


def _select_program(
    file_cfg: LoopfarmFileConfig,
    requested_name: str,
) -> ProgramFileConfig:
    requested = requested_name.strip()
    programs = _configured_programs(file_cfg)
    for program in programs:
        if requested == program.name:
            return program

    available = ", ".join(
        repr(program.name) for program in sorted(programs, key=lambda program: program.name)
    )
    print(
        f"error: program {requested_name!r} not found (available: {available})",
        file=sys.stderr,
    )
    raise SystemExit(2)


def _loop_phase_order(program: ProgramFileConfig) -> tuple[str, ...]:
    out: list[str] = []
    for phase, _ in program.loop_steps:
        if phase not in out:
            out.append(phase)
    return tuple(out)


def _phase_row(
    *,
    phase: str,
    in_steps: bool,
    phase_cfg: ProgramPhaseFileConfig | None,
) -> ProgramPhaseRow:
    if phase_cfg is None:
        return ProgramPhaseRow(
            phase=phase,
            in_steps=in_steps,
            configured=False,
            cli=None,
            model=None,
            reasoning=None,
            prompt=None,
            inject=(),
        )

    return ProgramPhaseRow(
        phase=phase,
        in_steps=in_steps,
        configured=True,
        cli=phase_cfg.cli,
        model=phase_cfg.model,
        reasoning=phase_cfg.reasoning,
        prompt=phase_cfg.prompt,
        inject=phase_cfg.inject,
    )


def _program_detail(program: ProgramFileConfig, *, file_cfg: LoopfarmFileConfig) -> ProgramDetail:
    source_path = program.source_path or file_cfg.path
    loop_phase_order = _loop_phase_order(program)
    loop_phase_set = set(loop_phase_order)

    phase_rows: list[ProgramPhaseRow] = []
    missing_phase_configs: list[str] = []
    for phase in loop_phase_order:
        phase_cfg = program.phases.get(phase)
        phase_rows.append(_phase_row(phase=phase, in_steps=True, phase_cfg=phase_cfg))
        if phase_cfg is None:
            missing_phase_configs.append(phase)

    extra_phase_configs = sorted(set(program.phases) - loop_phase_set)
    for phase in extra_phase_configs:
        phase_rows.append(
            _phase_row(
                phase=phase,
                in_steps=False,
                phase_cfg=program.phases.get(phase),
            )
        )

    loop_steps = tuple(
        LoopStepRow(index=index, phase=phase, repeat=repeat)
        for index, (phase, repeat) in enumerate(program.loop_steps, start=1)
    )
    return ProgramDetail(
        name=program.name,
        path=_format_path(source_path, file_cfg.repo_root),
        project=str(program.project or "-"),
        steps=_format_steps(program),
        loop_steps=loop_steps,
        termination_phase=program.termination_phase,
        report_source_phase=program.report_source_phase,
        report_target_phases=program.report_target_phases,
        phases=tuple(phase_rows),
        missing_phase_configs=tuple(missing_phase_configs),
        extra_phase_configs=tuple(extra_phase_configs),
    )


def _load_program_detail(repo_root: Path, requested_name: str) -> ProgramDetail:
    file_cfg = _load_config_or_exit(repo_root)
    program = _select_program(file_cfg, requested_name)
    return _program_detail(program, file_cfg=file_cfg)


def _emit_list_text(rows: list[ProgramRow]) -> None:
    for row in rows:
        print(f"{row.name}\t{row.path}")


def _emit_list_json(rows: list[ProgramRow]) -> None:
    payload = [{"name": row.name, "path": row.path} for row in rows]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _emit_list_rich(rows: list[ProgramRow]) -> None:
    console = make_console("rich")
    render_table(
        console,
        title="Loop Programs",
        headers=("Program", "Project", "Steps", "Terminate", "Config"),
        no_wrap_columns=(4,),
        rows=[
            (
                row.name,
                row.project,
                row.steps,
                row.termination_phase,
                row.path,
            )
            for row in rows
        ],
    )
    console.print()
    render_panel(
        console,
        "Inspect one program: loopfarm programs show <name>\n"
        "Step grammar docs: loopfarm docs show steps-grammar",
        title="Next",
    )


def _emit_show_text(detail: ProgramDetail) -> None:
    print(f"PROGRAM\t{detail.name}")
    print(f"SOURCE\t{detail.path}")
    print(f"PROJECT\t{detail.project}")
    print(f"STEPS\t{detail.steps}")
    print(f"TERMINATION_PHASE\t{detail.termination_phase}")
    print(f"REPORT_SOURCE_PHASE\t{detail.report_source_phase or '-'}")
    report_targets = ", ".join(detail.report_target_phases) if detail.report_target_phases else "-"
    print(f"REPORT_TARGET_PHASES\t{report_targets}")
    print()
    print("STEP\tPHASE\tREPEAT")
    for step in detail.loop_steps:
        print(f"{step.index}\t{step.phase}\t{step.repeat}")
    print()
    print("PHASE\tIN_STEPS\tCONFIGURED\tCLI\tMODEL\tREASONING\tINJECT\tPROMPT")
    for phase in detail.phases:
        inject = ", ".join(phase.inject) if phase.inject else "-"
        print(
            f"{phase.phase}\t"
            f"{'yes' if phase.in_steps else 'no'}\t"
            f"{'yes' if phase.configured else 'no'}\t"
            f"{phase.cli or '-'}\t"
            f"{phase.model or '-'}\t"
            f"{phase.reasoning or '-'}\t"
            f"{inject}\t"
            f"{phase.prompt or '-'}"
        )
    print()
    missing = ", ".join(detail.missing_phase_configs) if detail.missing_phase_configs else "-"
    extra = ", ".join(detail.extra_phase_configs) if detail.extra_phase_configs else "-"
    print(f"MISSING_PHASE_CONFIGS\t{missing}")
    print(f"EXTRA_PHASE_CONFIGS\t{extra}")


def _emit_show_json(detail: ProgramDetail) -> None:
    payload = {
        "name": detail.name,
        "path": detail.path,
        "project": detail.project,
        "steps": detail.steps,
        "loop_steps": [
            {"index": step.index, "phase": step.phase, "repeat": step.repeat}
            for step in detail.loop_steps
        ],
        "termination_phase": detail.termination_phase,
        "report_source_phase": detail.report_source_phase,
        "report_target_phases": list(detail.report_target_phases),
        "phases": [
            {
                "phase": phase.phase,
                "in_steps": phase.in_steps,
                "configured": phase.configured,
                "cli": phase.cli,
                "model": phase.model,
                "reasoning": phase.reasoning,
                "inject": list(phase.inject),
                "prompt": phase.prompt,
            }
            for phase in detail.phases
        ],
        "missing_phase_configs": list(detail.missing_phase_configs),
        "extra_phase_configs": list(detail.extra_phase_configs),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _emit_show_rich(detail: ProgramDetail) -> None:
    console = make_console("rich")
    summary = "\n".join(
        [
            f"source: {detail.path}",
            f"project: {detail.project}",
            f"steps: {detail.steps}",
            f"termination_phase: {detail.termination_phase}",
            f"report_source_phase: {detail.report_source_phase or '-'}",
            "report_target_phases: "
            f"{', '.join(detail.report_target_phases) if detail.report_target_phases else '-'}",
        ]
    )
    render_panel(console, summary, title=f"Program {detail.name}")
    render_table(
        console,
        title="Loop Steps",
        headers=("#", "Phase", "Repeat"),
        no_wrap_columns=(0, 1, 2),
        rows=[(step.index, step.phase, step.repeat) for step in detail.loop_steps],
    )
    render_table(
        console,
        title="Phase Config",
        headers=(
            "Phase",
            "In Steps",
            "Configured",
            "CLI",
            "Model",
            "Reasoning",
            "Inject",
            "Prompt",
        ),
        no_wrap_columns=(0, 1, 2),
        rows=[
            (
                phase.phase,
                "yes" if phase.in_steps else "no",
                "yes" if phase.configured else "no",
                phase.cli or "-",
                phase.model or "-",
                phase.reasoning or "-",
                ", ".join(phase.inject) if phase.inject else "-",
                phase.prompt or "-",
            )
            for phase in detail.phases
        ],
    )
    render_panel(
        console,
        (
            "Missing phase configs: "
            f"{', '.join(detail.missing_phase_configs) if detail.missing_phase_configs else '(none)'}\n"
            "Extra phase configs: "
            f"{', '.join(detail.extra_phase_configs) if detail.extra_phase_configs else '(none)'}"
        ),
        title="Validation Hints",
    )


def _print_help_rich() -> None:
    render_rich_help(
        command="loopfarm programs",
        summary="discover and inspect loop programs + effective phase config",
        usage=(
            "loopfarm programs list [--output MODE]",
            "loopfarm programs list --json",
            "loopfarm programs show <name> [--output MODE]",
            "loopfarm programs show <name> --json",
        ),
        sections=(
            (
                "Commands",
                (
                    ("list", "list discovered programs and source config files"),
                    (
                        "show <name>",
                        "inspect one program (steps, report fields, and per-phase config)",
                    ),
                ),
            ),
            (
                "Options",
                (
                    ("--json", "emit stable JSON payloads for automation"),
                    (
                        "--output MODE",
                        "auto|plain|rich (or LOOPFARM_OUTPUT) for table output",
                    ),
                    ("-h, --help", "show this help"),
                ),
            ),
            (
                "Quick Start",
                (
                    ("list programs", "loopfarm programs list"),
                    ("inspect one program", "loopfarm programs show implementation"),
                    ("agent payload", "loopfarm programs list --json"),
                    (
                        "agent inspection payload",
                        "loopfarm programs show implementation --json",
                    ),
                ),
            ),
        ),
        examples=(
            (
                "loopfarm programs list --json | jq '.[].name'",
                "extract program names for scripting",
            ),
            (
                "loopfarm programs list --output rich",
                "view project, steps, termination phase, and config file",
            ),
            (
                "loopfarm programs show implementation --output rich",
                "inspect phase CLI/model/prompt config and report wiring",
            ),
        ),
        docs_tip=(
            "See `loopfarm docs show steps-grammar` and "
            "`loopfarm docs show implementation-state-machine`."
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loopfarm programs",
        description="List and inspect discovered loopfarm programs.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    list_parser = sub.add_parser("list", help="List discovered programs")
    list_parser.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(list_parser)

    show_parser = sub.add_parser("show", help="Show one program configuration")
    show_parser.add_argument("name", help="Program name")
    show_parser.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(show_parser)
    return parser


def main(argv: list[str] | None = None) -> None:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if raw_argv in (["-h"], ["--help"]):
        try:
            help_output_mode = resolve_output_mode(
                is_tty=getattr(sys.stdout, "isatty", lambda: False)(),
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        if help_output_mode == "rich":
            _print_help_rich()
            raise SystemExit(0)
        _build_parser().parse_args(raw_argv)
        return

    if not raw_argv or raw_argv[0].startswith("-"):
        raw_argv = ["list", *raw_argv]

    args = _build_parser().parse_args(raw_argv)
    if args.command == "list":
        rows = _load_program_rows(Path.cwd())
        if args.json:
            _emit_list_json(rows)
            return

        try:
            mode = resolve_output_mode(getattr(args, "output", None))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        if mode == "rich":
            _emit_list_rich(rows)
        else:
            _emit_list_text(rows)
        return

    detail = _load_program_detail(Path.cwd(), args.name)
    if args.json:
        _emit_show_json(detail)
        return

    try:
        mode = resolve_output_mode(getattr(args, "output", None))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    if mode == "rich":
        _emit_show_rich(detail)
    else:
        _emit_show_text(detail)
