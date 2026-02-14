"""CLI entry point for inshallah."""

from __future__ import annotations

import argparse
import io
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .dag import DagRunner
from .events import new_run_id, run_context
from .fmt import get_formatter
from .forum_store import ForumStore
from .issue_store import IssueStore
from .prompt import list_roles_json


def _find_repo_root() -> Path:
    """Walk up to find .git directory."""
    p = Path.cwd()
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path.cwd()


def _run_parser(prog: str = "inshallah run") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, add_help=False)
    p.add_argument("prompt", nargs="*")
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--review", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--json", action="store_true")
    return p


def _ago(ts: int) -> str:
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


def _output(data: object, *, pretty: bool = False) -> None:
    indent = 2 if pretty else None
    json.dump(data, sys.stdout, indent=indent)
    sys.stdout.write("\n")


def _format_recovery(recovery: list[str] | None) -> str:
    if not recovery:
        return ""
    return " Recovery: " + " | ".join(recovery)


def _error(msg: str, *, recovery: list[str] | None = None) -> int:
    _output({"error": f"{msg}{_format_recovery(recovery)}"})
    return 1


def _print_next_steps(console: Console, steps: list[str], *, title: str = "Next Steps") -> None:
    if not steps:
        return
    table = Table(title=title, show_header=False, box=None, pad_edge=False)
    table.add_column("Step", style="bold")
    table.add_column("Command", style="bold cyan")
    for idx, command in enumerate(steps, start=1):
        table.add_row(str(idx), command)
    console.print(table)


def _fail(
    console: Console,
    msg: str,
    *,
    recovery: list[str] | None = None,
    json_mode: bool = False,
) -> int:
    if json_mode:
        return _error(msg, recovery=recovery)
    console.print(Text(msg, style="red"))
    if recovery:
        _print_next_steps(console, recovery, title="Recovery")
    return 1


def _runner_console(console: Console, *, json_mode: bool) -> Console:
    if not json_mode:
        return console
    # Keep --json output machine-readable by suppressing rich runner logs.
    return Console(file=io.StringIO(), force_terminal=False, color_system=None)


def _guide_cross_link(console: Console) -> None:
    console.print(Text("Need end-to-end context? Run `inshallah guide`.", style="dim"))


def _print_command_help(
    console: Console,
    *,
    title: str,
    usage: str,
    about: str,
    options: list[tuple[str, str]],
    examples: list[str],
    next_steps: list[str] | None = None,
    include_guide: bool = True,
) -> int:
    console.print(Panel.fit(about, title=title, border_style="cyan"))
    console.print(Text(f"Usage: {usage}", style="bold"))
    if options:
        table = Table(show_header=False, box=None, pad_edge=False)
        table.add_column("Option", style="bold")
        table.add_column("Description", style="dim")
        for opt, desc in options:
            table.add_row(opt, desc)
        console.print(table)
    if examples:
        console.print(Text("Examples:", style="bold"))
        for example in examples:
            console.print(f"  {example}")
    if next_steps:
        _print_next_steps(console, next_steps)
    if include_guide:
        _guide_cross_link(console)
    return 0


# ---------------------------------------------------------------------------
# Setup / run orchestration commands
# ---------------------------------------------------------------------------


def cmd_init(console: Console, *, force: bool = False) -> int:
    root = _find_repo_root()
    lf = root / ".inshallah"
    lf.mkdir(exist_ok=True)
    (lf / "issues.jsonl").touch()
    (lf / "forum.jsonl").touch()
    (lf / "events.jsonl").touch()

    # Copy default prompt templates from package into .inshallah/
    prompts_dir = Path(__file__).parent / "prompts"

    orch = lf / "orchestrator.md"
    if force or not orch.exists():
        shutil.copy2(prompts_dir / "orchestrator.md", orch)

    roles_dir = lf / "roles"
    roles_dir.mkdir(exist_ok=True)
    for role_name in ("worker", "reviewer"):
        dest = roles_dir / f"{role_name}.md"
        if force or not dest.exists():
            shutil.copy2(prompts_dir / "roles" / f"{role_name}.md", dest)

    (lf / "logs").mkdir(exist_ok=True)
    verb = "Reinitialized" if force else "Initialized"
    console.print(
        Panel(
            f"{verb} [bold].inshallah/[/bold] in {root}",
            style="green",
            expand=False,
        )
    )
    _print_next_steps(
        console,
        [
            "inshallah guide",
            "inshallah roles --table",
            "inshallah run \"Break down and execute this goal\"",
            "inshallah status",
        ],
    )
    return 0


