"""The compose `migrate` job loads the retention terms before `api` and `worker` start
(telemetry-and-audit R5.9, TA17).

Read from the compose file itself, because a deploy runs that file: a loader
that only the test fixture called would leave every real deployment with an
empty `platform.retention_terms`, and every narrow purge function stopping on
P0002.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[5]
COMPOSE = REPO_ROOT / "infra" / "compose" / "docker-compose.yml"
LOADER = "python -m dw_platform.adapters.persistence.retention_terms"


def _services() -> dict[str, Any]:
    services: dict[str, Any] = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]
    return services


def migrate_job_violations(services: dict[str, Any]) -> list[str]:
    found = []
    migrate = services.get("migrate", {})
    command = migrate.get("command", [])
    script = " ".join(command) if isinstance(command, list) else str(command)
    steps = [step.strip() for step in re.split(r"&&", script)]
    upgrade = next(
        (i for i, step in enumerate(steps) if "alembic" in step and "upgrade head" in step), None
    )
    load = next((i for i, step in enumerate(steps) if LOADER in step), None)
    if upgrade is None or load is None or load != upgrade + 1:
        found.append("migrate does not run the terms loader right after alembic upgrade head")
    if ";" in script or "||" in script:
        found.append("migrate's command can continue past a failed step")
    url = migrate.get("environment", {}).get("DW_PROVISIONER_DATABASE_URL", "")
    if "dw_provisioner:" not in url:
        found.append("migrate does not hand the loader a dw_provisioner URL")
    for name in ("api", "worker"):
        condition = services.get(name, {}).get("depends_on", {}).get("migrate", {})
        if condition.get("condition") != "service_completed_successfully":
            found.append(f"{name} does not wait for migrate to succeed")
    return found


def test_the_migrate_job_loads_the_terms_before_the_apps_start() -> None:
    assert migrate_job_violations(_services()) == []


@pytest.mark.parametrize(
    ("break_it", "expected"),
    [
        (
            lambda s: s["migrate"].update(command=["alembic", "-c", "x", "upgrade", "head"]),
            "migrate does not run the terms loader right after alembic upgrade head",
        ),
        (
            lambda s: s["migrate"].update(
                command=["sh", "-c", f"{LOADER} && alembic -c x upgrade head"]
            ),
            "migrate does not run the terms loader right after alembic upgrade head",
        ),
        (
            lambda s: s["migrate"].update(
                command=["sh", "-c", f"alembic -c x upgrade head; {LOADER}"]
            ),
            "migrate does not run the terms loader right after alembic upgrade head",
        ),
        (
            lambda s: s["migrate"]["environment"].pop("DW_PROVISIONER_DATABASE_URL"),
            "migrate does not hand the loader a dw_provisioner URL",
        ),
        (
            lambda s: s["api"]["depends_on"].pop("migrate"),
            "api does not wait for migrate to succeed",
        ),
        (
            lambda s: s["worker"]["depends_on"]["migrate"].update(condition="service_started"),
            "worker does not wait for migrate to succeed",
        ),
    ],
    ids=["no loader", "loader first", "semicolon", "no provisioner url", "api", "worker"],
)
def test_each_way_the_job_can_go_wrong_is_named(break_it: Any, expected: str) -> None:
    services = _services()
    break_it(services)
    assert expected in migrate_job_violations(services)
