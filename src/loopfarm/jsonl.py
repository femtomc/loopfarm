"""Low-level JSONL storage helpers."""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path


def short_id() -> str:
    return uuid.uuid4().hex[:8]


def now_ts() -> int:
    return int(time.time())


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    rows: list[dict] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")
    os.replace(tmp, path)
