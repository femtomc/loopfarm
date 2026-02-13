"""Async wrapper around DagRunner for web-based loop control."""

from __future__ import annotations

import asyncio
from pathlib import Path

from rich.console import Console

from ..dag import DagRunner
from ..forum_store import ForumStore
from ..issue_store import IssueStore
from .sse import EventBroadcaster


async def start_runner(
    store: IssueStore,
    forum: ForumStore,
    repo_root: Path,
    broadcaster: EventBroadcaster,
    runner_state: dict,
    root_id: str,
    max_steps: int = 20,
) -> None:
    """Run DagRunner in a thread, updating runner_state for the web UI."""
    runner_state["status"] = "running"
    runner_state["root_id"] = root_id
    runner_state["step"] = 0

    broadcaster.broadcast("runner_step", {
        "status": "running",
        "root_id": root_id,
        "step": 0,
    })

    def _run_sync():
        console = Console(quiet=True)
        runner = DagRunner(store, forum, repo_root, console=console)
        result = runner.run(root_id, max_steps=max_steps)
        return result

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _run_sync)
        runner_state["status"] = "done"
        runner_state["result"] = result.status
        broadcaster.broadcast("runner_done", {
            "root_id": root_id,
            "status": result.status,
            "steps": result.steps,
            "error": result.error,
        })
    except Exception as exc:
        runner_state["status"] = "error"
        runner_state["error"] = str(exc)
        broadcaster.broadcast("runner_done", {
            "root_id": root_id,
            "status": "error",
            "error": str(exc),
        })
