from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .ui import add_output_mode_argument, render_help, resolve_output_mode


def _print_help(*, output_mode: str) -> None:
    render_help(
        output_mode="rich" if output_mode == "rich" else "plain",
        command="loopfarm",
        summary="prompt-mode issue DAG orchestration",
        usage=(
            "loopfarm [OPTIONS] <prompt...>",
            "loopfarm issue <command> [ARGS]",
            "loopfarm <command> [ARGS]",
        ),
        sections=(
            (
                "Primary Workflows",
                (
                    (
                        "prompt → root issue → orchestrate",
                        "loopfarm \"<prompt>\" (or any unrecognized command)",
                    ),
                    (
                        "direct DAG operations",
                        "loopfarm issue <command> [ARGS]",
                    ),
                ),
            ),
            (
                "Prompt Mode",
                (
                    (
                        "fallback rule",
                        "if the first token is not a known command, loopfarm treats argv as a prompt",
                    ),
                    (
                        "reserved words",
                        "if your prompt starts with a command name, quote the full prompt (ex: loopfarm \"issue ...\")",
                    ),
                ),
            ),
            (
                "Commands",
                (
                    (
                        "init",
                        "scaffold .loopfarm/orchestrator.md and .loopfarm/roles/*.md",
                    ),
                    (
                        "issue",
                        "issue DAG operations (create/update, deps, orchestrate-run)",
                    ),
                    ("docs", "list/show/search built-in docs topics"),
                    ("forum", "post/read/search loopfarm forum topics/messages"),
                    ("sessions", "list/show recent loop sessions and summaries"),
                    ("history", "alias for `sessions list`"),
                    (
                        "roles (internal)",
                        "orchestrator-only role discovery/team assembly from role docs",
                    ),
                ),
            ),
            (
                "Prompt Workflow Options",
                (
                    (
                        "--max-steps N",
                        "step budget per orchestration pass (default: 20)",
                    ),
                    (
                        "--max-total-steps N",
                        "total step budget across repeated passes (default: 1000)",
                    ),
                    (
                        "--scan-limit N",
                        "frontier scan limit for orchestration selection (default: 20)",
                    ),
                    (
                        "--resume-mode MODE",
                        "manual|resume (default: manual)",
                    ),
                    (
                        "--full-maintenance",
                        "run full subtree reconcile/validate after each step",
                    ),
                    ("--json", "emit machine-stable JSON result payload"),
                ),
            ),
            (
                "Global Options",
                (
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
                    ("bootstrap", "loopfarm init"),
                    (
                        "prompt mode",
                        "loopfarm \"Design and implement sync engine\"",
                    ),
                    (
                        "orchestrate existing root",
                        "loopfarm issue orchestrate-run --root <id> --json",
                    ),
                    ("inspect DAG state", "loopfarm issue show <id> --json"),
                ),
            ),
        ),
        examples=(
            (
                "loopfarm \"Build OAuth flow with retries and observability\"",
                "create a root issue from prompt and run orchestration",
            ),
            (
                "loopfarm issue orchestrate-run --root loopfarm-123 --max-steps 8 --json",
                "run up to 8 deterministic orchestration steps",
            ),
        ),
        docs_tip=(
            "Use `loopfarm docs show issue-dag-orchestration --output rich` for the "
            "minimal-core execution contract."
        ),
        stderr=True,
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="loopfarm", add_help=False)
    parser.add_argument("-h", "--help", action="store_true", default=False)
    parser.add_argument("--version", action="store_true", default=False)
    parser.add_argument("--json", action="store_true", default=False)
    parser.add_argument("--max-steps", type=int, default=20)
    parser.add_argument("--max-total-steps", type=int, default=1000)
    parser.add_argument("--scan-limit", type=int, default=20)
    parser.add_argument("--resume-mode", choices=("manual", "resume"), default="manual")
    parser.add_argument("--full-maintenance", action="store_true", default=False)
    add_output_mode_argument(parser)
    parser.add_argument("command", nargs="?")
    parser.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def _prompt_title(prompt: str) -> str:
    first = next((line.strip() for line in prompt.splitlines() if line.strip()), "")
    if not first:
        return "Prompt Root"
    if len(first) <= 96:
        return first
    return first[:93].rstrip() + "..."


