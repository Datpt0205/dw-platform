"""ADR 0025's rules that a unit test can reach without being root.

The uid switch itself, the kill by uid and the purge after a command need uid 0
and the image; `tests/integration/test_sandbox_image.py` asserts those. What is
here is every decision the service makes about WHETHER to run: when it refuses
to start, which uid it may hand out, which session it refuses, and that every
route holds the one semaphore.
"""

from __future__ import annotations

import base64
import os
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dw_docgen import identity, main
from dw_docgen.main import create_app, refuse_unless_isolation_holds
from dw_docgen.settings import DocgenSettings
from dw_docgen.workspace import (
    SessionIsolationError,
    SessionPoolExhaustedError,
    SessionWorkspace,
)

pytestmark = pytest.mark.unit

POSIX_ONLY = pytest.mark.skipif(os.name != "posix", reason="needs /proc, uids and FIFOs")
OUTSIDE_THE_POOL = range(20000, 20010)


@pytest.fixture
def client(settings: DocgenSettings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, isolate_sessions=False)) as test_client:
        yield test_client


def isolate_as(client: TestClient, settings: DocgenSettings, uids: range) -> SessionWorkspace:
    """Swap in a workspace whose pool is `uids`, as `main` builds it when isolating."""
    workspace = SessionWorkspace(
        Path(settings.root), uids=uids, session_ttl_seconds=settings.session_ttl_seconds
    )
    client.app.state.workspace = workspace  # type: ignore[attr-defined]
    return workspace


def own_uid(root: Path) -> int:
    """The uid this test's files get: the one pool a non-root test can own."""
    probe = root / ".probe"
    probe.mkdir(parents=True, exist_ok=True)
    return probe.stat().st_uid


# ------------------------------------------------------------- startup --


def test_isolation_refuses_to_start_unless_it_is_uid_0(settings: DocgenSettings) -> None:
    with (
        pytest.raises(RuntimeError, match="must run as uid 0"),
        TestClient(create_app(settings)),
    ):
        pass


