from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROLE_TAG_PREFIX = "role:"


@dataclass(frozen=True)
class RoleDoc:
    role: str
    source_path: Path


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
            docs.append(RoleDoc(role=_parse_role_path(path), source_path=path))
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
