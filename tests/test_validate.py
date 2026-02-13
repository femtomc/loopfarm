"""Tests for IssueStore.validate() — DAG completion semantics."""

from __future__ import annotations

from pathlib import Path

from loopfarm.store import IssueStore


def _store(tmp_path: Path) -> IssueStore:
    lf = tmp_path / ".loopfarm"
    lf.mkdir(parents=True, exist_ok=True)
    (lf / "issues.jsonl").touch()
    return IssueStore(lf / "issues.jsonl")


class TestValidateBasic:
    def test_root_not_found(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        v = store.validate("nonexistent")
        assert v.is_final is True
        assert "not found" in v.reason

    def test_single_open_root(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        root = store.create("root", tags=["node:agent", "node:root"])
        v = store.validate(root["id"])
        assert v.is_final is False
        assert v.reason == "in progress"

    def test_single_root_closed_success(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        root = store.create("root", tags=["node:agent", "node:root"])
        store.close(root["id"], outcome="success")
        v = store.validate(root["id"])
        assert v.is_final is True

    def test_failure_is_final(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        root = store.create("root", tags=["node:agent", "node:root"])
        child = store.create("child", tags=["node:agent"])
        store.add_dep(child["id"], "parent", root["id"])
        store.close(child["id"], outcome="failure")
        v = store.validate(root["id"])
        assert v.is_final is True
        assert "failures" in v.reason


class TestValidateExpanded:
    """The core scenario: root closed with expanded, children still pending."""

    def test_expanded_root_children_open(self, tmp_path: Path) -> None:
        """Expanded root with open children → NOT final (loop continues)."""
        store = _store(tmp_path)
        root = store.create("root", tags=["node:agent", "node:root"])
        c1 = store.create("child 1", tags=["node:agent"])
        c2 = store.create("child 2", tags=["node:agent"])
        store.add_dep(c1["id"], "parent", root["id"])
        store.add_dep(c2["id"], "parent", root["id"])
        store.close(root["id"], outcome="expanded")

        v = store.validate(root["id"])
        assert v.is_final is False
        assert v.reason == "in progress"

    def test_expanded_root_some_children_done(self, tmp_path: Path) -> None:
        """Expanded root, one child closed, one open → NOT final."""
        store = _store(tmp_path)
        root = store.create("root", tags=["node:agent", "node:root"])
        c1 = store.create("child 1", tags=["node:agent"])
        c2 = store.create("child 2", tags=["node:agent"])
        store.add_dep(c1["id"], "parent", root["id"])
        store.add_dep(c2["id"], "parent", root["id"])
        store.close(root["id"], outcome="expanded")
        store.close(c1["id"], outcome="success")

        v = store.validate(root["id"])
        assert v.is_final is False
        assert v.reason == "in progress"

    def test_expanded_root_all_children_done(self, tmp_path: Path) -> None:
        """Expanded root, all children closed → final."""
        store = _store(tmp_path)
        root = store.create("root", tags=["node:agent", "node:root"])
        c1 = store.create("child 1", tags=["node:agent"])
        c2 = store.create("child 2", tags=["node:agent"])
        store.add_dep(c1["id"], "parent", root["id"])
        store.add_dep(c2["id"], "parent", root["id"])
        store.close(root["id"], outcome="expanded")
        store.close(c1["id"], outcome="success")
        store.close(c2["id"], outcome="success")

        v = store.validate(root["id"])
        assert v.is_final is True
        assert v.reason == "all work completed"

    def test_expanded_child_failure_still_final(self, tmp_path: Path) -> None:
        """Failure in a descendant stops the DAG even with expanded root."""
        store = _store(tmp_path)
        root = store.create("root", tags=["node:agent", "node:root"])
        c1 = store.create("child 1", tags=["node:agent"])
        store.add_dep(c1["id"], "parent", root["id"])
        store.close(root["id"], outcome="expanded")
        store.close(c1["id"], outcome="failure")

        v = store.validate(root["id"])
        assert v.is_final is True
        assert "failures" in v.reason

    def test_nested_expansion(self, tmp_path: Path) -> None:
        """Root expanded → child expanded → grandchildren open → NOT final."""
        store = _store(tmp_path)
        root = store.create("root", tags=["node:agent", "node:root"])
        child = store.create("child", tags=["node:agent"])
        gc1 = store.create("grandchild 1", tags=["node:agent"])
        gc2 = store.create("grandchild 2", tags=["node:agent"])
        store.add_dep(child["id"], "parent", root["id"])
        store.add_dep(gc1["id"], "parent", child["id"])
        store.add_dep(gc2["id"], "parent", child["id"])
        store.close(root["id"], outcome="expanded")
        store.close(child["id"], outcome="expanded")

        v = store.validate(root["id"])
        assert v.is_final is False

    def test_nested_expansion_all_done(self, tmp_path: Path) -> None:
        """Root expanded → child expanded → all grandchildren closed → final."""
        store = _store(tmp_path)
        root = store.create("root", tags=["node:agent", "node:root"])
        child = store.create("child", tags=["node:agent"])
        gc1 = store.create("grandchild 1", tags=["node:agent"])
        gc2 = store.create("grandchild 2", tags=["node:agent"])
        store.add_dep(child["id"], "parent", root["id"])
        store.add_dep(gc1["id"], "parent", child["id"])
        store.add_dep(gc2["id"], "parent", child["id"])
        store.close(root["id"], outcome="expanded")
        store.close(child["id"], outcome="expanded")
        store.close(gc1["id"], outcome="success")
        store.close(gc2["id"], outcome="success")

        v = store.validate(root["id"])
        assert v.is_final is True
        assert v.reason == "all work completed"


class TestValidateRootStillOpen:
    """When root is open and all descendants are closed, signal readiness."""

    def test_all_children_closed_root_open(self, tmp_path: Path) -> None:
        store = _store(tmp_path)
        root = store.create("root", tags=["node:agent", "node:root"])
        child = store.create("child", tags=["node:agent"])
        store.add_dep(child["id"], "parent", root["id"])
        store.close(child["id"], outcome="success")

        v = store.validate(root["id"])
        assert v.is_final is False
        assert "all children closed" in v.reason
