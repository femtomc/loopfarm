"""CLI entry point for loopfarm."""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .dag import DagRunner
from .fmt import get_formatter
from .store import ForumStore, IssueStore


def _find_repo_root() -> Path:
    """Walk up to find .git directory."""
    p = Path.cwd()
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path.cwd()


def _run_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loopfarm", add_help=False)
    p.add_argument("prompt", nargs="*")
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--cli", default="codex", choices=["codex", "claude"])
    p.add_argument("--model", default="o3")
    p.add_argument("--reasoning", default="high")
    p.add_argument("--prompt-path", default=None)
    p.add_argument("--json", action="store_true")
    return p


def _ago(ts: int) -> str:
    """Human-readable time ago string."""
    delta = int(time.time()) - ts
    if delta < 60:
        return "just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _status_style(status: str) -> str:
    return {"open": "yellow", "in_progress": "cyan", "closed": "green"}.get(status, "dim")


def cmd_init(console: Console) -> int:
    root = _find_repo_root()
    lf = root / ".loopfarm"
    lf.mkdir(exist_ok=True)
    (lf / "issues.jsonl").touch()
    (lf / "forum.jsonl").touch()

    orch = lf / "orchestrator.md"
    if not orch.exists():
        orch.write_text(
            "---\n"
            "cli: codex\n"
            "model: o3\n"
            "reasoning: high\n"
            "---\n\n"
            "{{PROMPT}}\n\n"
            "{{DYNAMIC_CONTEXT}}\n\n"
            "You are an orchestrator agent. Execute the task described above.\n"
            "When done, close the issue using the loopfarm issue store.\n"
        )

    (lf / "logs").mkdir(exist_ok=True)
    console.print(Panel(
        f"Initialized [bold].loopfarm/[/bold] in {root}",
        style="green",
        expand=False,
    ))
    return 0


def cmd_replay(argv: list[str], console: Console) -> int:
    root = _find_repo_root()
    logs_dir = root / ".loopfarm" / "logs"

    if not argv or argv[0] in ("-h", "--help"):
        console.print("[bold]loopfarm replay[/bold] — replay a logged run\n")
        console.print("  loopfarm replay [dim]<issue-id|path>[/dim] [dim][--backend codex|claude][/dim]\n")
        if logs_dir.exists():
            logs = sorted(logs_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
            if logs:
                table = Table(title="Recent Logs", expand=False, show_edge=False, pad_edge=False)
                table.add_column("ID", style="bold")
                table.add_column("Size", style="dim", justify="right")
                table.add_column("Modified", style="dim")
                for log in logs[:10]:
                    stat = log.stat()
                    size = f"{stat.st_size / 1024:.0f}K"
                    modified = _ago(int(stat.st_mtime))
                    table.add_row(log.stem, size, modified)
                console.print(table)
        return 0

    target = argv[0]
    backend_name = "codex"
    if "--backend" in argv:
        idx = argv.index("--backend")
        if idx + 1 < len(argv):
            backend_name = argv[idx + 1]

    # Resolve target: could be issue id, path, or stem
    path = Path(target)
    if not path.exists():
        path = logs_dir / f"{target}.jsonl"
    if not path.exists():
        candidates = list(logs_dir.glob(f"{target}*.jsonl"))
        if len(candidates) == 1:
            path = candidates[0]
        elif len(candidates) > 1:
            console.print(Text(f"Ambiguous prefix '{target}', matches:", style="red"))
            for c in candidates:
                console.print(f"  {c.stem}")
            return 1
    if not path.exists():
        console.print(Text(f"Log not found: {target}", style="red"))
        return 1

    console.print(Panel(f"Replaying [bold]{path.stem}[/bold]", style="dim", expand=False))
    fmt = get_formatter(backend_name, console)
    with open(path) as f:
        for line in f:
            fmt.process_line(line.rstrip("\n"))
    fmt.finish()
    return 0


def cmd_resume(argv: list[str], console: Console) -> int:
    root = _find_repo_root()
    store = IssueStore.from_workdir(root)
    forum = ForumStore.from_workdir(root)

    if not argv or argv[0] in ("-h", "--help"):
        console.print("[bold]loopfarm resume[/bold] — resume an interrupted DAG\n")
        console.print("  loopfarm resume [dim]<root-id>[/dim] [dim][--max-steps N] [--cli codex|claude] [--model M][/dim]\n")
        roots = store.list(tag="node:root")
        if roots:
            table = Table(title="Root Issues", expand=False, show_edge=False, pad_edge=False)
            table.add_column("ID", style="bold")
            table.add_column("Status")
            table.add_column("Title")
            table.add_column("Age", style="dim", justify="right")
            for r in roots[-10:]:
                style = _status_style(r["status"])
                table.add_row(
                    r["id"],
                    Text(r["status"], style=style),
                    r["title"][:50],
                    _ago(r.get("created_at", 0)),
                )
            console.print(table)
        return 0

    issue_id = argv[0]
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--cli", default="codex", choices=["codex", "claude"])
    p.add_argument("--model", default="o3")
    p.add_argument("--reasoning", default="high")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv[1:])

    # Resolve issue id (prefix match)
    issue = store.get(issue_id)
    if issue is None:
        candidates = [r for r in store.list() if r["id"].startswith(issue_id)]
        if len(candidates) == 1:
            issue = candidates[0]
        elif len(candidates) > 1:
            console.print(Text(f"Ambiguous prefix '{issue_id}'", style="red"))
            for c in candidates:
                console.print(f"  {c['id']}")
            return 1
    if issue is None:
        console.print(Text(f"Issue not found: {issue_id}", style="red"))
        return 1

    root_id = issue["id"]

    # Reset stale in_progress issues
    reset = store.reset_in_progress(root_id)
    if reset:
        console.print(Panel(
            f"Reset {len(reset)} stale issue(s) to open: " + ", ".join(reset),
            style="yellow",
            expand=False,
        ))

    console.print(Panel(
        f"Resuming [bold]{root_id}[/bold] — {issue['title'][:80]}",
        style="cyan",
        expand=False,
    ))

    runner = DagRunner(
        store, forum, root,
        default_cli=args.cli,
        default_model=args.model,
        default_reasoning=args.reasoning,
        console=console,
    )
    result = runner.run(root_id, max_steps=args.max_steps)

    if args.json:
        json.dump(
            {"status": result.status, "steps": result.steps, "error": result.error, "root_id": root_id},
            sys.stdout, indent=2,
        )
        print()

    return 0 if result.status == "root_final" else 1


