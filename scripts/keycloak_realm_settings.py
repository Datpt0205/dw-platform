"""Bring an existing realm's session and lockout settings in line with `dw-realm.json`.

Usage (reads `.env`; in a plain shell run `set -a; source .env; set +a` first):
    uv run python scripts/keycloak_realm_settings.py --check   # report, exit 1 on drift
    uv run python scripts/keycloak_realm_settings.py           # apply

`--import-realm` imports only into an empty Keycloak database (ADR-0009), so a
realm created before a change to these settings keeps its old values while the
file, and every test that reads it, says otherwise. This script is the by-hand
edit ADR-0009 asks for, done as one command: it reads the values of SETTINGS
from the file, the one owner, and writes only those keys to the running realm.
Nothing else in the realm (clients, flows, users) is touched.

On a deployed host the public hostname does not serve `/admin` (Caddy answers
404 there, ADR-0009), so run it on the host against the port compose publishes
on the loopback:
    export DW_KEYCLOAK_ADMIN_URL=http://127.0.0.1:${DW_KEYCLOAK_HOST_PORT:-8686}
    uv run python scripts/keycloak_realm_settings.py --check
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

REALM_FILE = Path(__file__).resolve().parents[1] / "infra/keycloak/dw-realm.json"

# org-and-principals R3.1-R3.3: how long a token and a session live, refresh-token
# rotation, and lockout after repeated wrong passwords.
SETTINGS = (
    "accessTokenLifespan",
    "ssoSessionIdleTimeout",
    "ssoSessionMaxLifespan",
    "revokeRefreshToken",
    "refreshTokenMaxReuse",
    "bruteForceProtected",
    "permanentLockout",
    "failureFactor",
    "waitIncrementSeconds",
    "maxFailureWaitSeconds",
    "maxDeltaTimeSeconds",
    "quickLoginCheckMilliSeconds",
    "minimumQuickLoginWaitSeconds",
)


def wanted() -> tuple[str, dict[str, object]]:
    realm = json.loads(REALM_FILE.read_text(encoding="utf-8"))
    missing = [key for key in SETTINGS if key not in realm]
    if missing:
        sys.exit(f"{REALM_FILE.name} does not set {', '.join(missing)}")
    return realm["realm"], {key: realm[key] for key in SETTINGS}


def _env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        sys.exit(f"{name} is not set (source .env)")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="report drift, change nothing")
    args = parser.parse_args()
    name, values = wanted()
    base = (os.environ.get("DW_KEYCLOAK_ADMIN_URL") or _env("NEXT_PUBLIC_KEYCLOAK_URL")).rstrip("/")

    with httpx.Client(base_url=base, timeout=30) as client:
        token = client.post(
            "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": _env("KEYCLOAK_ADMIN"),
                "password": _env("KEYCLOAK_ADMIN_PASSWORD"),
            },
        )
        token.raise_for_status()
        client.headers["Authorization"] = f"Bearer {token.json()['access_token']}"
        response = client.get(f"/admin/realms/{name}")
        response.raise_for_status()
        current = response.json()
        drift = {k: (current.get(k), v) for k, v in values.items() if current.get(k) != v}
        for key, (now, want) in drift.items():
            print(f"{key}: {now} -> {want}")
        if args.check:
            sys.exit(1 if drift else 0)
        if drift:
            changes = {k: values[k] for k in drift}
            client.put(f"/admin/realms/{name}", json=changes).raise_for_status()
            after = client.get(f"/admin/realms/{name}").json()
            still = [k for k in drift if after.get(k) != values[k]]
            if still:
                sys.exit(f"Keycloak did not take {', '.join(still)}")
        print(f"realm {name}: {len(drift)} setting(s) changed")


if __name__ == "__main__":
    main()
