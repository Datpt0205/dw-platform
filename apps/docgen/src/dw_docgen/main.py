"""Composition root for the sandbox service.

Deliberately small. This process holds no database handle, no object-store
client and no credentials of any kind: everything it needs arrives in the
request, and everything it produces leaves in the response. That is the whole
security argument — code the model wrote runs here, so there must be nothing
here worth reaching.

It does hold five capabilities, so that each session's shell can run under a
uid of its own (ADR 0025), and it refuses to start in any shape where that
isolation would not hold or would run the shell as root.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from dw_docgen.api import router
from dw_docgen.settings import DocgenSettings, get_settings
from dw_docgen.workspace import SessionWorkspace

logger = logging.getLogger(__name__)


def create_app(settings: DocgenSettings | None = None, *, isolate_sessions: bool = True) -> FastAPI:
    """The app. `uvicorn --factory` calls this with no argument, so it isolates.

    `isolate_sessions` is an argument in code, not a setting read from the
    environment, so no variable can turn isolation off in a container. Unit
    tests turn it off: they run as an ordinary user, who cannot change uid.
    """
    resolved = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if isolate_sessions:
            refuse_unless_isolation_holds(resolved)
        else:
            refuse_root_without_isolation()
        root = Path(resolved.root)
        root.mkdir(parents=True, exist_ok=True)
        app.state.settings = resolved
        app.state.sessions_isolated = isolate_sessions
        workspace = SessionWorkspace(
            root,
            uids=resolved.session_uids if isolate_sessions else None,
            shared_temp_dirs=resolved.shared_temp_dirs,
            session_ttl_seconds=resolved.session_ttl_seconds,
        )
        workspace.adopt_root()
        workspace.scratch_dir.mkdir(parents=True, exist_ok=True)
        app.state.workspace = workspace
        app.state.semaphore = asyncio.Semaphore(resolved.max_concurrency)
        app.state.active_sessions = set()
        if not resolved.enforce_limits:
            logger.warning(
                "resource limits are unavailable on this platform, so commands run "
                "uncapped. This build is for tests only - the sandbox image is Linux."
            )
        yield

    app = FastAPI(
        title="dw-docgen",
        version="0.1.0",
        lifespan=lifespan,
        # No interactive docs and no schema endpoint: nothing human browses this
        # service, and the smaller its surface the less there is to probe.
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.include_router(router)
    return app


def refuse_unless_isolation_holds(settings: DocgenSettings) -> None:
    """Raise unless every session's shell can run under its own pool uid."""
    if _euid() != 0:
        msg = (
            "docgen isolates sessions by uid and must run as uid 0 in its container "
            "with SETUID, SETGID, CHOWN, DAC_OVERRIDE and FOWNER (ADR 0025); "
            "it refuses to run every session as one uid"
        )
        raise RuntimeError(msg)
    if settings.max_concurrency != 1:
        msg = (
            f"max_concurrency is {settings.max_concurrency}; with sessions isolated it "
            "must be 1, because the one semaphore is what keeps a session's process "
            "from racing the service's own file writes (ADR 0025, decision 4)"
        )
        raise RuntimeError(msg)
    import pwd

    for n, uid in enumerate(settings.session_uids):
        try:
            name: str | None = pwd.getpwuid(uid).pw_name
        except KeyError:
            name = None
        if name != f"dws{n}":
            msg = (
                f"uid {uid} of the session pool has passwd entry {name!r}, not 'dws{n}'; "
                "the image's pool and DW_DOCGEN_SESSION_UID_* disagree"
            )
            raise RuntimeError(msg)


def refuse_root_without_isolation() -> None:
    """Raise if the shell would run as uid 0, with the service's capabilities."""
    if _euid() == 0:
        msg = "docgen runs as uid 0 without session isolation, so every shell would be root"
        raise RuntimeError(msg)


def _euid() -> int | None:
    return os.geteuid() if hasattr(os, "geteuid") else None
