from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import now_ms, resolve_state_dir


ISSUE_STATUSES = (
    "open",
    "in_progress",
    "paused",
    "closed",
    "duplicate",
)
TERMINAL_STATUSES = {"closed", "duplicate"}

RELATION_TYPES = (
    "blocks",
    "parent",
    "related",
)


_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    priority INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS issue_tags (
    issue_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    PRIMARY KEY(issue_id, tag),
    FOREIGN KEY(issue_id) REFERENCES issues(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS issue_comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_id TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY(issue_id) REFERENCES issues(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS issue_deps (
    src_id TEXT NOT NULL,
    rel_type TEXT NOT NULL,
    dst_id TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    PRIMARY KEY(src_id, rel_type, dst_id),
    FOREIGN KEY(src_id) REFERENCES issues(id) ON DELETE CASCADE,
    FOREIGN KEY(dst_id) REFERENCES issues(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_issues_status_priority_updated
    ON issues(status, priority, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_issue_tags_tag ON issue_tags(tag);
CREATE INDEX IF NOT EXISTS idx_issue_deps_src ON issue_deps(src_id, rel_type);
CREATE INDEX IF NOT EXISTS idx_issue_deps_dst ON issue_deps(dst_id, rel_type);
"""


def _new_issue_id() -> str:
    return f"loopfarm-{uuid.uuid4().hex[:8]}"


def _normalize_status(status: str) -> str:
    value = status.strip().lower()
    if value not in ISSUE_STATUSES:
        raise ValueError(f"invalid status: {status}")
    return value


def _normalize_priority(priority: int) -> int:
    value = int(priority)
    if value < 1 or value > 5:
        raise ValueError("priority must be between 1 and 5")
    return value


def _normalize_relation(rel_type: str) -> tuple[str, bool]:
    value = rel_type.strip().lower()
    if value == "blocked_by":
        return "blocks", True
    if value == "child":
        return "parent", True
    if value not in RELATION_TYPES:
        raise ValueError(f"invalid relation type: {rel_type}")
    return value, False


@dataclass
class IssueStore:
    root: Path
    create_on_connect: bool = True

    @classmethod
    def from_workdir(
        cls,
        cwd: Path | None = None,
        *,
        create: bool = True,
    ) -> "IssueStore":
        return cls(
            resolve_state_dir(cwd, create=create),
            create_on_connect=create,
        )

    @property
    def db_path(self) -> Path:
        return self.root / "issue.sqlite3"

    def _connect(self) -> sqlite3.Connection:
        if self.create_on_connect:
            self.root.mkdir(parents=True, exist_ok=True)
        elif not self.db_path.exists():
            raise FileNotFoundError(str(self.db_path))
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(_SCHEMA)
        return conn

    def create(
        self,
        title: str,
        *,
        body: str = "",
        status: str = "open",
        priority: int = 3,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        issue_title = title.strip()
        if not issue_title:
            raise ValueError("title cannot be empty")

        issue_status = _normalize_status(status)
        issue_priority = _normalize_priority(priority)
        now = now_ms()
        issue_id = _new_issue_id()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO issues(id, title, body, status, priority, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issue_id,
                    issue_title,
                    body,
                    issue_status,
                    issue_priority,
                    now,
                    now,
                ),
            )
            for tag in sorted({t.strip() for t in (tags or []) if t.strip()}):
                conn.execute(
                    "INSERT INTO issue_tags(issue_id, tag) VALUES(?, ?)",
                    (issue_id, tag),
                )

        issue = self.get(issue_id)
        if issue is None:
            raise RuntimeError("created issue could not be loaded")
        return issue

    def get(self, issue_id: str) -> dict[str, Any] | None:
        issue_key = issue_id.strip()
        if not issue_key:
            return None
        if not self.db_path.exists():
            return None
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT id, title, body, status, priority, created_at, updated_at
                FROM issues
                WHERE id=?
                """,
                (issue_key,),
            ).fetchone()
            if row is None:
                return None
            tags = self._tags_for_ids(conn, [issue_key]).get(issue_key, [])
        return {
            "id": str(row["id"]),
            "title": str(row["title"]),
            "body": str(row["body"]),
            "status": str(row["status"]),
            "priority": int(row["priority"]),
            "created_at": int(row["created_at"]),
            "updated_at": int(row["updated_at"]),
            "tags": tags,
        }

    def list(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        tag: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []

        where: list[str] = []
        params: list[Any] = []

        if status:
            where.append("i.status = ?")
            params.append(_normalize_status(status))

        if search:
            text = search.strip()
            if text:
                like = f"%{text}%"
                where.append("(i.id LIKE ? OR i.title LIKE ? OR i.body LIKE ?)")
                params.extend((like, like, like))

        if tag:
            where.append(
                "EXISTS (SELECT 1 FROM issue_tags t WHERE t.issue_id = i.id AND t.tag = ?)"
            )
            params.append(tag.strip())

        query = """
            SELECT i.id, i.title, i.body, i.status, i.priority, i.created_at, i.updated_at
            FROM issues i
        """
        if where:
            query += " WHERE " + " AND ".join(where)
        query += """
            ORDER BY
                CASE i.status
                    WHEN 'in_progress' THEN 0
                    WHEN 'open' THEN 1
                    WHEN 'paused' THEN 2
                    WHEN 'closed' THEN 3
                    ELSE 4
                END,
                i.priority ASC,
                i.updated_at DESC,
                i.id ASC
            LIMIT ?
        """
        params.append(max(1, int(limit)))

        with self._connect() as conn:
            rows = conn.execute(query, tuple(params)).fetchall()
            ids = [str(row["id"]) for row in rows]
            tags = self._tags_for_ids(conn, ids)

        return [
            {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "body": str(row["body"]),
                "status": str(row["status"]),
                "priority": int(row["priority"]),
                "created_at": int(row["created_at"]),
                "updated_at": int(row["updated_at"]),
                "tags": tags.get(str(row["id"]), []),
            }
            for row in rows
        ]

    def update(
        self,
        issue_id: str,
        *,
        title: str | None = None,
        body: str | None = None,
        status: str | None = None,
        priority: int | None = None,
    ) -> dict[str, Any]:
        issue_key = issue_id.strip()
        if not issue_key:
            raise ValueError("issue id cannot be empty")

        set_parts: list[str] = []
        params: list[Any] = []

        if title is not None:
            clean = title.strip()
            if not clean:
                raise ValueError("title cannot be empty")
            set_parts.append("title = ?")
            params.append(clean)

        if body is not None:
            set_parts.append("body = ?")
            params.append(body)

        if status is not None:
            set_parts.append("status = ?")
            params.append(_normalize_status(status))

        if priority is not None:
            set_parts.append("priority = ?")
            params.append(_normalize_priority(priority))

        if not set_parts:
            issue = self.get(issue_key)
            if issue is None:
                raise ValueError(f"unknown issue: {issue_key}")
            return issue

        params.extend((now_ms(), issue_key))

        with self._connect() as conn:
            cur = conn.execute(
                f"UPDATE issues SET {', '.join(set_parts)}, updated_at = ? WHERE id = ?",
                tuple(params),
            )
            if cur.rowcount == 0:
                raise ValueError(f"unknown issue: {issue_key}")

        issue = self.get(issue_key)
        if issue is None:
            raise ValueError(f"unknown issue: {issue_key}")
        return issue

    def set_status(self, issue_id: str, status: str) -> dict[str, Any]:
        return self.update(issue_id, status=status)

    def set_priority(self, issue_id: str, priority: int) -> dict[str, Any]:
        return self.update(issue_id, priority=priority)

    def delete(self, issue_id: str) -> dict[str, Any]:
        issue_key = issue_id.strip()
        if not issue_key:
            raise ValueError("issue id cannot be empty")

        issue = self.get(issue_key)
        if issue is None:
            raise ValueError(f"unknown issue: {issue_key}")

        with self._connect() as conn:
            conn.execute("DELETE FROM issues WHERE id = ?", (issue_key,))

        return {"id": issue_key, "deleted": True}

    def add_tag(self, issue_id: str, tag: str) -> dict[str, Any]:
        issue_key = issue_id.strip()
        value = tag.strip()
        if not issue_key or not value:
            raise ValueError("issue id and tag are required")

        if self.get(issue_key) is None:
            raise ValueError(f"unknown issue: {issue_key}")

        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO issue_tags(issue_id, tag) VALUES(?, ?)",
                (issue_key, value),
            )
            conn.execute(
                "UPDATE issues SET updated_at = ? WHERE id = ?",
                (now_ms(), issue_key),
            )

        issue = self.get(issue_key)
        if issue is None:
            raise ValueError(f"unknown issue: {issue_key}")
        return issue

    def remove_tag(self, issue_id: str, tag: str) -> dict[str, Any]:
        issue_key = issue_id.strip()
        value = tag.strip()
        if not issue_key or not value:
            raise ValueError("issue id and tag are required")

        if self.get(issue_key) is None:
            raise ValueError(f"unknown issue: {issue_key}")

        with self._connect() as conn:
            conn.execute(
                "DELETE FROM issue_tags WHERE issue_id = ? AND tag = ?",
                (issue_key, value),
            )
            conn.execute(
                "UPDATE issues SET updated_at = ? WHERE id = ?",
                (now_ms(), issue_key),
            )

        issue = self.get(issue_key)
        if issue is None:
            raise ValueError(f"unknown issue: {issue_key}")
        return issue

    def add_comment(
        self,
        issue_id: str,
        message: str,
        *,
        author: str | None = None,
    ) -> dict[str, Any]:
        issue_key = issue_id.strip()
        body = message.strip()
        if not issue_key:
            raise ValueError("issue id cannot be empty")
        if not body:
            raise ValueError("comment cannot be empty")
        if self.get(issue_key) is None:
            raise ValueError(f"unknown issue: {issue_key}")

        now = now_ms()
        with self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO issue_comments(issue_id, body, author, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (issue_key, body, author, now),
            )
            conn.execute(
                "UPDATE issues SET updated_at = ? WHERE id = ?",
                (now, issue_key),
            )
            comment_id = int(cur.lastrowid)

        return {
            "id": comment_id,
            "issue_id": issue_key,
            "body": body,
            "author": author,
            "created_at": now,
        }

    def list_comments(self, issue_id: str, *, limit: int = 25) -> list[dict[str, Any]]:
        issue_key = issue_id.strip()
        if not issue_key:
            return []
        if not self.db_path.exists():
            return []

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, issue_id, body, author, created_at
                FROM issue_comments
                WHERE issue_id = ?
                ORDER BY created_at DESC, id DESC
                LIMIT ?
                """,
                (issue_key, max(1, int(limit))),
            ).fetchall()

        return [
            {
                "id": int(row["id"]),
                "issue_id": str(row["issue_id"]),
                "body": str(row["body"]),
                "author": row["author"],
                "created_at": int(row["created_at"]),
            }
            for row in rows
        ]

    def add_dependency(self, src_id: str, rel_type: str, dst_id: str) -> dict[str, Any]:
        src = src_id.strip()
        dst = dst_id.strip()
        if not src or not dst:
            raise ValueError("source and destination issue IDs are required")
        if src == dst:
            raise ValueError("dependency cannot reference the same issue")

        relation, swapped = _normalize_relation(rel_type)
        if swapped:
            src, dst = dst, src

        if self.get(src) is None:
            raise ValueError(f"unknown issue: {src}")
        if self.get(dst) is None:
            raise ValueError(f"unknown issue: {dst}")

        now = now_ms()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO issue_deps(src_id, rel_type, dst_id, created_at)
                VALUES(?, ?, ?, ?)
                """,
                (src, relation, dst, now),
            )
            conn.execute(
                "UPDATE issues SET updated_at = ? WHERE id IN (?, ?)",
                (now, src, dst),
            )

        return {
            "src_id": src,
            "type": relation,
            "dst_id": dst,
            "created_at": now,
        }

    def dependencies(self, issue_id: str) -> list[dict[str, Any]]:
        issue_key = issue_id.strip()
        if not issue_key:
            return []
        if not self.db_path.exists():
            return []

        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    d.src_id,
                    d.rel_type,
                    d.dst_id,
                    d.created_at,
                    src.status AS src_status,
                    dst.status AS dst_status
                FROM issue_deps d
                LEFT JOIN issues src ON src.id = d.src_id
                LEFT JOIN issues dst ON dst.id = d.dst_id
                WHERE d.src_id = ? OR d.dst_id = ?
                ORDER BY d.created_at DESC, d.src_id ASC, d.dst_id ASC
                """,
                (issue_key, issue_key),
            ).fetchall()

        deps: list[dict[str, Any]] = []
        for row in rows:
            src_status = str(row["src_status"] or "")
            dst_status = str(row["dst_status"] or "")
            relation = str(row["rel_type"])
            src_active = src_status not in TERMINAL_STATUSES
            dst_active = dst_status not in TERMINAL_STATUSES

            if relation == "blocks":
                active = src_active
            elif relation == "parent":
                active = dst_active
            else:
                active = src_active and dst_active

            deps.append(
                {
                    "src_id": str(row["src_id"]),
                    "type": relation,
                    "dst_id": str(row["dst_id"]),
                    "created_at": int(row["created_at"]),
                    "src_status": src_status,
                    "dst_status": dst_status,
                    "active": active,
                    "direction": "out" if str(row["src_id"]) == issue_key else "in",
                }
            )
        return deps

    def ready(self, *, limit: int = 20) -> list[dict[str, Any]]:
        candidates = self.list(status="open", limit=max(50, limit * 8))
        ready: list[dict[str, Any]] = []
        for issue in candidates:
            issue_id = str(issue["id"])
            blocked = False
            has_open_children = False
            for dep in self.dependencies(issue_id):
                if not bool(dep.get("active")):
                    continue
                dep_type = str(dep.get("type") or "")
                src_id = str(dep.get("src_id") or "")
                dst_id = str(dep.get("dst_id") or "")
                if dep_type == "blocks" and dst_id == issue_id:
                    blocked = True
                if dep_type == "parent" and src_id == issue_id:
                    has_open_children = True
                if blocked or has_open_children:
                    break
            if blocked or has_open_children:
                continue
            ready.append(issue)
            if len(ready) >= max(1, int(limit)):
                break
        return ready

    def _tags_for_ids(
        self,
        conn: sqlite3.Connection,
        issue_ids: list[str],
    ) -> dict[str, list[str]]:
        if not issue_ids:
            return {}

        placeholders = ", ".join("?" for _ in issue_ids)
        rows = conn.execute(
            f"""
            SELECT issue_id, tag
            FROM issue_tags
            WHERE issue_id IN ({placeholders})
            ORDER BY tag ASC
            """,
            tuple(issue_ids),
        ).fetchall()

        tags: dict[str, list[str]] = {issue_id: [] for issue_id in issue_ids}
        for row in rows:
            tags[str(row["issue_id"])].append(str(row["tag"]))
        return tags
