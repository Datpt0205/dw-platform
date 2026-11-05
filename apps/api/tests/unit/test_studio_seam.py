"""The `/api/v1/studio` seam (studio-skeleton ticket 02: R6.1-R6.5, R6.8-R6.10).

Asked of the built app's behaviour and of `app.openapi()`, never of
`app.routes` (ADR-0100 decision 6). The gate is driven at the ASGI level with a
body source that counts what it handed over, so "not read" is a number, not a
reading of the code. Each refusal has a companion that removes the control and
shows the same case going through (failure-modes #3).
"""

from __future__ import annotations

import sys
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import httpx
import jwt
import pytest
from fastapi import APIRouter, Body, Depends, FastAPI, Request

from dw_api.bootstrap.studio import StudioContainer
from dw_api.bootstrap.wiring import build_container
from dw_api.dependencies.auth import get_studio_access_context, verify_bearer
from dw_api.exception_handlers import register_exception_handlers
from dw_api.main import create_app
from dw_api.middleware.studio_gate import MAX_BODY_BYTES, StudioGate, under_studio
from dw_api.routes.v1.studio_artifacts import router as artifacts_router
from dw_api.settings import ApiSettings
from dw_kernel.errors import UnauthenticatedError
from dw_platform.adapters.identity.dev_token import DevTokenVerifier
from dw_platform.application.access_context import AccessContext
from dw_platform.application.ports import VerifiedIdentity
from dw_studio.core.application.registry import ArtifactKindRegistry

pytestmark = pytest.mark.unit

# A module-level marker, not a call in a default (ruff B008).
_JSON_BODY = Body()

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "scripts"))

SECRET = "studio-seam-secret-0123456789abcdef0123"
PREFIX = "/api/v1/studio/"
PROBE = "/api/v1/studio/probe"
TWO_MIB = 2 * 1_048_576


def contract_app() -> FastAPI:
    from generate_contracts import build_app  # type: ignore[import-not-found]

    app: FastAPI = build_app()
    return app


def studio_operations(spec: dict[str, Any]) -> list[tuple[str, str]]:
    return sorted(
        (method.upper(), path)
        for path, item in spec["paths"].items()
        if path.startswith(PREFIX)
        for method in item
        if method in {"get", "post", "put", "patch", "delete"}
    )


def concrete(path: str) -> str:
    return path.replace("{artifact_id}", str(uuid.uuid4())).replace("{version_no}", "1")


