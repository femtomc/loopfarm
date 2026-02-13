"""CLI entry point for loopfarm."""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Callable

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .dag import DagRunner
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


def _run_parser(prog: str = "loopfarm run") -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog, add_help=False)
    p.add_argument("prompt", nargs="*")
    p.add_argument("--max-steps", type=int, default=20)
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


def _error(msg: str) -> int:
    _output({"error": msg})
    return 1


def _print_command_help(
    console: Console,
    *,
    title: str,
    usage: str,
    about: str,
    options: list[tuple[str, str]],
    examples: list[str],
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
    return 0


# ---------------------------------------------------------------------------
# Setup / run orchestration commands
# ---------------------------------------------------------------------------


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
            "description: Plan and decompose root goals into atomic issues, assign the best role to each issue, and manage dependency order.\n"
            "cli: codex\n"
            "model: gpt-5.3-codex\n"
            "reasoning: xhigh\n"
            "---\n\n"
            "You are the hierarchical orchestrator for the issue DAG.\n\n"
            "User prompt:\n\n"
            "{{PROMPT}}\n\n"
            "## Available Roles\n\n"
            "{{ROLES}}\n\n"
            "## Responsibilities\n\n"
            "1. Decide whether the selected issue is atomic.\n"
            "2. If not atomic, decompose into child issues with `outcome=expanded`.\n"
            "3. Assign a role to each child via `execution_spec.role`.\n"
            "4. Use `blocks` dependencies for sequential ordering.\n"
            "5. Keep decomposition deterministic and minimal.\n\n"
            "## CLI Quick Reference\n\n"
            "```bash\n"
            "# Inspect graph state\n"
            "loopfarm issues get <id>\n"
            "loopfarm issues list --root <root-id>\n"
            "loopfarm issues children <id>\n"
            "loopfarm issues ready --root <root-id>\n"
            "loopfarm issues validate <root-id>\n"
            "loopfarm roles --pretty\n\n"
            "# Decompose work\n"
            "loopfarm issues create \"Title\" --body \"Details\" --parent <id> --role worker --priority 2\n"
            "loopfarm issues dep <src-id> blocks <dst-id>\n"
            "loopfarm issues update <id> --role worker\n"
            "loopfarm issues close <id> --outcome expanded\n\n"
            "# Collaborate\n"
            "loopfarm forum post issue:<id> -m \"notes\" --author orchestrator\n"
            "loopfarm forum read issue:<id> --limit 20\n"
            "```\n"
        )

    roles_dir = lf / "roles"
    roles_dir.mkdir(exist_ok=True)
    worker = roles_dir / "worker.md"
    if not worker.exists():
        worker.write_text(
            "---\n"
            "description: Best for concrete execution tasks; implement exactly one atomic issue (code/tests/docs), verify results, then close with a terminal outcome.\n"
            "cli: codex\n"
            "model: gpt-5.3-codex\n"
            "reasoning: xhigh\n"
            "---\n\n"
            "You are a worker role executing one atomic issue.\n\n"
            "User prompt:\n\n"
            "{{PROMPT}}\n\n"
            "## Responsibilities\n\n"
            "1. Execute exactly one selected atomic issue end-to-end.\n"
            "2. Keep scope tight to the selected issue.\n"
            "3. Close with a terminal outcome: success, failure, or skipped.\n\n"
            "## CLI Quick Reference\n\n"
            "```bash\n"
            "loopfarm issues get <id>\n"
            "loopfarm issues update <id> --status in_progress\n"
            "loopfarm forum post issue:<id> -m \"status update\" --author worker\n"
            "loopfarm issues close <id> --outcome success\n"
            "```\n"
        )

    (lf / "logs").mkdir(exist_ok=True)
    console.print(
        Panel(
            f"Initialized [bold].loopfarm/[/bold] in {root}",
            style="green",
            expand=False,
        )
    )
    return 0


