from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .stores.issue import IssueStore


@dataclass
class Issue:
    store: IssueStore

    @classmethod
    def from_workdir(cls, cwd: Path | None = None) -> "Issue":
        return cls(IssueStore.from_workdir(cwd))

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
        return self.store.get(issue_id)

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


def _emit_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_issue(issue: dict[str, Any]) -> None:
    tags = ",".join(str(t) for t in issue.get("tags") or [])
    print(
        f"{issue['id']}\t{issue['status']}\tP{issue['priority']}\t"
        f"{issue['title']}\t{tags}"
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loopfarm issue")
    sub = p.add_subparsers(dest="command", required=True)

    ls = sub.add_parser("list")
    ls.add_argument("--status")
    ls.add_argument("--search")
    ls.add_argument("--tag")
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--json", action="store_true")

    ready = sub.add_parser("ready")
    ready.add_argument("--limit", type=int, default=20)
    ready.add_argument("--json", action="store_true")

    show = sub.add_parser("show")
    show.add_argument("id")
    show.add_argument("--json", action="store_true")

    new = sub.add_parser("new")
    new.add_argument("title")
    new.add_argument("-b", "--body", default="")
    new.add_argument("-s", "--status", default="open")
    new.add_argument("-p", "--priority", type=int, default=3)
    new.add_argument("-t", "--tag", action="append", default=[])
    new.add_argument("--json", action="store_true")

    status = sub.add_parser("status")
    status.add_argument("id")
    status.add_argument("value")
    status.add_argument("--json", action="store_true")

    priority = sub.add_parser("priority")
    priority.add_argument("id")
    priority.add_argument("value", type=int)
    priority.add_argument("--json", action="store_true")

    edit = sub.add_parser("edit")
    edit.add_argument("id")
    edit.add_argument("--title")
    edit.add_argument("-b", "--body")
    edit.add_argument("-s", "--status")
    edit.add_argument("-p", "--priority", type=int)
    edit.add_argument("--json", action="store_true")

    comment = sub.add_parser("comment")
    comment.add_argument("id")
    comment.add_argument("-m", "--message", required=True)
    comment.add_argument("--author")
    comment.add_argument("--json", action="store_true")

    deps = sub.add_parser("deps")
    deps.add_argument("id")
    deps.add_argument("--json", action="store_true")

    dep = sub.add_parser("dep")
    dep_sub = dep.add_subparsers(dest="dep_cmd", required=True)
    dep_add = dep_sub.add_parser("add")
    dep_add.add_argument("src_id")
    dep_add.add_argument("type")
    dep_add.add_argument("dst_id")
    dep_add.add_argument("--json", action="store_true")

    tag = sub.add_parser("tag")
    tag_sub = tag.add_subparsers(dest="tag_cmd", required=True)
    tag_add = tag_sub.add_parser("add")
    tag_add.add_argument("id")
    tag_add.add_argument("tag")
    tag_add.add_argument("--json", action="store_true")
    tag_rm = tag_sub.add_parser("remove")
    tag_rm.add_argument("id")
    tag_rm.add_argument("tag")
    tag_rm.add_argument("--json", action="store_true")

    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    issue = Issue.from_workdir(Path.cwd())

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
                for row in rows:
                    _print_issue(row)
            return

        if args.command == "ready":
            rows = issue.ready(limit=max(1, int(args.limit)))
            if args.json:
                _emit_json(rows)
            else:
                for row in rows:
                    _print_issue(row)
            return

        if args.command == "show":
            row = issue.show(args.id)
            if row is None:
                raise SystemExit(1)
            if args.json:
                _emit_json(row)
            else:
                _print_issue(row)
                body = str(row.get("body") or "").strip()
                if body:
                    print()
                    print(body)
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
        raise SystemExit(str(exc))


if __name__ == "__main__":
    main()
