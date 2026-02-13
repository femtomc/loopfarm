"""SSE event broadcaster — polls JSONL files for changes."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import AsyncIterator

from ..forum_store import ForumStore
from ..issue_store import IssueStore


class EventBroadcaster:
    """Polls issue/forum JSONL files at 1 Hz and broadcasts diffs via SSE."""

    def __init__(self, store: IssueStore, forum: ForumStore) -> None:
        self.store = store
        self.forum = forum
        self._subscribers: list[asyncio.Queue] = []
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self) -> asyncio.Task:
        self._running = True
        self._task = asyncio.create_task(self._poll_loop())
        return self._task

    def stop(self) -> None:
        self._running = False

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=256)
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        try:
            self._subscribers.remove(q)
        except ValueError:
            pass

    def broadcast(self, event: str, data: dict) -> None:
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        dead: list[asyncio.Queue] = []
        for q in self._subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            self._subscribers.remove(q)

    async def _poll_loop(self) -> None:
        issues_mtime = 0.0
        forum_mtime = 0.0
        prev_issues: dict[str, dict] = {}
        prev_forum_count = 0

        while self._running:
            try:
                # Check issues
                ip = Path(self.store.path)
                if ip.exists():
                    mt = ip.stat().st_mtime
                    if mt > issues_mtime:
                        issues_mtime = mt
                        current = {i["id"]: i for i in self.store.list()}
                        # Detect new and changed issues
                        for iid, issue in current.items():
                            prev = prev_issues.get(iid)
                            if prev is None:
                                self.broadcast("issue_created", _issue_summary(issue))
                            elif prev.get("updated_at") != issue.get("updated_at"):
                                self.broadcast("issue_updated", _issue_summary(issue))
                        prev_issues = current

                # Check forum
                fp = Path(self.forum.path)
                if fp.exists():
                    mt = fp.stat().st_mtime
                    if mt > forum_mtime:
                        forum_mtime = mt
                        from ..jsonl import read_jsonl
                        all_msgs = read_jsonl(fp)
                        new_count = len(all_msgs)
                        if new_count > prev_forum_count:
                            for msg in all_msgs[prev_forum_count:]:
                                self.broadcast("forum_post", msg)
                        prev_forum_count = new_count

                # Heartbeat
                self.broadcast("heartbeat", {"ts": int(time.time())})

            except Exception:
                pass

            await asyncio.sleep(1)

    async def iter_events(self, root_id: str | None = None) -> AsyncIterator[str]:
        q = self.subscribe()
        try:
            while True:
                payload = await q.get()
                yield payload
        finally:
            self.unsubscribe(q)


def _issue_summary(issue: dict) -> dict:
    return {
        "id": issue["id"],
        "title": issue["title"],
        "status": issue["status"],
        "outcome": issue.get("outcome"),
        "priority": issue.get("priority", 3),
        "tags": issue.get("tags", []),
        "updated_at": issue.get("updated_at", 0),
    }
