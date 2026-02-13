"""Prompt rendering: read markdown, substitute placeholders."""

from __future__ import annotations

from pathlib import Path

import yaml


def _split_frontmatter(text: str) -> tuple[dict, str]:
    """Split optional YAML frontmatter from markdown body."""
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    try:
        meta = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}, text
    return meta, parts[2].lstrip("\n")


def read_prompt_meta(path: str | Path) -> dict:
    """Read just the frontmatter metadata from a prompt file."""
    text = Path(path).read_text()
    meta, _ = _split_frontmatter(text)
    return meta


def render(path: str | Path, issue: dict) -> str:
    """Render a prompt template with issue data substituted."""
    text = Path(path).read_text()
    _, body = _split_frontmatter(text)

    prompt_text = issue.get("title", "")
    if issue.get("body"):
        prompt_text += "\n\n" + issue["body"]

    body = body.replace("{{PROMPT}}", prompt_text)
    return body