def cmd_serve(argv: list[str], console: Console) -> int:
    if argv and argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="loopfarm serve",
            usage="loopfarm serve [--host HOST] [--port PORT] [--reload]",
            about="Start the loopfarm web interface.",
            options=[
                ("--host", "Bind address (default: 127.0.0.1)"),
                ("--port", "Bind port (default: 8420)"),
                ("--reload", "Enable auto-reload for development"),
            ],
            examples=["loopfarm serve", "loopfarm serve --port 9000 --reload"],
        )

    p = argparse.ArgumentParser(prog="loopfarm serve", add_help=False)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8420)
    p.add_argument("--reload", action="store_true")
    args = p.parse_args(argv)

    try:
        import uvicorn
    except ImportError:
        console.print(
            "[red]Missing web dependencies.[/red] "
            "Install with: [bold]pip install loopfarm\\[web][/bold]"
        )
        return 1

    console.print(
        Panel(
            f"Starting web server at [bold]http://{args.host}:{args.port}[/bold]",
            title="loopfarm serve",
            style="cyan",
            expand=False,
        )
    )

    uvicorn.run(
        "loopfarm.web:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        reload=args.reload,
    )
    return 0


def cmd_replay(argv: list[str], console: Console) -> int:
    root = _find_repo_root()
    logs_dir = root / ".loopfarm" / "logs"

    if not argv or argv[0] in ("-h", "--help"):
        console.print("[bold]loopfarm replay[/bold] - replay a logged run\n")
        console.print("  loopfarm replay [dim]<issue-id|path>[/dim] [dim][--backend codex|claude|opencode|pi|gemini][/dim]\n")
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
        console.print("[bold]loopfarm resume[/bold] - resume an interrupted DAG\n")
        console.print("  loopfarm resume [dim]<root-id>[/dim] [dim][--max-steps N][/dim]\n")
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
        return 0

    issue_id = argv[0]
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--max-steps", type=int, default=20)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv[1:])

    issue = store.get(issue_id)
    if issue is None:
        candidates = [candidate for candidate in store.list() if candidate["id"].startswith(issue_id)]
        if len(candidates) == 1:
            issue = candidates[0]
        elif len(candidates) > 1:
            console.print(Text(f"Ambiguous prefix '{issue_id}'", style="red"))
            for candidate in candidates:
                console.print(f"  {candidate['id']}")
            return 1
    if issue is None:
        console.print(Text(f"Issue not found: {issue_id}", style="red"))
        return 1

    root_id = issue["id"]

    reset = store.reset_in_progress(root_id)
    if reset:
        console.print(
            Panel(
                f"Reset {len(reset)} stale issue(s) to open: " + ", ".join(reset),
                style="yellow",
                expand=False,
            )
        )

    console.print(
        Panel(
            f"Resuming [bold]{root_id}[/bold] - {issue['title'][:80]}",
            style="cyan",
            expand=False,
        )
    )

    runner = DagRunner(store, forum, root, console=console)
    result = runner.run(root_id, max_steps=args.max_steps)

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

    console.print(Panel.fit(f"Repo: {root}", title="loopfarm status", border_style="cyan"))

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

    return 0


def cmd_run(args: argparse.Namespace, console: Console) -> int:
    root = _find_repo_root()
    store = IssueStore.from_workdir(root)
    forum = ForumStore.from_workdir(root)

    prompt_text = " ".join(args.prompt)
    if not prompt_text:
        console.print(Text("No prompt provided.", style="red"))
        return 1

    root_issue = store.create(prompt_text, tags=["node:agent", "node:root"])
    console.print(
        Panel(
            f"[bold]{root_issue['id']}[/bold] - {prompt_text[:80]}",
            title="Root Issue",
            style="cyan",
            expand=False,
        )
    )

    runner = DagRunner(store, forum, root, console=console)
    result = runner.run(root_issue["id"], max_steps=args.max_steps)

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

    return 0 if result.status == "root_final" else 1


