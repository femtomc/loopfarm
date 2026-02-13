"""JSONL-backed issue and forum stores."""

from __future__ import annotations

import json
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _short_id() -> str:
    return uuid.uuid4().hex[:8]


def _now() -> int:
    return int(time.time())


# ---------------------------------------------------------------------------
# Low-level JSONL helpers
# ---------------------------------------------------------------------------


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    os.replace(tmp, path)


# ---------------------------------------------------------------------------
# IssueStore
# ---------------------------------------------------------------------------


class IssueStore:
    """JSONL-backed issue tracker stored in .loopfarm/issues.jsonl."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def from_workdir(cls, root: Path | None = None) -> IssueStore:
        root = root or Path.cwd()
        return cls(root / ".loopfarm" / "issues.jsonl")

    # -- read helpers -------------------------------------------------------

    def _load(self) -> list[dict]:
        return _read_jsonl(self.path)

    def _save(self, rows: list[dict]) -> None:
        _write_jsonl(self.path, rows)

    def _find(self, rows: list[dict], issue_id: str) -> dict | None:
        for r in rows:
            if r["id"] == issue_id:
                return r
        return None

    # -- public API ---------------------------------------------------------

    def create(
        self,
        title: str,
        *,
        body: str = "",
        tags: list[str] | None = None,
        execution_spec: dict | None = None,
        priority: int = 3,
    ) -> dict:
        now = _now()
        issue = {
            "id": f"loopfarm-{_short_id()}",
            "title": title,
            "body": body,
            "status": "open",
            "outcome": None,
            "tags": tags or [],
            "deps": [],
            "execution_spec": execution_spec,
            "priority": priority,
            "created_at": now,
            "updated_at": now,
        }
        rows = self._load()
        rows.append(issue)
        self._save(rows)
        return issue

    def get(self, issue_id: str) -> dict | None:
        return self._find(self._load(), issue_id)

    def list(
        self,
        *,
        status: str | None = None,
        tag: str | None = None,
    ) -> list[dict]:
        rows = self._load()
        if status:
            rows = [r for r in rows if r["status"] == status]
        if tag:
            rows = [r for r in rows if tag in r.get("tags", [])]
        return rows

    def update(self, issue_id: str, **fields: Any) -> dict:
        rows = self._load()
        issue = self._find(rows, issue_id)
        if issue is None:
            raise KeyError(issue_id)
        for k, v in fields.items():
            if k == "id":
                continue
            issue[k] = v
        issue["updated_at"] = _now()
        self._save(rows)
        return issue

    def claim(self, issue_id: str) -> bool:
        rows = self._load()
        issue = self._find(rows, issue_id)
        if issue is None or issue["status"] != "open":
            return False
        issue["status"] = "in_progress"
        issue["updated_at"] = _now()
        self._save(rows)
        return True

    def close(self, issue_id: str, outcome: str = "success") -> dict:
        return self.update(issue_id, status="closed", outcome=outcome)

    def reset_in_progress(self, root_id: str) -> list[str]:
        """Reset all in_progress issues in the subtree back to open. Returns reset ids."""
        rows = self._load()
        ids_in_scope = set(self.subtree_ids(root_id))
        reset = []
        for r in rows:
            if r["id"] in ids_in_scope and r["status"] == "in_progress":
                r["status"] = "open"
                r["updated_at"] = _now()
                reset.append(r["id"])
        if reset:
            self._save(rows)
        return reset

    # -- dependency helpers -------------------------------------------------

    def add_dep(self, src_id: str, dep_type: str, dst_id: str) -> None:
        rows = self._load()
        issue = self._find(rows, src_id)
        if issue is None:
            raise KeyError(src_id)
        dep = {"type": dep_type, "target": dst_id}
        if dep not in issue["deps"]:
            issue["deps"].append(dep)
            issue["updated_at"] = _now()
            self._save(rows)

    def children(self, parent_id: str) -> list[dict]:
        """Return issues that have a parent dep pointing to parent_id."""
        rows = self._load()
        result = []
        for r in rows:
            for d in r.get("deps", []):
                if d["type"] == "parent" and d["target"] == parent_id:
                    result.append(r)
                    break
        return result

    def subtree_ids(self, root_id: str) -> list[str]:
        """BFS from root_id via parent deps. Returns all descendant ids including root."""
        rows = self._load()
        # Build parent→children index
        children_of: dict[str, list[str]] = {}
        for r in rows:
            for d in r.get("deps", []):
                if d["type"] == "parent":
                    children_of.setdefault(d["target"], []).append(r["id"])

        result: list[str] = []
        q: deque[str] = deque([root_id])
        seen: set[str] = set()
        while q:
            nid = q.popleft()
            if nid in seen:
                continue
            seen.add(nid)
            result.append(nid)
            for child in children_of.get(nid, []):
                q.append(child)
        return result

    def ready(
        self,
        root_id: str | None = None,
        *,
        tags: list[str] | None = None,
    ) -> list[dict]:
        """Return open, unblocked leaf issues in the subtree, optionally filtered by tags."""
        rows = self._load()
        by_id = {r["id"]: r for r in rows}

        # Scope to subtree if root given
        if root_id:
            ids_in_scope = set(self.subtree_ids(root_id))
        else:
            ids_in_scope = set(by_id.keys())

        # Build blocked set: issues that have a "blocks" dep from a non-closed issue
        blocked: set[str] = set()
        for r in rows:
            for d in r.get("deps", []):
                if d["type"] == "blocks" and r["status"] != "closed":
                    blocked.add(d["target"])

        result = []
        for rid in ids_in_scope:
            r = by_id.get(rid)
            if r is None or r["status"] != "open":
                continue
            if rid in blocked:
                continue
            # Skip if has active (non-closed) children
            kids = [
                c
                for c in rows
                if any(
                    d["type"] == "parent" and d["target"] == rid
                    for d in c.get("deps", [])
                )
            ]
            if any(k["status"] != "closed" for k in kids):
                continue
            # Tag filter
            if tags and not all(t in r.get("tags", []) for t in tags):
                continue
            result.append(r)

        # Sort by priority (lower = higher priority)
        result.sort(key=lambda r: r.get("priority", 3))
        return result

    def validate(self, root_id: str) -> ValidationResult:
        """Check if the DAG rooted at root_id is complete."""
        rows = self._load()
        by_id = {r["id"]: r for r in rows}
        ids = set(self.subtree_ids(root_id))

        root = by_id.get(root_id)
        if root is None:
            return ValidationResult(is_final=True, reason="root not found")
        if root["status"] == "closed":
            return ValidationResult(is_final=True, reason="root closed")

        # Check if all children are closed
        all_closed = all(
            by_id[i]["status"] == "closed" for i in ids if i != root_id and i in by_id
        )
        if all_closed and len(ids) > 1:
            return ValidationResult(
                is_final=False, reason="all children closed, root still open"
            )

        # Check for failures
        failed = [
            i for i in ids if by_id.get(i, {}).get("outcome") == "failure"
        ]
        if failed:
            return ValidationResult(
                is_final=True, reason=f"failures: {','.join(failed)}"
            )

        return ValidationResult(is_final=False, reason="in progress")


@dataclass(frozen=True)
class ValidationResult:
    is_final: bool
    reason: str


# ---------------------------------------------------------------------------
# ForumStore
# ---------------------------------------------------------------------------


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
            "created_at": _now(),
        }
        rows = _read_jsonl(self.path)
        rows.append(msg)
        _write_jsonl(self.path, rows)
        return msg

    def read(self, topic: str, limit: int = 50) -> list[dict]:
        rows = _read_jsonl(self.path)
        matching = [r for r in rows if r["topic"] == topic]
        return matching[-limit:]