async def anonymous_answers(app: FastAPI) -> dict[tuple[str, str], int]:
    """Every Studio operation of the schema, called with no token."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    answers: dict[tuple[str, str], int] = {}
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        for method, path in studio_operations(app.openapi()):
            response = await client.request(method, concrete(path))
            answers[(method, path)] = response.status_code
    return answers


def tagged_problems(spec: dict[str, Any]) -> list[str]:
    """R6.3: an operation tagged `studio` outside the prefix."""
    return sorted(
        f"{method.upper()} {path}"
        for path, item in spec["paths"].items()
        for method, operation in item.items()
        if "studio" in operation.get("tags", []) and not path.startswith(PREFIX)
    )


# ------------------------------------------------------------ R6.1-R6.3 --


async def test_every_studio_path_of_the_schema_answers_an_anonymous_call_401() -> None:
    app = contract_app()
    answers = await anonymous_answers(app)

    assert answers, "the schema lists at least one path under /api/v1/studio/ (R6.2)"
    assert {op: code for op, code in answers.items() if code != 401} == {}
    assert tagged_problems(app.openapi()) == []


async def test_without_mount_studio_the_same_calls_are_404(monkeypatch: pytest.MonkeyPatch) -> None:
    """R6.1's control removed: the seam unmounted answers 404, and the test
    above would be red."""
    import dw_api.main as main

    expected = studio_operations(contract_app().openapi())
    monkeypatch.setattr(main, "mount_studio", lambda app, container: None)
    app = contract_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        codes = {(await client.request(m, concrete(p))).status_code for m, p in expected}

    assert codes == {404}
    assert studio_operations(app.openapi()) == [], "R6.2's check is red on an empty group"


def test_an_operation_tagged_studio_outside_the_prefix_is_named() -> None:
    app = contract_app()

    @app.get("/api/v1/objects", tags=["studio"])
    async def misplaced() -> dict[str, str]:
        return {}

    app.openapi_schema = None
    assert tagged_problems(app.openapi()) == ["GET /api/v1/objects"]


def _group_app(dependency: Callable[..., Awaitable[Any]]) -> FastAPI:
    """The group with its dependency and no gate: what R6.1 says the dependency
    alone does."""
    app = FastAPI()
    register_exception_handlers(app)
    app.state.container = SimpleNamespace(token_verifier=None, access_context_factory=None)
    group = APIRouter(prefix="/studio", dependencies=[Depends(dependency)])

    @group.get("/probe")
    async def probe() -> dict[str, str]:
        return {"ok": "yes"}

    app.include_router(group, prefix="/api/v1")
    return app


async def test_the_group_dependency_refuses_without_the_gates_result() -> None:
    async def passes(request: Request) -> None:
        return None

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_group_app(get_studio_access_context)),
        base_url="http://t",
    ) as client:
        closed = await client.get(PROBE, headers={"Authorization": "Bearer x"})
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_group_app(passes)), base_url="http://t"
    ) as client:
        opened = await client.get(PROBE)

    assert closed.status_code == 401
    assert closed.json()["code"] == "unauthenticated"
    assert opened.status_code == 200, "a dependency that lets it through would turn the test red"


# ------------------------------------------------------------------ R6.9 --


async def test_a_hidden_route_and_a_missing_path_under_the_prefix_are_401() -> None:
    app = contract_app()

    @app.get("/api/v1/studio/hidden-probe", include_in_schema=False)
    async def hidden() -> dict[str, str]:
        return {"ok": "yes"}

    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/api/v1/studio/hidden-probe")).status_code == 401
        assert (await client.get("/api/v1/studio/no-such-path")).status_code == 401
        assert (await client.get("/api/v1/studio")).status_code == 401
        assert (await client.get("/api/v1/studio-missing")).status_code == 404

    # The gate removed before the stack is built: the hidden route opens.
    ungated = contract_app()
    ungated.user_middleware = [m for m in ungated.user_middleware if m.cls is not StudioGate]

    @ungated.get("/api/v1/studio/hidden-probe", include_in_schema=False)
    async def hidden_too() -> dict[str, str]:
        return {"ok": "yes"}

    transport = httpx.ASGITransport(app=ungated, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        assert (await client.get("/api/v1/studio/hidden-probe")).status_code == 200


def test_the_prefix_is_the_path_and_what_is_below_it() -> None:
    assert under_studio("/api/v1/studio")
    assert under_studio("/api/v1/studio/artifacts")
    assert not under_studio("/api/v1/studio-missing")
    assert not under_studio("/api/v1/studios")


# ------------------------------------------------------------------ R6.4 --


def _no_database_app() -> FastAPI:
    container = build_container(ApiSettings(profile="test", dev_secret=SECRET))
    assert container.studio is None
    return create_app(container)


async def test_without_a_database_studio_is_absent_and_never_500() -> None:
    app = _no_database_app()
    expected = studio_operations(contract_app().openapi())
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        listed = await client.get("/api/v1/studio/artifacts")
        codes = {(await client.request(m, concrete(p))).status_code for m, p in expected}

    assert listed.status_code == 404
    assert codes == {404}


async def test_a_group_mounted_without_studio_answers_otherwise() -> None:
    """R6.4's control removed: a group mounted with nothing behind it is not a 404."""
    container = build_container(ApiSettings(profile="test", dev_secret=SECRET))
    container.studio = StudioContainer(
        kinds=ArtifactKindRegistry(()),
        artifacts=cast(Any, None),
        agent_settings=cast(Any, None),
        lifecycle=cast(Any, None),
        segments={},
        candidates=cast(Any, None),
        kill_switches=cast(Any, None),
        kill_segments={},
        routers=(artifacts_router,),
        run_manifests=cast(Any, None),
        pinned_manifests=cast(Any, None),
        run_requests=cast(Any, None),
        run_lanes=cast(Any, None),
        config_versions=cast(Any, None),
        bindings=cast(Any, None),
        binding_status=cast(Any, None),
        run_bindings=cast(Any, None),
        node_types={},
        actor_boundaries=cast(Any, None),
        records=cast(Any, None),
        record_door=cast(Any, None),
    )
    app = create_app(container)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        answer = await client.get("/api/v1/studio/artifacts")
    assert answer.status_code != 404


