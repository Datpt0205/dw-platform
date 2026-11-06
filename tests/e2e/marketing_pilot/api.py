"""The harness's door to the platform: its public HTTP API and nothing else
(marketing-pilot R1.2, MP17).

A person is a dev-issuer subject and an email; every call carries a token the
harness signs itself, HS256 over the dev issuer's secret, with the claims the
API's dev verifier requires (`iss` `dw-dev`, `aud` `dw-api`, `sub`, `exp`) and
the verified email an IdP would assert. Signed here on purpose, not by the
platform's `DevTokenVerifier`: the harness imports no `dw_*` module, so a
change in the claim format makes every call 401, loudly (gate MEDIUM (a)).

Every call is written to `log` (method, path, tenant, status) before its
answer is checked: R1.7 reads it to prove nothing reached a company still in
`setup` but the owners' sign-ins and the operator's status reads.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

import httpx
import jwt

ISSUER: Final = "dw-dev"
AUDIENCE: Final = "dw-api"
TOKEN_SECONDS: Final = 600
PREFIX: Final = "/api/v1"


class SeedError(RuntimeError):
    """A step of the seed did not answer as the platform promises."""


@dataclass(frozen=True)
class Person:
    key: str
    subject: str
    email: str
    display_name: str


@dataclass(frozen=True)
class Call:
    method: str
    path: str
    tenant_id: str | None
    status: int


@dataclass(frozen=True)
class Answer:
    status: int
    body: Any
    headers: Mapping[str, str]


@dataclass
class Api:
    base_url: str
    secret: str
    http: httpx.Client
    log: list[Call] = field(default_factory=list)

    def token(self, person: Person) -> str:
        now = int(time.time())
        claims = {
            "sub": person.subject,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": now,
            "exp": now + TOKEN_SECONDS,
            "email": person.email,
            "email_verified": True,
        }
        return jwt.encode(claims, self.secret, algorithm="HS256")

    def request(
        self,
        method: str,
        path: str,
        person: Person,
        *,
        tenant: str | None = None,
        workspace: str | None = None,
        body: Any = None,
        if_match: str | None = None,
        params: Mapping[str, str] | None = None,
    ) -> Answer:
        headers = {"Authorization": f"Bearer {self.token(person)}"}
        if tenant is not None:
            headers["X-Tenant-Id"] = tenant
        if workspace is not None:
            headers["X-Workspace-Id"] = workspace
        if method != "GET":
            headers["Idempotency-Key"] = str(uuid.uuid4())
        if if_match is not None:
            headers["If-Match"] = if_match
        response = self.http.request(
            method,
            f"{self.base_url}{PREFIX}{path}",
            headers=headers,
            json=body,
            params=params,
        )
        self.log.append(Call(method, path, tenant, response.status_code))
        payload = response.json() if response.content else None
        return Answer(response.status_code, payload, response.headers)

    def call(
        self,
        method: str,
        path: str,
        person: Person,
        *,
        expect: int | tuple[int, ...] = 200,
        **kwargs: Any,
    ) -> Any:
        answer = self.request(method, path, person, **kwargs)
        expected = (expect,) if isinstance(expect, int) else expect
        if answer.status not in expected:
            raise SeedError(
                f"{method} {path} as {person.key}: {answer.status} {str(answer.body)[:600]}"
            )
        return answer.body

    def sign_in(self, person: Person) -> dict[str, Any]:
        """The web's first call after sign-in: links an invitation to the person."""
        signed: dict[str, Any] = self.call("GET", "/auth/bootstrap", person)
        return signed


def wait_until_ready(http: httpx.Client, base_url: str, *, seconds: float = 120) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            if http.get(f"{base_url}{PREFIX}/health").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            raise SeedError(f"the API at {base_url} is not ready after {seconds:.0f}s")
        time.sleep(0.5)
