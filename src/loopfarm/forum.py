from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .stores.forum import ForumStore


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

    show = sub.add_parser("show", help="Show a message by ID")
    show.add_argument("id", type=int, help="Message id")
    show.add_argument("--json", action="store_true", help="Output JSON")

    search = sub.add_parser("search", help="Search forum messages")
    search.add_argument("query", help="Search text")
    search.add_argument("--topic", help="Restrict to one topic")
    search.add_argument("--limit", type=int, default=20, help="Max rows (default: 20)")
    search.add_argument("--json", action="store_true", help="Output JSON")

    topic = sub.add_parser("topic", help="Topic operations")
    topic_sub = topic.add_subparsers(dest="topic_cmd", required=True, metavar="topic_cmd")

    topic_list = topic_sub.add_parser("list", help="List topics")
    topic_list.add_argument("--limit", type=int, help="Max rows")
    topic_list.add_argument("--json", action="store_true", help="Output JSON")

    topic_new = topic_sub.add_parser("new", help="Create topic if missing")
    topic_new.add_argument("name", help="Topic name")
    topic_new.add_argument("--json", action="store_true", help="Output JSON")

    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)

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
