from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .execution_spec import normalize_execution_spec_payload
from .forum import Forum
from .issue import Issue
from .runtime.issue_dag_execution import DEFAULT_RUN_TOPIC
from .runtime.roles import RoleCatalog
from .ui import (
    add_output_mode_argument,
    make_console,
    render_panel,
    render_help,
    render_table,
    resolve_output_mode,
)


@dataclass(frozen=True)
class RoleRow:
    name: str
    path: str


def _format_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except Exception:
        return str(path)


def _role_rows(repo_root: Path) -> list[RoleRow]:
    catalog = RoleCatalog.from_repo(repo_root)
    rows = [
        RoleRow(name=doc.role, path=_format_path(doc.source_path, repo_root))
        for doc in catalog.available_docs()
    ]
    rows.sort(key=lambda row: row.name)
    return rows


def _require_role(catalog: RoleCatalog, role: str) -> None:
    if catalog.resolve(role=role) is None:
        available = ", ".join(repr(name) for name in catalog.available_roles())
        if available:
            raise ValueError(f"unknown role {role!r} (available: {available})")
        raise ValueError("no roles found under .loopfarm/roles")


def _emit_list_plain(rows: list[RoleRow]) -> None:
    if not rows:
        print("(no roles)")
        return
    for row in rows:
        print(f"{row.name}\t{row.path}")


def _emit_list_json(rows: list[RoleRow]) -> None:
    payload = [{"role": row.name, "path": row.path} for row in rows]
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _emit_list_rich(rows: list[RoleRow]) -> None:
    console = make_console("rich")
    if not rows:
        render_panel(console, "(no roles)", title="Roles")
        return
    render_table(
        console,
        title="Roles",
        headers=("Role", "Document"),
        no_wrap_columns=(0, 1),
        rows=[(row.name, row.path) for row in rows],
    )


def _emit_show_plain(*, role: str, path: str, content: str) -> None:
    print(f"ROLE\t{role}")
    print(f"PATH\t{path}")
    print()
    print(content)


