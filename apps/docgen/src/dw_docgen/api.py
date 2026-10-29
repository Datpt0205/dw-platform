"""HTTP surface: one session, one shell, files in and out.

Four routes, because a `deepagents` sandbox backend needs exactly four things —
run a command, put files in, take files out — plus a release that ends the
session. Every route is scoped to a session id that maps to one directory and
nothing else.
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from dw_docgen.files import BatchTooLargeError, download, upload
from dw_docgen.models import (
    DownloadReply,
    DownloadRequest,
    ExecuteReply,
    ExecuteRequest,
    HealthReply,
    UploadReply,
    UploadRequest,
)
from dw_docgen.runner import run_command
from dw_docgen.settings import DocgenSettings
from dw_docgen.workspace import (
    InvalidSessionError,
    SessionIsolationError,
    SessionPoolExhaustedError,
    SessionUncleanError,
    SessionWorkspace,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def _settings(request: Request) -> DocgenSettings:
    settings: DocgenSettings = request.app.state.settings
    return settings


def _workspace(request: Request) -> SessionWorkspace:
    workspace: SessionWorkspace = request.app.state.workspace
    return workspace


def require_token(request: Request) -> None:
    """Reject a caller that does not present the shared secret.

    Skipped entirely when no token is configured: the service is published on no
    network but `dw-sandbox`, whose only other member is the forwarder in front
    of it, so an empty token is a deployment choice rather than an oversight.
    Compared in constant time so a wrong token leaks nothing about the right one.
    """
    expected: str = request.app.state.settings.token
    if not expected:
        return
    header = request.headers.get("authorization", "")
    presented = header.removeprefix("Bearer ").strip()
    if not secrets.compare_digest(presented, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")


Settings = Annotated[DocgenSettings, Depends(_settings)]
Workspace = Annotated[SessionWorkspace, Depends(_workspace)]
Authorized = Depends(require_token)


@router.get("/health")
def health(request: Request, settings: Settings) -> HealthReply:
    return HealthReply(
        status="ok",
        limits_enforced=settings.enforce_limits,
        sessions_isolated=request.app.state.sessions_isolated,
    )


@router.post("/v1/sessions/{session_id}/execute", dependencies=[Authorized])
async def execute(
    session_id: str,
    payload: ExecuteRequest,
    request: Request,
    settings: Settings,
    workspace: Workspace,
) -> ExecuteReply:
    timeout = min(
        payload.timeout_seconds or settings.default_timeout_seconds,
        settings.max_timeout_seconds,
    )
    active: set[str] = request.app.state.active_sessions

    def run() -> ExecuteReply:
        cwd = workspace.session_dir(session_id)
        active.add(session_id)
        try:
            result = run_command(
                payload.command,
                cwd=cwd,
                sink_dir=workspace.scratch_dir,
                settings=settings,
                timeout_seconds=timeout,
                uid=workspace.uid_of(session_id),
            )
            # Still under the semaphore: a sweep must not delete a session
            # that a file route is writing into.
            _sweep(workspace, settings, active)
        finally:
            active.discard(session_id)
        return ExecuteReply(
            output=result.output,
            exit_code=result.exit_code,
            truncated=result.truncated,
            timed_out=result.timed_out,
        )

    return await _exclusively(request, run)


@router.post("/v1/sessions/{session_id}/files/upload", dependencies=[Authorized])
async def upload_files(
    session_id: str,
    payload: UploadRequest,
    request: Request,
    settings: Settings,
    workspace: Workspace,
) -> UploadReply:
    def write() -> UploadReply:
        workspace.session_dir(session_id)
        owner = workspace.uid_of(session_id)
        return UploadReply(results=upload(workspace, session_id, payload.files, settings, owner))

    return await _exclusively(request, write)


@router.post("/v1/sessions/{session_id}/files/download", dependencies=[Authorized])
async def download_files(
    session_id: str,
    payload: DownloadRequest,
    request: Request,
    settings: Settings,
    workspace: Workspace,
) -> DownloadReply:
    def read() -> DownloadReply:
        # A read never creates a session, so it never takes a uid from the pool:
        # every path of a session that does not exist is simply not found.
        if workspace.session_dir(session_id, create=False).exists():
            workspace.uid_of(session_id)
        return DownloadReply(results=download(workspace, session_id, payload.paths, settings))

    return await _exclusively(request, read)


@router.post(
    "/v1/sessions/{session_id}",
    dependencies=[Authorized],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def release(session_id: str, request: Request, workspace: Workspace) -> Response:
    """Delete the session's directory. The chat host calls this when a run ends."""
    await _exclusively(request, lambda: workspace.reset(session_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _exclusively[T](request: Request, work: Callable[[], T]) -> T:
    """Run `work` in a thread while holding the one semaphore.

    Every route that touches a session holds it, not only execute. The service
    writes with DAC_OVERRIDE, so no process of a session may be alive to swap a
    path component for a symlink between the containment check and the write -
    and between commands none is, because each command ends by killing its uid
    (ADR 0025, decision 4). `main` refuses `max_concurrency` other than 1 with
    sessions isolated, which is what makes this semaphore that guarantee.
    """
    semaphore: asyncio.Semaphore = request.app.state.semaphore
    async with semaphore:
        try:
            return await asyncio.to_thread(work)
        except InvalidSessionError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        except BatchTooLargeError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail=str(exc)
            ) from exc
        except (SessionPoolExhaustedError, SessionUncleanError) as exc:
            logger.warning("session %s refused: %s", request.path_params.get("session_id"), exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            ) from exc
        except SessionIsolationError as exc:
            # Not the caller's mistake and not transient: a directory this
            # service would have to run as the wrong uid to serve.
            logger.error("session isolation fault: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="session isolation fault",
            ) from exc


def _sweep(workspace: SessionWorkspace, settings: DocgenSettings, active: set[str]) -> None:
    """Drop workdirs left behind by runs that never called release.

    Runs after a command rather than on a timer: this service has one caller and
    a low request rate, so a directory listing per command is cheaper than a
    background task that has to be cancelled cleanly on shutdown.
    """
    try:
        swept = workspace.sweep(older_than_seconds=settings.session_ttl_seconds, skip=active)
    except OSError:
        logger.warning("sweep of abandoned sessions failed", exc_info=True)
        return
    if swept:
        logger.info("swept %d abandoned sandbox sessions", len(swept))
