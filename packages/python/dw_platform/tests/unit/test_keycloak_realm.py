"""The realm file carries the session and lockout values org-and-principals R3 decided.

ADR-0103 (Accepted) decision 9: an access token lives five minutes, a session
idles out after thirty and ends after ten hours, a refresh token is used once,
and repeated wrong passwords lock the account. Revocation waited up to eight
hours while the token lived 28 800 seconds. The live behaviour is probed by
`tests/integration/test_keycloak_realm_live.py`; an existing realm is brought in
line by `scripts/keycloak_realm_settings.py`, whose key list is checked here.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[5]
_REALM = _REPO / "infra/keycloak/dw-realm.json"

EXPECTED: dict[str, Any] = {
    "accessTokenLifespan": 300,
    "ssoSessionIdleTimeout": 1800,
    "ssoSessionMaxLifespan": 36000,
    "revokeRefreshToken": True,
    "refreshTokenMaxReuse": 0,
    "bruteForceProtected": True,
    "permanentLockout": False,
    "failureFactor": 10,
    "waitIncrementSeconds": 60,
    "maxFailureWaitSeconds": 900,
    # Keycloak's own defaults, written down so "consecutive" has a stated window
    # (failures count within 12 hours) and a burst inside one second locks at once.
    "maxDeltaTimeSeconds": 43200,
    "quickLoginCheckMilliSeconds": 1000,
    "minimumQuickLoginWaitSeconds": 60,
}


def _realm() -> dict[str, Any]:
    realm: dict[str, Any] = json.loads(_REALM.read_text(encoding="utf-8"))
    return realm


@pytest.mark.parametrize(("key", "value"), sorted(EXPECTED.items()))
def test_the_realm_sets(key: str, value: object) -> None:
    assert _realm().get(key) == value


def test_no_client_takes_a_password_directly() -> None:
    # A direct grant skips the "dw browser" flow, and with it the support staff's
    # mandatory OTP (ADR-0024); the live probe makes its own client and deletes it.
    direct = [c["clientId"] for c in _realm()["clients"] if c.get("directAccessGrantsEnabled")]
    assert direct == []


def test_the_sync_script_writes_every_decided_key() -> None:
    spec = importlib.util.spec_from_file_location(
        "keycloak_realm_settings", _REPO / "scripts/keycloak_realm_settings.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert set(module.SETTINGS) == set(EXPECTED)
    assert module.wanted()[1] == EXPECTED
