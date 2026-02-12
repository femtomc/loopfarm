from __future__ import annotations

import os
import time
from pathlib import Path


def now_ms() -> int:
    return int(time.time() * 1000)


def resolve_state_dir(cwd: Path | None = None, *, create: bool = True) -> Path:
    """Return the loopfarm state directory, creating it if needed.

    Resolution order:
    1. LOOPFARM_STATE_DIR
    2. nearest existing .loopfarm directory from cwd upward
    3. cwd/.loopfarm
    """
    raw = os.environ.get("LOOPFARM_STATE_DIR", "").strip()
    if raw:
        state_dir = Path(raw).expanduser().resolve()
    else:
        start = (cwd or Path.cwd()).resolve()
        state_dir = start / ".loopfarm"
        for base in (start, *start.parents):
            candidate = base / ".loopfarm"
            if candidate.exists() and candidate.is_dir():
                state_dir = candidate
                break

    if create:
        state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir
