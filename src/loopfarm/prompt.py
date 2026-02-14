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


def _first_non_empty_line(text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _extract_description(meta: dict, body: str) -> tuple[str, str]:
    """Return role description and where it came from."""
    raw = meta.get("description")
    desc = raw.strip() if isinstance(raw, str) else ""
    if desc:
        return desc, "frontmatter"
    body_desc = _first_non_empty_line(body)
    if body_desc:
        return body_desc, "body"
    return "", "none"


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
        prompt_path = path.relative_to(repo_root).as_posix()
        desc, desc_source = _extract_description(meta, body)
        # Build config summary from frontmatter
        parts = []
        for key in ("cli", "model", "reasoning"):
            if key in meta:
                parts.append(f"{key}: {meta[key]}")
        config_line = " | ".join(parts) if parts else "default config"
        catalog_desc = desc or "No description provided."
        sections.append(
            f"### {name}\n"
            f"description: {catalog_desc}\n"
            f"description_source: {desc_source}\n"
            f"prompt: {prompt_path}\n"
            f"config: {config_line}"
        )
    return "\n\n".join(sections)


def list_roles_json(repo_root: Path) -> list[dict]:
    """Return structured role data from .loopfarm/roles/*.md."""
    roles_dir = repo_root / ".loopfarm" / "roles"
    if not roles_dir.is_dir():
        return []
    result: list[dict] = []
    for path in sorted(roles_dir.glob("*.md")):
        text = path.read_text()
        meta, body = _split_frontmatter(text)
        desc, desc_source = _extract_description(meta, body)
        result.append({
            "name": path.stem,
            "prompt_path": path.relative_to(repo_root).as_posix(),
            "cli": meta.get("cli", ""),
            "model": meta.get("model", ""),
            "reasoning": meta.get("reasoning", ""),
            "description": desc,
            "description_source": desc_source,
        })
    return result


def render(path: str | Path, issue: dict, *, repo_root: Path | None = None) -> str:
    """Render a prompt template with issue data substituted."""
    text = Path(path).read_text()
    _, body = _split_frontmatter(text)

    prompt_text = issue.get("title", "")
    if issue.get("body"):
        prompt_text += "\n\n" + issue["body"]

    body = body.replace("{{PROMPT}}", prompt_text)
    body = body.replace("{{ISSUE_ID}}", issue.get("id", ""))

    if "{{ROLES}}" in body:
        catalog = build_role_catalog(repo_root) if repo_root else ""
        body = body.replace("{{ROLES}}", catalog)

    return body
