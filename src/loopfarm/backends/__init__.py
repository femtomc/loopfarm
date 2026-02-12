from __future__ import annotations

from .registry import get_backend, list_backends, register_backend
from .types import Backend


_LOADED = False


def load_builtin_backends() -> None:
    global _LOADED
    if _LOADED:
        return
    from .claude import ClaudeBackend
    from .codex import CodexBackend
    from .gemini import GeminiBackend
    from .kimi import KimiBackend

    register_backend(ClaudeBackend())
    register_backend(CodexBackend())
    register_backend(GeminiBackend())
    register_backend(KimiBackend())
    _LOADED = True


load_builtin_backends()

__all__ = [
    "Backend",
    "get_backend",
    "list_backends",
    "load_builtin_backends",
    "register_backend",
]
