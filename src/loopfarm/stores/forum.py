from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import now_ms, resolve_state_dir


_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS forum_topics (
    name TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS forum_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic_name TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(topic_name) REFERENCES forum_topics(name)
);
CREATE INDEX IF NOT EXISTS idx_forum_messages_topic_created
    ON forum_messages(topic_name, created_at DESC, id DESC);
"""


@dataclass
class ForumStore:
    root: Path
    create_on_connect: bool = True

    @classmethod
    def from_workdir(
        cls,
        cwd: Path | None = None,
        *,
        create: bool = True,
    ) -> "ForumStore":
        return cls(
            resolve_state_dir(cwd, create=create),
            create_on_connect=create,
        )

    @property
    def db_path(self) -> Path:
        return self.root / "forum.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        if self.create_on_connect:
            self.root.mkdir(parents=True, exist_ok=True)
        elif not self.db_path.exists():
            raise FileNotFoundError(str(self.db_path))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(_SCHEMA)
        return conn

    def ensure_topic(self, name: str) -> dict[str, Any]:
        topic = name.strip()
        if not topic:
            raise ValueError("topic name cannot be empty")
        now = now_ms()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO forum_topics(name, created_at, updated_at, message_count)
                VALUES(?, ?, ?, 0)
                ON CONFLICT(name) DO NOTHING
                """,
                (topic, now, now),
            )
            row = conn.execute(
                "SELECT name, created_at, updated_at, message_count FROM forum_topics WHERE name=?",
                (topic,),
            ).fetchone()
        assert row is not None
        return {
            "name": str(row["name"]),
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
            "message_count": int(row["message_count"]),
        }

    def post(self, topic: str, body: str, *, author: str | None = None) -> dict[str, Any]:
        topic_name = topic.strip()
        if not topic_name:
            raise ValueError("topic name cannot be empty")
        if not body:
            raise ValueError("message body cannot be empty")

        now = now_ms()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO forum_topics(name, created_at, updated_at, message_count)
                VALUES(?, ?, ?, 0)
                ON CONFLICT(name) DO NOTHING
                """,
                (topic_name, now, now),
            )
            cur = conn.execute(
                """
                INSERT INTO forum_messages(topic_name, body, author, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (topic_name, body, author, now),
            )
            msg_id = int(cur.lastrowid)
            conn.execute(
                """
                UPDATE forum_topics
                SET updated_at=?, message_count=message_count+1
                WHERE name=?
                """,
                (now, topic_name),
            )

        return {
            "id": str(msg_id),
            "topic": topic_name,
            "body": body,
            "author": author,
            "created_at": now,
        }

    def read(self, topic: str, *, limit: int = 25) -> list[dict[str, Any]]:
        topic_name = topic.strip()
        if not topic_name:
            return []
        if not self.db_path.exists():
            return []
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, topic_name, body, author, created_at
                FROM forum_messages
                WHERE topic_name=?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (topic_name, max(1, int(limit))),
            ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            out.append(
                {
                    "id": str(row["id"]),
                    "topic": str(row["topic_name"]),
                    "body": str(row["body"]),
                    "author": row["author"],
                    "created_at": int(row["created_at"]),
                }
            )
        return out

    def topics(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []

        query = (
            "SELECT name, created_at, updated_at, message_count "
            "FROM forum_topics ORDER BY updated_at DESC, name ASC"
        )
        params: tuple[Any, ...] = ()
        if limit is not None:
            query += " LIMIT ?"
            params = (max(1, int(limit)),)

        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [
            {
                "name": str(row["name"]),
                "created_at": int(row["created_at"]),
                "updated_at": int(row["updated_at"]),
                "message_count": int(row["message_count"]),
            }
            for row in rows
        ]

    def show(self, message_id: int) -> dict[str, Any] | None:
        if not self.db_path.exists():
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, topic_name, body, author, created_at
                FROM forum_messages
                WHERE id=?
                """,
                (int(message_id),),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": str(row["id"]),
            "topic": str(row["topic_name"]),
            "body": str(row["body"]),
            "author": row["author"],
            "created_at": int(row["created_at"]),
        }

    def search(
        self,
        query: str,
        *,
        topic: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        text = query.strip()
        if not text:
            return []
        if not self.db_path.exists():
            return []

        like = f"%{text}%"
        where = "(m.body LIKE ? OR m.topic_name LIKE ?)"
        params: list[Any] = [like, like]
        if topic and topic.strip():
            where += " AND m.topic_name = ?"
            params.append(topic.strip())
        params.append(max(1, int(limit)))

        with self._connect() as conn:
            rows = conn.execute(
                f"""
                SELECT m.id, m.topic_name, m.body, m.author, m.created_at
                FROM forum_messages m
                WHERE {where}
                ORDER BY m.created_at DESC, m.id DESC
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()

        return [
            {
                "id": str(row["id"]),
                "topic": str(row["topic_name"]),
                "body": str(row["body"]),
                "author": row["author"],
                "created_at": int(row["created_at"]),
            }
            for row in rows
        ]
