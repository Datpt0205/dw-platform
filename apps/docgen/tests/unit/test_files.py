"""Bytes in and out, with the per-file error vocabulary deepagents expects."""

from __future__ import annotations

import base64
import os
from pathlib import Path

import pytest

from dw_docgen.files import BatchTooLargeError, download, upload
from dw_docgen.models import UploadFile
from dw_docgen.settings import DocgenSettings
from dw_docgen.workspace import SessionWorkspace

pytestmark = pytest.mark.unit

SESSION = "run-1"


@pytest.fixture
def workspace(settings: DocgenSettings) -> SessionWorkspace:
    return SessionWorkspace(Path(settings.root), uids=None)


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")


def test_a_file_survives_the_round_trip(
    workspace: SessionWorkspace, settings: DocgenSettings
) -> None:
    payload = b"PK\x03\x04 template bytes"

    uploaded = upload(
        workspace,
        SESSION,
        [UploadFile(path="tpl/shell.docx", content_b64=_b64(payload))],
        settings,
        None,
    )
    fetched = download(workspace, SESSION, ["tpl/shell.docx"], settings)

    assert uploaded == [uploaded[0].model_copy(update={"error": None})]
    assert fetched[0].error is None
    assert fetched[0].content_b64 is not None
    assert base64.b64decode(fetched[0].content_b64) == payload


def test_upload_creates_the_parent_directory(
    workspace: SessionWorkspace, settings: DocgenSettings
) -> None:
    upload(
        workspace, SESSION, [UploadFile(path="a/b/c.txt", content_b64=_b64(b"x"))], settings, None
    )

    assert (workspace.session_dir(SESSION) / "a" / "b" / "c.txt").exists()


def test_a_path_outside_the_session_is_reported_not_written(
    workspace: SessionWorkspace, settings: DocgenSettings
) -> None:
    results = upload(
        workspace,
        SESSION,
        [UploadFile(path="../escaped.txt", content_b64=_b64(b"x"))],
        settings,
        None,
    )

    assert results[0].error == "invalid_path"
    assert not (workspace.root / "escaped.txt").exists()


def test_a_missing_file_reports_file_not_found(
    workspace: SessionWorkspace, settings: DocgenSettings
) -> None:
    results = download(workspace, SESSION, ["out/never-written.docx"], settings)

    assert results[0].error == "file_not_found"
    assert results[0].content_b64 is None


def test_a_directory_is_not_downloadable(
    workspace: SessionWorkspace, settings: DocgenSettings
) -> None:
    (workspace.session_dir(SESSION) / "out").mkdir()

    results = download(workspace, SESSION, ["out"], settings)

    assert results[0].error == "is_directory"


def test_one_bad_path_does_not_lose_the_rest_of_the_batch(
    workspace: SessionWorkspace, settings: DocgenSettings
) -> None:
    results = upload(
        workspace,
        SESSION,
        [
            UploadFile(path="good.txt", content_b64=_b64(b"one")),
            UploadFile(path="../bad.txt", content_b64=_b64(b"two")),
        ],
        settings,
        None,
    )

    assert [r.error for r in results] == [None, "invalid_path"]
    assert (workspace.session_dir(SESSION) / "good.txt").read_bytes() == b"one"


def test_too_many_files_refuses_the_whole_batch(
    workspace: SessionWorkspace, settings: DocgenSettings
) -> None:
    files = [UploadFile(path=f"f{i}.txt", content_b64=_b64(b"x")) for i in range(4)]

    with pytest.raises(BatchTooLargeError):
        upload(workspace, SESSION, files, settings, None)

    assert not (workspace.session_dir(SESSION) / "f0.txt").exists()


def test_too_many_bytes_refuses_the_whole_batch(
    workspace: SessionWorkspace, settings: DocgenSettings
) -> None:
    files = [UploadFile(path="big.bin", content_b64=_b64(b"x" * (settings.max_upload_bytes + 1)))]

    with pytest.raises(BatchTooLargeError):
        upload(workspace, SESSION, files, settings, None)


def test_a_download_over_budget_is_reported_rather_than_returned(
    workspace: SessionWorkspace, settings: DocgenSettings
) -> None:
    oversized = workspace.session_dir(SESSION) / "huge.bin"
    oversized.write_bytes(b"x" * (settings.max_download_bytes + 1))

    results = download(workspace, SESSION, ["huge.bin"], settings)

    assert results[0].error == "file_too_large"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX")
def test_a_fifo_is_neither_downloaded_nor_written_through(
    workspace: SessionWorkspace, settings: DocgenSettings
) -> None:
    # Opened, a FIFO with nobody on the other end would block the request while
    # it holds the semaphore every session waits on; it is refused instead.
    os.mkfifo(workspace.session_dir(SESSION) / "out.docx")

    read = download(workspace, SESSION, ["out.docx"], settings)
    written = upload(
        workspace, SESSION, [UploadFile(path="out.docx", content_b64=_b64(b"x"))], settings, None
    )

    assert read[0].error == "invalid_path"
    assert written[0].error == "invalid_path"
