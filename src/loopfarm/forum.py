from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .stores.forum import ForumStore


@dataclass
class Forum:
    store: ForumStore

    @classmethod
    def from_workdir(cls, cwd: Path | None = None) -> "Forum":
        return cls(ForumStore.from_workdir(cwd))

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


def _emit_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _print_messages(messages: list[dict[str, Any]]) -> None:
    for item in messages:
        msg_id = item.get("id")
        topic = item.get("topic")
        created = item.get("created_at")
        body = str(item.get("body") or "")
        print(f"[{msg_id}] {topic} @{created}")
        print(body)
        print()


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="loopfarm forum")
    sub = p.add_subparsers(dest="command", required=True)

    post = sub.add_parser("post")
    post.add_argument("topic")
    post.add_argument("-m", "--message", required=True)
    post.add_argument("--author")
    post.add_argument("--json", action="store_true")

    read = sub.add_parser("read")
    read.add_argument("topic")
    read.add_argument("--limit", type=int, default=25)
    read.add_argument("--json", action="store_true")

    show = sub.add_parser("show")
    show.add_argument("id", type=int)
    show.add_argument("--json", action="store_true")

    search = sub.add_parser("search")
    search.add_argument("query")
    search.add_argument("--topic")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--json", action="store_true")

    topic = sub.add_parser("topic")
    topic_sub = topic.add_subparsers(dest="topic_cmd", required=True)

    topic_list = topic_sub.add_parser("list")
    topic_list.add_argument("--limit", type=int)
    topic_list.add_argument("--json", action="store_true")

    topic_new = topic_sub.add_parser("new")
    topic_new.add_argument("name")
    topic_new.add_argument("--json", action="store_true")

    return p


def main(argv: list[str] | None = None) -> None:
    args = _build_parser().parse_args(argv)
    forum = Forum.from_workdir(Path.cwd())

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
            _print_messages(rows)
        return

    if args.command == "show":
        row = forum.show(int(args.id))
        if row is None:
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
            _print_messages(rows)
        return

    if args.command == "topic":
        if args.topic_cmd == "list":
            rows = forum.list_topics(limit=args.limit)
            if args.json:
                _emit_json(rows)
            else:
                for row in rows:
                    print(
                        f"{row['name']}\tcreated={row['created_at']}\t"
                        f"updated={row['updated_at']}\tcount={row['message_count']}"
                    )
            return

        if args.topic_cmd == "new":
            row = forum.ensure_topic(args.name)
            if args.json:
                _emit_json(row)
            else:
                print(row["name"])
            return


if __name__ == "__main__":
    main()