# ------------------------------------------------- the gate, R6.5 R6.8 R6.10 --


class Source:
    """An ASGI `receive` over one body: 64 KiB chunks that end exactly at the
    cap, then the one byte past it alone, then 64 KiB again, so the count shows
    exactly where reading stopped."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.at = 0
        self.read = 0

    async def __call__(self) -> dict[str, Any]:
        if self.at >= len(self.body):
            return {"type": "http.request", "body": b"", "more_body": False}
        if self.at < MAX_BODY_BYTES:
            size = min(65_536, MAX_BODY_BYTES - self.at)
        elif self.at == MAX_BODY_BYTES:
            size = 1
        else:
            size = 65_536
        chunk = self.body[self.at : self.at + size]
        self.at += len(chunk)
        self.read += len(chunk)
        return {"type": "http.request", "body": chunk, "more_body": self.at < len(self.body)}


def json_body(size: int) -> bytes:
    body = b'{"x":"' + b"a" * (size - 8) + b'"}'
    assert len(body) == size
    return body


Verify = Callable[[str | None], Awaitable[VerifiedIdentity]]


def _real_verify(verifier: Any = None) -> Verify:
    container = cast(Any, SimpleNamespace(token_verifier=verifier or DevTokenVerifier(SECRET)))

    async def verify(header: str | None) -> VerifiedIdentity:
        return await verify_bearer(container, header)

    return verify


def gated_app(*, verify: Verify | None = None, gate: bool = True) -> tuple[FastAPI, list[int]]:
    """A fake handler that declares a body, behind the gate."""
    app = FastAPI()
    register_exception_handlers(app)
    calls: list[int] = []

    @app.post(PROBE)
    async def probe(payload: dict[str, Any] = _JSON_BODY) -> dict[str, int]:
        calls.append(len(payload.get("x", "")))
        return {"length": calls[-1]}

    @app.get(PROBE)
    async def read() -> dict[str, str]:
        calls.append(0)
        return {"ok": "yes"}

    if gate:
        app.add_middleware(StudioGate, verify=verify or _real_verify())
    return app, calls


async def drive(
    app: FastAPI, source: Source, headers: dict[str, str], method: str = "POST"
) -> tuple[int, dict[str, str], bytes]:
    sent: list[dict[str, Any]] = []

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": PROBE,
        "raw_path": PROBE.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": ("test", 1),
        "server": ("test", 80),
    }
    await app(scope, source, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    found = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    return start["status"], found, body


def token(verifier: DevTokenVerifier | None = None, **kw: Any) -> str:
    return (verifier or DevTokenVerifier(SECRET)).issue("seam-user", **kw)


def auth(value: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {value}", "Content-Type": "application/json"}


@pytest.mark.parametrize("declared", ["exact", "absent", "ten"])
async def test_a_body_past_the_cap_is_413_and_never_read_past_one_byte(declared: str) -> None:
    app, calls = gated_app()
    size = MAX_BODY_BYTES + 1
    source = Source(json_body(size) + b" " * 4096)
    headers = auth(token())
    if declared == "exact":
        headers["Content-Length"] = str(size)
    elif declared == "ten":
        headers["Content-Length"] = "10"

    status, sent, body = await drive(app, source, headers)

    assert status == 413
    assert b'"code":"payload_too_large"' in body
    assert sent["content-type"].startswith("application/problem+json")
    assert calls == []
    # A declared length past the cap is refused unread; otherwise the byte
    # past the cap is the last one asked for, whatever was declared.
    assert source.read == (0 if declared == "exact" else MAX_BODY_BYTES + 1)


async def test_a_body_at_the_cap_reaches_the_handler() -> None:
    app, calls = gated_app()
    source = Source(json_body(MAX_BODY_BYTES))

    status, _, _ = await drive(app, source, auth(token()))

    assert status == 200
    assert calls == [MAX_BODY_BYTES - 8]


async def test_without_the_gate_the_same_body_reaches_the_handler() -> None:
    """R6.5's control removed: the handler runs on a body past the cap."""
    app, calls = gated_app(gate=False)
    source = Source(json_body(MAX_BODY_BYTES + 1))

    status, _, _ = await drive(app, source, {"Content-Type": "application/json"})

    assert status == 200
    assert calls


