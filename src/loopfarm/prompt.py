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


def build_role_catalog(repo_root: Path) -> str:
    """Build a markdown catalog of available roles from .loopfarm/roles/*.md."""
    roles_dir = repo_root / ".loopfarm" / "roles"
    if not roles_dir.is_dir():
        return ""
    sections: list[str] = []
    for path in sorted(roles_dir.glob("*.md")):
        text = path.read_text()
        meta, body = _split_frontmatter(text)
        name = path.stem
        # Build config summary from frontmatter
        parts = []
        for key in ("cli", "model", "reasoning"):
            if key in meta:
                parts.append(f"{key}: {meta[key]}")
        config_line = " | ".join(parts) if parts else "default config"
        # First non-empty body line as description
        desc = ""
        for line in body.splitlines():
            stripped = line.strip()
            if stripped:
                desc = stripped
                break
        sections.append(f"### {name}\n{config_line}\n> {desc}")
    return "\n\n".join(sections)


def render(path: str | Path, issue: dict, *, repo_root: Path | None = None) -> str:
    """Render a prompt template with issue data substituted."""
    text = Path(path).read_text()
    _, body = _split_frontmatter(text)

    prompt_text = issue.get("title", "")
    if issue.get("body"):
        prompt_text += "\n\n" + issue["body"]

    body = body.replace("{{PROMPT}}", prompt_text)

    if "{{ROLES}}" in body:
        catalog = build_role_catalog(repo_root) if repo_root else ""
        body = body.replace("{{ROLES}}", catalog)

    return body
