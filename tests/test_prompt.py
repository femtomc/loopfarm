"""Tests for prompt rendering and role catalog."""

from __future__ import annotations

from pathlib import Path

from loopfarm.prompt import build_role_catalog, render


def _write_role(tmp_path: Path, name: str, frontmatter: str, body: str) -> None:
    roles_dir = tmp_path / ".loopfarm" / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    (roles_dir / f"{name}.md").write_text(f"---\n{frontmatter}---\n{body}")


class TestBuildRoleCatalog:
    def test_no_roles_dir(self, tmp_path: Path) -> None:
        assert build_role_catalog(tmp_path) == ""

    def test_empty_roles_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".loopfarm" / "roles").mkdir(parents=True)
        assert build_role_catalog(tmp_path) == ""

    def test_single_role(self, tmp_path: Path) -> None:
        _write_role(tmp_path, "worker", "cli: codex\nmodel: gpt-5.2\nreasoning: xhigh\n", "You are a worker.\n")
        catalog = build_role_catalog(tmp_path)
        assert "### worker" in catalog
        assert "cli: codex" in catalog
        assert "model: gpt-5.2" in catalog
        assert "reasoning: xhigh" in catalog
        assert "> You are a worker." in catalog

    def test_multiple_roles_sorted(self, tmp_path: Path) -> None:
        _write_role(tmp_path, "worker", "cli: codex\n", "Worker description.\n")
        _write_role(tmp_path, "reviewer", "cli: claude\nmodel: opus\n", "Reviewer description.\n")
        catalog = build_role_catalog(tmp_path)
        # reviewer comes before worker alphabetically
        rev_pos = catalog.index("### reviewer")
        work_pos = catalog.index("### worker")
        assert rev_pos < work_pos

    def test_role_with_no_frontmatter_keys(self, tmp_path: Path) -> None:
        roles_dir = tmp_path / ".loopfarm" / "roles"
        roles_dir.mkdir(parents=True)
        (roles_dir / "plain.md").write_text("Just a plain role.\n")
        catalog = build_role_catalog(tmp_path)
        assert "### plain" in catalog
        assert "default config" in catalog
        assert "> Just a plain role." in catalog

    def test_role_skips_blank_lines_for_description(self, tmp_path: Path) -> None:
        _write_role(tmp_path, "tester", "cli: claude\n", "\n\nActual description here.\n")
        catalog = build_role_catalog(tmp_path)
        assert "> Actual description here." in catalog


class TestRender:
    def test_basic_substitution(self, tmp_path: Path) -> None:
        prompt = tmp_path / "test.md"
        prompt.write_text("---\ncli: claude\n---\nTask: {{PROMPT}}\n")
        result = render(prompt, {"title": "Do stuff"})
        assert result == "Task: Do stuff\n"

    def test_roles_substitution(self, tmp_path: Path) -> None:
        _write_role(tmp_path, "worker", "cli: codex\n", "Worker role.\n")
        prompt = tmp_path / "test.md"
        prompt.write_text("---\ncli: claude\n---\n{{PROMPT}}\n\n{{ROLES}}\n")
        result = render(prompt, {"title": "Hello"}, repo_root=tmp_path)
        assert "### worker" in result
        assert "Hello" in result

    def test_roles_without_repo_root(self, tmp_path: Path) -> None:
        prompt = tmp_path / "test.md"
        prompt.write_text("---\ncli: claude\n---\n{{ROLES}}\n")
        result = render(prompt, {"title": ""})
        # Without repo_root, {{ROLES}} is replaced with empty string
        assert "{{ROLES}}" not in result

    def test_no_roles_placeholder(self, tmp_path: Path) -> None:
        prompt = tmp_path / "test.md"
        prompt.write_text("---\ncli: claude\n---\n{{PROMPT}}\n")
        result = render(prompt, {"title": "Hi"}, repo_root=tmp_path)
        assert result == "Hi\n"

    def test_prompt_with_body(self, tmp_path: Path) -> None:
        prompt = tmp_path / "test.md"
        prompt.write_text("{{PROMPT}}\n")
        result = render(prompt, {"title": "Title", "body": "Details"})
        assert "Title\n\nDetails" in result
