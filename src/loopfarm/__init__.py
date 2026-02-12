from __future__ import annotations

from typing import TYPE_CHECKING

__all__ = [
    "__version__",
    "LoopfarmConfig",
    "LoopfarmEvent",
    "LoopfarmIO",
    "LoopfarmRunner",
    "run_loop",
]

__version__ = "0.1.0"

if TYPE_CHECKING:
    from .events import LoopfarmEvent
    from .runner import LoopfarmConfig, LoopfarmIO, LoopfarmRunner, run_loop


def __getattr__(name: str):
    if name == "LoopfarmEvent":
        from .events import LoopfarmEvent

        return LoopfarmEvent
    if name in {"LoopfarmConfig", "LoopfarmIO", "LoopfarmRunner", "run_loop"}:
        from .runner import LoopfarmConfig, LoopfarmIO, LoopfarmRunner, run_loop

        return {
            "LoopfarmConfig": LoopfarmConfig,
            "LoopfarmIO": LoopfarmIO,
            "LoopfarmRunner": LoopfarmRunner,
            "run_loop": run_loop,
        }[name]
    raise AttributeError(f"module 'loopfarm' has no attribute {name!r}")
