"""What `demo_dw_seed` and `demo_dw_run` share: a person, the API as one of them, the error.

A person signs in with the dev issuer (``DW_API_DEV_SECRET``, the ``local``
profile only): a token naming their subject and their invited email, which is
what an IdP asserting a verified address does. Every write carries a fresh
``Idempotency-Key``, as the web sends one.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

import httpx

from dw_platform.adapters.identity.dev_token import DevTokenVerifier


class DemoError(RuntimeError):
    """A step of the demo did not go as the platform promises."""


@dataclass(frozen=True)
class Person:
    role: str
    subject: str
    email: str
    display_name: str
    role_keys: tuple[str, ...] = ()


@dataclass
class Api:
    base_url: str
    tokens: DevTokenVerifier
    http: httpx.Client

    def call(
        self,
        method: str,
        path: str,
        person: Person,
        *,
        scope: tuple[str, str] | None = None,
        body: dict[str, Any] | None = None,
        expect: int = 200,
    ) -> Any:
        token = self.tokens.issue(person.subject, email=person.email)
        headers = {"Authorization": f"Bearer {token}"}
        if scope is not None:
            headers["X-Tenant-Id"], headers["X-Workspace-Id"] = scope
        if method != "GET":
            headers["Idempotency-Key"] = str(uuid.uuid4())
        response = self.http.request(
            method, f"{self.base_url}/api/v1{path}", headers=headers, json=body
        )
        if response.status_code != expect:
            raise DemoError(
                f"{method} {path} as {person.role}: {response.status_code} {response.text[:500]}"
            )
        return response.json() if response.content else None

    def sign_in(self, person: Person) -> dict[str, Any]:
        """The web's first call after sign-in: creates or links the person."""
        signed: dict[str, Any] = self.call("GET", "/auth/bootstrap", person)
        return signed


def wait_until_up(http: httpx.Client, base_url: str, *, seconds: float = 120) -> None:
    deadline = time.monotonic() + seconds
    while True:
        try:
            if http.get(f"{base_url}/api/v1/ready").status_code == 200:
                return
        except httpx.HTTPError:
            pass
        if time.monotonic() > deadline:
            raise DemoError(f"the API at {base_url} is not ready after {seconds:.0f}s")
        time.sleep(2)
