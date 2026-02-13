"""Tests for ExecutionSpec auto-resolution and optional fields."""

from __future__ import annotations

from pathlib import Path

from loopfarm.spec import ExecutionSpec


def _write_role(tmp_path: Path, name: str, frontmatter: str, body: str) -> None:
    roles_dir = tmp_path / ".loopfarm" / "roles"
    roles_dir.mkdir(parents=True, exist_ok=True)
    (roles_dir / f"{name}.md").write_text(f"---\n{frontmatter}---\n{body}")


class TestFromDict:
    def test_empty_dict(self) -> None:
        spec = ExecutionSpec.from_dict({})
        assert spec.role is None
        assert spec.prompt_path is None
        assert spec.cli is None
        assert spec.model is None
        assert spec.reasoning is None

    def test_explicit_fields(self) -> None:
        spec = ExecutionSpec.from_dict({
            "role": "reviewer",
            "cli": "claude",
            "model": "opus",
            "reasoning": "high",
            "prompt_path": "/some/path.md",
        })
        assert spec.role == "reviewer"
        assert spec.cli == "claude"
        assert spec.model == "opus"
        assert spec.reasoning == "high"
        assert spec.prompt_path == "/some/path.md"

    def test_auto_resolve_prompt_path_from_role(self, tmp_path: Path) -> None:
        _write_role(tmp_path, "worker", "cli: codex\n", "Worker.\n")
        spec = ExecutionSpec.from_dict({"role": "worker"}, repo_root=tmp_path)
        assert spec.prompt_path == str(tmp_path / ".loopfarm" / "roles" / "worker.md")

    def test_no_auto_resolve_without_repo_root(self) -> None:
        spec = ExecutionSpec.from_dict({"role": "worker"})
        assert spec.prompt_path is None

    def test_no_auto_resolve_if_role_file_missing(self, tmp_path: Path) -> None:
        (tmp_path / ".loopfarm" / "roles").mkdir(parents=True)
        spec = ExecutionSpec.from_dict({"role": "missing"}, repo_root=tmp_path)
        assert spec.prompt_path is None

    def test_explicit_prompt_path_wins_over_role(self, tmp_path: Path) -> None:
        _write_role(tmp_path, "worker", "cli: codex\n", "Worker.\n")
        spec = ExecutionSpec.from_dict(
            {"role": "worker", "prompt_path": "/custom/prompt.md"},
            repo_root=tmp_path,
        )
        assert spec.prompt_path == "/custom/prompt.md"

    def test_relative_prompt_path_resolved(self, tmp_path: Path) -> None:
        spec = ExecutionSpec.from_dict(
            {"prompt_path": "prompts/test.md"},
            repo_root=tmp_path,
        )
        assert spec.prompt_path == str(tmp_path / "prompts" / "test.md")

    def test_empty_string_fields_become_none(self) -> None:
        spec = ExecutionSpec.from_dict({
            "role": "",
            "cli": "",
            "model": "",
            "reasoning": "",
            "prompt_path": "",
        })
        assert spec.role is None
        assert spec.cli is None
        assert spec.model is None
        assert spec.reasoning is None
        assert spec.prompt_path is None
