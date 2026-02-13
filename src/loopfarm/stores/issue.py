from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..execution_spec import normalize_execution_spec_payload
from .state import now_ms, resolve_state_dir


ISSUE_STATUSES = (
    "open",
    "in_progress",
    "paused",
    "closed",
    "duplicate",
)
TERMINAL_STATUSES = {"closed", "duplicate"}
ISSUE_OUTCOMES = (
    "success",
    "failure",
    "expanded",
    "skipped",
)
FINAL_OUTCOMES = {
    "success",
    "failure",
    "skipped",
}
NON_FINAL_OUTCOMES = {
    "expanded",
}
ROOT_FINAL_OUTCOMES = {
    "success",
    "failure",
}
CONTROL_FLOW_TAG_TO_KIND = {
    "cf:sequence": "sequence",
    "cf:fallback": "fallback",
    "cf:parallel": "parallel",
}
CONTROL_FLOW_TAGS = tuple(CONTROL_FLOW_TAG_TO_KIND.keys())
CONTROL_FLOW_KINDS = tuple(CONTROL_FLOW_TAG_TO_KIND.values())
RECONCILE_PRUNE_TAGS = {
    "sequence": "reason:upstream_failure",
    "fallback": "reason:pruned",
}

RELATION_TYPES = (
    "blocks",
    "parent",
    "related",
)
TEAM_TAG_PREFIX = "team:"


_SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS issues (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    outcome TEXT,
    execution_spec TEXT,
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


def _normalize_outcome(outcome: str) -> str:
    value = outcome.strip().lower()
    if value not in ISSUE_OUTCOMES:
        raise ValueError(f"invalid outcome: {outcome}")
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


def _control_flow_kind_from_tags(
    tags: list[str],
    *,
    issue_id: str | None = None,
    strict: bool = False,
) -> str | None:
    present = [
        CONTROL_FLOW_TAG_TO_KIND[tag] for tag in CONTROL_FLOW_TAGS if tag in tags
    ]
    if not present:
        return None
    if len(present) > 1:
        if strict:
            target = issue_id or "issue"
            raise ValueError(f"multiple control-flow tags for {target}")
        return None
    return present[0]


def _evaluate_control_flow_outcome(
    control_flow: str,
    child_outcomes: list[str | None],
) -> str:
    if not child_outcomes:
        raise ValueError("control-flow evaluation requires at least one child outcome")
    if any(outcome not in FINAL_OUTCOMES for outcome in child_outcomes):
        raise ValueError(
            "control-flow evaluation requires final child outcomes "
            "(success, failure, skipped)"
        )

    success_count = sum(1 for outcome in child_outcomes if outcome == "success")
    non_success_count = len(child_outcomes) - success_count

    if control_flow == "sequence":
        return "success" if success_count == len(child_outcomes) else "failure"
    if control_flow == "fallback":
        return "success" if success_count > 0 else "failure"
    if control_flow == "parallel":
        return "success" if success_count > non_success_count else "failure"
    raise ValueError(f"invalid control-flow kind: {control_flow}")


def _is_terminal_with_final_outcome(*, status: str, outcome: str | None) -> bool:
    return status in TERMINAL_STATUSES and outcome in FINAL_OUTCOMES


def _team_tags_from_tags(tags: list[str]) -> list[str]:
    return [
        tag
        for tag in tags
        if tag.startswith(TEAM_TAG_PREFIX) and tag[len(TEAM_TAG_PREFIX) :].strip()
    ]


def _serialize_execution_spec(value: object | None) -> str | None:
    if value is None:
        return None
    normalized = normalize_execution_spec_payload(value)
    return json.dumps(normalized, ensure_ascii=False, sort_keys=True)


def _deserialize_execution_spec(value: object) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        raw_text = value.decode("utf-8", errors="replace")
    else:
        raw_text = str(value)
    text = raw_text.strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"stored execution_spec is invalid JSON: {exc}") from exc
    normalized = normalize_execution_spec_payload(payload)
    return dict(normalized)


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
        self._migrate_schema(conn)
        return conn

    def _migrate_schema(self, conn: sqlite3.Connection) -> None:
        issue_columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(issues)").fetchall()
        }
        if "outcome" not in issue_columns:
            conn.execute("ALTER TABLE issues ADD COLUMN outcome TEXT")
        if "execution_spec" not in issue_columns:
            conn.execute("ALTER TABLE issues ADD COLUMN execution_spec TEXT")

    def create(
        self,
        title: str,
        *,
        body: str = "",
        status: str = "open",
        priority: int = 3,
        tags: list[str] | None = None,
        execution_spec: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        issue_title = title.strip()
        if not issue_title:
            raise ValueError("title cannot be empty")

        issue_status = _normalize_status(status)
        issue_priority = _normalize_priority(priority)
        spec_json = _serialize_execution_spec(execution_spec)
        now = now_ms()
        issue_id = _new_issue_id()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO issues(
                    id, title, body, status, outcome, execution_spec, priority, created_at, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    issue_id,
                    issue_title,
                    body,
                    issue_status,
                    None,
                    spec_json,
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
                SELECT id, title, body, status, outcome, execution_spec, priority, created_at, updated_at
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
            "outcome": (str(row["outcome"]) if row["outcome"] is not None else None),
            "execution_spec": _deserialize_execution_spec(row["execution_spec"]),
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
            SELECT
                i.id,
                i.title,
                i.body,
                i.status,
                i.outcome,
                i.execution_spec,
                i.priority,
                i.created_at,
                i.updated_at
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
                "outcome": (
                    str(row["outcome"]) if row["outcome"] is not None else None
                ),
                "execution_spec": _deserialize_execution_spec(row["execution_spec"]),
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
        outcome: str | None = None,
        outcome_provided: bool = False,
        execution_spec: dict[str, Any] | None = None,
        execution_spec_provided: bool = False,
    ) -> dict[str, Any]:
        issue_key = issue_id.strip()
        if not issue_key:
            raise ValueError("issue id cannot be empty")

        current_issue = self.get(issue_key)
        if current_issue is None:
            raise ValueError(f"unknown issue: {issue_key}")

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

        target_status = str(current_issue["status"])
        if status is not None:
            target_status = _normalize_status(status)
            set_parts.append("status = ?")
            params.append(target_status)

        current_outcome = current_issue.get("outcome")
        target_outcome = current_outcome
        if outcome_provided:
            target_outcome = (
                _normalize_outcome(outcome) if outcome is not None else None
            )

        if target_status not in TERMINAL_STATUSES:
            if outcome_provided and target_outcome is not None:
                raise ValueError(
                    "outcome can only be set for terminal statuses (closed, duplicate)"
                )
            if current_outcome is not None or outcome_provided:
                set_parts.append("outcome = ?")
                params.append(None)
        elif outcome_provided:
            set_parts.append("outcome = ?")
            params.append(target_outcome)

        if priority is not None:
            set_parts.append("priority = ?")
            params.append(_normalize_priority(priority))

        if execution_spec_provided:
            set_parts.append("execution_spec = ?")
            params.append(_serialize_execution_spec(execution_spec))

        if not set_parts:
            return current_issue

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

    def set_status(
        self,
        issue_id: str,
        status: str,
        *,
        outcome: str | None = None,
        outcome_provided: bool = False,
    ) -> dict[str, Any]:
        return self.update(
            issue_id,
            status=status,
            outcome=outcome,
            outcome_provided=outcome_provided,
        )

    def set_execution_spec(
        self,
        issue_id: str,
        execution_spec: dict[str, Any],
    ) -> dict[str, Any]:
        return self.update(
            issue_id,
            execution_spec=execution_spec,
            execution_spec_provided=True,
        )

    def clear_execution_spec(self, issue_id: str) -> dict[str, Any]:
        return self.update(
            issue_id,
            execution_spec=None,
            execution_spec_provided=True,
        )

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

    def _control_children(
        self,
        conn: sqlite3.Connection,
        issue_id: str,
    ) -> list[dict[str, Any]]:
        rows = conn.execute(
            """
            SELECT i.id, i.status, i.outcome, i.priority, i.updated_at
            FROM issue_deps d
            JOIN issues i ON i.id = d.dst_id
            WHERE d.src_id = ? AND d.rel_type = 'parent'
            ORDER BY i.priority ASC, i.updated_at DESC, i.id ASC
            """,
            (issue_id,),
        ).fetchall()

        return [
            {
                "id": str(row["id"]),
                "status": str(row["status"]),
                "outcome": (
                    str(row["outcome"]) if row["outcome"] is not None else None
                ),
                "priority": int(row["priority"]),
                "updated_at": int(row["updated_at"]),
            }
            for row in rows
        ]

    def _subtree_ids_with_depth(
        self,
        conn: sqlite3.Connection,
        root_issue_id: str,
    ) -> list[tuple[str, int]]:
        rows = conn.execute(
            """
            WITH RECURSIVE descendants(id, depth, path) AS (
                SELECT ?, 0, ',' || ? || ','
                UNION ALL
                SELECT
                    d.dst_id,
                    descendants.depth + 1,
                    descendants.path || d.dst_id || ','
                FROM issue_deps d
                JOIN descendants ON d.src_id = descendants.id
                WHERE d.rel_type = 'parent'
                  AND instr(descendants.path, ',' || d.dst_id || ',') = 0
            )
            SELECT id, MAX(depth) AS depth
            FROM descendants
            GROUP BY id
            ORDER BY depth DESC, id ASC
            """,
            (root_issue_id, root_issue_id),
        ).fetchall()
        return [(str(row["id"]), int(row["depth"])) for row in rows]

    def _subtree_children_map(
        self,
        conn: sqlite3.Connection,
        root_issue_id: str,
    ) -> dict[str, list[str]]:
        rows = conn.execute(
            """
            WITH RECURSIVE descendants(id, path) AS (
                SELECT ?, ',' || ? || ','
                UNION ALL
                SELECT d.dst_id, descendants.path || d.dst_id || ','
                FROM issue_deps d
                JOIN descendants ON d.src_id = descendants.id
                WHERE d.rel_type = 'parent'
                  AND instr(descendants.path, ',' || d.dst_id || ',') = 0
            )
            SELECT d.src_id, d.dst_id
            FROM issue_deps d
            JOIN descendants src ON src.id = d.src_id
            JOIN descendants dst ON dst.id = d.dst_id
            WHERE d.rel_type = 'parent'
            ORDER BY d.src_id ASC, d.dst_id ASC
            """,
            (root_issue_id, root_issue_id),
        ).fetchall()

        children: dict[str, list[str]] = {}
        for row in rows:
            src_id = str(row["src_id"])
            dst_id = str(row["dst_id"])
            children.setdefault(src_id, []).append(dst_id)
        return children

    def _descendants_with_depth_from_adjacency(
        self,
        root_issue_id: str,
        children_by_parent: dict[str, list[str]],
    ) -> dict[str, int]:
        queue: list[tuple[str, int]] = [(root_issue_id, 0)]
        depths: dict[str, int] = {root_issue_id: 0}
        cursor = 0
        while cursor < len(queue):
            current, depth = queue[cursor]
            cursor += 1
            next_depth = depth + 1
            for child in sorted(children_by_parent.get(current, [])):
                previous = depths.get(child)
                if previous is not None and previous <= next_depth:
                    continue
                depths[child] = next_depth
                queue.append((child, next_depth))
        return depths

    def _normalize_cycle_nodes(self, cycle: list[str]) -> tuple[str, ...]:
        if len(cycle) < 2:
            return tuple(cycle)
        path = cycle[:-1]
        if not path:
            return tuple(cycle)

        rotations = [
            tuple(path[index:] + path[:index]) for index in range(len(path))
        ]
        return min(rotations)

    def _detect_parent_cycles(
        self,
        root_issue_id: str,
        *,
        descendants: set[str],
        children_by_parent: dict[str, list[str]],
    ) -> list[list[str]]:
        state: dict[str, int] = {}
        stack: list[str] = []
        index_by_id: dict[str, int] = {}
        seen: set[tuple[str, ...]] = set()
        cycles: list[list[str]] = []

        def walk(issue_id: str) -> None:
            state[issue_id] = 1
            index_by_id[issue_id] = len(stack)
            stack.append(issue_id)
            for child_id in sorted(children_by_parent.get(issue_id, [])):
                if child_id not in descendants:
                    continue
                child_state = state.get(child_id, 0)
                if child_state == 0:
                    walk(child_id)
                    continue
                if child_state != 1:
                    continue
                start_index = index_by_id[child_id]
                cycle_path = stack[start_index:] + [child_id]
                normalized = self._normalize_cycle_nodes(cycle_path)
                if normalized in seen:
                    continue
                seen.add(normalized)
                cycles.append(cycle_path)

            stack.pop()
            index_by_id.pop(issue_id, None)
            state[issue_id] = 2

        walk(root_issue_id)
        return cycles

    def _issue_validation_findings(
        self,
        *,
        root_issue_id: str,
        descendants: list[str],
        depth_by_id: dict[str, int],
        issue_state: dict[str, dict[str, str | None]],
        tags_by_id: dict[str, list[str]],
        children_by_parent: dict[str, list[str]],
        parents_by_child: dict[str, list[str]],
        blocks_edges: list[tuple[str, str]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        scope = set(descendants)
        orphaned_expanded_nodes: list[dict[str, Any]] = []

        cycle_paths = self._detect_parent_cycles(
            root_issue_id,
            descendants=scope,
            children_by_parent=children_by_parent,
        )
        for cycle in cycle_paths:
            errors.append(
                {
                    "code": "parent_cycle",
                    "id": cycle[0],
                    "cycle": cycle,
                    "message": f"parent cycle detected: {' -> '.join(cycle)}",
                }
            )

        for issue_id in descendants:
            if issue_id == root_issue_id:
                continue
            parent_ids = sorted(
                parent_id
                for parent_id in parents_by_child.get(issue_id, [])
                if parent_id in scope
            )
            if parent_ids:
                continue
            errors.append(
                {
                    "code": "orphan_node",
                    "id": issue_id,
                    "message": (
                        "node is inside root scope but has no parent edge from "
                        "another in-scope node"
                    ),
                }
            )

        for issue_id in descendants:
            tags = tags_by_id.get(issue_id, [])
            control_tags = [tag for tag in CONTROL_FLOW_TAGS if tag in tags]
            is_agent = "node:agent" in tags
            is_control = "node:control" in tags
            has_node_kind = any(tag.startswith("node:") for tag in tags)

            if is_control and len(control_tags) != 1:
                errors.append(
                    {
                        "code": "node_control_invalid_cf_tags",
                        "id": issue_id,
                        "tags": control_tags,
                        "message": (
                            "node:control requires exactly one cf:* tag "
                            "(cf:sequence|cf:fallback|cf:parallel)"
                        ),
                    }
                )

            if is_agent and control_tags:
                errors.append(
                    {
                        "code": "node_agent_has_cf_tag",
                        "id": issue_id,
                        "tags": control_tags,
                        "message": "node:agent must not include any cf:* tag",
                    }
                )

            if is_agent and is_control:
                errors.append(
                    {
                        "code": "node_type_conflict",
                        "id": issue_id,
                        "message": "node cannot be both node:agent and node:control",
                    }
                )

            state = issue_state.get(issue_id)
            if state is None:
                continue
            status = str(state.get("status") or "")
            outcome = state.get("outcome")

            if has_node_kind and status in TERMINAL_STATUSES and outcome is None:
                errors.append(
                    {
                        "code": "terminal_node_missing_outcome",
                        "id": issue_id,
                        "status": status,
                        "message": (
                            "terminal node:* issue must include a non-null outcome"
                        ),
                    }
                )

        for src_id, dst_id in blocks_edges:
            src_in_scope = src_id in scope
            dst_in_scope = dst_id in scope
            if src_in_scope and dst_in_scope:
                src_parents = {
                    parent_id
                    for parent_id in parents_by_child.get(src_id, [])
                    if parent_id in scope
                }
                dst_parents = {
                    parent_id
                    for parent_id in parents_by_child.get(dst_id, [])
                    if parent_id in scope
                }
                shared_parent_ids = sorted(src_parents & dst_parents)
                if shared_parent_ids:
                    continue
                errors.append(
                    {
                        "code": "blocks_not_siblings",
                        "src_id": src_id,
                        "dst_id": dst_id,
                        "message": (
                            "blocks edges must connect siblings under the same parent "
                            "within the validated root scope"
                        ),
                    }
                )
                continue

            if src_in_scope or dst_in_scope:
                warnings.append(
                    {
                        "code": "blocks_cross_scope",
                        "src_id": src_id,
                        "dst_id": dst_id,
                        "message": (
                            "blocks edge crosses root scope boundary; prefer sibling "
                            "edges within a shared parent"
                        ),
                    }
                )

        active_or_descendant_active: dict[str, bool] = {}
        ordered_descendants = sorted(
            descendants,
            key=lambda issue_id: (-int(depth_by_id.get(issue_id, 0)), issue_id),
        )
        for issue_id in ordered_descendants:
            state = issue_state.get(issue_id)
            status = str(state.get("status")) if state is not None else "open"
            active = status not in TERMINAL_STATUSES
            active_or_descendant_active[issue_id] = active
            for child_id in children_by_parent.get(issue_id, []):
                if child_id not in scope:
                    continue
                if active_or_descendant_active.get(child_id, False):
                    active_or_descendant_active[issue_id] = True
                    break

        has_active_descendants = {
            issue_id: any(
                active_or_descendant_active.get(child_id, False)
                for child_id in children_by_parent.get(issue_id, [])
                if child_id in scope
            )
            for issue_id in descendants
        }

        for issue_id in descendants:
            state = issue_state.get(issue_id)
            if state is None:
                continue
            status = str(state.get("status") or "")
            outcome = state.get("outcome")
            if status not in TERMINAL_STATUSES or outcome != "expanded":
                continue
            if has_active_descendants.get(issue_id, False):
                continue
            orphaned_expanded_nodes.append(
                {
                    "id": issue_id,
                    "status": status,
                    "outcome": outcome,
                    "message": (
                        "expanded node has no active descendants; update it to a "
                        "final outcome (success/failure) or reopen and decompose"
                    ),
                }
            )
            errors.append(
                {
                    "code": "orphaned_expanded_node",
                    "id": issue_id,
                    "message": (
                        "expanded node has no active descendants; update it to a "
                        "final outcome (success/failure) or reopen and decompose"
                    ),
                }
            )

        return errors, warnings, orphaned_expanded_nodes

    def validate_dag(self, root_issue_id: str) -> dict[str, Any]:
        root_key = root_issue_id.strip()
        if not root_key:
            raise ValueError("root issue id cannot be empty")
        if self.get(root_key) is None:
            raise ValueError(f"unknown issue: {root_key}")

        with self._connect() as conn:
            parent_rows = conn.execute(
                """
                SELECT src_id, dst_id
                FROM issue_deps
                WHERE rel_type = 'parent'
                ORDER BY src_id ASC, dst_id ASC
                """
            ).fetchall()
            blocks_rows = conn.execute(
                """
                SELECT src_id, dst_id
                FROM issue_deps
                WHERE rel_type = 'blocks'
                ORDER BY src_id ASC, dst_id ASC
                """
            ).fetchall()

            children_by_parent: dict[str, list[str]] = {}
            parents_by_child: dict[str, list[str]] = {}
            for row in parent_rows:
                src_id = str(row["src_id"])
                dst_id = str(row["dst_id"])
                children_by_parent.setdefault(src_id, []).append(dst_id)
                parents_by_child.setdefault(dst_id, []).append(src_id)

            depth_by_id = self._descendants_with_depth_from_adjacency(
                root_key,
                children_by_parent,
            )
            descendants = sorted(
                depth_by_id.keys(),
                key=lambda issue_id: (int(depth_by_id.get(issue_id, 0)), issue_id),
            )
            issue_state = self._issue_states_for_ids(conn, descendants)
            tags_by_id = self._tags_for_ids(conn, descendants)
            blocks_edges = [
                (str(row["src_id"]), str(row["dst_id"])) for row in blocks_rows
            ]

        errors, warnings, orphaned_expanded_nodes = self._issue_validation_findings(
            root_issue_id=root_key,
            descendants=descendants,
            depth_by_id=depth_by_id,
            issue_state=issue_state,
            tags_by_id=tags_by_id,
            children_by_parent=children_by_parent,
            parents_by_child=parents_by_child,
            blocks_edges=blocks_edges,
        )

        descendant_set = set(descendants)
        in_scope_parent_edges = [
            (src_id, dst_id)
            for src_id, dst_id in (
                (str(row["src_id"]), str(row["dst_id"])) for row in parent_rows
            )
            if src_id in descendant_set and dst_id in descendant_set
        ]
        in_scope_blocks_edges = [
            (src_id, dst_id)
            for src_id, dst_id in blocks_edges
            if src_id in descendant_set and dst_id in descendant_set
        ]

        checks = {
            "parent_acyclic": not any(
                finding.get("code") == "parent_cycle" for finding in errors
            ),
            "node_typing": not any(
                finding.get("code")
                in (
                    "node_control_invalid_cf_tags",
                    "node_agent_has_cf_tag",
                    "node_type_conflict",
                )
                for finding in errors
            ),
            "terminal_outcomes": not any(
                finding.get("code") == "terminal_node_missing_outcome"
                for finding in errors
            ),
            "blocks_sibling_wiring": not any(
                finding.get("code") == "blocks_not_siblings" for finding in errors
            ),
            "orphan_reachability": not any(
                finding.get("code") in ("orphan_node", "orphaned_expanded_node")
                for finding in errors
            ),
        }

        return {
            "root_id": root_key,
            "node_count": len(descendants),
            "nodes": descendants,
            "edges": {
                "parent": len(in_scope_parent_edges),
                "blocks": len(in_scope_blocks_edges),
            },
            "checks": checks,
            "orphaned_expanded_nodes": orphaned_expanded_nodes,
            "errors": errors,
            "warnings": warnings,
        }

    def _issue_states_for_ids(
        self,
        conn: sqlite3.Connection,
        issue_ids: list[str],
    ) -> dict[str, dict[str, str | None]]:
        if not issue_ids:
            return {}

        placeholders = ", ".join("?" for _ in issue_ids)
        rows = conn.execute(
            f"""
            SELECT id, status, outcome
            FROM issues
            WHERE id IN ({placeholders})
            """,
            tuple(issue_ids),
        ).fetchall()
        return {
            str(row["id"]): {
                "status": str(row["status"]),
                "outcome": (
                    str(row["outcome"]) if row["outcome"] is not None else None
                ),
            }
            for row in rows
        }

    def _ancestor_ids_with_depth(
        self,
        conn: sqlite3.Connection,
        issue_id: str,
    ) -> list[tuple[str, int]]:
        rows = conn.execute(
            """
            WITH RECURSIVE ancestors(id, depth, path) AS (
                SELECT ?, 0, ',' || ? || ','
                UNION ALL
                SELECT d.src_id, ancestors.depth + 1, ancestors.path || d.src_id || ','
                FROM issue_deps d
                JOIN ancestors ON d.dst_id = ancestors.id
                WHERE d.rel_type = 'parent'
                  AND instr(ancestors.path, ',' || d.src_id || ',') = 0
            )
            SELECT id, MIN(depth) AS depth
            FROM ancestors
            GROUP BY id
            ORDER BY depth ASC, id ASC
            """,
            (issue_id, issue_id),
        ).fetchall()
        return [(str(row["id"]), int(row["depth"])) for row in rows]

    def _ancestor_chains_with_depth(
        self,
        conn: sqlite3.Connection,
        issue_ids: list[str],
    ) -> dict[str, list[tuple[str, int]]]:
        if not issue_ids:
            return {}

        unique_issue_ids = list(dict.fromkeys(issue_ids))
        placeholders = ", ".join("(?)" for _ in unique_issue_ids)
        rows = conn.execute(
            f"""
            WITH RECURSIVE
            seed(issue_id) AS (
                VALUES {placeholders}
            ),
            ancestors(issue_id, ancestor_id, depth, path) AS (
                SELECT
                    seed.issue_id,
                    seed.issue_id,
                    0,
                    ',' || seed.issue_id || ','
                FROM seed
                UNION ALL
                SELECT
                    ancestors.issue_id,
                    d.src_id,
                    ancestors.depth + 1,
                    ancestors.path || d.src_id || ','
                FROM issue_deps d
                JOIN ancestors ON d.dst_id = ancestors.ancestor_id
                WHERE d.rel_type = 'parent'
                  AND instr(ancestors.path, ',' || d.src_id || ',') = 0
            )
            SELECT issue_id, ancestor_id, MIN(depth) AS depth
            FROM ancestors
            GROUP BY issue_id, ancestor_id
            ORDER BY issue_id ASC, depth ASC, ancestor_id ASC
            """,
            tuple(unique_issue_ids),
        ).fetchall()

        chains: dict[str, list[tuple[str, int]]] = {
            issue_id: [] for issue_id in unique_issue_ids
        }
        for row in rows:
            issue_id = str(row["issue_id"])
            chains.setdefault(issue_id, []).append(
                (str(row["ancestor_id"]), int(row["depth"]))
            )
        return chains

    def _ancestor_scope_under_root(
        self,
        conn: sqlite3.Connection,
        *,
        issue_id: str,
        root_id: str,
        chain: list[tuple[str, int]],
    ) -> set[str]:
        chain_ids = [node_id for node_id, _depth in chain]
        if root_id not in chain_ids:
            raise ValueError(
                f"issue {issue_id} is not in the parent-descendant subtree of root {root_id}"
            )

        placeholders = ", ".join("?" for _ in chain_ids)
        rows = conn.execute(
            f"""
            SELECT src_id, dst_id
            FROM issue_deps
            WHERE rel_type = 'parent'
              AND src_id IN ({placeholders})
              AND dst_id IN ({placeholders})
            ORDER BY src_id ASC, dst_id ASC
            """,
            tuple(chain_ids + chain_ids),
        ).fetchall()

        children_by_parent: dict[str, list[str]] = {}
        for row in rows:
            src_id = str(row["src_id"])
            dst_id = str(row["dst_id"])
            children_by_parent.setdefault(src_id, []).append(dst_id)

        scoped_ids: set[str] = {root_id}
        queue: list[str] = [root_id]
        cursor = 0
        while cursor < len(queue):
            parent_id = queue[cursor]
            cursor += 1
            for child_id in children_by_parent.get(parent_id, []):
                if child_id in scoped_ids:
                    continue
                scoped_ids.add(child_id)
                queue.append(child_id)

        if issue_id not in scoped_ids:
            raise ValueError(
                f"issue {issue_id} is not in the parent-descendant subtree of root {root_id}"
            )
        return scoped_ids

    def _resolve_team_from_chain(
        self,
        issue_id: str,
        chain: list[tuple[str, int]],
        tags_by_id: dict[str, list[str]],
        *,
        default_team: str | None = None,
    ) -> dict[str, Any]:
        if not chain:
            raise ValueError(f"unknown issue: {issue_id}")

        chain_ids = [node_id for node_id, _depth in chain]
        for node_id, depth in chain:
            tags = tags_by_id.get(node_id, [])
            team_tags = _team_tags_from_tags(tags)
            if len(team_tags) > 1:
                joined = ", ".join(team_tags)
                raise ValueError(
                    f"multiple team:* tags on issue {node_id}: {joined}"
                )
            if len(team_tags) == 1:
                team_tag = team_tags[0]
                team_name = team_tag[len(TEAM_TAG_PREFIX) :].strip()
                source = "issue_tag" if depth == 0 else "ancestor_tag"
                return {
                    "issue_id": issue_id,
                    "team": team_name,
                    "source": source,
                    "source_issue_id": node_id,
                    "source_tag": team_tag,
                    "depth": depth,
                    "lineage": chain_ids,
                }

        fallback_team = (default_team or "").strip()
        if fallback_team:
            return {
                "issue_id": issue_id,
                "team": fallback_team,
                "source": "default_team",
                "source_issue_id": None,
                "source_tag": None,
                "depth": None,
                "lineage": chain_ids,
            }

        raise ValueError(
            f"unable to resolve team for {issue_id}: add optional team:<name> "
            "on the node or an ancestor"
        )

    def _resolve_team(
        self,
        conn: sqlite3.Connection,
        issue_id: str,
        *,
        default_team: str | None = None,
    ) -> dict[str, Any]:
        chain = self._ancestor_ids_with_depth(conn, issue_id)
        if not chain:
            raise ValueError(f"unknown issue: {issue_id}")

        chain_ids = [node_id for node_id, _depth in chain]
        tags_by_id = self._tags_for_ids(conn, chain_ids)
        return self._resolve_team_from_chain(
            issue_id,
            chain,
            tags_by_id,
            default_team=default_team,
        )

    def resolve_team(
        self,
        issue_id: str,
        *,
        default_team: str | None = None,
    ) -> dict[str, Any]:
        issue_key = issue_id.strip()
        if not issue_key:
            raise ValueError("issue id cannot be empty")

        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM issues WHERE id = ? LIMIT 1",
                (issue_key,),
            ).fetchone()
            if exists is None:
                raise ValueError(f"unknown issue: {issue_key}")
            return self._resolve_team(
                conn,
                issue_key,
                default_team=default_team,
            )

    def affected_control_flow_ancestors(
        self,
        issue_id: str,
        *,
        root_id: str | None = None,
    ) -> list[dict[str, Any]]:
        issue_key = issue_id.strip()
        if not issue_key:
            raise ValueError("issue id cannot be empty")

        root_key: str | None = None
        if root_id is not None:
            root_key = root_id.strip()
            if not root_key:
                raise ValueError("root issue id cannot be empty")

        with self._connect() as conn:
            issue_exists = conn.execute(
                "SELECT 1 FROM issues WHERE id = ? LIMIT 1",
                (issue_key,),
            ).fetchone()
            if issue_exists is None:
                raise ValueError(f"unknown issue: {issue_key}")

            if root_key is not None:
                root_exists = conn.execute(
                    "SELECT 1 FROM issues WHERE id = ? LIMIT 1",
                    (root_key,),
                ).fetchone()
                if root_exists is None:
                    raise ValueError(f"unknown issue: {root_key}")

            chain = self._ancestor_ids_with_depth(conn, issue_key)
            scoped_ids = {node_id for node_id, _depth in chain}
            if root_key is not None:
                scoped_ids = self._ancestor_scope_under_root(
                    conn,
                    issue_id=issue_key,
                    root_id=root_key,
                    chain=chain,
                )

            tags_by_id = self._tags_for_ids(conn, sorted(scoped_ids))

        targets: list[dict[str, Any]] = []
        for node_id, depth in chain:
            if depth == 0 or node_id not in scoped_ids:
                continue
            control_flow = _control_flow_kind_from_tags(
                tags_by_id.get(node_id, []),
                issue_id=node_id,
                strict=False,
            )
            if control_flow in ("sequence", "fallback"):
                targets.append(
                    {
                        "id": node_id,
                        "depth": depth,
                        "control_flow": control_flow,
                    }
                )
        return targets

    def reconcile_control_flow_ancestors(
        self,
        issue_id: str,
        *,
        root_issue_id: str,
    ) -> dict[str, Any]:
        issue_key = issue_id.strip()
        if not issue_key:
            raise ValueError("issue id cannot be empty")
        root_key = root_issue_id.strip()
        if not root_key:
            raise ValueError("root issue id cannot be empty")

        targets = self.affected_control_flow_ancestors(
            issue_key,
            root_id=root_key,
        )
        reconciled = [
            self.reconcile_control_flow(str(target["id"]))
            for target in targets
        ]
        validation = self.validate_orchestration_subtree(root_key)
        return {
            "root_id": root_key,
            "issue_id": issue_key,
            "target_count": len(targets),
            "target_ids": [str(target["id"]) for target in targets],
            "targets": targets,
            "reconciled_count": len(reconciled),
            "reconciled": reconciled,
            "validation": validation,
        }

    def validate_orchestration_subtree(self, root_issue_id: str) -> dict[str, Any]:
        root_key = root_issue_id.strip()
        if not root_key:
            raise ValueError("root issue id cannot be empty")

        with self._connect() as conn:
            exists = conn.execute(
                "SELECT 1 FROM issues WHERE id = ? LIMIT 1",
                (root_key,),
            ).fetchone()
            if exists is None:
                raise ValueError(f"unknown issue: {root_key}")

            node_rows = self._subtree_ids_with_depth(conn, root_key)
            node_ids = [issue_id for issue_id, _depth in node_rows]
            issue_state = self._issue_states_for_ids(conn, node_ids)
            children = self._subtree_children_map(conn, root_key)
            tags_by_id = self._tags_for_ids(conn, node_ids)

        active_or_descendant_active: dict[str, bool] = {}
        for issue_id, _depth in node_rows:
            state = issue_state.get(issue_id)
            status = str(state.get("status")) if state is not None else "open"
            active = status not in TERMINAL_STATUSES
            active_or_descendant_active[issue_id] = active
            for child_id in children.get(issue_id, []):
                if active_or_descendant_active.get(child_id, False):
                    active_or_descendant_active[issue_id] = True
                    break

        has_active_descendants = {
            issue_id: any(
                active_or_descendant_active.get(child_id, False)
                for child_id in children.get(issue_id, [])
            )
            for issue_id in node_ids
        }

        orphaned_expanded_nodes: list[dict[str, Any]] = []
        for issue_id in node_ids:
            state = issue_state.get(issue_id)
            if state is None:
                continue
            status = str(state.get("status"))
            outcome = state.get("outcome")
            if status not in TERMINAL_STATUSES or outcome != "expanded":
                continue
            if has_active_descendants.get(issue_id, False):
                continue
            orphaned_expanded_nodes.append(
                {
                    "id": issue_id,
                    "status": status,
                    "outcome": outcome,
                    "message": (
                        "expanded node has no active descendants; update it to a "
                        "final outcome (success/failure) or reopen and decompose"
                    ),
                }
            )

        errors = [
            {
                "code": "orphaned_expanded_node",
                "id": row["id"],
                "message": row["message"],
            }
            for row in orphaned_expanded_nodes
        ]

        root_state = issue_state.get(root_key)
        if root_state is None:
            raise ValueError(f"unknown issue: {root_key}")
        root_status = str(root_state.get("status") or "")
        root_outcome = root_state.get("outcome")
        root_has_active_descendants = has_active_descendants.get(root_key, False)

        if root_status not in TERMINAL_STATUSES:
            termination_reason = "root_not_terminal"
            root_is_final = False
        elif root_outcome in ROOT_FINAL_OUTCOMES:
            if root_has_active_descendants:
                termination_reason = "root_final_outcome_has_active_descendants"
                root_is_final = False
                errors.append(
                    {
                        "code": "root_final_with_active_descendants",
                        "id": root_key,
                        "message": (
                            "root cannot terminate while descendants are active; "
                            "reconcile descendants first"
                        ),
                    }
                )
            else:
                termination_reason = "root_final_outcome"
                root_is_final = True
        elif root_outcome in NON_FINAL_OUTCOMES:
            termination_reason = "expanded_non_final"
            root_is_final = False
        else:
            termination_reason = "root_terminal_non_final_outcome"
            root_is_final = False

        warnings: list[dict[str, str]] = []
        if root_outcome in NON_FINAL_OUTCOMES and not root_has_active_descendants:
            warnings.append(
                {
                    "code": "root_expanded_without_active_descendants",
                    "message": (
                        "root is expanded but has no active descendants; this is "
                        "usually an orphaned expansion"
                    ),
                }
            )

        return {
            "root_id": root_key,
            "root": {
                "status": root_status,
                "outcome": root_outcome,
            },
            "termination": {
                "final_outcomes": sorted(ROOT_FINAL_OUTCOMES),
                "is_final": root_is_final,
                "reason": termination_reason,
                "has_active_descendants": root_has_active_descendants,
            },
            "orphaned_expanded_nodes": orphaned_expanded_nodes,
            "errors": errors,
            "warnings": warnings,
        }

    def reconcile_control_flow(self, issue_id: str) -> dict[str, Any]:
        issue_key = issue_id.strip()
        if not issue_key:
            raise ValueError("issue id cannot be empty")

        issue = self.get(issue_key)
        if issue is None:
            raise ValueError(f"unknown issue: {issue_key}")

        control_flow = _control_flow_kind_from_tags(
            [str(tag) for tag in issue.get("tags") or []],
            issue_id=issue_key,
            strict=True,
        )
        if control_flow not in ("sequence", "fallback"):
            raise ValueError(
                f"reconcile supports cf:sequence/cf:fallback nodes only: {issue_key}"
            )

        prune_tag = RECONCILE_PRUNE_TAGS[control_flow]
        pruned_ids: list[str] = []
        closed = False
        target_outcome: str | None = None

        with self._connect() as conn:
            children = self._control_children(conn, issue_key)
            if not children:
                return {
                    "id": issue_key,
                    "control_flow": control_flow,
                    "outcome": None,
                    "closed": False,
                    "pruned_count": 0,
                    "pruned_ids": [],
                    "prune_tag": prune_tag,
                    "all_children_terminal": True,
                    "children": [],
                }

            child_outcomes = [child.get("outcome") for child in children]
            has_failure = any(outcome == "failure" for outcome in child_outcomes)
            has_success = any(outcome == "success" for outcome in child_outcomes)

            if control_flow == "sequence" and has_failure:
                target_outcome = "failure"
            elif control_flow == "fallback" and has_success:
                target_outcome = "success"

            should_prune = target_outcome is not None
            if should_prune:
                for child in children:
                    child_id = str(child["id"])
                    child_status = str(child["status"])
                    if child_status in TERMINAL_STATUSES:
                        continue

                    now = now_ms()
                    updated = conn.execute(
                        """
                        UPDATE issues
                        SET status = 'duplicate', outcome = 'skipped', updated_at = ?
                        WHERE id = ? AND status NOT IN ('closed', 'duplicate')
                        """,
                        (now, child_id),
                    )
                    if updated.rowcount == 0:
                        continue

                    pruned_ids.append(child_id)
                    conn.execute(
                        "INSERT OR IGNORE INTO issue_tags(issue_id, tag) VALUES(?, ?)",
                        (child_id, prune_tag),
                    )

            children = self._control_children(conn, issue_key)
            all_children_final = all(
                _is_terminal_with_final_outcome(
                    status=str(child["status"]),
                    outcome=(
                        str(child["outcome"])
                        if child.get("outcome") is not None
                        else None
                    ),
                )
                for child in children
            )

            if target_outcome is None and all_children_final:
                target_outcome = _evaluate_control_flow_outcome(
                    control_flow,
                    [child.get("outcome") for child in children],
                )

            if target_outcome is not None:
                now = now_ms()
                closed_row = conn.execute(
                    """
                    UPDATE issues
                    SET status = 'closed', outcome = ?, updated_at = ?
                    WHERE id = ? AND (
                        status != 'closed'
                        OR COALESCE(outcome, '') != ?
                    )
                    """,
                    (target_outcome, now, issue_key, target_outcome),
                )
                closed = closed_row.rowcount > 0

        refreshed = self.get(issue_key)
        if refreshed is None:
            raise ValueError(f"unknown issue: {issue_key}")
        refreshed_children = self._children_with_tags(issue_key)
        return {
            "id": issue_key,
            "control_flow": control_flow,
            "outcome": refreshed.get("outcome"),
            "closed": closed,
            "pruned_count": len(pruned_ids),
            "pruned_ids": pruned_ids,
            "prune_tag": prune_tag,
            "all_children_terminal": all(
                str(child["status"]) in TERMINAL_STATUSES
                for child in refreshed_children
            ),
            "all_children_final": all(
                _is_terminal_with_final_outcome(
                    status=str(child["status"]),
                    outcome=(
                        str(child["outcome"])
                        if child.get("outcome") is not None
                        else None
                    ),
                )
                for child in refreshed_children
            ),
            "children": refreshed_children,
        }

    def reconcile_control_flow_subtree(self, root_issue_id: str) -> dict[str, Any]:
        root_key = root_issue_id.strip()
        if not root_key:
            raise ValueError("root issue id cannot be empty")
        if self.get(root_key) is None:
            raise ValueError(f"unknown issue: {root_key}")

        with self._connect() as conn:
            rows = self._subtree_ids_with_depth(conn, root_key)
            issue_ids = [issue_id for issue_id, _depth in rows]
            tags_by_id = self._tags_for_ids(conn, issue_ids)

        targets = [
            issue_id
            for issue_id, _depth in rows
            if _control_flow_kind_from_tags(
                tags_by_id.get(issue_id, []),
                issue_id=issue_id,
                strict=False,
            )
            in ("sequence", "fallback")
        ]

        reconciled = [self.reconcile_control_flow(issue_id) for issue_id in targets]
        validation = self.validate_orchestration_subtree(root_key)
        return {
            "root_id": root_key,
            "reconciled_count": len(reconciled),
            "reconciled": reconciled,
            "validation": validation,
        }

    def _children_with_tags(self, issue_id: str) -> list[dict[str, Any]]:
        with self._connect() as conn:
            children = self._control_children(conn, issue_id)
            child_ids = [str(child["id"]) for child in children]
            tags_by_id = self._tags_for_ids(conn, child_ids)
        for child in children:
            child["tags"] = tags_by_id.get(str(child["id"]), [])
        return children

    def evaluate_control_flow(self, issue_id: str) -> dict[str, Any] | None:
        issue_key = issue_id.strip()
        if not issue_key:
            raise ValueError("issue id cannot be empty")

        issue = self.get(issue_key)
        if issue is None:
            raise ValueError(f"unknown issue: {issue_key}")

        control_flow = _control_flow_kind_from_tags(
            [str(tag) for tag in issue.get("tags") or []],
            issue_id=issue_key,
            strict=True,
        )
        if control_flow is None:
            raise ValueError(f"issue is not a control-flow node: {issue_key}")

        with self._connect() as conn:
            children = self._control_children(conn, issue_key)

        if not children:
            return None
        if any(str(child["status"]) not in TERMINAL_STATUSES for child in children):
            return None

        child_outcomes = [child.get("outcome") for child in children]
        if any(outcome not in FINAL_OUTCOMES for outcome in child_outcomes):
            return None
        outcome = _evaluate_control_flow_outcome(control_flow, child_outcomes)

        outcome_counts = {name: 0 for name in ISSUE_OUTCOMES}
        unset_count = 0
        for child_outcome in child_outcomes:
            if child_outcome is None:
                unset_count += 1
                continue
            if child_outcome in outcome_counts:
                outcome_counts[child_outcome] += 1

        return {
            "id": issue_key,
            "control_flow": control_flow,
            "outcome": outcome,
            "all_children_terminal": True,
            "all_children_final": True,
            "child_count": len(children),
            "outcome_counts": {
                **outcome_counts,
                "unset": unset_count,
            },
            "children": children,
        }

    def evaluatable_control_flow_nodes(
        self, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        candidates = self.list(limit=max(50, int(limit) * 8))
        rows: list[dict[str, Any]] = []
        for issue in candidates:
            if str(issue.get("status") or "") in TERMINAL_STATUSES:
                continue
            control_flow = _control_flow_kind_from_tags(
                [str(tag) for tag in issue.get("tags") or []],
                strict=False,
            )
            if control_flow is None:
                continue

            evaluated = self.evaluate_control_flow(str(issue["id"]))
            if evaluated is None:
                continue
            rows.append(evaluated)
            if len(rows) >= max(1, int(limit)):
                break
        return rows

    def _ready_where_clauses(
        self,
        *,
        issue_alias: str,
        status: str,
        required_tags: list[str],
    ) -> tuple[list[str], list[Any]]:
        clauses: list[str] = [
            f"{issue_alias}.status = ?",
            f"""
            NOT EXISTS (
                SELECT 1
                FROM issue_deps d
                JOIN issues blocker ON blocker.id = d.src_id
                WHERE d.rel_type = 'blocks'
                  AND d.dst_id = {issue_alias}.id
                  AND blocker.status NOT IN ('closed', 'duplicate')
            )
            """,
            f"""
            NOT EXISTS (
                SELECT 1
                FROM issue_deps d
                JOIN issues child ON child.id = d.dst_id
                WHERE d.rel_type = 'parent'
                  AND d.src_id = {issue_alias}.id
                  AND child.status NOT IN ('closed', 'duplicate')
            )
            """,
        ]
        params: list[Any] = [status]
        for index, required_tag in enumerate(required_tags):
            tag_alias = f"t{index}"
            clauses.append(
                f"""
                EXISTS (
                    SELECT 1
                    FROM issue_tags {tag_alias}
                    WHERE {tag_alias}.issue_id = {issue_alias}.id
                      AND {tag_alias}.tag = ?
                )
                """
            )
            params.append(required_tag)
        return clauses, params

    def _ready_rows(
        self,
        conn: sqlite3.Connection,
        *,
        status: str,
        limit: int,
        root_key: str | None,
        required_tags: list[str],
        updated_desc: bool,
    ) -> list[sqlite3.Row]:
        where, params = self._ready_where_clauses(
            issue_alias="i",
            status=status,
            required_tags=required_tags,
        )
        if root_key is not None:
            where.append("EXISTS (SELECT 1 FROM scope WHERE scope.id = i.id)")

        query = """
            SELECT
                i.id,
                i.title,
                i.body,
                i.status,
                i.outcome,
                i.execution_spec,
                i.priority,
                i.created_at,
                i.updated_at
            FROM issues i
        """
        if root_key is not None:
            query = """
                WITH RECURSIVE scope(id) AS (
                    SELECT ?
                    UNION
                    SELECT d.dst_id
                    FROM issue_deps d
                    JOIN scope ON d.src_id = scope.id
                    WHERE d.rel_type = 'parent'
                )
                SELECT
                    i.id,
                    i.title,
                    i.body,
                    i.status,
                    i.outcome,
                    i.execution_spec,
                    i.priority,
                    i.created_at,
                    i.updated_at
                FROM issues i
            """
            params = [root_key, *params]
        query += " WHERE " + " AND ".join(where)
        order_direction = "DESC" if updated_desc else "ASC"
        query += f"""
            ORDER BY i.priority ASC, i.updated_at {order_direction}, i.id ASC
            LIMIT ?
        """
        params.append(max(1, int(limit)))
        return conn.execute(query, tuple(params)).fetchall()

    def ready(
        self,
        *,
        limit: int = 20,
        root_id: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        requested_limit = max(1, int(limit))
        root_key: str | None = None
        if root_id is not None:
            root_key = root_id.strip()
            if not root_key:
                raise ValueError("root issue id cannot be empty")

        required_tags = sorted({tag.strip() for tag in (tags or []) if tag.strip()})

        if not self.db_path.exists():
            if root_key is not None:
                raise ValueError(f"unknown issue: {root_key}")
            return []

        with self._connect() as conn:
            if root_key is not None:
                root_exists = conn.execute(
                    "SELECT 1 FROM issues WHERE id = ?",
                    (root_key,),
                ).fetchone()
                if root_exists is None:
                    raise ValueError(f"unknown issue: {root_key}")

            rows = self._ready_rows(
                conn,
                status="open",
                limit=requested_limit,
                root_key=root_key,
                required_tags=required_tags,
                updated_desc=True,
            )
            ids = [str(row["id"]) for row in rows]
            tags_by_id = self._tags_for_ids(conn, ids)

        return [
            {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "body": str(row["body"]),
                "status": str(row["status"]),
                "outcome": (
                    str(row["outcome"]) if row["outcome"] is not None else None
                ),
                "execution_spec": _deserialize_execution_spec(row["execution_spec"]),
                "priority": int(row["priority"]),
                "created_at": int(row["created_at"]),
                "updated_at": int(row["updated_at"]),
                "tags": tags_by_id.get(str(row["id"]), []),
            }
            for row in rows
        ]

    def resumable(
        self,
        *,
        limit: int = 20,
        root_id: str | None = None,
        tags: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        requested_limit = max(1, int(limit))
        root_key: str | None = None
        if root_id is not None:
            root_key = root_id.strip()
            if not root_key:
                raise ValueError("root issue id cannot be empty")

        required_tags = sorted({tag.strip() for tag in (tags or []) if tag.strip()})

        if not self.db_path.exists():
            if root_key is not None:
                raise ValueError(f"unknown issue: {root_key}")
            return []

        with self._connect() as conn:
            if root_key is not None:
                root_exists = conn.execute(
                    "SELECT 1 FROM issues WHERE id = ?",
                    (root_key,),
                ).fetchone()
                if root_exists is None:
                    raise ValueError(f"unknown issue: {root_key}")

            rows = self._ready_rows(
                conn,
                status="in_progress",
                limit=requested_limit,
                root_key=root_key,
                required_tags=required_tags,
                updated_desc=False,
            )
            ids = [str(row["id"]) for row in rows]
            tags_by_id = self._tags_for_ids(conn, ids)

        return [
            {
                "id": str(row["id"]),
                "title": str(row["title"]),
                "body": str(row["body"]),
                "status": str(row["status"]),
                "outcome": (
                    str(row["outcome"]) if row["outcome"] is not None else None
                ),
                "execution_spec": _deserialize_execution_spec(row["execution_spec"]),
                "priority": int(row["priority"]),
                "created_at": int(row["created_at"]),
                "updated_at": int(row["updated_at"]),
                "tags": tags_by_id.get(str(row["id"]), []),
            }
            for row in rows
        ]

    def claim_ready_leaf(
        self,
        issue_id: str,
        *,
        root_id: str | None = None,
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        issue_key = issue_id.strip()
        if not issue_key:
            raise ValueError("issue id cannot be empty")

        root_key: str | None = None
        if root_id is not None:
            root_key = root_id.strip()
            if not root_key:
                raise ValueError("root issue id cannot be empty")

        required_tags = sorted({tag.strip() for tag in (tags or []) if tag.strip()})
        claim_timestamp = now_ms()
        with self._connect() as conn:
            issue_exists = conn.execute(
                "SELECT 1 FROM issues WHERE id = ?",
                (issue_key,),
            ).fetchone()
            if issue_exists is None:
                raise ValueError(f"unknown issue: {issue_key}")

            if root_key is not None:
                root_exists = conn.execute(
                    "SELECT 1 FROM issues WHERE id = ?",
                    (root_key,),
                ).fetchone()
                if root_exists is None:
                    raise ValueError(f"unknown issue: {root_key}")

            where, where_params = self._ready_where_clauses(
                issue_alias="i",
                status="open",
                required_tags=required_tags,
            )
            where.insert(0, "i.id = ?")
            where_params = [issue_key, *where_params]

            query = ""
            params: list[Any] = []
            if root_key is not None:
                query += """
                    WITH RECURSIVE scope(id) AS (
                        SELECT ?
                        UNION
                        SELECT d.dst_id
                        FROM issue_deps d
                        JOIN scope ON d.src_id = scope.id
                        WHERE d.rel_type = 'parent'
                    )
                """
                params.append(root_key)
                where.append("EXISTS (SELECT 1 FROM scope WHERE scope.id = i.id)")

            query += f"""
                UPDATE issues AS i
                SET status = 'in_progress', updated_at = ?
                WHERE {' AND '.join(where)}
                RETURNING id
            """
            params.extend([claim_timestamp, *where_params])
            claimed = conn.execute(query, tuple(params)).fetchone() is not None

        issue = self.get(issue_key)
        if issue is None:
            raise ValueError(f"unknown issue: {issue_key}")
        return {
            "id": issue_key,
            "claimed": claimed,
            "claimed_at": claim_timestamp if claimed else None,
            "issue": issue,
        }

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
