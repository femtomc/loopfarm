from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re


INCLUDE_RE = re.compile(r"\{\{\>\s*([^}]+?)\s*\}\}")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


@dataclass(frozen=True)
class TemplateContext:
    prompt: str
    session: str
    project: str


def render_template(path: Path, ctx: TemplateContext) -> str:
    content = _render_with_includes(path, seen=set())
    content = _strip_frontmatter(content)
    return (
        content.replace("{{PROMPT}}", ctx.prompt)
        .replace("{{SESSION}}", ctx.session)
        .replace("{{PROJECT}}", ctx.project)
    )


def _render_with_includes(path: Path, *, seen: set[Path]) -> str:
    resolved = path.resolve()
    if resolved in seen:
        raise ValueError(f"cyclic template include detected: {path}")
    seen.add(resolved)
    content = path.read_text(encoding="utf-8")

    def include_repl(match: re.Match[str]) -> str:
        rel = match.group(1).strip()
        include_path = (path.parent / rel).resolve()
        return _render_with_includes(include_path, seen=seen.copy())

    return INCLUDE_RE.sub(include_repl, content)


def _strip_frontmatter(content: str) -> str:
    match = FRONTMATTER_RE.match(content)
    if match is None:
        return content
    return content[match.end() :]
