"""Page and API routes for loopfarm web interface."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from pydantic import BaseModel

from .. import __version__
from ..jsonl import read_jsonl
from ..prompt import list_roles_json

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _store(req: Request):
    return req.app.state.store


def _forum(req: Request):
    return req.app.state.forum


def _templates(req: Request):
    return req.app.state.templates


def _repo_root(req: Request) -> Path:
    return req.app.state.repo_root


def _issue_json(issue: dict) -> dict:
    return {
        "id": issue["id"],
        "title": issue["title"],
        "body": issue.get("body", ""),
        "status": issue["status"],
        "outcome": issue.get("outcome"),
        "tags": issue.get("tags", []),
        "deps": issue.get("deps", []),
        "execution_spec": issue.get("execution_spec"),
        "priority": issue.get("priority", 3),
        "created_at": issue.get("created_at", 0),
        "updated_at": issue.get("updated_at", 0),
    }


def _build_tree(issues: list[dict], root_id: str) -> dict:
    """Build a nested tree structure from a flat list of issues."""
    by_id = {i["id"]: {**i, "children": []} for i in issues}
    root = by_id.get(root_id)
    if root is None:
        return {}

    # Build parent→children map
    for issue in issues:
        for dep in issue.get("deps", []):
            if dep["type"] == "parent" and dep["target"] in by_id:
                by_id[dep["target"]]["children"].append(by_id[issue["id"]])

    # Sort children by priority then created_at
    for node in by_id.values():
        node["children"].sort(key=lambda c: (c.get("priority", 3), c.get("created_at", 0)))

    return root


# ---------------------------------------------------------------------------
# Pages (HTML)
# ---------------------------------------------------------------------------


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    store = _store(request)
    forum = _forum(request)

    roots = store.list(tag="node:root")
    all_issues = store.list()
    open_issues = [i for i in all_issues if i["status"] == "open"]
    failed = [i for i in all_issues if i.get("outcome") == "failure"]
    ready = store.ready(tags=["node:agent"])

    # Build per-root stats
    root_stats = []
    for root in roots:
        subtree_ids = set(store.subtree_ids(root["id"]))
        subtree = [i for i in all_issues if i["id"] in subtree_ids]
        total = len(subtree)
        closed = sum(1 for i in subtree if i["status"] == "closed")
        failed_count = sum(1 for i in subtree if i.get("outcome") == "failure")
        pct = int(closed / total * 100) if total > 0 else 0
        root_stats.append({
            "issue": root,
            "total": total,
            "closed": closed,
            "failed": failed_count,
            "pct": pct,
        })

    return _templates(request).TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "roots": root_stats,
            "total_issues": len(all_issues),
            "open_count": len(open_issues),
            "ready_count": len(ready),
            "failed_count": len(failed),
            "version": __version__,
            "repo_root": str(_repo_root(request)),
        },
    )


@router.get("/dag/{root_id}", response_class=HTMLResponse)
async def editor(request: Request, root_id: str):
    store = _store(request)

    root_issue = store.get(root_id)
    if root_issue is None:
        return HTMLResponse("<h1>Root not found</h1>", status_code=404)

    subtree_ids = store.subtree_ids(root_id)
    all_issues = store.list()
    subtree = [i for i in all_issues if i["id"] in set(subtree_ids)]
    tree = _build_tree(subtree, root_id)

    return _templates(request).TemplateResponse(
        "editor.html",
        {
            "request": request,
            "root": root_issue,
            "tree": tree,
            "version": __version__,
            "repo_root": str(_repo_root(request)),
            "runner_state": request.app.state.runner_state,
        },
    )


@router.get("/roles", response_class=HTMLResponse)
async def roles_page(request: Request):
    roles = list_roles_json(_repo_root(request))
    return _templates(request).TemplateResponse(
        "roles.html",
        {
            "request": request,
            "roles": roles,
            "version": __version__,
            "repo_root": str(_repo_root(request)),
        },
    )


# ---------------------------------------------------------------------------
# Data API (JSON, read-only)
# ---------------------------------------------------------------------------


@router.get("/api/status")
async def api_status(request: Request):
    store = _store(request)
    roots = store.list(tag="node:root")
    all_issues = store.list()
    open_issues = [i for i in all_issues if i["status"] == "open"]
    ready = store.ready(tags=["node:agent"])
    failed = [i for i in all_issues if i.get("outcome") == "failure"]
    return {
        "roots": len(roots),
        "total": len(all_issues),
        "open": len(open_issues),
        "ready": len(ready),
        "failed": len(failed),
    }


@router.get("/api/issues")
async def api_issues(
    request: Request,
    status: str | None = None,
    tag: str | None = None,
    root: str | None = None,
    limit: int = 0,
):
    store = _store(request)
    issues = store.list(status=status, tag=tag)
    if root:
        ids = set(store.subtree_ids(root))
        issues = [i for i in issues if i["id"] in ids]
    if limit > 0:
        issues = issues[-limit:]
    return [_issue_json(i) for i in issues]


@router.get("/api/issues/{issue_id}")
async def api_issue(request: Request, issue_id: str):
    issue = _store(request).get(issue_id)
    if issue is None:
        return {"error": "not found"}
    return _issue_json(issue)


@router.get("/api/issues/{issue_id}/children")
async def api_children(request: Request, issue_id: str):
    children = _store(request).children(issue_id)
    children.sort(key=lambda i: i.get("priority", 3))
    return [_issue_json(i) for i in children]


@router.get("/api/issues/{issue_id}/subtree")
async def api_subtree(request: Request, issue_id: str):
    store = _store(request)
    ids = store.subtree_ids(issue_id)
    all_issues = store.list()
    subtree = [i for i in all_issues if i["id"] in set(ids)]
    return [_issue_json(i) for i in subtree]


@router.get("/api/ready")
async def api_ready(request: Request, root: str | None = None):
    store = _store(request)
    issues = store.ready(root, tags=["node:agent"])
    return [_issue_json(i) for i in issues]


@router.get("/api/validate/{root_id}")
async def api_validate(request: Request, root_id: str):
    result = _store(request).validate(root_id)
    return {"root_id": root_id, "is_final": result.is_final, "reason": result.reason}


@router.get("/api/roles")
async def api_roles(request: Request):
    return list_roles_json(_repo_root(request))


@router.get("/api/logs/{issue_id}")
async def api_logs(request: Request, issue_id: str, offset: int = 0, limit: int = 200):
    log_path = _repo_root(request) / ".loopfarm" / "logs" / f"{issue_id}.jsonl"
    if not log_path.exists():
        return []
    lines = read_jsonl(log_path)
    return lines[offset : offset + limit]


@router.get("/api/forum/topics")
async def api_forum_topics(request: Request, prefix: str | None = None):
    return _forum(request).topics(prefix=prefix)


@router.get("/api/forum/{topic:path}")
async def api_forum_read(request: Request, topic: str, limit: int = 50):
    return _forum(request).read(topic, limit=limit)


@router.get("/api/runner")
async def api_runner(request: Request):
    return request.app.state.runner_state


# ---------------------------------------------------------------------------
# Actions API (JSON, mutating)
# ---------------------------------------------------------------------------


class IssueCreate(BaseModel):
    title: str
    body: str = ""
    parent: str | None = None
    tags: list[str] = []
    role: str | None = None
    cli: str | None = None
    model: str | None = None
    priority: int = 3


class IssueUpdate(BaseModel):
    title: str | None = None
    body: str | None = None
    priority: int | None = None
    execution_spec: dict[str, Any] | None = None


class IssueClose(BaseModel):
    outcome: str = "success"


class DepAction(BaseModel):
    dep_type: str = "blocks"
    target: str = ""


class ForumPost(BaseModel):
    body: str
    author: str = "web"


class RunnerStart(BaseModel):
    root_id: str
    max_steps: int = 20


@router.post("/api/issues")
async def api_create_issue(request: Request, body: IssueCreate):
    store = _store(request)
    tags = list(body.tags)
    if "node:agent" not in tags:
        tags.append("node:agent")

    spec = None
    if body.role or body.cli or body.model:
        spec = {}
        if body.role:
            spec["role"] = body.role
        if body.cli:
            spec["cli"] = body.cli
        if body.model:
            spec["model"] = body.model

    issue = store.create(body.title, body=body.body, tags=tags, execution_spec=spec, priority=body.priority)

    if body.parent:
        store.add_dep(issue["id"], "parent", body.parent)
        issue = store.get(issue["id"])

    return _issue_json(issue)


@router.patch("/api/issues/{issue_id}")
async def api_update_issue(request: Request, issue_id: str, body: IssueUpdate):
    store = _store(request)
    fields: dict[str, Any] = {}
    if body.title is not None:
        fields["title"] = body.title
    if body.body is not None:
        fields["body"] = body.body
    if body.priority is not None:
        fields["priority"] = body.priority
    if body.execution_spec is not None:
        fields["execution_spec"] = body.execution_spec
    if not fields:
        issue = store.get(issue_id)
        return _issue_json(issue) if issue else {"error": "not found"}
    updated = store.update(issue_id, **fields)
    return _issue_json(updated)


@router.post("/api/issues/{issue_id}/close")
async def api_close_issue(request: Request, issue_id: str, body: IssueClose):
    issue = _store(request).close(issue_id, outcome=body.outcome)
    return _issue_json(issue)


@router.post("/api/issues/{issue_id}/reopen")
async def api_reopen_issue(request: Request, issue_id: str):
    issue = _store(request).update(issue_id, status="open", outcome=None)
    return _issue_json(issue)


@router.post("/api/issues/{issue_id}/claim")
async def api_claim_issue(request: Request, issue_id: str):
    _store(request).claim(issue_id)
    issue = _store(request).get(issue_id)
    return _issue_json(issue) if issue else {"error": "not found"}


@router.post("/api/issues/{issue_id}/dep")
async def api_add_dep(request: Request, issue_id: str, body: DepAction):
    _store(request).add_dep(issue_id, body.dep_type, body.target)
    return {"ok": True}


@router.delete("/api/issues/{issue_id}/dep")
async def api_remove_dep(request: Request, issue_id: str, body: DepAction):
    removed = _store(request).remove_dep(issue_id, body.dep_type, body.target)
    return {"ok": removed}


@router.post("/api/forum/{topic:path}")
async def api_forum_post(request: Request, topic: str, body: ForumPost):
    msg = _forum(request).post(topic, body.body, author=body.author)
    return msg


@router.post("/api/runner/start")
async def api_runner_start(request: Request, body: RunnerStart):
    state = request.app.state.runner_state
    if state["status"] == "running":
        return {"error": "runner already active"}

    from .runner import start_runner

    asyncio.create_task(
        start_runner(
            _store(request),
            _forum(request),
            _repo_root(request),
            request.app.state.broadcaster,
            state,
            body.root_id,
            body.max_steps,
        )
    )
    return {"ok": True, "root_id": body.root_id}


@router.post("/api/runner/pause")
async def api_runner_pause(request: Request):
    request.app.state.runner_state["status"] = "paused"
    return {"ok": True}


@router.post("/api/runner/resume")
async def api_runner_resume(request: Request):
    state = request.app.state.runner_state
    root_id = state.get("root_id")
    if not root_id:
        return {"error": "no root to resume"}

    from .runner import start_runner

    asyncio.create_task(
        start_runner(
            _store(request),
            _forum(request),
            _repo_root(request),
            request.app.state.broadcaster,
            state,
            root_id,
        )
    )
    return {"ok": True, "root_id": root_id}


# ---------------------------------------------------------------------------
# SSE
# ---------------------------------------------------------------------------


@router.get("/api/events")
async def api_events(request: Request, root: str | None = None):
    broadcaster = request.app.state.broadcaster

    async def event_stream():
        async for payload in broadcaster.iter_events(root_id=root):
            yield payload

    return StreamingResponse(event_stream(), media_type="text/event-stream")
