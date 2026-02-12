from __future__ import annotations

from .types import Backend


_BACKENDS: dict[str, Backend] = {}


def register_backend(backend: Backend) -> None:
    name = backend.name
    if not name:
        raise ValueError("backend name cannot be empty")
    if name in _BACKENDS:
        if _BACKENDS[name] is backend:
            return
        raise ValueError(f"backend already registered: {name}")
    _BACKENDS[name] = backend


def get_backend(name: str) -> Backend:
    if name in _BACKENDS:
        return _BACKENDS[name]
    available = ", ".join(sorted(_BACKENDS))
    raise KeyError(f"unknown backend '{name}'. available: {available}")


def list_backends() -> list[str]:
    return sorted(_BACKENDS)
