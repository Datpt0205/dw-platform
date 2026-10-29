"""Wire shapes for the sandbox service.

Field names mirror `deepagents`' `ExecuteResponse`, `FileUploadResponse` and
`FileDownloadResponse` so the backend on the other side maps one to one and has
nowhere to invent a translation.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExecuteRequest(BaseModel):
    command: str = Field(min_length=1)
    timeout_seconds: int | None = Field(default=None, ge=1)


class ExecuteReply(BaseModel):
    output: str
    exit_code: int | None
    truncated: bool
    timed_out: bool


class UploadFile(BaseModel):
    path: str = Field(min_length=1)
    content_b64: str


class UploadRequest(BaseModel):
    files: list[UploadFile]


class UploadResult(BaseModel):
    path: str
    error: str | None = None


class UploadReply(BaseModel):
    results: list[UploadResult]


class DownloadRequest(BaseModel):
    paths: list[str]


class DownloadResult(BaseModel):
    path: str
    content_b64: str | None = None
    error: str | None = None


class DownloadReply(BaseModel):
    results: list[DownloadResult]


class HealthReply(BaseModel):
    status: str
    limits_enforced: bool
    # Each session's shell under its own uid (ADR 0025). The image test asserts
    # it, so a compose file that runs the service unisolated fails CI.
    sessions_isolated: bool
