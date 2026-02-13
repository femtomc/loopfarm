from __future__ import annotations

import time
from pathlib import Path


def now_ms() -> int:
    return int(time.time() * 1000)


def resolve_state_dir(
    cwd: Path | None = None,
    *,
    create: bool = True,
    state_dir: Path | str | None = None,
) -> Path:
    """Return the loopfarm state directory, creating it if needed.

    Resolution order:
    1. explicit state_dir argument
    2. nearest existing .loopfarm directory from cwd upward
    3. cwd/.loopfarm
    """
    if state_dir is not None:
        resolved_state_dir = Path(state_dir).expanduser().resolve()
    else:
        start = (cwd or Path.cwd()).resolve()
        resolved_state_dir = start / ".loopfarm"
        for base in (start, *start.parents):
            candidate = base / ".loopfarm"
            if candidate.exists() and candidate.is_dir():
                resolved_state_dir = candidate
                break

    if create:
        resolved_state_dir.mkdir(parents=True, exist_ok=True)
    return resolved_state_dir
