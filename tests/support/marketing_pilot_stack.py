"""A fresh platform for the marketing pilot's seed (marketing-pilot ticket 02):
a new database, migrated, the API and the worker as their own processes on
the host, and the first platform operator, the one step no API can do.

Here and not in `tests/e2e/marketing_pilot`: provisioning a platform is not the
harness's business, and the harness imports no `dw_*` module and opens no
database (MP17, `marketing_pilot_independence`). Nothing here imports `dw_*`
either: the processes are `uvicorn dw_api.main:app` and `python -m
dw_worker.main`, and the operator is granted by the documented bootstrap,
`scripts/grant_platform_operator.py`, run as written, as `make demo-dw` does.

The database is new on every run (`dw_e2e_marketing_pilot` plus
`DW_TEST_DB_SUFFIX`), so a half-seeded company of a failed run is gone with it,
as a fresh compose project's volumes are for `make demo-dw`. The API listens on
loopback, on `MP_API_PORT` (8010 by default; 8000, 3000 and the `si-*`
project's ports are another project's).
"""

from __future__ import annotations

import asyncio
import os
import secrets
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import IO

import httpx
from pg_test_db import (
    REPO_ROOT,
    database_urls,
    ensure_provisioner,
    load_env,
    provisioner_url,
    recreate_database,
    run_migrations,
)

DB_NAME = "dw_e2e_marketing_pilot"
READY_SECONDS = 120


@dataclass(frozen=True)
class Stack:
    api_url: str
    secret: str
    migrator_url: str
    logs: Path


def _environment(app_url: str, migrator_url: str, secret: str, port: int) -> dict[str, str]:
    env = {**os.environ, **load_env()}
    # Nothing of the developer's own stack: no cache, no OIDC, no real model.
    for name in ("REDIS_URL", "DW_API_REDIS_URL", "DW_API_OIDC_ISSUER_URL", "OIDC_ISSUER_URL"):
        env.pop(name, None)
    env.update(
        {
            "DW_API_PROFILE": "test",
            "DW_WORKER_PROFILE": "test",
            "DW_API_AUTH_MODE": "dev",
            "DW_API_DEV_SECRET": secret,
            "DW_API_PORT": str(port),
            "DW_API_DATABASE_URL": app_url,
            "DW_WORKER_DATABASE_URL": app_url,
            "DW_CHAT_DATABASE_URL": app_url,
            "DW_PROVISIONER_DATABASE_URL": provisioner_url(migrator_url),
            "DW_DATABASE_URL": migrator_url,
            "DW_MODEL_PROVIDER": "mock",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return env


def _start(command: list[str], env: dict[str, str], log: IO[str]) -> subprocess.Popen[str]:
    return subprocess.Popen(
        command, cwd=REPO_ROOT, env=env, stdout=log, stderr=subprocess.STDOUT, text=True
    )


def _wait_ready(api_url: str, process: subprocess.Popen[str], log: Path) -> None:
    deadline = time.monotonic() + READY_SECONDS
    with httpx.Client(timeout=5) as http:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(f"the API exited: see {log}")
            try:
                # Live, not `ready`: readiness also asks the data plane (Qdrant,
                # the S3 store), which the seed never reaches.
                if http.get(f"{api_url}/api/v1/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(0.5)
    raise RuntimeError(f"the API is not ready after {READY_SECONDS}s: see {log}")


def grant_operator(stack: Stack, email: str) -> None:
    """The documented first-operator bootstrap, for a person who signed in."""
    done = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "grant_platform_operator.py"),
            "--email",
            email,
        ],
        cwd=REPO_ROOT,
        env={**os.environ, "DW_DATABASE_URL": stack.migrator_url},
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise RuntimeError(f"grant_platform_operator: {done.stderr or done.stdout}")


@contextmanager
def running_stack(logs: Path) -> Iterator[Stack]:
    urls = database_urls(DB_NAME)
    asyncio.run(recreate_database(urls.admin, DB_NAME))
    asyncio.run(ensure_provisioner(urls.admin))
    migrated = run_migrations(urls.migrator)
    if migrated.returncode != 0:
        raise RuntimeError(f"migrations failed:\n{migrated.stdout}\n{migrated.stderr}")
    port = int(os.environ.get("MP_API_PORT", "8010"))
    secret = secrets.token_hex(32)
    env = _environment(urls.app, urls.migrator, secret, port)
    logs.mkdir(parents=True, exist_ok=True)
    api_log, worker_log = logs / "api.log", logs / "worker.log"
    with api_log.open("w", encoding="utf-8") as a, worker_log.open("w", encoding="utf-8") as w:
        api = _start(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "dw_api.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            env,
            a,
        )
        worker = _start([sys.executable, "-m", "dw_worker.main"], env, w)
        try:
            api_url = f"http://127.0.0.1:{port}"
            _wait_ready(api_url, api, api_log)
            yield Stack(api_url, secret, urls.migrator, logs)
        finally:
            for process in (api, worker):
                process.terminate()
            for process in (api, worker):
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
