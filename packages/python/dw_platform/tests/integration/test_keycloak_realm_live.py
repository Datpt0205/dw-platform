"""The running realm does what `dw-realm.json` says (org-and-principals R3.1-R3.3).

The unit test reads the file; this asks Keycloak. A realm imported before the
change keeps its old values (`--import-realm` writes into an empty database
only, ADR-0009), and only a probe of the running server sees that.

`dw-web` takes no password directly, and the seeded users have none, so the
probe creates its own public client with direct grants and its own user through
the admin API, and deletes both. Neither is ever in the realm file
(`test_keycloak_realm.py` refuses a direct-grant client there).

Keycloak is the compose one (`DW_TEST_KEYCLOAK_URL`, else the host port compose
publishes). Locally an absent Keycloak skips; in CI it fails, so a broken
service cannot pass as a probe that ran.
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
import pytest
from pg_test_db import load_env

pytestmark = pytest.mark.integration

REALM = "dw"


@dataclass(frozen=True)
class Probe:
    http: httpx.Client
    admin: httpx.Client
    client_id: str
    user_id: str
    username: str
    password: str

    def login(self, password: str | None = None) -> httpx.Response:
        return self.http.post(
            f"/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": self.client_id,
                "username": self.username,
                "password": password or self.password,
            },
        )

    def refresh(self, refresh_token: str) -> httpx.Response:
        return self.http.post(
            f"/realms/{REALM}/protocol/openid-connect/token",
            data={
                "grant_type": "refresh_token",
                "client_id": self.client_id,
                "refresh_token": refresh_token,
            },
        )


def _base_url(env: dict[str, str]) -> str:
    if url := env.get("DW_TEST_KEYCLOAK_URL"):
        return url.rstrip("/")
    return f"http://localhost:{env.get('DW_KEYCLOAK_HOST_PORT', '8686')}"


@pytest.fixture(scope="module")
def probe() -> Iterator[Probe]:
    env = load_env()
    base = _base_url(env)
    http = httpx.Client(base_url=base, timeout=30)
    try:
        http.get(f"/realms/{REALM}/.well-known/openid-configuration").raise_for_status()
    except httpx.HTTPError as exc:
        http.close()
        if os.environ.get("CI"):
            raise
        pytest.skip(f"Keycloak realm {REALM} not reachable at {base}: {exc}")

    token = http.post(
        "/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": os.environ.get("KEYCLOAK_ADMIN") or env["KEYCLOAK_ADMIN"],
            "password": os.environ.get("KEYCLOAK_ADMIN_PASSWORD") or env["KEYCLOAK_ADMIN_PASSWORD"],
        },
    )
    token.raise_for_status()
    admin = httpx.Client(
        base_url=f"{base}/admin/realms/{REALM}",
        timeout=30,
        headers={"Authorization": f"Bearer {token.json()['access_token']}"},
    )
    suffix = secrets.token_hex(4)
    client_id = f"dw-probe-{suffix}"
    username = f"probe-{suffix}"
    password = secrets.token_urlsafe(18)
    created_client = admin.post(
        "/clients",
        json={
            "clientId": client_id,
            "publicClient": True,
            "directAccessGrantsEnabled": True,
            "standardFlowEnabled": False,
        },
    )
    created_client.raise_for_status()
    client_uuid = created_client.headers["Location"].rsplit("/", 1)[-1]
    user_id = ""
    try:
        created_user = admin.post(
            "/users",
            json={
                "username": username,
                "email": f"{username}@probe.invalid",
                "firstName": "Probe",
                "lastName": "Realm",
                "enabled": True,
                "emailVerified": True,
                "credentials": [{"type": "password", "value": password, "temporary": False}],
            },
        )
        created_user.raise_for_status()
        user_id = created_user.headers["Location"].rsplit("/", 1)[-1]
        yield Probe(http, admin, client_id, user_id, username, password)
    finally:
        if user_id:
            admin.delete(f"/attack-detection/brute-force/users/{user_id}")
            admin.delete(f"/users/{user_id}")
        admin.delete(f"/clients/{client_uuid}")
        admin.close()
        http.close()


def _claims(jwt: str) -> dict[str, int]:
    payload = jwt.split(".")[1]
    claims: dict[str, int] = json.loads(
        base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
    )
    return claims


def test_an_access_token_lives_five_minutes(probe: Probe) -> None:
    response = probe.login()
    assert response.status_code == 200, response.text
    claims = _claims(response.json()["access_token"])
    assert claims["exp"] - claims["iat"] == 300


def test_a_refresh_token_is_used_once(probe: Probe) -> None:
    first = probe.login()
    assert first.status_code == 200, first.text
    refresh_token = first.json()["refresh_token"]
    assert probe.refresh(refresh_token).status_code == 200
    replayed = probe.refresh(refresh_token)
    assert replayed.status_code == 400
    assert replayed.json()["error"] == "invalid_grant"


def _wrong(probe: Probe, times: int) -> None:
    for _ in range(times):
        # Past quickLoginCheckMilliSeconds, so the count, not the burst rule, decides.
        time.sleep(1.2)
        # Keycloak 26.7 answers a wrong password with 400 `invalid_grant`, measured.
        assert probe.login("not-the-password").json()["error"] == "invalid_grant"


def test_ten_wrong_passwords_in_a_row_lock_the_account(probe: Probe) -> None:
    _wrong(probe, 9)
    time.sleep(1.2)
    assert probe.login().status_code == 200, "nine failures must not lock"
    _wrong(probe, 10)
    time.sleep(1.2)
    refused = probe.login()
    assert refused.status_code == 400, refused.text
    assert refused.json()["error"] == "invalid_grant"
