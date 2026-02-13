from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROLE_TAG_PREFIX = "role:"
_FRONTMATTER_BOUNDARY = "---"
_LOOP_STEP_ITEM_RE = re.compile(r"^\s*([a-zA-Z0-9_.:-]+)\s*(?:\*\s*([0-9]+))?\s*$")


@dataclass(frozen=True)
class RoleDoc:
    role: str
    source_path: Path
    frontmatter: dict[str, Any]
    execution_defaults: "RoleExecutionDefaults"


@dataclass(frozen=True)
class RoleExecutionDefaults:
    cli: str | None = None
    model: str | None = None
    reasoning: str | None = None
    team: str | None = None
    termination_phase: str | None = None
    loop_steps: tuple[tuple[str, int], ...] = ()
    control_flow_mode: str | None = None

    @classmethod
    def from_frontmatter(cls, payload: dict[str, Any]) -> "RoleExecutionDefaults":
        cli = _as_text(payload.get("cli"))
        model = _as_text(payload.get("model"))
        reasoning = _as_text(payload.get("reasoning"))
        team = _as_text(payload.get("team"))
        termination_phase = _as_text(payload.get("termination_phase"))
        control_flow_mode = _as_text(payload.get("control_flow_mode")) or _as_text(
            payload.get("control_flow")
        )
        loop_steps = _parse_loop_steps(payload.get("loop_steps"))
        return cls(
            cli=cli,
            model=model,
            reasoning=reasoning,
            team=team,
            termination_phase=termination_phase,
            loop_steps=loop_steps,
            control_flow_mode=control_flow_mode,
        )


def discover_role_paths(repo_root: Path) -> tuple[Path, ...]:
    roles_dir = repo_root / ".loopfarm" / "roles"
    if not roles_dir.exists() or not roles_dir.is_dir():
        return ()
    return tuple(
        sorted(
            (
                path
                for path in roles_dir.iterdir()
                if path.is_file() and path.suffix == ".md"
            ),
            key=lambda path: path.name,
        )
    )


def _parse_role_path(path: Path) -> str:
    stem = path.stem.strip().lower()
    if not stem:
        raise ValueError(f"invalid empty role filename: {path.name!r}")
    if "." in stem:
        raise ValueError(
            f"invalid role filename {path.name!r}; expected '<role>.md' only"
        )
    return stem


def _as_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _parse_loop_steps(value: object) -> tuple[tuple[str, int], ...]:
    if value is None:
        return ()
    items: list[str] = []
    if isinstance(value, str):
        items = [part.strip() for part in value.split(",") if part.strip()]
    elif isinstance(value, list):
        for raw in value:
            if not isinstance(raw, str):
                raise ValueError(
                    "frontmatter loop_steps list must contain strings only"
                )
            text = raw.strip()
            if text:
                items.append(text)
    else:
        raise ValueError("frontmatter loop_steps must be a string or list of strings")

    steps: list[tuple[str, int]] = []
    for item in items:
        match = _LOOP_STEP_ITEM_RE.match(item)
        if match is None:
            raise ValueError(
                "invalid loop_steps entry "
                f"{item!r}; expected '<phase>' or '<phase>*<repeat>'"
            )
        phase = match.group(1).strip()
        repeat_text = (match.group(2) or "").strip()
        repeat = int(repeat_text) if repeat_text else 1
        if repeat < 1:
            raise ValueError(
                f"invalid loop_steps repeat for phase {phase!r}: {repeat}"
            )
        steps.append((phase, repeat))
    return tuple(steps)


def _parse_frontmatter_scalar(value: str) -> object:
    text = value.strip()
    if not text:
        return ""
    if text.startswith('"') and text.endswith('"') and len(text) >= 2:
        return text[1:-1]
    if text.startswith("'") and text.endswith("'") and len(text) >= 2:
        return text[1:-1]
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered.isdigit() or (
        lowered.startswith("-") and lowered[1:].isdigit()
    ):
        try:
            return int(lowered)
        except ValueError:
            return text
    if text.startswith("[") and text.endswith("]"):
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_frontmatter_scalar(part) for part in inner.split(",")]
    return text


