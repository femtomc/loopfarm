from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .stores.forum import ForumStore
from .ui import (
    add_output_mode_argument,
    make_console,
    render_panel,
    render_help,
    render_table,
    resolve_output_mode,
)


@dataclass
class Forum:
    store: ForumStore

    @classmethod
    def from_workdir(
        cls,
        cwd: Path | None = None,
        *,
        create: bool = True,
    ) -> "Forum":
        return cls(ForumStore.from_workdir(cwd, create=create))

    def ensure_topic(self, topic: str) -> dict[str, Any]:
        return self.store.ensure_topic(topic)

    def post(self, topic: str, body: str, *, author: str | None = None) -> dict[str, Any]:
        return self.store.post(topic, body, author=author)

    def post_json(self, topic: str, payload: Any, *, author: str | None = None) -> None:
        self.store.post(topic, json.dumps(payload, ensure_ascii=False), author=author)

    def read(self, topic: str, *, limit: int = 25) -> list[dict[str, Any]]:
        return self.store.read(topic, limit=limit)

    def read_json(self, topic: str, *, limit: int) -> list[dict[str, Any]]:
        return self.store.read(topic, limit=limit)

    def list_topics(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        return self.store.topics(limit=limit)

    def show(self, message_id: int) -> dict[str, Any] | None:
        return self.store.show(message_id)

    def search(
        self,
        query: str,
        *,
        topic: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        return self.store.search(query, topic=topic, limit=limit)


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


def _print_messages(messages: list[dict[str, Any]]) -> None:
    for item in messages:
        msg_id = item.get("id")
        topic = item.get("topic")
        created = _format_time(item.get("created_at"))
        author = item.get("author") or "unknown"
        body = str(item.get("body") or "")
        print(f"[{msg_id}] {topic} @{created} by {author}")
        print(body)
        print()


def _print_messages_rich(messages: list[dict[str, Any]]) -> None:
    console = make_console("rich")
    if not messages:
        render_panel(console, "(no messages)", title="Forum")
        return

    for item in messages:
        msg_id = item.get("id")
        topic = item.get("topic")
        created = _format_time(item.get("created_at"))
        author = item.get("author") or "unknown"
        body = str(item.get("body") or "").rstrip() or "(empty)"
        render_panel(
            console,
            body,
            title=f"[{msg_id}] {topic} @{created} by {author}",
        )


def _print_topics(rows: list[dict[str, Any]]) -> None:
    headers = ("TOPIC", "CREATED", "UPDATED", "COUNT")
    values: list[tuple[str, str, str, str]] = []
    for row in rows:
        values.append(
            (
                _truncate(row.get("name"), 64),
                _format_time(row.get("created_at")),
                _format_time(row.get("updated_at")),
                str(row.get("message_count") or 0),
            )
        )

    widths = [len(item) for item in headers]
    for row in values:
        for idx, col in enumerate(row):
            widths[idx] = max(widths[idx], len(col))

    print("  ".join(headers[idx].ljust(widths[idx]) for idx in range(len(headers))))
    print("  ".join("-" * widths[idx] for idx in range(len(headers))))
    for row in values:
        print("  ".join(row[idx].ljust(widths[idx]) for idx in range(len(headers))))


def _print_topics_rich(rows: list[dict[str, Any]]) -> None:
    console = make_console("rich")
    if not rows:
        render_panel(console, "(no topics)", title="Topics")
        return

    render_table(
        console,
        title="Forum Topics",
        headers=("Topic", "Created", "Updated", "Count"),
        no_wrap_columns=(0, 1, 2, 3),
        rows=[
            (
                str(row.get("name") or ""),
                _format_time(row.get("created_at")),
                _format_time(row.get("updated_at")),
                str(row.get("message_count") or 0),
            )
            for row in rows
        ],
    )


def _print_help(*, output_mode: str) -> None:
    render_help(
        output_mode="rich" if output_mode == "rich" else "plain",
        command="loopfarm forum",
        summary="async message bus for loopfarm sessions and agent notes",
        usage=("loopfarm forum <command> [ARGS]",),
        sections=(
            (
                "Commands",
                (
                    ("post <topic> -m \"...\"", "post a message"),
                    ("read <topic>", "read messages in chronological order"),
                    ("show <id>", "show one message by numeric id"),
                    ("search <query>", "full-text search across forum messages"),
                    ("topic list", "list known topics"),
                    ("topic new <name>", "ensure topic exists"),
                ),
            ),
            (
                "Topic Patterns",
                (
                    ("issue:<id>", "per-issue implementation notes"),
                    ("loopfarm:status:<session>", "session status/decision payloads"),
                    ("loopfarm:briefing:<session>", "phase briefing payloads"),
                    ("research:<project>:<topic>", "research findings"),
                ),
            ),
            (
                "Options",
                (
                    ("--json", "emit machine-readable payloads"),
                    (
                        "--output MODE",
                        "auto|plain|rich (or LOOPFARM_OUTPUT)",
                    ),
                    ("--author <name>", "override author label for post"),
                    ("--limit <n>", "cap read/search/topic rows"),
                    ("-h, --help", "show this help"),
                ),
            ),
            (
                "Quick Start",
                (
                    (
                        "post progress",
                        "loopfarm forum post issue:<id> -m \"Implemented parser changes\"",
                    ),
                    (
                        "read thread",
                        "loopfarm forum read issue:<id> --limit 10",
                    ),
                    (
                        "search history",
                        "loopfarm forum search \"state machine\" --limit 20",
                    ),
                ),
            ),
        ),
        examples=(
            (
                "loopfarm forum post loopfarm:status:abc123 -m '{\"decision\":\"CONTINUE\"}'",
                "store structured status records",
            ),
            (
                "loopfarm forum read loopfarm:briefing:abc123 --json",
                "fetch briefing payloads for agent context",
            ),
        ),
        docs_tip=(
            "For end-to-end workflow context, run `loopfarm docs show source-layout`."
        ),
    )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="loopfarm forum",
        description="Post, read, and search loopfarm forum messages.",
    )
    sub = p.add_subparsers(dest="command", required=True, metavar="command")

    post = sub.add_parser("post", help="Post a message to a topic")
    post.add_argument("topic", help="Topic name")
    post.add_argument("-m", "--message", required=True, help="Message body")
    post.add_argument("--author", help="Author label")
    post.add_argument("--json", action="store_true", help="Output JSON")

    read = sub.add_parser("read", help="Read messages from a topic")
    read.add_argument("topic", help="Topic name")
    read.add_argument("--limit", type=int, default=25, help="Max rows (default: 25)")
    read.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(read)

    show = sub.add_parser("show", help="Show a message by ID")
    show.add_argument("id", type=int, help="Message id")
    show.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(show)

    search = sub.add_parser("search", help="Search forum messages")
    search.add_argument("query", help="Search text")
    search.add_argument("--topic", help="Restrict to one topic")
    search.add_argument("--limit", type=int, default=20, help="Max rows (default: 20)")
    search.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(search)

    topic = sub.add_parser("topic", help="Topic operations")
    topic_sub = topic.add_subparsers(dest="topic_cmd", required=True, metavar="topic_cmd")

    topic_list = topic_sub.add_parser("list", help="List topics")
    topic_list.add_argument("--limit", type=int, help="Max rows")
    topic_list.add_argument("--json", action="store_true", help="Output JSON")
    add_output_mode_argument(topic_list)

    topic_new = topic_sub.add_parser("new", help="Create topic if missing")
    topic_new.add_argument("name", help="Topic name")
    topic_new.add_argument("--json", action="store_true", help="Output JSON")

    return p


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
        _print_help(output_mode=help_output_mode)
        raise SystemExit(0)

    args = _build_parser().parse_args(raw_argv)

    output_mode = "plain"
    if hasattr(args, "output"):
        try:
            output_mode = resolve_output_mode(getattr(args, "output", None))
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            raise SystemExit(2)

    create = False
    if args.command == "post":
        create = True
    elif args.command == "topic" and args.topic_cmd == "new":
        create = True
    forum = Forum.from_workdir(Path.cwd(), create=create)

    try:
        if args.command == "post":
            row = forum.post(args.topic, args.message, author=args.author)
            if args.json:
                _emit_json(row)
            else:
                print(row["id"])
            return

        if args.command == "read":
            rows = forum.read(args.topic, limit=max(1, int(args.limit)))
            if args.json:
                _emit_json(rows)
            else:
                if output_mode == "rich":
                    _print_messages_rich(rows)
                else:
                    if not rows:
                        print("(no messages)")
                    else:
                        _print_messages(rows)
            return

        if args.command == "show":
            row = forum.show(int(args.id))
            if row is None:
                print(f"error: message not found: {args.id}", file=sys.stderr)
                raise SystemExit(1)
            if args.json:
                _emit_json(row)
            else:
                if output_mode == "rich":
                    _print_messages_rich([row])
                else:
                    _print_messages([row])
            return

        if args.command == "search":
            rows = forum.search(
                args.query,
                topic=args.topic,
                limit=max(1, int(args.limit)),
            )
            if args.json:
                _emit_json(rows)
            else:
                if output_mode == "rich":
                    _print_messages_rich(rows)
                else:
                    if not rows:
                        print("(no results)")
                    else:
                        _print_messages(rows)
            return

        if args.command == "topic":
            if args.topic_cmd == "list":
                rows = forum.list_topics(limit=args.limit)
                if args.json:
                    _emit_json(rows)
                else:
                    if output_mode == "rich":
                        _print_topics_rich(rows)
                    else:
                        if not rows:
                            print("(no topics)")
                        else:
                            _print_topics(rows)
                return

            if args.topic_cmd == "new":
                row = forum.ensure_topic(args.name)
                if args.json:
                    _emit_json(row)
                else:
                    print(row["name"])
                return
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