def cmd_run(args: argparse.Namespace, console: Console) -> int:
    root = _find_repo_root()
    store = IssueStore.from_workdir(root)
    forum = ForumStore.from_workdir(root)

    prompt_text = " ".join(args.prompt)
    if not prompt_text:
        console.print(Text("No prompt provided.", style="red"))
        return 1

    root_issue = store.create(
        prompt_text,
        tags=["node:agent", "node:root"],
        execution_spec={
            "role": "orchestrator",
            "prompt_path": args.prompt_path or "",
            "cli": args.cli,
            "model": args.model,
            "reasoning": args.reasoning,
        },
    )
    console.print(Panel(
        f"[bold]{root_issue['id']}[/bold] — {prompt_text[:80]}",
        title="Root Issue",
        style="cyan",
        expand=False,
    ))

    runner = DagRunner(
        store, forum, root,
        default_cli=args.cli,
        default_model=args.model,
        default_reasoning=args.reasoning,
        console=console,
    )
    result = runner.run(root_issue["id"], max_steps=args.max_steps)

    if args.json:
        json.dump(
            {"status": result.status, "steps": result.steps, "error": result.error, "root_id": root_issue["id"]},
            sys.stdout, indent=2,
        )
        print()

    return 0 if result.status == "root_final" else 1


def _print_help(console: Console) -> None:
    help_text = Text()
    help_text.append("loopfarm", style="bold")
    help_text.append(f" {__version__}", style="dim")
    help_text.append(" — DAG-based loop runner for agentic workflows")
    console.print(help_text)
    console.print()

    cmds = Table(show_header=False, expand=False, show_edge=False, pad_edge=False, box=None)
    cmds.add_column("Command", style="bold cyan")
    cmds.add_column("Description")
    cmds.add_row("loopfarm init", "Scaffold .loopfarm/ directory")
    cmds.add_row("loopfarm replay <id>", "Replay a logged run")
    cmds.add_row("loopfarm resume <id>", "Resume an interrupted DAG")
    cmds.add_row("loopfarm <prompt>", "Create root issue and run DAG")
    console.print(cmds)
    console.print()

    opts = Table(show_header=False, expand=False, show_edge=False, pad_edge=False, box=None)
    opts.add_column("Option", style="bold")
    opts.add_column("Description", style="dim")
    opts.add_row("--max-steps N", "Step budget (default: 20)")
    opts.add_row("--cli codex|claude", "Default backend (default: codex)")
    opts.add_row("--model MODEL", "Default model (default: o3)")
    opts.add_row("--reasoning LEVEL", "Reasoning level (default: high)")
    opts.add_row("--prompt-path PATH", "Prompt template path")
    opts.add_row("--json", "JSON output")
    opts.add_row("--version", "Show version")
    console.print(opts)


def main(argv: list[str] | None = None) -> None:
    raw = argv if argv is not None else sys.argv[1:]
    console = Console()

    if "--version" in raw:
        console.print(Text(f"loopfarm {__version__}", style="bold"))
        sys.exit(0)
    if not raw or raw == ["--help"] or raw == ["-h"]:
        _print_help(console)
        sys.exit(0)

    # Subcommand dispatch
    if raw[0] == "init":
        sys.exit(cmd_init(console))

    if raw[0] == "replay":
        sys.exit(cmd_replay(raw[1:], console))

    if raw[0] == "resume":
        sys.exit(cmd_resume(raw[1:], console))

    # Everything else is a run command
    args = _run_parser().parse_args(raw)
    sys.exit(cmd_run(args, console))


if __name__ == "__main__":
    main()