def _emit_show_json(*, role: str, path: str, content: str) -> None:
    print(
        json.dumps(
            {
                "role": role,
                "path": path,
                "markdown": content,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _emit_show_rich(*, role: str, path: str, content: str) -> None:
    console = make_console("rich")
    render_panel(console, f"role: {role}\npath: {path}", title="Role")
    render_panel(console, content or "(empty)", title="Markdown")


def _print_help(*, output_mode: str) -> None:
    render_help(
        output_mode="rich" if output_mode == "rich" else "plain",
        command="loopfarm roles",
        summary="internal: role doc discovery + issue team metadata",
        usage=(
            "loopfarm roles list [--output MODE] [--json]",
            "loopfarm roles show <role> [--output MODE] [--json]",
            "loopfarm roles assign <issue-id> --team <name> --lead <role> [--role <role> ...] [--json]",
        ),
        sections=(
            (
                "Commands (Internal)",
                (
                    ("list", "list roles discovered under .loopfarm/roles/*.md"),
                    ("show <role>", "show one role markdown document"),
                    (
                        "assign",
                        "write team metadata, emit node.team events, and materialize execution_spec",
                    ),
                ),
            ),
            (
                "Options",
                (
                    ("--json", "emit machine-stable JSON output"),
                    (
                        "--output MODE",
                        "auto|plain|rich for list/show (or LOOPFARM_OUTPUT)",
                    ),
                    ("--team <name>", "team label written as team:<name> tag (assign)"),
                    ("--lead <role>", "lead role written as role:<lead> tag (assign)"),
                    ("--role <role>", "additional role member (repeatable) (assign)"),
                    ("-h, --help", "show this help"),
                ),
            ),
            (
                "Quick Start",
                (
                    ("list roles", "loopfarm roles list"),
                    ("inspect one role", "loopfarm roles show worker"),
                    (
                        "assign issue team",
                        "loopfarm roles assign loopfarm-123 --team platform --lead worker --role reviewer",
                    ),
                ),
            ),
        ),
        docs_tip=(
            "Most users won't need this command; see `loopfarm docs show issue-dag-orchestration`."
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="loopfarm roles",
        description="Discover roles and manage issue team assembly metadata.",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="command")

    list_parser = sub.add_parser("list", help="List discovered roles")
    list_parser.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(list_parser)

    show_parser = sub.add_parser("show", help="Show one role document")
    show_parser.add_argument("name", help="Role name (filename stem)")
    show_parser.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(show_parser)

    assign_parser = sub.add_parser(
        "assign",
        help="Record dynamic team assembly for one issue",
    )
    assign_parser.add_argument("issue_id", help="Issue id")
    assign_parser.add_argument("--team", required=True, help="Team label to assign")
    assign_parser.add_argument(
        "--lead",
        required=True,
        help="Lead role; also applied as role:<lead> tag",
    )
    assign_parser.add_argument(
        "--role",
        action="append",
        default=[],
        help="Additional role member (repeatable)",
    )
    assign_parser.add_argument(
        "--author",
        default="orchestrator",
        help="Forum author label (default: orchestrator)",
    )
    assign_parser.add_argument(
        "--run-topic",
        default=DEFAULT_RUN_TOPIC,
        help=f"Run-level topic for team events (default: {DEFAULT_RUN_TOPIC})",
    )
    assign_parser.add_argument("--json", action="store_true", help="Output JSON")

    return parser


def _resolve_output_mode(args: argparse.Namespace) -> str:
    if not hasattr(args, "output"):
        return "plain"
    return resolve_output_mode(getattr(args, "output", None))


def _build_assignment_payload(
    *,
    issue_id: str,
    team: str,
    lead: str,
    roles: list[str],
    catalog: RoleCatalog,
    repo_root: Path,
    execution_spec: dict[str, object],
) -> dict[str, object]:
    role_docs: list[dict[str, str]] = []
    for role in roles:
        doc = catalog.require(role=role)
        role_docs.append(
            {
                "role": role,
                "role_doc": _format_path(doc.source_path, repo_root),
            }
        )

    return {
        "kind": "node.team",
        "id": issue_id,
        "team": team,
        "lead_role": lead,
        "roles": roles,
        "role_docs": role_docs,
        "execution_spec": execution_spec,
        "source": "roles_catalog",
    }


def _build_execution_spec_from_role(
    *,
    role: str,
    team: str,
    catalog: RoleCatalog,
    repo_root: Path,
) -> dict[str, object]:
    role_doc = catalog.require(role=role)
    defaults = role_doc.execution_defaults
    loop_steps = [
        {"phase": phase, "repeat": repeat}
        for phase, repeat in defaults.loop_steps
    ]
    if not loop_steps:
        loop_steps = [{"phase": "role", "repeat": 1}]
    termination_phase = defaults.termination_phase or str(loop_steps[-1]["phase"])
    payload: dict[str, object] = {
        "version": 1,
        "role": role,
        "team": team,
        "prompt_path": _format_path(role_doc.source_path, repo_root),
        "loop_steps": loop_steps,
        "termination_phase": termination_phase,
    }
    if defaults.cli:
        payload["default_cli"] = defaults.cli
    if defaults.model:
        payload["default_model"] = defaults.model
    if defaults.reasoning:
        payload["default_reasoning"] = defaults.reasoning
    if defaults.control_flow_mode:
        payload["control_flow"] = {"mode": defaults.control_flow_mode}
    return normalize_execution_spec_payload(payload)


def _assign_issue_team(args: argparse.Namespace, *, repo_root: Path) -> dict[str, object]:
    issue_id = str(args.issue_id or "").strip()
    if not issue_id:
        raise ValueError("issue_id is required")

    team = str(args.team or "").strip()
    if not team:
        raise ValueError("--team is required")

    lead = str(args.lead or "").strip().lower()
    if not lead:
        raise ValueError("--lead is required")

    catalog = RoleCatalog.from_repo(repo_root)
    _require_role(catalog, lead)

    ordered_roles: list[str] = [lead]
    seen = {lead}
    for raw in list(args.role or []):
        role = str(raw or "").strip().lower()
        if not role or role in seen:
            continue
        _require_role(catalog, role)
        seen.add(role)
        ordered_roles.append(role)

    issue = Issue.from_workdir(repo_root, create=True)
    existing = issue.show(issue_id)
    if existing is None:
        raise ValueError(f"issue not found: {issue_id}")

    tags = [str(tag).strip() for tag in existing.get("tags") or [] if str(tag).strip()]

    desired_team_tag = f"team:{team}"
    for tag in [tag for tag in tags if tag.startswith("team:") and tag != desired_team_tag]:
        issue.remove_tag(issue_id, tag)
    if desired_team_tag not in tags:
        issue.add_tag(issue_id, desired_team_tag)

    desired_role_tag = f"role:{lead}"
    for tag in [tag for tag in tags if tag.startswith("role:") and tag != desired_role_tag]:
        issue.remove_tag(issue_id, tag)
    if desired_role_tag not in tags:
        issue.add_tag(issue_id, desired_role_tag)

    execution_spec = _build_execution_spec_from_role(
        role=lead,
        team=team,
        catalog=catalog,
        repo_root=repo_root,
    )
    issue.set_execution_spec(issue_id, execution_spec)

    payload = _build_assignment_payload(
        issue_id=issue_id,
        team=team,
        lead=lead,
        roles=ordered_roles,
        catalog=catalog,
        repo_root=repo_root,
        execution_spec=execution_spec,
    )

    forum = Forum.from_workdir(repo_root)
    forum.post_json(f"issue:{issue_id}", payload, author=args.author)
    forum.post_json(str(args.run_topic), payload, author=args.author)

    result = {
        "issue_id": issue_id,
        "team": team,
        "lead_role": lead,
        "roles": ordered_roles,
        "tags_updated": {
            "team": desired_team_tag,
            "role": desired_role_tag,
        },
        "execution_spec": execution_spec,
        "event": payload,
    }
    return result


def main(argv: list[str] | None = None) -> None:
    raw_argv = list(argv) if argv is not None else sys.argv[1:]
    if raw_argv in (["-h"], ["--help"]):
        try:
            output_mode = resolve_output_mode(
                is_tty=getattr(sys.stdout, "isatty", lambda: False)(),
            )
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(2) from exc
        _print_help(output_mode=output_mode)
        raise SystemExit(0)

    args = _build_parser().parse_args(raw_argv)
    repo_root = Path.cwd()

    try:
        output_mode = _resolve_output_mode(args)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc

    try:
        if args.command == "list":
            rows = _role_rows(repo_root)
            if args.json:
                _emit_list_json(rows)
            elif output_mode == "rich":
                _emit_list_rich(rows)
            else:
                _emit_list_plain(rows)
            return

        if args.command == "show":
            role_name = str(args.name or "").strip().lower()
            if not role_name:
                raise ValueError("role name is required")
            catalog = RoleCatalog.from_repo(repo_root)
            doc = catalog.require(role=role_name)
            path = _format_path(doc.source_path, repo_root)
            content = doc.source_path.read_text(encoding="utf-8")

            if args.json:
                _emit_show_json(role=doc.role, path=path, content=content)
            elif output_mode == "rich":
                _emit_show_rich(role=doc.role, path=path, content=content)
            else:
                _emit_show_plain(role=doc.role, path=path, content=content)
            return

        if args.command == "assign":
            result = _assign_issue_team(args, repo_root=repo_root)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print(
                    f"assigned: issue={result['issue_id']} team={result['team']} "
                    f"lead={result['lead_role']} roles={','.join(result['roles'])}"
                )
            return
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