def _parse_frontmatter_block(block: str, *, source: Path) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for idx, raw_line in enumerate(block.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise ValueError(
                f"invalid markdown frontmatter line in {source.name}:{idx}: {raw_line!r}"
            )
        key_text, value_text = line.split(":", 1)
        key = key_text.strip().lower()
        if not key:
            raise ValueError(
                f"invalid empty frontmatter key in {source.name}:{idx}: {raw_line!r}"
            )
        payload[key] = _parse_frontmatter_scalar(value_text)
    return payload


def _read_markdown_frontmatter(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines:
        return {}
    if lines[0].strip() != _FRONTMATTER_BOUNDARY:
        return {}

    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == _FRONTMATTER_BOUNDARY:
            end_index = idx
            break
    if end_index is None:
        raise ValueError(
            f"invalid markdown frontmatter in {path.name!r}: missing closing '---'"
        )
    block = "\n".join(lines[1:end_index])
    return _parse_frontmatter_block(block, source=path)


def read_markdown_frontmatter(path: Path) -> dict[str, Any]:
    return _read_markdown_frontmatter(path)


def read_execution_defaults(path: Path) -> RoleExecutionDefaults:
    return RoleExecutionDefaults.from_frontmatter(read_markdown_frontmatter(path))


def _format_path(path: Path, repo_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(repo_root.resolve()))
    except Exception:
        return str(path)


class RoleCatalog:
    def __init__(self, *, repo_root: Path, docs: tuple[RoleDoc, ...]) -> None:
        self.repo_root = repo_root
        self.docs = docs
        by_role: dict[str, RoleDoc] = {}
        for doc in docs:
            key = doc.role
            if key in by_role:
                raise ValueError(
                    "duplicate role document for "
                    f"role={doc.role!r}: "
                    f"{_format_path(by_role[key].source_path, repo_root)} and "
                    f"{_format_path(doc.source_path, repo_root)}"
                )
            by_role[key] = doc
        self._by_role = by_role

    @classmethod
    def from_repo(cls, repo_root: Path) -> "RoleCatalog":
        docs: list[RoleDoc] = []
        for path in discover_role_paths(repo_root):
            frontmatter = read_markdown_frontmatter(path)
            docs.append(
                RoleDoc(
                    role=_parse_role_path(path),
                    source_path=path,
                    frontmatter=frontmatter,
                    execution_defaults=RoleExecutionDefaults.from_frontmatter(
                        frontmatter
                    ),
                )
            )
        return cls(repo_root=repo_root, docs=tuple(docs))

    def resolve(self, *, role: str) -> RoleDoc | None:
        normalized_role = role.strip().lower()
        if not normalized_role:
            return None
        return self._by_role.get(normalized_role)

    def require(self, *, role: str) -> RoleDoc:
        doc = self.resolve(role=role)
        if doc is not None:
            return doc

        available = ", ".join(sorted({doc.role for doc in self.docs}))
        if available:
            raise ValueError(
                f"missing role doc for role {role!r} "
                f"in .loopfarm/roles (available: {available})"
            )
        raise ValueError(
            "no role docs found in .loopfarm/roles; add at least one "
            "Markdown file such as 'worker.md'"
        )

    def has_role(self, *, role: str) -> bool:
        return self.resolve(role=role) is not None

    def available_roles(self) -> tuple[str, ...]:
        return tuple(sorted({doc.role for doc in self.docs}))

    def available_docs(self) -> tuple[RoleDoc, ...]:
        resolved_docs: list[RoleDoc] = []
        for role in self.available_roles():
            doc = self.resolve(role=role)
            if doc is not None:
                resolved_docs.append(doc)
        return tuple(resolved_docs)
