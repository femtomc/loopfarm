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
    """JSONL-backed issue tracker stored in .inshallah/issues.jsonl."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def from_workdir(cls, root: Path | None = None) -> IssueStore:
        root = root or Path.cwd()
        return cls(root / ".inshallah" / "issues.jsonl")

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
            "id": f"inshallah-{short_id()}",
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
                if dep["type"] == "blocks" and (
                    row["status"] != "closed"
                    or row.get("outcome") == "expanded"
                ):
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

    def collapsible(self, root_id: str) -> list[dict]:
        """Return expanded issues whose children are all terminally closed.

        A node is collapsible when:
        - It is in the subtree rooted at *root_id*
        - Its status is ``closed`` with outcome ``expanded``
        - It has at least one child
        - Every direct child is ``closed`` with a terminal outcome
          (``success`` or ``skipped`` — NOT ``expanded``)

        Bottom-up ordering is enforced by the terminal-children constraint:
        a parent can't be collapsible while any child is still expanded.
        """
        rows = self._load()
        by_id = {row["id"]: row for row in rows}
        ids_in_scope = set(self.subtree_ids(root_id))

        # Build parent→children mapping
        children_of: dict[str, list[dict]] = {}
        for row in rows:
            for dep in row.get("deps", []):
                if dep["type"] == "parent":
                    children_of.setdefault(dep["target"], []).append(row)

        # Collapse is only valid when children "passed" the work. Failures and
        # needs_work are handled by re-orchestration, not collapse.
        terminal_outcomes = {"success", "skipped"}
        result: list[dict] = []

        for issue_id in ids_in_scope:
            node = by_id.get(issue_id)
            if node is None:
                continue
            if node["status"] != "closed" or node.get("outcome") != "expanded":
                continue
            kids = children_of.get(issue_id, [])
            if not kids:
                continue
            if all(
                kid["status"] == "closed"
                and kid.get("outcome") in terminal_outcomes
                for kid in kids
            ):
                result.append(node)

        return result

    def validate(self, root_id: str) -> ValidationResult:
        """Check if the DAG rooted at root_id is complete.

        Completion semantics:
        - ``expanded`` is a *delegation* outcome: the issue itself finished
          (decomposition), but its logical completion flows through to its
          descendants.  Expanded nodes are transparent when determining
          whether work remains.
        - ``failure`` and ``needs_work`` are *not* final: they signal that the
          orchestrator should re-expand the issue with remediation children.
        - All other closed outcomes (for example ``success`` and ``skipped``)
          are terminal.
        - The DAG is final when there is no remaining open/in_progress work,
          and no node is awaiting re-orchestration.
        """
        rows = self._load()
        by_id = {row["id"]: row for row in rows}
        ids = set(self.subtree_ids(root_id))

        root = by_id.get(root_id)
        if root is None:
            return ValidationResult(is_final=True, reason="root not found")

        # Build parent→children mapping so we can detect invalid "expanded"
        # nodes that have no child work.
        children_of: dict[str, list[str]] = {}
        for row in rows:
            for dep in row.get("deps", []):
                if dep["type"] == "parent":
                    children_of.setdefault(dep["target"], []).append(row["id"])

        # Closed failures / needs_work are not final: they require the
        # orchestrator to re-expand and create new leaf work.
        needs_reorch = sorted(
            [
                issue_id
                for issue_id in ids
                if by_id.get(issue_id, {}).get("status") == "closed"
                and by_id.get(issue_id, {}).get("outcome")
                in {"failure", "needs_work"}
            ]
        )
        if needs_reorch:
            return ValidationResult(
                is_final=False, reason=f"needs work: {','.join(needs_reorch)}"
            )

        # "expanded" without children is a structural bug: there is no leaf
        # work remaining, but the DAG can't converge without re-orchestration.
        bad_expanded = sorted(
            [
                issue_id
                for issue_id in ids
                if by_id.get(issue_id, {}).get("status") == "closed"
                and by_id.get(issue_id, {}).get("outcome") == "expanded"
                and not children_of.get(issue_id)
            ]
        )
        if bad_expanded:
            return ValidationResult(
                is_final=False,
                reason=f"expanded without children: {','.join(bad_expanded)}",
            )

        # Collect issues that still need work.  Expanded nodes are
        # transparent — they delegated to children and are not themselves
        # "pending."  Every other non-closed issue counts as pending.
        pending = [
            issue_id
            for issue_id in ids
            if issue_id in by_id
            and not (
                by_id[issue_id]["status"] == "closed"
                and by_id[issue_id].get("outcome") == "expanded"
            )
            and by_id[issue_id]["status"] != "closed"
        ]

        if not pending:
            return ValidationResult(is_final=True, reason="all work completed")

        # If only the root is pending and all descendants are done, signal
        # that the root is ready to be closed by the next agent step.
        if pending == [root_id] and len(ids) > 1:
            return ValidationResult(
                is_final=False,
                reason="all children closed, root still open",
            )

        return ValidationResult(is_final=False, reason="in progress")
