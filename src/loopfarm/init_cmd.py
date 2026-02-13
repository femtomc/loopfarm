from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .ui import render_help, resolve_output_mode


ORCHESTRATOR_PROMPT = """---
cli: codex
model: gpt-5.2
reasoning: xhigh
loop_steps: role
termination_phase: role
---
You are the hierarchical orchestrator for the issue DAG.

User prompt:

{{PROMPT}}

{{DYNAMIC_CONTEXT}}

## Responsibilities

1. Decide whether the selected issue is atomic.
2. If not atomic, decompose it into child issues and close it with `outcome=expanded`.
3. Keep `parent` and `blocks` dependencies coherent.
4. Keep issue decomposition deterministic and minimal.
"""


ROLE_WORKER_PROMPT = """---
cli: codex
model: gpt-5.2
reasoning: xhigh
loop_steps: role
termination_phase: role
---
You are a worker role executing one atomic issue.

User prompt:

{{PROMPT}}

{{DYNAMIC_CONTEXT}}

## Responsibilities

1. Execute exactly one selected atomic issue end-to-end.
2. Keep scope tight to the selected issue.
3. Close with a terminal status and outcome (`success`, `failure`, or `skipped`).
"""


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loopfarm init",
        add_help=False,
        description=(
            "Initialize minimal hierarchical orchestration prompts in the current "
            "directory.\n"
            "Writes .loopfarm/orchestrator.md and .loopfarm/roles/*.md."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-h", "--help", action="store_true", default=False)
    parser.add_argument(
        "--force",
        action="store_true",
        default=False,
        help="Overwrite existing scaffold files",
    )
    return parser


def _print_help(*, output_mode: str) -> None:
    render_help(
        output_mode="rich" if output_mode == "rich" else "plain",
        command="loopfarm init",
        summary="scaffold minimal DAG orchestration prompt surfaces",
        usage=("loopfarm init [--force]",),
        sections=(
            (
                "Options",
                (
                    ("--force", "overwrite existing scaffold files"),
                    ("-h, --help", "show this help"),
                ),
            ),
            (
                "Generated Files",
                (
                    (
                        ".loopfarm/orchestrator.md",
                        "used when a selected leaf is non-atomic (decompose)",
                    ),
                    (
                        ".loopfarm/roles/worker.md",
                        "default atomic execution role prompt",
                    ),
                ),
            ),
            (
                "Next Steps",
                (
                    ("run prompt mode", 'loopfarm "Design and implement sync engine"'),
                    (
                        "run existing root",
                        "loopfarm issue orchestrate-run --root <id> --json",
                    ),
                    (
                        "add more roles",
                        "create .loopfarm/roles/<role>.md and tag issues with role:<role>",
                    ),
                ),
            ),
        ),
        examples=(
            ("loopfarm init", "initialize orchestrator + role prompt files"),
            ("loopfarm init --force", "overwrite existing scaffold files"),
        ),
        docs_tip=(
            "See `loopfarm docs show issue-dag-orchestration` for the minimal-core contract."
        ),
    )


def _scaffold_files() -> dict[Path, str]:
    return {
        Path(".loopfarm/orchestrator.md"): ORCHESTRATOR_PROMPT,
        Path(".loopfarm/roles/worker.md"): ROLE_WORKER_PROMPT,
    }


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = _build_parser()
    args = parser.parse_args(argv or [])

    if args.help:
        try:
            help_output_mode = resolve_output_mode(
                is_tty=getattr(sys.stdout, "isatty", lambda: False)(),
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        _print_help(output_mode=help_output_mode)
        raise SystemExit(0)

    repo_root = Path.cwd()
    files = _scaffold_files()

    created: list[Path] = []
    overwritten: list[Path] = []
    skipped: list[Path] = []

    for rel_path, content in files.items():
        path = repo_root / rel_path
        existed_before = path.exists()
        if existed_before and not args.force:
            skipped.append(rel_path)
            continue
        _write(path, content)
        if existed_before:
            overwritten.append(rel_path)
        else:
            created.append(rel_path)

    for rel_path in created:
        print(f"created: {rel_path}")
    for rel_path in overwritten:
        print(f"overwrote: {rel_path}")
    for rel_path in skipped:
        print(f"skipped: {rel_path}", file=sys.stderr)

    if not created and not overwritten:
        print("nothing changed", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