def _run_prompt_mode(
    *,
    prompt: str,
    output_mode: str,
    as_json: bool,
    max_steps: int,
    max_total_steps: int,
    scan_limit: int,
    resume_mode: str,
    full_maintenance: bool,
) -> None:
    from .forum import Forum
    from .issue import Issue
    from .runtime.issue_dag_runner import IssueDagRunner

    repo_root = Path.cwd()
    issue = Issue.from_workdir(repo_root, create=True)
    root = issue.create(
        _prompt_title(prompt),
        body=prompt,
        tags=["node:agent"],
    )

    runner = IssueDagRunner(
        repo_root=repo_root,
        issue=issue,
        forum=Forum.from_workdir(repo_root),
        scan_limit=max(1, int(scan_limit)),
    )

    root_id = str(root["id"])
    per_pass_budget = max(1, int(max_steps))
    total_budget = max(1, int(max_total_steps))

    collected_steps: list[dict[str, Any]] = []
    stop_reason = "max_total_steps_exhausted"
    error: str | None = None
    termination: dict[str, Any] = {}
    cursor = 0

    while total_budget > 0:
        batch_budget = min(per_pass_budget, total_budget)
        run = runner.run(
            root_id=root_id,
            max_steps=batch_budget,
            resume_mode=resume_mode,
            full_maintenance=bool(full_maintenance),
        )

        run_steps = list(run.steps)
        for step in run_steps:
            cursor += 1
            collected_steps.append(
                {
                    "index": cursor,
                    "issue_id": step.selection.issue_id,
                    "team": step.selection.team,
                    "role": step.selection.role,
                    "program": step.selection.program,
                    "route": str(step.selection.metadata.get("route") or ""),
                    "success": bool(step.execution.success),
                    "session_id": step.execution.session_id,
                }
            )

        total_budget -= len(run_steps)
        stop_reason = run.stop_reason
        error = run.error
        termination = dict(run.termination)

        if stop_reason != "max_steps_exhausted":
            break
        if not run_steps:
            stop_reason = "no_progress"
            break
    else:
        stop_reason = "max_total_steps_exhausted"

    payload = {
        "root_issue_id": root_id,
        "prompt": prompt,
        "stop_reason": stop_reason,
        "step_count": len(collected_steps),
        "error": error,
        "termination": termination,
        "steps": collected_steps,
    }

    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    _ = output_mode
    print(
        f"root={payload['root_issue_id']} stop_reason={payload['stop_reason']} "
        f"steps={payload['step_count']}"
    )
    if payload["error"]:
        print(f"error: {payload['error']}")
    for step in payload["steps"]:
        print(
            f"step {step['index']}: {step['issue_id']} "
            f"route={step['route'] or '-'} role={step['role']} "
            f"program={step['program']} success={step['success']}"
        )


def main(argv: list[str] | None = None) -> None:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
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

    command = str(args.command or "").strip()
    sub_argv = list(args.args or [])
    if not command:
        _print_help(output_mode=output_mode)
        raise SystemExit(0)

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
    if command == "roles":
        from .roles_cmd import main as roles_main

        roles_main(sub_argv)
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

    prompt = " ".join([command, *sub_argv]).strip()
    if not prompt:
        print("error: prompt cannot be empty", file=sys.stderr)
        raise SystemExit(2)

    try:
        _run_prompt_mode(
            prompt=prompt,
            output_mode=output_mode,
            as_json=bool(args.json),
            max_steps=max(1, int(args.max_steps)),
            max_total_steps=max(1, int(args.max_total_steps)),
            scan_limit=max(1, int(args.scan_limit)),
            resume_mode=str(args.resume_mode),
            full_maintenance=bool(args.full_maintenance),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