def cmd_roles(argv: list[str], console: Console | None = None) -> int:
    console = console or Console()
    if argv and argv[0] in ("-h", "--help"):
        console.print(Panel.fit(
            "List available role templates from .loopfarm/roles/*.md.",
            title="loopfarm roles",
            border_style="cyan",
        ))
        console.print("Usage: loopfarm roles [--json] [--table] [--pretty]")
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
        return None, f"not found: {raw_id}"
    if len(matches) > 1:
        sample = ", ".join(matches[:5])
        suffix = "..." if len(matches) > 5 else ""
        return None, f"ambiguous id prefix: {raw_id} ({sample}{suffix})"
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
        title="loopfarm issues",
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
    console.print(Text("Run `loopfarm issues <command> --help` for details.", style="dim"))
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
            title="loopfarm issues list",
            usage="loopfarm issues list [--status STATUS] [--tag TAG] [--root ID] [--limit N] [--pretty]",
            about="List issues from the store with optional status, tag, and subtree filtering.",
            options=[
                ("--status", "open | in_progress | closed"),
                ("--tag", "Filter by tag; repeatable"),
                ("--root", "Scope to subtree rooted at this issue"),
                ("--limit", "Limit number of returned issues (default: all)"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "loopfarm issues list --status open",
                "loopfarm issues list --root loopfarm-ab12cd34 --tag node:agent",
            ],
        )

    p = argparse.ArgumentParser(prog="loopfarm issues list", add_help=False)
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
            title="loopfarm issues get",
            usage="loopfarm issues get <id-or-prefix> [--pretty]",
            about="Fetch a single issue.",
            options=[("--pretty", "Indent JSON output")],
            examples=["loopfarm issues get loopfarm-ab12cd34", "loopfarm issues get loopfarm-ab12"],
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
            title="loopfarm issues create",
            usage=(
                "loopfarm issues create <title> [--body TEXT] [--parent ID] [--tag TAG] "
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
                "loopfarm issues create \"Write migration\" -t backend -p 2",
                "loopfarm issues create \"Break down root\" --parent loopfarm-ab12 --role worker",
            ],
        )

    p = argparse.ArgumentParser(prog="loopfarm issues create", add_help=False)
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
        return _error("missing title")
    if args.priority < 1 or args.priority > 5:
        return _error("priority must be in range 1-5")

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
            title="loopfarm issues update",
            usage=(
                "loopfarm issues update <id-or-prefix> [--title TEXT] [--body TEXT] "
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
                "loopfarm issues update loopfarm-ab12 --status in_progress",
                "loopfarm issues update loopfarm-ab12 --role worker --model gpt-5.3-codex",
            ],
        )

    p = argparse.ArgumentParser(prog="loopfarm issues update", add_help=False)
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
        return _error(f"not found: {args.id}")

    if args.priority is not None and (args.priority < 1 or args.priority > 5):
        return _error("priority must be in range 1-5")

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
        return _error("no fields to update")

    updated = store.update(issue_id, **fields)
    _output(_issue_json(updated), pretty=pretty)
    return 0


def _issues_cmd_claim(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="loopfarm issues claim",
            usage="loopfarm issues claim <id-or-prefix> [--pretty]",
            about="Mark an open issue as in_progress.",
            options=[("--pretty", "Indent JSON output")],
            examples=["loopfarm issues claim loopfarm-ab12"],
        )

    store = _issues_store()
    issue_id, err = _resolve_issue_id(store, argv[0])
    if err:
        return _error(err)

    issue = store.get(issue_id)
    if issue is None:
        return _error(f"not found: {argv[0]}")
    if issue["status"] != "open":
        return _error(f"cannot claim issue in status={issue['status']}")

    store.claim(issue_id)
    claimed = store.get(issue_id)
    _output(_issue_json(claimed), pretty=pretty)
    return 0


def _issues_cmd_open(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="loopfarm issues open",
            usage="loopfarm issues open <id-or-prefix> [--pretty]",
            about="Reopen an issue and clear outcome.",
            options=[("--pretty", "Indent JSON output")],
            examples=["loopfarm issues open loopfarm-ab12"],
        )

    store = _issues_store()
    issue_id, err = _resolve_issue_id(store, argv[0])
    if err:
        return _error(err)

    issue = store.get(issue_id)
    if issue is None:
        return _error(f"not found: {argv[0]}")

    reopened = store.update(issue_id, status="open", outcome=None)
    _output(_issue_json(reopened), pretty=pretty)
    return 0