def cmd_serve(argv: list[str], console: Console) -> int:
    if argv and argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah serve",
            usage="inshallah serve [--host HOST] [--port PORT] [--reload]",
            about="Start the inshallah web interface.",
            options=[
                ("--host", "Bind address (default: 127.0.0.1)"),
                ("--port", "Bind port (default: 8420)"),
                ("--reload", "Enable auto-reload for development"),
            ],
            examples=["inshallah serve", "inshallah serve --port 9000 --reload"],
        )

    p = argparse.ArgumentParser(prog="inshallah serve", add_help=False)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8420)
    p.add_argument("--reload", action="store_true")
    args = p.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]Missing web dependencies.[/red] "
            "Install with: [bold]pip install inshallah\\[web][/bold]"
        )
        return 1

    console.print(
        Panel(
            f"Starting web server at [bold]http://{args.host}:{args.port}[/bold]",
            title="inshallah serve",
            style="cyan",
            expand=False,
        )
    )

    uvicorn.run(
        "inshallah.web:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def cmd_replay(argv: list[str], console: Console) -> int:
    root = _find_repo_root()
    logs_dir = root / ".inshallah" / "logs"

    if not argv or argv[0] in ("-h", "--help"):
        console.print("[bold]inshallah replay[/bold] - replay a logged run\n")
        console.print("  inshallah replay [dim]<issue-id|path>[/dim] [dim][--backend codex|claude|opencode|pi|gemini][/dim]\n")
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

    path = Path(target)
    if not path.exists():
        path = logs_dir / f"{target}.jsonl"
    if not path.exists():
        candidates = list(logs_dir.glob(f"{target}*.jsonl"))
        if len(candidates) == 1:
            path = candidates[0]
        elif len(candidates) > 1:
            console.print(Text(f"Ambiguous prefix '{target}', matches:", style="red"))
            for candidate in candidates:
                console.print(f"  {candidate.stem}")
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
        console.print("[bold]inshallah resume[/bold] - resume an interrupted DAG\n")
        console.print("  inshallah resume [dim]<root-id>[/dim] [dim][--max-steps N][/dim]\n")
        roots = store.list(tag="node:root")
        if roots:
            table = Table(title="Root Issues", expand=False, show_edge=False, pad_edge=False)
            table.add_column("ID", style="bold")
            table.add_column("Status")
            table.add_column("Title")
            table.add_column("Age", style="dim", justify="right")
            for issue in roots[-10:]:
                style = _status_style(issue["status"])
                table.add_row(
                    issue["id"],
                    Text(issue["status"], style=style),
                    issue["title"][:50],
                    _ago(issue.get("created_at", 0)),
                )
            console.print(table)
            sample_root = roots[-1]["id"]
            _print_next_steps(
                console,
                [
                    f"inshallah resume {sample_root}",
                    f"inshallah issues ready --root {sample_root}",
                    "inshallah guide --section workflow",
                ],
            )
        else:
            _print_next_steps(
                console,
                [
                    "inshallah run \"Break down and execute this goal\"",
                    "inshallah guide --section workflow",
                ],
            )
        return 0

    issue_id = argv[0]
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--review", action=argparse.BooleanOptionalAction, default=True)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv[1:])

    issue = store.get(issue_id)
    if issue is None:
        candidates = [candidate for candidate in store.list() if candidate["id"].startswith(issue_id)]
        if len(candidates) == 1:
            issue = candidates[0]
        elif len(candidates) > 1:
            sample = ", ".join(candidate["id"] for candidate in candidates[:5])
            suffix = "..." if len(candidates) > 5 else ""
            return _fail(
                console,
                f"Ambiguous prefix '{issue_id}' ({sample}{suffix})",
                recovery=[
                    "inshallah status",
                    "inshallah issues list --root <root-id> --limit 20",
                    "inshallah guide --section workflow",
                ],
                json_mode=args.json,
            )
    if issue is None:
        return _fail(
            console,
            f"Issue not found: {issue_id}",
            recovery=[
                "inshallah status",
                "inshallah issues list --limit 20",
                "inshallah guide --section workflow",
            ],
            json_mode=args.json,
        )

    root_id = issue["id"]

    reset = store.reset_in_progress(root_id)
    if reset and not args.json:
        console.print(
            Panel(
                f"Reset {len(reset)} stale issue(s) to open: " + ", ".join(reset),
                style="yellow",
                expand=False,
            )
        )

    if not args.json:
        console.print(
            Panel(
                f"Resuming [bold]{root_id}[/bold] - {issue['title'][:80]}",
                style="cyan",
                expand=False,
            )
        )

    run_id = new_run_id()
    with run_context(run_id=run_id):
        runner = DagRunner(store, forum, root, console=_runner_console(console, json_mode=args.json))
        result = runner.run(
            root_id, max_steps=args.max_steps, review=args.review
        )

    if args.json:
        _output(
            {
                "status": result.status,
                "steps": result.steps,
                "error": result.error,
                "root_id": root_id,
            },
            pretty=True,
        )
    else:
        if result.error:
            console.print(Text(f"Runner error: {result.error}", style="red"))
        if result.status == "root_final":
            _print_next_steps(
                console,
                [
                    f"inshallah issues validate {root_id}",
                    "inshallah status",
                    "inshallah guide --section workflow",
                ],
            )
        else:
            _print_next_steps(
                console,
                [
                    f"inshallah resume {root_id}",
                    f"inshallah issues ready --root {root_id}",
                    "inshallah guide --section workflow",
                ],
            )

    return 0 if result.status == "root_final" else 1


def cmd_status(argv: list[str], console: Console) -> int:
    pretty = "--pretty" in argv
    json_mode = "--json" in argv

    root = _find_repo_root()
    store = IssueStore.from_workdir(root)
    forum = ForumStore.from_workdir(root)

    roots = store.list(tag="node:root")
    open_issues = store.list(status="open")
    ready = store.ready(tags=["node:agent"])
    topics = forum.topics(prefix="issue:")[:10]

    payload = {
        "repo_root": str(root),
        "roots": roots,
        "open_count": len(open_issues),
        "ready_count": len(ready),
        "ready": ready[:10],
        "recent_topics": topics,
        "roles": list_roles_json(root),
    }

    if json_mode:
        _output(payload, pretty=pretty)
        return 0

    console.print(Panel.fit(f"Repo: {root}", title="inshallah status", border_style="cyan"))

    summary = Table(show_header=False, box=None, pad_edge=False)
    summary.add_column("Metric", style="bold")
    summary.add_column("Value")
    summary.add_row("Root issues", str(len(roots)))
    summary.add_row("Open issues", str(len(open_issues)))
    summary.add_row("Ready issues", str(len(ready)))
    summary.add_row("Roles", str(len(payload["roles"])))
    console.print(summary)

    if ready:
        table = Table(title="Ready Issues", show_edge=False, pad_edge=False)
        table.add_column("ID", style="bold")
        table.add_column("Priority", justify="right")
        table.add_column("Title")
        for issue in ready[:10]:
            table.add_row(issue["id"], str(issue.get("priority", 3)), issue["title"][:80])
        console.print(table)

    if topics:
        ttable = Table(title="Recent Issue Topics", show_edge=False, pad_edge=False)
        ttable.add_column("Topic", style="bold")
        ttable.add_column("Messages", justify="right")
        ttable.add_column("Last", style="dim")
        for topic in topics:
            ttable.add_row(topic["topic"], str(topic["messages"]), _ago(topic["last_at"]))
        console.print(ttable)

    if not roots:
        _print_next_steps(
            console,
            [
                "inshallah init",
                "inshallah guide",
                "inshallah run \"Break down and execute this goal\"",
            ],
        )
        return 0

    if ready:
        issue_id = ready[0]["id"]
        _print_next_steps(
            console,
            [
                f"inshallah issues get {issue_id}",
                f"inshallah forum read issue:{issue_id} --limit 20",
                f"inshallah issues update {issue_id} --status in_progress",
                "inshallah guide --section workflow",
            ],
        )
    else:
        root_id = roots[-1]["id"]
        _print_next_steps(
            console,
            [
                f"inshallah issues ready --root {root_id}",
                f"inshallah resume {root_id}",
                "inshallah guide --section workflow",
            ],
        )

    return 0


def cmd_run(args: argparse.Namespace, console: Console) -> int:
    root = _find_repo_root()
    store = IssueStore.from_workdir(root)
    forum = ForumStore.from_workdir(root)

    prompt_text = " ".join(args.prompt)
    if not prompt_text:
        if args.json:
            return _error(
                "missing prompt",
                recovery=[
                    "inshallah run \"Break down and execute this goal\"",
                    "inshallah guide --section workflow",
                ],
            )
        console.print(Text("No prompt provided.", style="red"))
        _print_next_steps(
            console,
            [
                "inshallah guide --section workflow",
                "inshallah run \"Break down and execute this goal\"",
            ],
            title="Recovery",
        )
        return 1

    run_id = new_run_id()
    with run_context(run_id=run_id):
        root_issue = store.create(prompt_text, tags=["node:agent", "node:root"])
        if not args.json:
            console.print(
                Panel(
                    Markdown(prompt_text),
                    title="Root Issue",
                    subtitle=root_issue["id"],
                    style="cyan",
                    expand=False,
                )
            )

        runner = DagRunner(store, forum, root, console=_runner_console(console, json_mode=args.json))
        result = runner.run(
            root_issue["id"],
            max_steps=args.max_steps,
            review=args.review,
        )

    if args.json:
        _output(
            {
                "status": result.status,
                "steps": result.steps,
                "error": result.error,
                "root_id": root_issue["id"],
            },
            pretty=True,
        )
    else:
        if result.error:
            console.print(Text(f"Runner error: {result.error}", style="red"))
        if result.status == "root_final":
            _print_next_steps(
                console,
                [
                    f"inshallah issues validate {root_issue['id']}",
                    "inshallah status",
                    "inshallah guide --section workflow",
                ],
            )
        else:
            _print_next_steps(
                console,
                [
                    f"inshallah issues ready --root {root_issue['id']}",
                    f"inshallah resume {root_issue['id']}",
                    "inshallah guide --section workflow",
                ],
            )

    return 0 if result.status == "root_final" else 1


def cmd_roles(argv: list[str], console: Console | None = None) -> int:
    console = console or Console()
    if argv and argv[0] in ("-h", "--help"):
        console.print(Panel.fit(
            "List available role templates from .inshallah/roles/*.md.",
            title="inshallah roles",
            border_style="cyan",
        ))
        console.print("Usage: inshallah roles [--json] [--table] [--pretty]")
        console.print("Defaults to JSON output for automation.", style="dim")
        return 0

    pretty = "--pretty" in argv
    table_mode = "--table" in argv
    json_mode = "--json" in argv or not table_mode

    roles = list_roles_json(_find_repo_root())

    if json_mode:
        _output(roles, pretty=pretty)
        return 0

    table = Table(title="Roles", show_edge=False, pad_edge=False)
    table.add_column("Name", style="bold cyan")
    table.add_column("Prompt")
    table.add_column("CLI")
    table.add_column("Model")
    table.add_column("Reasoning")
    table.add_column("Description")
    table.add_column("Desc Source")

    for role in roles:
        table.add_row(
            role["name"],
            role.get("prompt_path", "") or "-",
            role.get("cli", "") or "-",
            role.get("model", "") or "-",
            role.get("reasoning", "") or "-",
            role.get("description", "") or "",
            role.get("description_source", "") or "-",
        )

    console.print(table)
    return 0


# ---------------------------------------------------------------------------
# Issues CLI
# ---------------------------------------------------------------------------


def _issues_store() -> IssueStore:
    return IssueStore.from_workdir(_find_repo_root())


def _resolve_issue_id(store: IssueStore, raw_id: str) -> tuple[str | None, str | None]:
    """Resolve exact or unique prefix issue IDs."""
    issue = store.get(raw_id)
    if issue is not None:
        return issue["id"], None

    matches = [issue["id"] for issue in store.list() if issue["id"].startswith(raw_id)]
    if not matches:
        return (
            None,
            (
                f"not found: {raw_id}"
                " Recovery: inshallah issues list --limit 20"
                " | inshallah issues ready --root <root-id>"
            ),
        )
    if len(matches) > 1:
        sample = ", ".join(matches[:5])
        suffix = "..." if len(matches) > 5 else ""
        return (
            None,
            (
                f"ambiguous id prefix: {raw_id} ({sample}{suffix})"
                " Recovery: use a longer id prefix"
                " | inshallah issues list --limit 20"
            ),
        )
    return matches[0], None


def _issue_json(issue: dict) -> dict:
    return {
        "id": issue["id"],
        "title": issue["title"],
        "body": issue.get("body", ""),
        "status": issue["status"],
        "outcome": issue.get("outcome"),
        "tags": issue.get("tags", []),
        "deps": issue.get("deps", []),
        "execution_spec": issue.get("execution_spec"),
        "priority": issue.get("priority", 3),
        "created_at": issue.get("created_at", 0),
        "updated_at": issue.get("updated_at", 0),
    }


def _print_issues_help(console: Console) -> int:
    console.print(Panel.fit(
        "Issue DAG commands for orchestrators and workers. Data commands return JSON.",
        title="inshallah issues",
        border_style="cyan",
    ))

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description")
    table.add_row("list", "List issues with optional filters")
    table.add_row("get", "Get one issue by id or unique prefix")
    table.add_row("create", "Create a new issue")
    table.add_row("update", "Patch fields (status, tags, routing, priority)")
    table.add_row("claim", "Mark an open issue as in_progress")
    table.add_row("open", "Reopen an issue")
    table.add_row("close", "Close an issue with an outcome")
    table.add_row("dep", "Add dependency edge: blocks or parent")
    table.add_row("undep", "Remove dependency edge")
    table.add_row("children", "List direct children of an issue")
    table.add_row("ready", "List executable leaf issues")
    table.add_row("validate", "Validate DAG completion state for a root")
    console.print(table)
    console.print(Text("Run `inshallah issues <command> --help` for details.", style="dim"))
    _print_next_steps(
        console,
        [
            "inshallah issues ready --root <root-id>",
            "inshallah issues get <issue-id>",
            "inshallah forum read issue:<issue-id> --limit 20",
            "inshallah guide --section workflow",
        ],
    )
    _guide_cross_link(console)
    return 0


def _build_execution_spec(args: argparse.Namespace) -> dict | None:
    spec: dict[str, str] = {}
    if args.role:
        spec["role"] = args.role
    if args.cli:
        spec["cli"] = args.cli
    if args.model:
        spec["model"] = args.model
    if args.reasoning:
        spec["reasoning"] = args.reasoning
    if args.prompt_path:
        spec["prompt_path"] = args.prompt_path
    return spec or None


def _issues_cmd_list(argv: list[str], pretty: bool, console: Console) -> int:
    if argv and argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues list",
            usage="inshallah issues list [--status STATUS] [--tag TAG] [--root ID] [--limit N] [--pretty]",
            about="List issues from the store with optional status, tag, and subtree filtering.",
            options=[
                ("--status", "open | in_progress | closed"),
                ("--tag", "Filter by tag; repeatable"),
                ("--root", "Scope to subtree rooted at this issue"),
                ("--limit", "Limit number of returned issues (default: all)"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "inshallah issues list --status open",
                "inshallah issues list --root inshallah-ab12cd34 --tag node:agent",
            ],
        )

    p = argparse.ArgumentParser(prog="inshallah issues list", add_help=False)
    p.add_argument("--status", choices=("open", "in_progress", "closed"), default=None)
    p.add_argument("--tag", action="append", default=[])
    p.add_argument("--root", default=None)
    p.add_argument("--limit", type=int, default=0)
    args = p.parse_args(argv)

    store = _issues_store()
    issues = store.list(status=args.status)

    if args.tag:
        issues = [issue for issue in issues if all(tag in issue.get("tags", []) for tag in args.tag)]

    if args.root:
        root_id, err = _resolve_issue_id(store, args.root)
        if err:
            return _error(err)
        subtree = set(store.subtree_ids(root_id))
        issues = [issue for issue in issues if issue["id"] in subtree]

    if args.limit > 0:
        issues = issues[-args.limit:]

    _output([_issue_json(issue) for issue in issues], pretty=pretty)
    return 0


def _issues_cmd_get(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues get",
            usage="inshallah issues get <id-or-prefix> [--pretty]",
            about="Fetch a single issue.",
            options=[("--pretty", "Indent JSON output")],
            examples=["inshallah issues get inshallah-ab12cd34", "inshallah issues get inshallah-ab12"],
        )

    store = _issues_store()
    issue_id, err = _resolve_issue_id(store, argv[0])
    if err:
        return _error(err)

    issue = store.get(issue_id)
    if issue is None:
        return _error(f"not found: {argv[0]}")

    _output(_issue_json(issue), pretty=pretty)
    return 0


def _issues_cmd_create(argv: list[str], pretty: bool, console: Console) -> int:
    if argv and argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues create",
            usage=(
                "inshallah issues create <title> [--body TEXT] [--parent ID] [--tag TAG] "
                "[--role ROLE] [--cli NAME] [--model NAME] [--reasoning LEVEL] "
                "[--prompt-path PATH] [--priority N] [--pretty]"
            ),
            about="Create a new issue. Automatically adds the node:agent tag.",
            options=[
                ("--body, -b", "Issue description/body"),
                ("--parent", "Add parent dependency to another issue"),
                ("--tag, -t", "Tag to add; repeatable"),
                ("--role, -r", "Set execution_spec.role"),
                ("--cli", "Set execution_spec.cli"),
                ("--model", "Set execution_spec.model"),
                ("--reasoning", "Set execution_spec.reasoning"),
                ("--prompt-path", "Set execution_spec.prompt_path"),
                ("--priority, -p", "1-5, lower is higher priority (default: 3)"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "inshallah issues create \"Write migration\" -t backend -p 2",
                "inshallah issues create \"Break down root\" --parent inshallah-ab12 --role worker",
            ],
        )

    p = argparse.ArgumentParser(prog="inshallah issues create", add_help=False)
    p.add_argument("title", nargs="?", default=None)
    p.add_argument("--body", "-b", default="")
    p.add_argument("--parent", default=None)
    p.add_argument("--tag", "-t", action="append", default=[])
    p.add_argument("--role", "-r", default=None)
    p.add_argument("--cli", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--reasoning", default=None)
    p.add_argument("--prompt-path", default=None)
    p.add_argument("--priority", "-p", type=int, default=3)
    args = p.parse_args(argv)

    if not args.title:
        return _error(
            "missing title",
            recovery=["inshallah issues create \"Title\" --body \"Details\""],
        )
    if args.priority < 1 or args.priority > 5:
        return _error(
            "priority must be in range 1-5",
            recovery=["inshallah issues create \"Title\" --priority 2"],
        )

    tags = list(dict.fromkeys(args.tag))
    if "node:agent" not in tags:
        tags.append("node:agent")

    execution_spec = _build_execution_spec(args)

    store = _issues_store()
    parent_id = None
    if args.parent:
        parent_id, err = _resolve_issue_id(store, args.parent)
        if err:
            return _error(err)

    issue = store.create(
        args.title,
        body=args.body,
        tags=tags,
        execution_spec=execution_spec,
        priority=args.priority,
    )

    if parent_id:
        store.add_dep(issue["id"], "parent", parent_id)
        issue = store.get(issue["id"])

    _output(_issue_json(issue), pretty=pretty)
    return 0


def _issues_cmd_update(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues update",
            usage=(
                "inshallah issues update <id-or-prefix> [--title TEXT] [--body TEXT] "
                "[--status STATUS] [--outcome OUTCOME] [--priority N] "
                "[--add-tag TAG] [--remove-tag TAG] [--role ROLE] [--cli NAME] "
                "[--model NAME] [--reasoning LEVEL] [--prompt-path PATH] "
                "[--clear-execution-spec] [--pretty]"
            ),
            about="Patch issue fields and routing metadata.",
            options=[
                ("--title", "Update title"),
                ("--body", "Update body"),
                ("--status", "open | in_progress | closed"),
                ("--outcome", "Set outcome label"),
                ("--priority", "Set priority 1-5"),
                ("--add-tag", "Add tag; repeatable"),
                ("--remove-tag", "Remove tag; repeatable"),
                ("--role/--cli/--model/--reasoning/--prompt-path", "Update execution_spec fields"),
                ("--clear-execution-spec", "Clear execution_spec entirely"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "inshallah issues update inshallah-ab12 --status in_progress",
                "inshallah issues update inshallah-ab12 --role worker --model gpt-5.3-codex",
            ],
        )

    p = argparse.ArgumentParser(prog="inshallah issues update", add_help=False)
    p.add_argument("id")
    p.add_argument("--title", default=None)
    p.add_argument("--body", default=None)
    p.add_argument("--status", choices=("open", "in_progress", "closed"), default=None)
    p.add_argument("--outcome", default=None)
    p.add_argument("--priority", type=int, default=None)
    p.add_argument("--add-tag", action="append", default=[])
    p.add_argument("--remove-tag", action="append", default=[])
    p.add_argument("--role", default=None)
    p.add_argument("--cli", default=None)
    p.add_argument("--model", default=None)
    p.add_argument("--reasoning", default=None)
    p.add_argument("--prompt-path", default=None)
    p.add_argument("--clear-execution-spec", action="store_true")
    args = p.parse_args(argv)

    store = _issues_store()
    issue_id, err = _resolve_issue_id(store, args.id)
    if err:
        return _error(err)

    issue = store.get(issue_id)
    if issue is None:
        return _error(
            f"not found: {args.id}",
            recovery=["inshallah issues list --limit 20"],
        )

    if args.priority is not None and (args.priority < 1 or args.priority > 5):
        return _error(
            "priority must be in range 1-5",
            recovery=[f"inshallah issues update {issue_id} --priority 2"],
        )

    fields: dict[str, object] = {}
    if args.title is not None:
        fields["title"] = args.title
    if args.body is not None:
        fields["body"] = args.body
    if args.status is not None:
        fields["status"] = args.status
    if args.outcome is not None:
        fields["outcome"] = args.outcome
    if args.priority is not None:
        fields["priority"] = args.priority

    if args.add_tag or args.remove_tag:
        tags = list(issue.get("tags", []))
        for tag in args.add_tag:
            if tag not in tags:
                tags.append(tag)
        for tag in args.remove_tag:
            tags = [tag for tag in tags if tag not in args.remove_tag]
        fields["tags"] = tags

    routing_touched = any(
        value is not None
        for value in (
            args.role,
            args.cli,
            args.model,
            args.reasoning,
            args.prompt_path,
        )
    )

    if args.clear_execution_spec:
        fields["execution_spec"] = None
    elif routing_touched:
        spec = dict(issue.get("execution_spec") or {})
        if args.role is not None:
            spec["role"] = args.role
        if args.cli is not None:
            spec["cli"] = args.cli
        if args.model is not None:
            spec["model"] = args.model
        if args.reasoning is not None:
            spec["reasoning"] = args.reasoning
        if args.prompt_path is not None:
            spec["prompt_path"] = args.prompt_path
        fields["execution_spec"] = spec or None

    if not fields:
        return _error(
            "no fields to update",
            recovery=[f"inshallah issues update {issue_id} --status in_progress"],
        )

    updated = store.update(issue_id, **fields)
    _output(_issue_json(updated), pretty=pretty)
    return 0


def _issues_cmd_claim(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues claim",
            usage="inshallah issues claim <id-or-prefix> [--pretty]",
            about="Mark an open issue as in_progress.",
            options=[("--pretty", "Indent JSON output")],
            examples=["inshallah issues claim inshallah-ab12"],
        )

    store = _issues_store()
    issue_id, err = _resolve_issue_id(store, argv[0])
    if err:
        return _error(err)

    issue = store.get(issue_id)
    if issue is None:
        return _error(
            f"not found: {argv[0]}",
            recovery=["inshallah issues list --status open --limit 20"],
        )
    if issue["status"] != "open":
        return _error(
            f"cannot claim issue in status={issue['status']}",
            recovery=[
                f"inshallah issues get {issue_id}",
                f"inshallah issues update {issue_id} --status open",
            ],
        )

    store.claim(issue_id)
    claimed = store.get(issue_id)
    _output(_issue_json(claimed), pretty=pretty)
    return 0


def _issues_cmd_open(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues open",
            usage="inshallah issues open <id-or-prefix> [--pretty]",
            about="Reopen an issue and clear outcome.",
            options=[("--pretty", "Indent JSON output")],
            examples=["inshallah issues open inshallah-ab12"],
        )

    store = _issues_store()
    issue_id, err = _resolve_issue_id(store, argv[0])
    if err:
        return _error(err)

    issue = store.get(issue_id)
    if issue is None:
        return _error(
            f"not found: {argv[0]}",
            recovery=["inshallah issues list --limit 20"],
        )

    reopened = store.update(issue_id, status="open", outcome=None)
    _output(_issue_json(reopened), pretty=pretty)
    return 0


def _issues_cmd_close(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues close",
            usage="inshallah issues close <id-or-prefix> [--outcome OUTCOME] [--pretty]",
            about="Close an issue.",
            options=[
                ("--outcome", "success | failure | needs_work | skipped | expanded (default: success)"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=["inshallah issues close inshallah-ab12 --outcome expanded"],
        )

    issue_id_raw = argv[0]
    p = argparse.ArgumentParser(prog="inshallah issues close", add_help=False)
    p.add_argument("--outcome", default="success")
    args = p.parse_args(argv[1:])

    store = _issues_store()
    issue_id, err = _resolve_issue_id(store, issue_id_raw)
    if err:
        return _error(err)

    issue = store.close(issue_id, outcome=args.outcome)
    _output(_issue_json(issue), pretty=pretty)
    return 0


def _issues_cmd_dep(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues dep",
            usage="inshallah issues dep <src-id> <blocks|parent> <dst-id> [--pretty]",
            about="Add a dependency edge between two issues.",
            options=[
                ("blocks", "Source must close before destination is ready"),
                ("parent", "Source becomes child of destination"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "inshallah issues dep inshallah-a1 blocks inshallah-b2",
                "inshallah issues dep inshallah-child parent inshallah-root",
            ],
        )

    if len(argv) < 3:
        return _error(
            "usage: inshallah issues dep <src> <type> <dst>",
            recovery=["inshallah issues dep <src-id> blocks <dst-id>"],
        )

    src_raw, dep_type, dst_raw = argv[0], argv[1], argv[2]
    if dep_type not in ("blocks", "parent"):
        return _error(
            f"invalid dep type: {dep_type} (use 'blocks' or 'parent')",
            recovery=[
                "inshallah issues dep <src-id> blocks <dst-id>",
                "inshallah issues dep <child-id> parent <parent-id>",
            ],
        )

    store = _issues_store()
    src, err = _resolve_issue_id(store, src_raw)
    if err:
        return _error(err)
    dst, err = _resolve_issue_id(store, dst_raw)
    if err:
        return _error(err)

    if src == dst:
        return _error(
            "source and destination must be different",
            recovery=["inshallah issues dep <src-id> blocks <dst-id>"],
        )

    store.add_dep(src, dep_type, dst)
    _output({"ok": True, "src": src, "type": dep_type, "dst": dst}, pretty=pretty)
    return 0


def _issues_cmd_undep(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues undep",
            usage="inshallah issues undep <src-id> <blocks|parent> <dst-id> [--pretty]",
            about="Remove a dependency edge.",
            options=[("--pretty", "Indent JSON output")],
            examples=["inshallah issues undep inshallah-a1 blocks inshallah-b2"],
        )

    if len(argv) < 3:
        return _error(
            "usage: inshallah issues undep <src> <type> <dst>",
            recovery=["inshallah issues undep <src-id> blocks <dst-id>"],
        )

    src_raw, dep_type, dst_raw = argv[0], argv[1], argv[2]
    if dep_type not in ("blocks", "parent"):
        return _error(
            f"invalid dep type: {dep_type} (use 'blocks' or 'parent')",
            recovery=["inshallah issues undep <src-id> blocks <dst-id>"],
        )

    store = _issues_store()
    src, err = _resolve_issue_id(store, src_raw)
    if err:
        return _error(err)
    dst, err = _resolve_issue_id(store, dst_raw)
    if err:
        return _error(err)

    removed = store.remove_dep(src, dep_type, dst)
    _output({"ok": removed, "src": src, "type": dep_type, "dst": dst}, pretty=pretty)
    return 0


def _issues_cmd_children(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues children",
            usage="inshallah issues children <id-or-prefix> [--pretty]",
            about="List direct child issues.",
            options=[("--pretty", "Indent JSON output")],
            examples=["inshallah issues children inshallah-root12"],
        )

    store = _issues_store()
    parent_id, err = _resolve_issue_id(store, argv[0])
    if err:
        return _error(err)

    children = store.children(parent_id)
    children.sort(key=lambda issue: issue.get("priority", 3))
    _output([_issue_json(issue) for issue in children], pretty=pretty)
    return 0


def _issues_cmd_ready(argv: list[str], pretty: bool, console: Console) -> int:
    if argv and argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues ready",
            usage="inshallah issues ready [--root ID] [--tag TAG] [--pretty]",
            about="List open, unblocked, leaf issues tagged node:agent.",
            options=[
                ("--root", "Scope to subtree rooted at this issue"),
                ("--tag", "Additional required tag; repeatable"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "inshallah issues ready",
                "inshallah issues ready --root inshallah-ab12 --tag backend",
            ],
        )

    p = argparse.ArgumentParser(prog="inshallah issues ready", add_help=False)
    p.add_argument("--root", default=None)
    p.add_argument("--tag", action="append", default=[])
    args = p.parse_args(argv)

    store = _issues_store()

    root_id = None
    if args.root:
        root_id, err = _resolve_issue_id(store, args.root)
        if err:
            return _error(err)

    tags = ["node:agent", *args.tag]
    issues = store.ready(root_id, tags=tags)
    _output([_issue_json(issue) for issue in issues], pretty=pretty)
    return 0


def _issues_cmd_validate(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah issues validate",
            usage="inshallah issues validate <root-id-or-prefix> [--pretty]",
            about="Check if a DAG root has reached a final terminal condition.",
            options=[("--pretty", "Indent JSON output")],
            examples=["inshallah issues validate inshallah-root12"],
        )

    store = _issues_store()
    root_id, err = _resolve_issue_id(store, argv[0])
    if err:
        return _error(err)

    result = store.validate(root_id)
    _output(
        {
            "root_id": root_id,
            "is_final": result.is_final,
            "reason": result.reason,
        },
        pretty=pretty,
    )
    return 0


_ISSUES_SUBCMDS: dict[str, tuple[Callable[[list[str], bool, Console], int], str]] = {
    "list": (_issues_cmd_list, "List issues with optional filters"),
    "get": (_issues_cmd_get, "Get one issue by id or prefix"),
    "create": (_issues_cmd_create, "Create an issue"),
    "update": (_issues_cmd_update, "Update issue fields"),
    "claim": (_issues_cmd_claim, "Mark an issue in_progress"),
    "open": (_issues_cmd_open, "Reopen an issue"),
    "close": (_issues_cmd_close, "Close an issue"),
    "dep": (_issues_cmd_dep, "Add a dependency edge"),
    "undep": (_issues_cmd_undep, "Remove a dependency edge"),
    "children": (_issues_cmd_children, "List direct child issues"),
    "ready": (_issues_cmd_ready, "List executable leaf issues"),
    "validate": (_issues_cmd_validate, "Validate root completion state"),
}


def cmd_issues(argv: list[str], console: Console | None = None) -> int:
    """Dispatch inshallah issues subcommands."""
    pretty = "--pretty" in argv
    argv = [arg for arg in argv if arg != "--pretty"]

    console = console or Console()

    if not argv or argv[0] in ("-h", "--help"):
        return _print_issues_help(console)

    sub = argv[0]
    entry = _ISSUES_SUBCMDS.get(sub)
    if entry is None:
        return _error(
            f"unknown subcommand: {sub}",
            recovery=["inshallah issues --help", "inshallah guide --section workflow"],
        )

    handler, _ = entry
    return handler(argv[1:], pretty, console)


# ---------------------------------------------------------------------------
# Forum CLI
# ---------------------------------------------------------------------------


def _forum_store() -> ForumStore:
    return ForumStore.from_workdir(_find_repo_root())


def _print_forum_help(console: Console) -> int:
    console.print(Panel.fit(
        "Forum messages for cross-agent coordination. Data commands return JSON.",
        title="inshallah forum",
        border_style="cyan",
    ))

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description")
    table.add_row("post", "Post a message to a topic")
    table.add_row("read", "Read recent messages from a topic")
    table.add_row("topics", "List topics with message counts and latest activity")
    console.print(table)
    console.print(Text("Run `inshallah forum <command> --help` for details.", style="dim"))
    _print_next_steps(
        console,
        [
            "inshallah forum read issue:<issue-id> --limit 20",
            "inshallah forum post issue:<issue-id> -m \"status update\" --author worker",
            "inshallah guide --section workflow",
        ],
    )
    _guide_cross_link(console)
    return 0


def _forum_cmd_post(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah forum post",
            usage="inshallah forum post <topic> -m <message> [--author NAME] [--pretty]",
            about="Post a message to a forum topic.",
            options=[
                ("<topic>", "Topic key, e.g. issue:<id> or research:roles"),
                ("-m, --message", "Message body (required)"),
                ("--author", "Author id (default: system)"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "inshallah forum post issue:inshallah-ab12 -m \"Waiting on DB migration\" --author worker",
            ],
        )

    p = argparse.ArgumentParser(prog="inshallah forum post", add_help=False)
    p.add_argument("topic")
    p.add_argument("--message", "-m", required=True)
    p.add_argument("--author", default="system")
    args = p.parse_args(argv)

    store = _forum_store()
    msg = store.post(args.topic, args.message, author=args.author)
    _output(msg, pretty=pretty)
    return 0


def _forum_cmd_read(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah forum read",
            usage="inshallah forum read <topic> [--limit N] [--pretty]",
            about="Read messages from a topic in chronological order.",
            options=[
                ("--limit", "Maximum messages to return (default: 50)"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=["inshallah forum read issue:inshallah-ab12 --limit 20"],
        )

    p = argparse.ArgumentParser(prog="inshallah forum read", add_help=False)
    p.add_argument("topic")
    p.add_argument("--limit", type=int, default=50)
    args = p.parse_args(argv)

    if args.limit < 1:
        return _error(
            "limit must be >= 1",
            recovery=["inshallah forum read issue:<issue-id> --limit 20"],
        )

    store = _forum_store()
    msgs = store.read(args.topic, limit=args.limit)
    _output(msgs, pretty=pretty)
    return 0


def _forum_cmd_topics(argv: list[str], pretty: bool, console: Console) -> int:
    if argv and argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah forum topics",
            usage="inshallah forum topics [--prefix PREFIX] [--limit N] [--pretty]",
            about="List active forum topics sorted by most recent message.",
            options=[
                ("--prefix", "Only include topics starting with this prefix"),
                ("--limit", "Maximum topics to return (default: 100)"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "inshallah forum topics",
                "inshallah forum topics --prefix issue: --limit 20",
            ],
        )

    p = argparse.ArgumentParser(prog="inshallah forum topics", add_help=False)
    p.add_argument("--prefix", default=None)
    p.add_argument("--limit", type=int, default=100)
    args = p.parse_args(argv)

    if args.limit < 1:
        return _error(
            "limit must be >= 1",
            recovery=["inshallah forum topics --limit 20"],
        )

    store = _forum_store()
    topics = store.topics(prefix=args.prefix)
    if args.limit > 0:
        topics = topics[: args.limit]
    _output(topics, pretty=pretty)
    return 0


_FORUM_SUBCMDS: dict[str, tuple[Callable[[list[str], bool, Console], int], str]] = {
    "post": (_forum_cmd_post, "Post a message to a topic"),
    "read": (_forum_cmd_read, "Read messages from a topic"),
    "topics": (_forum_cmd_topics, "List forum topics"),
}


def cmd_forum(argv: list[str], console: Console | None = None) -> int:
    """Dispatch inshallah forum subcommands."""
    pretty = "--pretty" in argv
    argv = [arg for arg in argv if arg != "--pretty"]

    console = console or Console()

    if not argv or argv[0] in ("-h", "--help"):
        return _print_forum_help(console)

    sub = argv[0]
    entry = _FORUM_SUBCMDS.get(sub)
    if entry is None:
        return _error(
            f"unknown subcommand: {sub}",
            recovery=["inshallah forum --help", "inshallah guide --section workflow"],
        )

    handler, _ = entry
    return handler(argv[1:], pretty, console)


# ---------------------------------------------------------------------------
# Guide command
# ---------------------------------------------------------------------------


_GUIDE_CONCEPTS: list[tuple[str, str, str]] = [
    (
        "issue",
        "A tracked unit of work in the DAG. Root issues represent goals; child issues represent decomposed tasks.",
        "inshallah issues get <id> (shows status, deps, role routing, and outcome).",
    ),
    (
        "parent edge",
        "Hierarchy edge from child to parent (`child --parent--> parent`).",
        "inshallah issues children <parent-id> (shows direct children).",
    ),
    (
        "blocks edge",
        "Ordering edge from prerequisite to dependent (`a --blocks--> b`). `b` is not ready until `a` closes.",
        "inshallah issues dep <a> blocks <b> (creates ordering).",
    ),
    (
        "leaf issue",
        "An issue with no open children. Leaves are executable work items.",
        "inshallah issues ready --root <root-id> (returns executable leaves only).",
    ),
    (
        "ready issue",
        "An open, unblocked leaf issue tagged `node:agent`.",
        "inshallah issues ready --root <root-id> (current queue).",
    ),
    (
        "roles",
        "Routing metadata for which agent prompt/config should execute an issue (for example `worker` or `reviewer`).",
        "inshallah roles --table and inshallah issues update <id> --role <name>.",
    ),
    (
        "statuses",
        "`open` (queued), `in_progress` (claimed), `closed` (finished with an outcome).",
        "inshallah issues update <id> --status in_progress.",
    ),
    (
        "outcomes",
        "`success`, `failure`, `needs_work`, `skipped`, `expanded` (decomposed into child work).",
        "inshallah issues close <id> --outcome expanded.",
    ),
]


_GUIDE_WORKFLOW: list[tuple[str, str, str]] = [
    (
        "Initialize state",
        "inshallah init",
        "Creates `.inshallah/` stores, prompt templates, role files, and logs directory.",
    ),
    (
        "Inspect execution roles",
        "inshallah roles --table",
        "Shows available role templates and routing defaults (`cli`, `model`, `reasoning`).",
    ),
    (
        "Start orchestration",
        "inshallah run \"Break down and execute this goal\"",
        "Creates a root issue and starts the DAG loop.",
    ),
    (
        "Observe decomposition",
        "inshallah issues children <root-id>",
        "Shows child issues created by the orchestrator via `parent` edges.",
    ),
    (
        "Pick executable work",
        "inshallah issues ready --root <root-id>",
        "Lists the current ready queue (open + unblocked + leaf).",
    ),
    (
        "Execute one atomic issue",
        "inshallah issues get <issue-id> && inshallah forum read issue:<issue-id> --limit 20",
        "Gives full issue context plus recent coordination notes before running the assigned role.",
    ),
    (
        "Close or expand work",
        "inshallah issues close <issue-id> --outcome success",
        "Workers close with terminal outcomes; orchestrators close with `expanded` after decomposition.",
    ),
    (
        "Review pass (optional role)",
        "inshallah forum read issue:<issue-id> --limit 50",
        "Reviewer activity is logged in the issue topic; reviewer can keep success or mark needs_work so the orchestrator expands targeted fixes.",
    ),
    (
        "Validate DAG completion",
        "inshallah issues validate <root-id>",
        "Returns `is_final` and `reason` so you know whether work is done or still in progress.",
    ),
]


def _print_guide_plain(console: Console, section: str) -> None:
    console.print("inshallah guide")
    console.print("Mental model and workflow for running inshallah from CLI only.")

    if section in ("all", "concepts"):
        console.print("")
        console.print("Core concepts")
        for concept, meaning, signal in _GUIDE_CONCEPTS:
            console.print(f"- {concept}: {meaning}")
            console.print(f"  command signal: {signal}")

    if section in ("all", "workflow"):
        console.print("")
        console.print("End-to-end workflow")
        for idx, (step, command, interpretation) in enumerate(_GUIDE_WORKFLOW, start=1):
            console.print(f"{idx}. {step}")
            console.print(f"   command: {command}")
            console.print(f"   interpretation: {interpretation}")


def _print_guide_rich(console: Console, section: str) -> None:
    console.print(
        Panel.fit(
            "Understand inshallah's DAG model and execute the full workflow from the CLI.",
            title="inshallah guide",
            border_style="cyan",
        )
    )

    if section in ("all", "concepts"):
        concepts = Table(title="Core Concepts", show_edge=False, pad_edge=False)
        concepts.add_column("Concept", style="bold cyan")
        concepts.add_column("Meaning")
        concepts.add_column("Command Signal", style="dim")
        for concept, meaning, signal in _GUIDE_CONCEPTS:
            concepts.add_row(concept, meaning, signal)
        console.print(concepts)

    if section in ("all", "workflow"):
        flow = Table(title="Workflow", show_edge=False, pad_edge=False)
        flow.add_column("Step", style="bold")
        flow.add_column("Command", style="bold cyan")
        flow.add_column("Interpretation")
        for idx, (step, command, interpretation) in enumerate(_GUIDE_WORKFLOW, start=1):
            flow.add_row(str(idx), command, f"{step}: {interpretation}")
        console.print(flow)

    console.print(
        Text(
            "Tip: `inshallah issues ready --root <root-id>` is the executable queue; "
            "`inshallah issues validate <root-id>` is the completion gate.",
            style="dim",
        )
    )


def cmd_guide(argv: list[str], console: Console | None = None) -> int:
    console = console or Console()
    if argv and argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="inshallah guide",
            usage="inshallah guide [--section all|concepts|workflow] [--plain]",
            about="Show an in-CLI onboarding guide for inshallah mental model and workflow.",
            options=[
                ("--section", "all | concepts | workflow (default: all)"),
                ("--plain", "Force plain text rendering"),
            ],
            examples=[
                "inshallah guide",
                "inshallah guide --section concepts",
                "inshallah guide --plain",
            ],
            include_guide=False,
        )

    p = argparse.ArgumentParser(prog="inshallah guide", add_help=False)
    p.add_argument("--section", choices=("all", "concepts", "workflow"), default="all")
    p.add_argument("--plain", action="store_true")
    args = p.parse_args(argv)

    plain = args.plain or not console.is_terminal
    if plain:
        _print_guide_plain(console, args.section)
    else:
        _print_guide_rich(console, args.section)
    return 0


# ---------------------------------------------------------------------------
# Top-level help and dispatch
# ---------------------------------------------------------------------------


def _print_help(console: Console) -> None:
    help_text = Text()
    help_text.append("inshallah", style="bold")
    help_text.append(f" {__version__}", style="dim")
    help_text.append(" - DAG-based loop runner for agentic workflows")
    console.print(help_text)
    console.print()

    cmds = Table(show_header=False, expand=False, show_edge=False, pad_edge=False, box=None)
    cmds.add_column("Command", style="bold cyan")
    cmds.add_column("Description")
    cmds.add_row("inshallah init", "Initialize .inshallah state, templates, and logs")
    cmds.add_row("inshallah guide", "Show mental model + workflow onboarding guide")
    cmds.add_row("inshallah status", "Summarize roots, ready work, roles, and forum activity")
    cmds.add_row("inshallah run <prompt>", "Create root issue and run the DAG")
    cmds.add_row("inshallah resume <root-id>", "Resume an interrupted DAG run")
    cmds.add_row("inshallah replay <issue-id>", "Replay a logged backend run")
    cmds.add_row("inshallah roles", "List role templates (JSON by default)")
    cmds.add_row("inshallah issues <command>", "Issue DAG operations (create/update/close/deps/ready)")
    cmds.add_row("inshallah forum <command>", "Forum operations (post/read/topics)")
    cmds.add_row("inshallah serve", "Start the web interface")
    console.print(cmds)
    console.print()

    quick = Table(title="Quick Start", show_header=False, expand=False, show_edge=False, pad_edge=False)
    quick.add_column("Step", style="bold")
    quick.add_column("Command")
    quick.add_row("1", "inshallah init")
    quick.add_row("2", "inshallah guide")
    quick.add_row("3", "inshallah roles --table")
    quick.add_row("4", "inshallah run \"Break down and execute this goal\"")
    quick.add_row("5", "inshallah issues ready --root <root-id>")
    console.print(quick)
    console.print(Text("Run `inshallah <command> --help` for command-specific details.", style="dim"))
    _guide_cross_link(console)


def _dispatch_prompt_shorthand(raw: list[str], console: Console) -> int:
    """Support legacy shorthand: inshallah <prompt words...>."""
    args = _run_parser(prog="inshallah").parse_args(raw)
    return cmd_run(args, console)



def main(argv: list[str] | None = None) -> None:
    raw = argv if argv is not None else sys.argv[1:]
    console = Console()

    if "--version" in raw:
        console.print(Text(f"inshallah {__version__}", style="bold"))
        sys.exit(0)

    if not raw or raw == ["--help"] or raw == ["-h"]:
        _print_help(console)
        sys.exit(0)

    command = raw[0]

    if command == "init":
        sys.exit(cmd_init(console, force="--force" in raw[1:]))

    if command == "guide":
        sys.exit(cmd_guide(raw[1:], console))

    if command == "status":
        sys.exit(cmd_status(raw[1:], console))

    if command == "run":
        args = _run_parser().parse_args(raw[1:])
        sys.exit(cmd_run(args, console))

    if command == "roles":
        sys.exit(cmd_roles(raw[1:], console))

    if command == "issues":
        sys.exit(cmd_issues(raw[1:], console))

    if command == "forum":
        sys.exit(cmd_forum(raw[1:], console))

    if command == "replay":
        sys.exit(cmd_replay(raw[1:], console))

    if command == "resume":
        sys.exit(cmd_resume(raw[1:], console))

    if command == "serve":
        sys.exit(cmd_serve(raw[1:], console))

    # Default: treat unknown args as a run prompt.
    sys.exit(_dispatch_prompt_shorthand(raw, console))


if __name__ == "__main__":
    main()