def test_without_isolation_uid_0_refuses_to_start(
    settings: DocgenSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Every shell would be root, holding the service's five capabilities.
    monkeypatch.setattr(main, "_euid", lambda: 0)

    with (
        pytest.raises(RuntimeError, match="every shell would be root"),
        TestClient(create_app(settings, isolate_sessions=False)),
    ):
        pass


def test_isolation_refuses_more_than_one_command_at_a_time(
    settings: DocgenSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(main, "_euid", lambda: 0)

    with pytest.raises(RuntimeError, match="max_concurrency is 2"):
        refuse_unless_isolation_holds(settings.model_copy(update={"max_concurrency": 2}))


@POSIX_ONLY
def test_isolation_refuses_a_pool_uid_without_its_passwd_entry(
    settings: DocgenSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A test runner has no `dws0`; the image has one per pool uid.
    monkeypatch.setattr(main, "_euid", lambda: 0)

    with pytest.raises(RuntimeError, match="not 'dws0'"):
        refuse_unless_isolation_holds(settings)


def test_the_uid_range_cannot_reach_system_uids() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 10000"):
        DocgenSettings(session_uid_base=0)


# ----------------------------------------------------------- the pool --


def test_a_session_owned_outside_the_pool_is_refused(tmp_path: Path) -> None:
    # Root, or the old shared uid: running as its owner would undo isolation.
    workspace = SessionWorkspace(tmp_path, uids=OUTSIDE_THE_POOL)
    (tmp_path / "s1").mkdir()

    with pytest.raises(SessionIsolationError, match="outside the session pool"):
        workspace.uid_of("s1")


@POSIX_ONLY
def test_a_uid_with_a_live_process_is_never_handed_out(tmp_path: Path) -> None:
    # The pool is this test's own uid, which no directory holds but which has a
    # process alive - this one - so it is not free.
    workspace = SessionWorkspace(tmp_path, uids=range(os.getuid(), os.getuid() + 1))

    with pytest.raises(SessionPoolExhaustedError):
        workspace.session_dir("new")

    assert not (tmp_path / "new").exists()


def test_a_full_pool_sweeps_stale_sessions_before_refusing_with_503(
    client: TestClient, settings: DocgenSettings
) -> None:
    root = Path(settings.root)
    uid = own_uid(root)
    isolate_as(client, settings, range(uid, uid + 1))
    (root / "held").mkdir()
    stale = root / "stale"
    stale.mkdir()
    long_ago = time.time() - settings.session_ttl_seconds - 60
    os.utime(stale, (long_ago, long_ago))

    reply = client.post("/v1/sessions/fresh/execute", json={"command": "echo hi"})

    assert reply.status_code == 503
    assert not stale.exists()
    assert not (root / "fresh").exists()


@POSIX_ONLY
def test_a_session_whose_uid_still_has_a_process_is_refused(
    client: TestClient, settings: DocgenSettings
) -> None:
    # The pool is this test's uid, alive by definition: as if the last
    # command's kill had not converged.
    root = Path(settings.root)
    root.mkdir(parents=True, exist_ok=True)
    isolate_as(client, settings, range(os.getuid(), os.getuid() + 1))
    (root / "s1").mkdir()

    ran = client.post("/v1/sessions/s1/execute", json={"command": "echo hi"})
    read = client.post("/v1/sessions/s1/files/download", json={"paths": ["x"]})
    wrote = client.post(
        "/v1/sessions/s1/files/upload",
        json={"files": [{"path": "x", "content_b64": _b64(b"x")}]},
    )

    assert (ran.status_code, read.status_code, wrote.status_code) == (503, 503, 503)


@POSIX_ONLY
def test_purge_removes_the_uids_entries_and_leaves_everyone_elses(tmp_path: Path) -> None:
    shared = tmp_path / "tmp"
    (shared / "lo-profile").mkdir(parents=True)
    (shared / "pipe").write_text("x", encoding="utf-8")
    mine = os.getuid()

    identity.purge(mine + 1, [str(shared)])
    kept = sorted(path.name for path in shared.iterdir())
    identity.purge(mine, [str(shared), str(tmp_path / "absent")])

    assert kept == ["lo-profile", "pipe"]
    assert list(shared.iterdir()) == []


def test_adopting_the_root_drops_what_no_pool_uid_owns(tmp_path: Path) -> None:
    (tmp_path / "from-before").mkdir()
    (tmp_path / "stray.txt").write_text("x", encoding="utf-8")
    (tmp_path / ".service").mkdir()
    workspace = SessionWorkspace(tmp_path, uids=OUTSIDE_THE_POOL)

    workspace.adopt_root()

    assert sorted(path.name for path in tmp_path.iterdir()) == [".service"]
    if os.name == "posix":
        assert tmp_path.stat().st_mode & 0o777 == 0o711


# ---------------------------------------------------------- the routes --


def test_a_download_never_creates_a_session(client: TestClient, settings: DocgenSettings) -> None:
    reply = client.post("/v1/sessions/never/files/download", json={"paths": ["out.docx"]})

    assert reply.json()["results"][0]["error"] == "file_not_found"
    assert not (Path(settings.root) / "never").exists()


def test_releasing_a_session_that_never_existed_creates_nothing(
    client: TestClient, settings: DocgenSettings
) -> None:
    reply = client.post("/v1/sessions/never")

    assert reply.status_code == 204
    assert not (Path(settings.root) / "never").exists()


def test_the_sweep_after_a_command_runs_under_the_semaphore(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = client.app.state  # type: ignore[attr-defined]
    seen: list[bool] = []

    def sweep(**_: object) -> list[str]:
        seen.append(state.semaphore.locked())
        return []

    monkeypatch.setattr(state.workspace, "sweep", sweep)

    client.post("/v1/sessions/s1/execute", json={"command": f'"{sys.executable}" -c "1"'})

    assert seen == [True]


def test_an_upload_waits_for_the_command_holding_the_semaphore(client: TestClient) -> None:
    semaphore = client.app.state.semaphore  # type: ignore[attr-defined]
    assert client.portal is not None
    client.portal.call(semaphore.acquire)
    upload = {"files": [{"path": "x.txt", "content_b64": _b64(b"x")}]}
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(client.post, "/v1/sessions/s1/files/upload", json=upload)
        time.sleep(0.5)
        waited = not pending.done()
        client.portal.call(semaphore.release)
        reply = pending.result(timeout=10)

    assert waited
    assert reply.status_code == 200


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")
