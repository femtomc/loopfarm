from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .stores.issue import ISSUE_STATUSES, RELATION_TYPES, IssueStore

_RELATION_CHOICES = tuple(RELATION_TYPES) + ("blocked_by", "child")


@dataclass
class Issue:
    store: IssueStore

    @classmethod
    def from_workdir(
        cls,
        cwd: Path | None = None,
        *,
        create: bool = True,
    ) -> "Issue":
        return cls(IssueStore.from_workdir(cwd, create=create))

    def list(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return self.store.list(status=status, search=search, tag=tag, limit=limit)

    def ready(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.store.ready(limit=limit)

    def show(self, issue_id: str) -> dict[str, Any] | None:
        row = self.store.get(issue_id)
        if row is None:
            return None

        issue_key = str(row.get("id") or issue_id).strip()
        payload = dict(row)
        payload["comments"] = self.store.list_comments(issue_key, limit=100)
        payload["dependencies"] = self.store.dependencies(issue_key)
        return payload

    def comments(self, issue_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
        return self.store.list_comments(issue_id, limit=limit)

    def create(
        self,
        title: str,
        *,
        body: str = "",
        status: str = "open",
        priority: int = 3,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.store.create(
            title,
            body=body,
            status=status,
            priority=priority,
            tags=tags,
        )

    def set_status(self, issue_id: str, status: str) -> dict[str, Any]:
        return self.store.set_status(issue_id, status)

    def set_priority(self, issue_id: str, priority: int) -> dict[str, Any]:
        return self.store.set_priority(issue_id, priority)

    def edit(
        self,
        issue_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        status: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        return self.store.update(
            issue_id,
            title=title,
            body=body,
            status=status,
            priority=priority,
        )

    def delete(self, issue_id: str) -> dict[str, Any]:
        return self.store.delete(issue_id)

    def add_comment(
        self,
        issue_id: str,
        message: str,
        *,
        author: str | None = None,
    ) -> dict[str, Any]:
        return self.store.add_comment(issue_id, message, author=author)

    def deps(self, issue_id: str) -> list[dict[str, Any]]:
        return self.store.dependencies(issue_id)

    def add_dep(self, src_id: str, rel_type: str, dst_id: str) -> dict[str, Any]:
        return self.store.add_dependency(src_id, rel_type, dst_id)

    def add_tag(self, issue_id: str, tag: str) -> dict[str, Any]:
        return self.store.add_tag(issue_id, tag)

    def remove_tag(self, issue_id: str, tag: str) -> dict[str, Any]:
        return self.store.remove_tag(issue_id, tag)


def _to_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            return None
    return None


def _iso_from_epoch_ms(value: object) -> str | None:
    ms = _to_int(value)
    if ms is None:
        return None
    try:
        dt = datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _with_iso_timestamps(payload: Any) -> Any:
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            out[key] = _with_iso_timestamps(value)
            if key.endswith("_at"):
                iso = _iso_from_epoch_ms(value)
                if iso:
                    out[f"{key}_iso"] = iso
        return out
    if isinstance(payload, list):
        return [_with_iso_timestamps(item) for item in payload]
    return payload


def _emit_json(payload: Any) -> None:
    print(json.dumps(_with_iso_timestamps(payload), ensure_ascii=False, indent=2))


def _format_time(value: object) -> str:
    return _iso_from_epoch_ms(value) or "-"


def _truncate(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    if limit <= 3:
        return text[:limit]
    return text[: limit - 3] + "..."


def _issue_columns(issue: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(issue.get("id") or ""),
        str(issue.get("status") or ""),
        f"P{issue.get('priority')}",
        _format_time(issue.get("updated_at")),
        _truncate(issue.get("title"), 56),
        _truncate(",".join(str(t) for t in issue.get("tags") or []), 28),
    )


def _print_issue(issue: dict[str, Any]) -> None:
    row = _issue_columns(issue)
    print(f"{row[0]}  {row[1]:<11}  {row[2]:<3}  {row[3]}  {row[4]}  {row[5]}")


def _print_issue_table(rows: list[dict[str, Any]]) -> None:
    headers = ("ID", "STATUS", "PR", "UPDATED", "TITLE", "TAGS")
    values = [_issue_columns(row) for row in rows]

    widths = [len(item) for item in headers]
    for row in values:
        for idx, col in enumerate(row):
            widths[idx] = max(widths[idx], len(col))

    print("  ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("  ".join("-" * widths[idx] for idx in range(len(headers))))
    for row in values:
        print("  ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def _print_issue_details(issue: dict[str, Any]) -> None:
    _print_issue(issue)
    print(f"created: {_format_time(issue.get('created_at'))}")
    print(f"updated: {_format_time(issue.get('updated_at'))}")

    body = str(issue.get("body") or "").strip()
    if body:
        print()
        print(body)

    deps = issue.get("dependencies") or []
    print()
    print("dependencies:")
    if not deps:
        print("  (none)")
    else:
        for dep in deps:
            direction = str(dep.get("direction") or "?")
            active = "active" if dep.get("active") else "inactive"
            created = _format_time(dep.get("created_at"))
            print(
                f"  {dep.get('src_id')} {dep.get('type')} {dep.get('dst_id')} "
                f"({direction}, {active}, created={created})"
            )

    comments = issue.get("comments") or []
    print()
    print("comments:")
    if not comments:
        print("  (none)")
    else:
        for comment in comments:
            comment_id = comment.get("id")
            author = comment.get("author") or "unknown"
            created = _format_time(comment.get("created_at"))
            print(f"  [{comment_id}] {author} @ {created}")
            print(f"  {comment.get('body')}")


def _print_comments(rows: list[dict[str, Any]]) -> None:
    for row in rows:
        comment_id = row.get("id")
        author = row.get("author") or "unknown"
        created = _format_time(row.get("created_at"))
        print(f"[{comment_id}] {author} @ {created}")
        print(str(row.get("body") or ""))
        print()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="loopfarm issue",
        description="Manage loopfarm issues.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    ls = sub.add_parser("list", help="List issues")
    ls.add_argument("--status", help=f"Filter by status ({', '.join(ISSUE_STATUSES)})")
    ls.add_argument("--search", help="Filter by text in id/title/body")
    ls.add_argument("--tag", help="Filter by tag")
    ls.add_argument("--limit", type=int, default=50, help="Max rows (default: 50)")
    ls.add_argument("--json", action="store_true", help="Output JSON")

    ready = sub.add_parser("ready", help="List ready-to-work issues")
    ready.add_argument("--limit", type=int, default=20, help="Max rows (default: 20)")
    ready.add_argument("--json", action="store_true", help="Output JSON")

    show = sub.add_parser("show", help="Show one issue with details")
    show.add_argument("id", help="Issue id")
    show.add_argument("--json", action="store_true", help="Output JSON")

    comments = sub.add_parser("comments", help="List comments for an issue")
    comments.add_argument("id", help="Issue id")
    comments.add_argument("--limit", type=int, default=25, help="Max rows (default: 25)")
    comments.add_argument("--json", action="store_true", help="Output JSON")

    new = sub.add_parser("new", help="Create a new issue")
    new.add_argument("title", help="Issue title")
    new.add_argument("-b", "--body", default="", help="Issue description/body")
    new.add_argument(
        "-s",
        "--status",
        default="open",
        choices=ISSUE_STATUSES,
        help=f"Initial status ({', '.join(ISSUE_STATUSES)})",
    )
    new.add_argument("-p", "--priority", type=int, default=3, help="Priority 1-5")
    new.add_argument("-t", "--tag", action="append", default=[], help="Tag (repeatable)")
    new.add_argument("--json", action="store_true", help="Output JSON")

    status = sub.add_parser("status", help="Set issue status")
    status.add_argument("id", help="Issue id")
    status.add_argument(
        "value",
        choices=ISSUE_STATUSES,
        help=f"New status ({', '.join(ISSUE_STATUSES)})",
    )
    status.add_argument("--json", action="store_true", help="Output JSON")

    close = sub.add_parser("close", help="Set issue status to closed")
    close.add_argument("id", nargs="+", help="Issue id(s)")
    close.add_argument("--json", action="store_true", help="Output JSON")

    reopen = sub.add_parser("reopen", help="Set issue status to open")
    reopen.add_argument("id", nargs="+", help="Issue id(s)")
    reopen.add_argument("--json", action="store_true", help="Output JSON")

    delete = sub.add_parser("delete", help="Delete issue(s)")
    delete.add_argument("id", nargs="+", help="Issue id(s)")
    delete.add_argument(
        "--yes",
        action="store_true",
        help="Confirm delete operation",
    )
    delete.add_argument("--json", action="store_true", help="Output JSON")

    priority = sub.add_parser("priority", help="Set issue priority")
    priority.add_argument("id", help="Issue id")
    priority.add_argument("value", type=int, help="Priority 1-5")
    priority.add_argument("--json", action="store_true", help="Output JSON")

    edit = sub.add_parser("edit", help="Edit issue fields")
    edit.add_argument("id", help="Issue id")
    edit.add_argument("--title", help="New title")
    edit.add_argument("-b", "--body", help="New body")
    edit.add_argument("-s", "--status", choices=ISSUE_STATUSES, help="New status")
    edit.add_argument("-p", "--priority", type=int, help="New priority 1-5")
    edit.add_argument("--json", action="store_true", help="Output JSON")

    comment = sub.add_parser("comment", help="Add a comment to an issue")
    comment.add_argument("id", help="Issue id")
    comment.add_argument("-m", "--message", required=True, help="Comment body")
    comment.add_argument("--author", help="Author label")
    comment.add_argument("--json", action="store_true", help="Output JSON")

    deps = sub.add_parser("deps", help="List dependencies connected to an issue")
    deps.add_argument("id", help="Issue id")
    deps.add_argument("--json", action="store_true", help="Output JSON")

    dep = sub.add_parser("dep", help="Dependency operations")
    dep_sub = dep.add_subparsers(dest="dep_cmd", required=True, metavar="dep_cmd")
    dep_add = dep_sub.add_parser("add", help="Add a dependency relation")
    dep_add.add_argument("src_id", help="Source issue id")
    dep_add.add_argument(
        "type",
        choices=_RELATION_CHOICES,
        help="Relation type (blocks, parent, related, blocked_by, child)",
    )
    dep_add.add_argument("dst_id", help="Destination issue id")
    dep_add.add_argument("--json", action="store_true", help="Output JSON")

    tag = sub.add_parser("tag", help="Tag operations")
    tag_sub = tag.add_subparsers(dest="tag_cmd", required=True, metavar="tag_cmd")
    tag_add = tag_sub.add_parser("add", help="Add a tag")
    tag_add.add_argument("id", help="Issue id")
    tag_add.add_argument("tag", help="Tag value")
    tag_add.add_argument("--json", action="store_true", help="Output JSON")
    tag_rm = tag_sub.add_parser("remove", help="Remove a tag")
    tag_rm.add_argument("id", help="Issue id")
    tag_rm.add_argument("tag", help="Tag value")
    tag_rm.add_argument("--json", action="store_true", help="Output JSON")

    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

    create = args.command not in {"list", "ready", "show", "deps", "comments"}
    issue = Issue.from_workdir(Path.cwd(), create=create)

    try:
        if args.command == "list":
            rows = issue.list(
                status=args.status,
                search=args.search,
                tag=args.tag,
                limit=max(1, int(args.limit)),
            )
            if args.json:
                _emit_json(rows)
            else:
                if not rows:
                    if args.status or args.search or args.tag:
                        print("(no matching issues)")
                    else:
                        print("(no issues)")
                else:
                    _print_issue_table(rows)
            return

        if args.command == "ready":
            rows = issue.ready(limit=max(1, int(args.limit)))
            if args.json:
                _emit_json(rows)
            else:
                if not rows:
                    print("(no ready issues)")
                else:
                    _print_issue_table(rows)
            return

        if args.command == "show":
            row = issue.show(args.id)
            if row is None:
                print(f"error: issue not found: {args.id}", file=sys.stderr)
                raise SystemExit(1)
            if args.json:
                _emit_json(row)
            else:
                _print_issue_details(row)
            return

        if args.command == "comments":
            rows = issue.comments(args.id, limit=max(1, int(args.limit)))
            if args.json:
                _emit_json(rows)
            else:
                if not rows:
                    print("(no comments)")
                else:
                    _print_comments(rows)
            return

        if args.command == "new":
            row = issue.create(
                args.title,
                body=args.body,
                status=args.status,
                priority=args.priority,
                tags=list(args.tag or []),
            )
            if args.json:
                _emit_json(row)
            else:
                print(row["id"])
            return

        if args.command == "status":
            row = issue.set_status(args.id, args.value)
            if args.json:
                _emit_json(row)
            else:
                _print_issue(row)
            return

        if args.command == "close":
            rows = [issue.set_status(issue_id, "closed") for issue_id in args.id]
            if args.json:
                _emit_json(rows)
            else:
                for row in rows:
                    _print_issue(row)
            return

        if args.command == "reopen":
            rows = [issue.set_status(issue_id, "open") for issue_id in args.id]
            if args.json:
                _emit_json(rows)
            else:
                for row in rows:
                    _print_issue(row)
            return

        if args.command == "delete":
            if not args.yes:
                print("error: refusing to delete without --yes", file=sys.stderr)
                raise SystemExit(1)
            rows = [issue.delete(issue_id) for issue_id in args.id]
            if args.json:
                _emit_json(rows)
            else:
                for row in rows:
                    print(f"deleted: {row['id']}")
            return

        if args.command == "priority":
            row = issue.set_priority(args.id, int(args.value))
            if args.json:
                _emit_json(row)
            else:
                _print_issue(row)
            return

        if args.command == "edit":
            row = issue.edit(
                args.id,
                title=args.title,
                body=args.body,
                status=args.status,
                priority=args.priority,
            )
            if args.json:
                _emit_json(row)
            else:
                _print_issue(row)
            return

        if args.command == "comment":
            row = issue.add_comment(args.id, args.message, author=args.author)
            if args.json:
                _emit_json(row)
            else:
                print(row["id"])
            return

        if args.command == "deps":
            rows = issue.deps(args.id)
            if args.json:
                _emit_json(rows)
            else:
                if not rows:
                    print("(no dependencies)")
                for row in rows:
                    print(
                        f"{row['src_id']} {row['type']} {row['dst_id']}\t"
                        f"active={row['active']}"
                    )
            return

        if args.command == "dep" and args.dep_cmd == "add":
            row = issue.add_dep(args.src_id, args.type, args.dst_id)
            if args.json:
                _emit_json(row)
            else:
                print(f"{row['src_id']} {row['type']} {row['dst_id']}")
            return

        if args.command == "tag" and args.tag_cmd == "add":
            row = issue.add_tag(args.id, args.tag)
            if args.json:
                _emit_json(row)
            else:
                _print_issue(row)
            return

        if args.command == "tag" and args.tag_cmd == "remove":
            row = issue.remove_tag(args.id, args.tag)
            if args.json:
                _emit_json(row)
            else:
                _print_issue(row)
            return
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
