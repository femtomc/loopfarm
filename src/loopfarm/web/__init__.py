"""Loopfarm web interface — FastAPI app factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from ..forum_store import ForumStore
from ..issue_store import IssueStore
from .sse import EventBroadcaster

_HERE = Path(__file__).parent


def _find_repo_root() -> Path:
    p = Path.cwd()
    while p != p.parent:
        if (p / ".git").exists():
            return p
        p = p.parent
    return Path.cwd()


def create_app() -> FastAPI:
    repo_root = _find_repo_root()
    store = IssueStore.from_workdir(repo_root)
    forum = ForumStore.from_workdir(repo_root)
    broadcaster = EventBroadcaster(store, forum)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        task = broadcaster.start()
        yield
        broadcaster.stop()
        await task

    app = FastAPI(title="loopfarm", lifespan=lifespan)

    app.state.repo_root = repo_root
    app.state.store = store
    app.state.forum = forum
    app.state.broadcaster = broadcaster
    app.state.runner_state = {"status": "idle", "root_id": None, "step": 0}

    app.mount(
        "/static",
        StaticFiles(directory=str(_HERE / "static")),
        name="static",
    )

    templates = Jinja2Templates(directory=str(_HERE / "templates"))
    app.state.templates = templates

    from .routes import router

    app.include_router(router)

    return app