def _issues_cmd_close(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="loopfarm issues close",
            usage="loopfarm issues close <id-or-prefix> [--outcome OUTCOME] [--pretty]",
            about="Close an issue.",
            options=[
                ("--outcome", "success | failure | skipped | expanded (default: success)"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=["loopfarm issues close loopfarm-ab12 --outcome expanded"],
        )

    issue_id_raw = argv[0]
    p = argparse.ArgumentParser(prog="loopfarm issues close", add_help=False)
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
            title="loopfarm issues dep",
            usage="loopfarm issues dep <src-id> <blocks|parent> <dst-id> [--pretty]",
            about="Add a dependency edge between two issues.",
            options=[
                ("blocks", "Source must close before destination is ready"),
                ("parent", "Source becomes child of destination"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "loopfarm issues dep loopfarm-a1 blocks loopfarm-b2",
                "loopfarm issues dep loopfarm-child parent loopfarm-root",
            ],
        )

    if len(argv) < 3:
        return _error("usage: loopfarm issues dep <src> <type> <dst>")

    src_raw, dep_type, dst_raw = argv[0], argv[1], argv[2]
    if dep_type not in ("blocks", "parent"):
        return _error(f"invalid dep type: {dep_type} (use 'blocks' or 'parent')")

    store = _issues_store()
    src, err = _resolve_issue_id(store, src_raw)
    if err:
        return _error(err)
    dst, err = _resolve_issue_id(store, dst_raw)
    if err:
        return _error(err)

    if src == dst:
        return _error("source and destination must be different")

    store.add_dep(src, dep_type, dst)
    _output({"ok": True, "src": src, "type": dep_type, "dst": dst}, pretty=pretty)
    return 0


def _issues_cmd_undep(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="loopfarm issues undep",
            usage="loopfarm issues undep <src-id> <blocks|parent> <dst-id> [--pretty]",
            about="Remove a dependency edge.",
            options=[("--pretty", "Indent JSON output")],
            examples=["loopfarm issues undep loopfarm-a1 blocks loopfarm-b2"],
        )

    if len(argv) < 3:
        return _error("usage: loopfarm issues undep <src> <type> <dst>")

    src_raw, dep_type, dst_raw = argv[0], argv[1], argv[2]
    if dep_type not in ("blocks", "parent"):
        return _error(f"invalid dep type: {dep_type} (use 'blocks' or 'parent')")

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
            title="loopfarm issues children",
            usage="loopfarm issues children <id-or-prefix> [--pretty]",
            about="List direct child issues.",
            options=[("--pretty", "Indent JSON output")],
            examples=["loopfarm issues children loopfarm-root12"],
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
            title="loopfarm issues ready",
            usage="loopfarm issues ready [--root ID] [--tag TAG] [--pretty]",
            about="List open, unblocked, leaf issues tagged node:agent.",
            options=[
                ("--root", "Scope to subtree rooted at this issue"),
                ("--tag", "Additional required tag; repeatable"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "loopfarm issues ready",
                "loopfarm issues ready --root loopfarm-ab12 --tag backend",
            ],
        )

    p = argparse.ArgumentParser(prog="loopfarm issues ready", add_help=False)
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
            title="loopfarm issues validate",
            usage="loopfarm issues validate <root-id-or-prefix> [--pretty]",
            about="Check if a DAG root has reached a final terminal condition.",
            options=[("--pretty", "Indent JSON output")],
            examples=["loopfarm issues validate loopfarm-root12"],
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
    """Dispatch loopfarm issues subcommands."""
    pretty = "--pretty" in argv
    argv = [arg for arg in argv if arg != "--pretty"]

    console = console or Console()

    if not argv or argv[0] in ("-h", "--help"):
        return _print_issues_help(console)

    sub = argv[0]
    entry = _ISSUES_SUBCMDS.get(sub)
    if entry is None:
        return _error(f"unknown subcommand: {sub}")

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
        title="loopfarm forum",
        border_style="cyan",
    ))

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column("Command", style="bold cyan")
    table.add_column("Description")
    table.add_row("post", "Post a message to a topic")
    table.add_row("read", "Read recent messages from a topic")
    table.add_row("topics", "List topics with message counts and latest activity")
    console.print(table)
    console.print(Text("Run `loopfarm forum <command> --help` for details.", style="dim"))
    return 0


