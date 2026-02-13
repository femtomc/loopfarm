"""JSONL-backed issue tracker and DAG utilities."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .jsonl import now_ts, read_jsonl, short_id, write_jsonl


@dataclass(frozen=True)
class ValidationResult:
    is_final: bool
    reason: str


class IssueStore:
    """JSONL-backed issue tracker stored in .loopfarm/issues.jsonl."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def from_workdir(cls, root: Path | None = None) -> IssueStore:
        root = root or Path.cwd()
        return cls(root / ".loopfarm" / "issues.jsonl")

    def _load(self) -> list[dict]:
        return read_jsonl(self.path)

    def _save(self, rows: list[dict]) -> None:
        write_jsonl(self.path, rows)

    def _find(self, rows: list[dict], issue_id: str) -> dict | None:
        for row in rows:
            if row["id"] == issue_id:
                return row
        return None

    def create(
        self,
        title: str,
        *,
        body: str = "",
        tags: list[str] | None = None,
        execution_spec: dict | None = None,
        priority: int = 3,
    ) -> dict:
        now = now_ts()
        issue = {
            "id": f"loopfarm-{short_id()}",
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
            rows = [row for row in rows if row["status"] == status]
        if tag:
            rows = [row for row in rows if tag in row.get("tags", [])]
        return rows

    def update(self, issue_id: str, **fields: Any) -> dict:
        rows = self._load()
        issue = self._find(rows, issue_id)
        if issue is None:
            raise KeyError(issue_id)
        for key, value in fields.items():
            if key == "id":
                continue
            issue[key] = value
        issue["updated_at"] = now_ts()
        self._save(rows)
        return issue

    def claim(self, issue_id: str) -> bool:
        rows = self._load()
        issue = self._find(rows, issue_id)
        if issue is None or issue["status"] != "open":
            return False
        issue["status"] = "in_progress"
        issue["updated_at"] = now_ts()
        self._save(rows)
        return True

    def close(self, issue_id: str, outcome: str = "success") -> dict:
        return self.update(issue_id, status="closed", outcome=outcome)

    def reset_in_progress(self, root_id: str) -> list[str]:
        """Reset all in_progress issues in the subtree back to open. Returns reset ids."""
        rows = self._load()
        ids_in_scope = set(self.subtree_ids(root_id))
        reset: list[str] = []
        for row in rows:
            if row["id"] in ids_in_scope and row["status"] == "in_progress":
                row["status"] = "open"
                row["updated_at"] = now_ts()
                reset.append(row["id"])
        if reset:
            self._save(rows)
        return reset

    def add_dep(self, src_id: str, dep_type: str, dst_id: str) -> None:
        rows = self._load()
        issue = self._find(rows, src_id)
        if issue is None:
            raise KeyError(src_id)
        dep = {"type": dep_type, "target": dst_id}
        if dep not in issue["deps"]:
            issue["deps"].append(dep)
            issue["updated_at"] = now_ts()
            self._save(rows)

    def remove_dep(self, src_id: str, dep_type: str, dst_id: str) -> bool:
        """Remove one dependency edge. Returns True if an edge was removed."""
        rows = self._load()
        issue = self._find(rows, src_id)
        if issue is None:
            raise KeyError(src_id)
        before = len(issue.get("deps", []))
        issue["deps"] = [
            dep
            for dep in issue.get("deps", [])
            if not (dep.get("type") == dep_type and dep.get("target") == dst_id)
        ]
        changed = len(issue["deps"]) != before
        if changed:
            issue["updated_at"] = now_ts()
            self._save(rows)
        return changed

    def children(self, parent_id: str) -> list[dict]:
        """Return issues that have a parent dep pointing to parent_id."""
        rows = self._load()
        result = []
        for row in rows:
            for dep in row.get("deps", []):
                if dep["type"] == "parent" and dep["target"] == parent_id:
                    result.append(row)
                    break
        return result

    def subtree_ids(self, root_id: str) -> list[str]:
        """BFS from root_id via parent deps. Returns all descendant ids including root."""
        rows = self._load()
        children_of: dict[str, list[str]] = {}
        for row in rows:
            for dep in row.get("deps", []):
                if dep["type"] == "parent":
                    children_of.setdefault(dep["target"], []).append(row["id"])

        result: list[str] = []
        q: deque[str] = deque([root_id])
        seen: set[str] = set()
        while q:
            node_id = q.popleft()
            if node_id in seen:
                continue
            seen.add(node_id)
            result.append(node_id)
            for child in children_of.get(node_id, []):
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
        by_id = {row["id"]: row for row in rows}

        if root_id:
            ids_in_scope = set(self.subtree_ids(root_id))
        else:
            ids_in_scope = set(by_id.keys())

        blocked: set[str] = set()
        for row in rows:
            for dep in row.get("deps", []):
                if dep["type"] == "blocks" and row["status"] != "closed":
                    blocked.add(dep["target"])

        result = []
        for issue_id in ids_in_scope:
            row = by_id.get(issue_id)
            if row is None or row["status"] != "open":
                continue
            if issue_id in blocked:
                continue

            children = [
                child
                for child in rows
                if any(
                    dep["type"] == "parent" and dep["target"] == issue_id
                    for dep in child.get("deps", [])
                )
            ]
            if any(child["status"] != "closed" for child in children):
                continue

            if tags and not all(tag in row.get("tags", []) for tag in tags):
                continue
            result.append(row)

        result.sort(key=lambda row: row.get("priority", 3))
        return result

    def validate(self, root_id: str) -> ValidationResult:
        """Check if the DAG rooted at root_id is complete."""
        rows = self._load()
        by_id = {row["id"]: row for row in rows}
        ids = set(self.subtree_ids(root_id))

        root = by_id.get(root_id)
        if root is None:
            return ValidationResult(is_final=True, reason="root not found")
        if root["status"] == "closed":
            return ValidationResult(is_final=True, reason="root closed")

        failed = [issue_id for issue_id in ids if by_id.get(issue_id, {}).get("outcome") == "failure"]
        if failed:
            return ValidationResult(is_final=True, reason=f"failures: {','.join(failed)}")

        all_closed = all(
            by_id[issue_id]["status"] == "closed"
            for issue_id in ids
            if issue_id != root_id and issue_id in by_id
        )
        if all_closed and len(ids) > 1:
            return ValidationResult(is_final=False, reason="all children closed, root still open")

        return ValidationResult(is_final=False, reason="in progress")
