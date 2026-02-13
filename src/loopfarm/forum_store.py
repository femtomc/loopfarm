"""JSONL-backed forum message store."""

from __future__ import annotations

from pathlib import Path

from .jsonl import now_ts, read_jsonl, write_jsonl


class ForumStore:
    """JSONL-backed message forum stored in .loopfarm/forum.jsonl."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def from_workdir(cls, root: Path | None = None) -> ForumStore:
        root = root or Path.cwd()
        return cls(root / ".loopfarm" / "forum.jsonl")

    def post(self, topic: str, body: str, author: str = "system") -> dict:
        msg = {
            "topic": topic,
            "body": body,
            "author": author,
            "created_at": now_ts(),
        }
        rows = read_jsonl(self.path)
        rows.append(msg)
        write_jsonl(self.path, rows)
        return msg

    def read(self, topic: str, limit: int = 50) -> list[dict]:
        rows = read_jsonl(self.path)
        matching = [row for row in rows if row["topic"] == topic]
        return matching[-limit:]

    def topics(self, prefix: str | None = None) -> list[dict]:
        """Return topic metadata sorted by most-recent activity."""
        rows = read_jsonl(self.path)
        by_topic: dict[str, dict] = {}
        for row in rows:
            topic = row.get("topic")
            if not topic:
                continue
            if prefix and not topic.startswith(prefix):
                continue
            entry = by_topic.setdefault(topic, {"topic": topic, "messages": 0, "last_at": 0})
            entry["messages"] += 1
            entry["last_at"] = max(entry["last_at"], int(row.get("created_at", 0)))
        return sorted(
            by_topic.values(),
            key=lambda item: (item["last_at"], item["topic"]),
            reverse=True,
        )
