"""The containment rule: a session's paths stay inside its own directory."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from dw_docgen.workspace import (
    InvalidSessionError,
    PathOutsideSessionError,
    SessionWorkspace,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def workspace(tmp_path: Path) -> SessionWorkspace:
    return SessionWorkspace(tmp_path / "work", uids=None)


def test_session_directory_is_created_under_the_root(workspace: SessionWorkspace) -> None:
    path = workspace.session_dir("run-1")

    assert path.is_dir()
    assert path.parent == workspace.root


@pytest.mark.parametrize("session_id", ["", "../etc", "a/b", "-leading", "x" * 65, "ru n"])
def test_a_session_id_that_is_not_a_plain_name_is_refused(
    workspace: SessionWorkspace, session_id: str
) -> None:
    with pytest.raises(InvalidSessionError):
        workspace.session_dir(session_id)


def test_a_relative_path_lands_inside_the_session(workspace: SessionWorkspace) -> None:
    resolved = workspace.resolve("run-1", "out/proposal.docx")

    assert resolved == (workspace.session_dir("run-1") / "out" / "proposal.docx").resolve()


def test_an_absolute_path_inside_the_session_is_honoured(workspace: SessionWorkspace) -> None:
    inside = workspace.session_dir("run-1") / "gen.py"

    assert workspace.resolve("run-1", str(inside)) == inside.resolve()


@pytest.mark.parametrize("escape", ["../run-2/secret.docx", "../../etc/passwd", "out/../../x"])
def test_a_path_climbing_out_of_the_session_is_refused(
    workspace: SessionWorkspace, escape: str
) -> None:
    with pytest.raises(PathOutsideSessionError):
        workspace.resolve("run-1", escape)


def test_an_absolute_path_in_another_session_is_refused(workspace: SessionWorkspace) -> None:
    other = workspace.session_dir("run-2") / "draft.docx"

    with pytest.raises(PathOutsideSessionError):
        workspace.resolve("run-1", str(other))


def test_a_symlink_planted_by_the_script_does_not_widen_the_session(
    workspace: SessionWorkspace, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("customer data", encoding="utf-8")
    link = workspace.session_dir("run-1") / "escape"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - platform capability
        pytest.skip(f"symlinks unavailable on this platform: {exc}")

    with pytest.raises(PathOutsideSessionError):
        workspace.resolve("run-1", "escape/secret.txt")


def test_reset_removes_everything_the_session_wrote(workspace: SessionWorkspace) -> None:
    (workspace.session_dir("run-1") / "draft.docx").write_bytes(b"PK\x03\x04")

    workspace.reset("run-1")

    assert not (workspace.root / "run-1").exists()


def test_reset_on_a_session_that_never_ran_is_not_an_error(workspace: SessionWorkspace) -> None:
    workspace.reset("never-used")


def test_sweep_drops_stale_sessions_and_keeps_the_ones_still_running(
    workspace: SessionWorkspace,
) -> None:
    stale = workspace.session_dir("stale")
    running = workspace.session_dir("running")
    fresh = workspace.session_dir("fresh")
    old = 1_000_000.0
    os.utime(stale, (old, old))
    os.utime(running, (old, old))

    swept = workspace.sweep(older_than_seconds=60, skip={"running"}, now=old + 3600)

    assert swept == ["stale"]
    assert running.exists()
    assert fresh.exists()