def _wrong_tokens() -> dict[str, str | None]:
    return {
        "none": None,
        "expired": token(ttl=timedelta(hours=-1)),
        "bad signature": token(DevTokenVerifier("another-secret-0123456789abcdef0123456")),
        "wrong audience": token(DevTokenVerifier(SECRET, audience="not-dw-api")),
    }


@pytest.mark.parametrize("case", sorted(_wrong_tokens()))
async def test_a_caller_the_verifier_refuses_gets_401_with_nothing_read(case: str) -> None:
    app, calls = gated_app()
    source = Source(json_body(TWO_MIB))
    value = _wrong_tokens()[case]
    headers = {"Content-Type": "application/json", "Content-Length": str(TWO_MIB)}
    if value is not None:
        headers["Authorization"] = f"Bearer {value}"

    status, sent, body = await drive(app, source, headers)

    assert status == 401
    assert sent["www-authenticate"] == "Bearer"
    assert b'"code":"unauthenticated"' in body
    assert source.read == 0
    assert calls == []


async def test_a_verifier_that_checks_only_the_signature_lets_the_wrong_audience_in() -> None:
    """R6.8's companion: the audience case is red against a weaker verifier."""

    class SignatureOnly:
        async def verify(self, raw: str) -> Any:
            jwt.decode(raw, key=SECRET, algorithms=["HS256"], options={"verify_aud": False})
            return SimpleNamespace(subject="x")

    app, _calls = gated_app(verify=_real_verify(SignatureOnly()))
    source = Source(json_body(64))
    status, _, _ = await drive(app, source, auth(_wrong_tokens()["wrong audience"] or ""))

    assert status == 200


async def test_authentication_as_a_dependency_reads_the_body_first() -> None:
    """R6.8's companion: a route that declares a body has it read before any
    dependency runs (FastAPI 0.141.1), so a refusal there comes after the bytes."""
    app = FastAPI()
    register_exception_handlers(app)

    async def refuse() -> None:
        raise UnauthenticatedError("no token")

    @app.post(PROBE, dependencies=[Depends(refuse)])
    async def probe(payload: dict[str, Any] = _JSON_BODY) -> dict[str, str]:
        return {}

    source = Source(json_body(TWO_MIB))
    status, _, _ = await drive(app, source, {"Content-Type": "application/json"})

    assert status == 401
    assert source.read == TWO_MIB


@pytest.mark.parametrize("method", ["POST", "GET"])
async def test_a_compressed_body_is_415_and_not_read(method: str) -> None:
    app, calls = gated_app()
    source = Source(json_body(TWO_MIB))
    headers = {**auth(token()), "Content-Encoding": "gzip"}

    status, _, body = await drive(app, source, headers, method=method)

    assert status == 415
    assert b'"code":"unsupported_media_type"' in body
    assert source.read == 0
    assert calls == []


async def test_without_the_encoding_check_a_compressed_body_is_read() -> None:
    """R6.10's companion: the gate removed, the bytes are read."""
    app, _calls = gated_app(gate=False)
    source = Source(json_body(64))
    headers = {"Content-Type": "application/json", "Content-Encoding": "gzip"}

    status, _, _ = await drive(app, source, headers)

    assert status == 200
    assert source.read == 64


async def test_a_verifier_that_fails_refuses_rather_than_passes() -> None:
    async def broken(_: str | None) -> VerifiedIdentity:
        raise RuntimeError("the identity provider timed out")

    app, calls = gated_app(verify=broken)
    status, _, _body = await drive(app, Source(json_body(64)), auth(token()))

    assert status == 503
    assert calls == []


async def test_a_refusal_carries_the_request_id() -> None:
    app = contract_app()
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        answer = await client.get("/api/v1/studio/artifacts", headers={"X-Request-ID": "req-1"})

    assert answer.status_code == 401
    assert answer.json()["request_id"] == "req-1"
    assert answer.headers["X-Request-ID"] == "req-1"
    assert answer.headers["WWW-Authenticate"] == "Bearer"


def test_the_context_the_group_builds_is_an_access_context() -> None:
    assert get_studio_access_context.__annotations__["return"] in {AccessContext, "AccessContext"}