def _forum_cmd_post(argv: list[str], pretty: bool, console: Console) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="loopfarm forum post",
            usage="loopfarm forum post <topic> -m <message> [--author NAME] [--pretty]",
            about="Post a message to a forum topic.",
            options=[
                ("<topic>", "Topic key, e.g. issue:<id> or research:roles"),
                ("-m, --message", "Message body (required)"),
                ("--author", "Author id (default: system)"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "loopfarm forum post issue:loopfarm-ab12 -m \"Waiting on DB migration\" --author worker",
            ],
        )

    p = argparse.ArgumentParser(prog="loopfarm forum post", add_help=False)
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
            title="loopfarm forum read",
            usage="loopfarm forum read <topic> [--limit N] [--pretty]",
            about="Read messages from a topic in chronological order.",
            options=[
                ("--limit", "Maximum messages to return (default: 50)"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=["loopfarm forum read issue:loopfarm-ab12 --limit 20"],
        )

    p = argparse.ArgumentParser(prog="loopfarm forum read", add_help=False)
    p.add_argument("topic")
    p.add_argument("--limit", type=int, default=50)
    args = p.parse_args(argv)

    if args.limit < 1:
        return _error("limit must be >= 1")

    store = _forum_store()
    msgs = store.read(args.topic, limit=args.limit)
    _output(msgs, pretty=pretty)
    return 0


def _forum_cmd_topics(argv: list[str], pretty: bool, console: Console) -> int:
    if argv and argv[0] in ("-h", "--help"):
        return _print_command_help(
            console,
            title="loopfarm forum topics",
            usage="loopfarm forum topics [--prefix PREFIX] [--limit N] [--pretty]",
            about="List active forum topics sorted by most recent message.",
            options=[
                ("--prefix", "Only include topics starting with this prefix"),
                ("--limit", "Maximum topics to return (default: 100)"),
                ("--pretty", "Indent JSON output"),
            ],
            examples=[
                "loopfarm forum topics",
                "loopfarm forum topics --prefix issue: --limit 20",
            ],
        )

    p = argparse.ArgumentParser(prog="loopfarm forum topics", add_help=False)
    p.add_argument("--prefix", default=None)
    p.add_argument("--limit", type=int, default=100)
    args = p.parse_args(argv)

    if args.limit < 1:
        return _error("limit must be >= 1")

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
    """Dispatch loopfarm forum subcommands."""
    pretty = "--pretty" in argv
    argv = [arg for arg in argv if arg != "--pretty"]

    console = console or Console()

    if not argv or argv[0] in ("-h", "--help"):
        return _print_forum_help(console)

    sub = argv[0]
    entry = _FORUM_SUBCMDS.get(sub)
    if entry is None:
        return _error(f"unknown subcommand: {sub}")

    handler, _ = entry
    return handler(argv[1:], pretty, console)


# ---------------------------------------------------------------------------
# Top-level help and dispatch
# ---------------------------------------------------------------------------


def _print_help(console: Console) -> None:
    help_text = Text()
    help_text.append("loopfarm", style="bold")
    help_text.append(f" {__version__}", style="dim")
    help_text.append(" - DAG-based loop runner for agentic workflows")
    console.print(help_text)
    console.print()

    cmds = Table(show_header=False, expand=False, show_edge=False, pad_edge=False, box=None)
    cmds.add_column("Command", style="bold cyan")
    cmds.add_column("Description")
    cmds.add_row("loopfarm init", "Initialize .loopfarm state, templates, and logs")
    cmds.add_row("loopfarm status", "Summarize roots, ready work, roles, and forum activity")
    cmds.add_row("loopfarm run <prompt>", "Create root issue and run the DAG")
    cmds.add_row("loopfarm resume <root-id>", "Resume an interrupted DAG run")
    cmds.add_row("loopfarm replay <issue-id>", "Replay a logged backend run")
    cmds.add_row("loopfarm roles", "List role templates (JSON by default)")
    cmds.add_row("loopfarm issues <command>", "Issue DAG operations (create/update/close/deps/ready)")
    cmds.add_row("loopfarm forum <command>", "Forum operations (post/read/topics)")
    cmds.add_row("loopfarm serve", "Start the web interface")
    console.print(cmds)
    console.print()

    quick = Table(title="Quick Start", show_header=False, expand=False, show_edge=False, pad_edge=False)
    quick.add_column("Step", style="bold")
    quick.add_column("Command")
    quick.add_row("1", "loopfarm init")
    quick.add_row("2", "loopfarm roles --table")
    quick.add_row("3", "loopfarm run \"Break down and execute this goal\"")
    quick.add_row("4", "loopfarm issues ready --root <root-id>")
    console.print(quick)
    console.print(Text("Run `loopfarm <command> --help` for command-specific details.", style="dim"))


def _dispatch_prompt_shorthand(raw: list[str], console: Console) -> int:
    """Support legacy shorthand: loopfarm <prompt words...>."""
    args = _run_parser(prog="loopfarm").parse_args(raw)
    return cmd_run(args, console)


def main(argv: list[str] | None = None) -> None:
    raw = argv if argv is not None else sys.argv[1:]
    console = Console()

    if "--version" in raw:
        console.print(Text(f"loopfarm {__version__}", style="bold"))
        sys.exit(0)

    if not raw or raw == ["--help"] or raw == ["-h"]:
        _print_help(console)
        sys.exit(0)

    command = raw[0]

    if command == "init":
        sys.exit(cmd_init(console))

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

    # Backward-compatible shorthand: treat unknown top-level text as run prompt.
    sys.exit(_dispatch_prompt_shorthand(raw, console))


if __name__ == "__main__":
    main()
