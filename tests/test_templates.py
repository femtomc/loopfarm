from __future__ import annotations

from pathlib import Path

import pytest

from loopfarm.templates import TemplateContext, render_template


def test_render_template_supports_relative_includes(tmp_path: Path) -> None:
    (tmp_path / "shared").mkdir()
    (tmp_path / "shared" / "header.md").write_text(
        "USER PROMPT: {{PROMPT}}\n",
        encoding="utf-8",
    )
    (tmp_path / "main.md").write_text(
        "{{> shared/header.md}}\nSession: {{SESSION}}\nProject: {{PROJECT}}\n",
        encoding="utf-8",
    )

    rendered = render_template(
        tmp_path / "main.md",
        TemplateContext(prompt="Do thing", session="loopfarm-1234", project="workshop"),
    )
    assert "USER PROMPT: Do thing" in rendered
    assert "Session: loopfarm-1234" in rendered
    assert "Project: workshop" in rendered


def test_render_template_rejects_cyclic_includes(tmp_path: Path) -> None:
    (tmp_path / "a.md").write_text("{{> b.md}}", encoding="utf-8")
    (tmp_path / "b.md").write_text("{{> a.md}}", encoding="utf-8")

    with pytest.raises(ValueError, match="cyclic template include detected"):
        render_template(
            tmp_path / "a.md",
            TemplateContext(prompt="x", session="y", project="z"),
        )

