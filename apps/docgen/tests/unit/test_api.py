"""The four routes a sandbox backend needs, over HTTP."""

from __future__ import annotations

import base64
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dw_docgen.main import create_app
from dw_docgen.settings import DocgenSettings

pytestmark = pytest.mark.unit

SESSION = "run-1"


@pytest.fixture
def client(settings: DocgenSettings) -> Iterator[TestClient]:
    with TestClient(create_app(settings, isolate_sessions=False)) as test_client:
        yield test_client


def test_health_reports_whether_the_limits_are_on(
    client: TestClient, settings: DocgenSettings
) -> None:
    reply = client.get("/health")

    assert reply.status_code == 200
    assert reply.json() == {
        "status": "ok",
        "limits_enforced": settings.enforce_limits,
        "sessions_isolated": False,
    }


def test_a_command_runs_and_its_files_come_back(client: TestClient) -> None:
    source = 'open("out.txt", "w").write("generated")\n'
    client.post(
        f"/v1/sessions/{SESSION}/files/upload",
        json={"files": [{"path": "gen.py", "content_b64": _b64(source.encode())}]},
    )

    ran = client.post(
        f"/v1/sessions/{SESSION}/execute", json={"command": f'"{sys.executable}" gen.py'}
    )
    fetched = client.post(f"/v1/sessions/{SESSION}/files/download", json={"paths": ["out.txt"]})

    assert ran.json()["exit_code"] == 0
    body = fetched.json()["results"][0]
    assert base64.b64decode(body["content_b64"]) == b"generated"


def test_the_timeout_is_clamped_to_the_service_maximum(
    client: TestClient, settings: DocgenSettings
) -> None:
    reply = client.post(
        f"/v1/sessions/{SESSION}/execute",
        json={"command": f'"{sys.executable}" -c "1"', "timeout_seconds": 9999},
    )

    assert reply.status_code == 200
    assert settings.max_timeout_seconds < 9999


@pytest.mark.parametrize("session_id", ["../etc", "a/b", ""])
def test_a_session_id_that_is_not_a_plain_name_is_refused(
    client: TestClient, session_id: str
) -> None:
    reply = client.post(f"/v1/sessions/{session_id}/execute", json={"command": "echo hi"})

    assert reply.status_code in (400, 404, 405)


def test_release_deletes_the_session(client: TestClient, settings: DocgenSettings) -> None:
    client.post(
        f"/v1/sessions/{SESSION}/files/upload",
        json={"files": [{"path": "draft.docx", "content_b64": _b64(b"PK")}]},
    )

    released = client.post(f"/v1/sessions/{SESSION}")

    assert released.status_code == 204
    assert not (Path(settings.root) / SESSION).exists()


def test_an_oversized_batch_is_refused_with_413(client: TestClient) -> None:
    files = [{"path": f"f{i}.txt", "content_b64": _b64(b"x")} for i in range(9)]

    reply = client.post(f"/v1/sessions/{SESSION}/files/upload", json={"files": files})

    assert reply.status_code == 413


class TestWithAToken:
    @pytest.fixture
    def client(self, settings: DocgenSettings) -> Iterator[TestClient]:
        with TestClient(
            create_app(settings.model_copy(update={"token": "s3cret"}), isolate_sessions=False)
        ) as test_client:
            yield test_client

    def test_a_caller_without_the_token_is_refused(self, client: TestClient) -> None:
        reply = client.post(f"/v1/sessions/{SESSION}/execute", json={"command": "echo hi"})

        assert reply.status_code == 401

    def test_a_caller_with_the_token_is_served(self, client: TestClient) -> None:
        reply = client.post(
            f"/v1/sessions/{SESSION}/execute",
            json={"command": f'"{sys.executable}" -c "1"'},
            headers={"Authorization": "Bearer s3cret"},
        )

        assert reply.status_code == 200

    def test_health_needs_no_token(self, client: TestClient) -> None:
        assert client.get("/health").status_code == 200


def _b64(payload: bytes) -> str:
    return base64.b64encode(payload).decode("ascii")
