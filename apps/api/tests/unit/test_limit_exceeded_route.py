"""A route that is no Studio run and meets a spent limit answers 429
(usage-and-limits R6.2; ADR-0121 decision 6; gate 4/11/2026 (a)).

The workflow assistant is today's one such route that reaches a model (its
call is a builder's assistance, an operation outside any run): a spent month is
429 problem+json with `limit_exceeded` and `Retry-After` up to the period's
reset; a run's own ceiling, which resets by nothing, sends no `Retry-After`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from test_digital_workers_endpoint import (
    AssistantGateway,
    FakeRepo,
    call,
    lead_care,
    make_container,
)

from dw_kernel.limits import LimitExceededError

pytestmark = pytest.mark.unit


async def _ask(refusal: LimitExceededError) -> tuple[int, dict[str, str], dict[str, object]]:
    repo = FakeRepo()
    dw_id = (await call(make_container(repo), "POST", payload=lead_care())).json()["id"]
    gateway = AssistantGateway(refusal)
    answered = await call(
        make_container(repo, gateway=gateway),
        "POST",
        f"/{dw_id}/workflow-assistant",
        {"instruction": "Thêm một lần chờ"},
    )
    assert gateway.calls == 1
    return answered.status_code, dict(answered.headers), answered.json()


async def test_a_spent_month_is_429_limit_exceeded_with_retry_after_its_reset() -> None:
    resets_at = datetime.now(UTC) + timedelta(hours=2)
    status, headers, problem = await _ask(
        LimitExceededError(
            "Đã dùng hết hạn mức của kỳ này",
            metric="cost_usd",
            scope_type="tenant",
            window="month",
            resets_at=resets_at,
        )
    )

    assert status == 429
    assert headers["content-type"].startswith("application/problem+json")
    details = problem["details"]
    assert isinstance(details, dict)
    assert (details["reason_code"], details["metric"]) == ("limit_exceeded", "cost_usd")
    assert details["resets_at"] == resets_at.isoformat()
    wait = int(headers["retry-after"])
    assert 7100 <= wait <= 7200


async def test_a_limit_that_resets_by_nothing_sends_no_retry_after() -> None:
    status, headers, problem = await _ask(
        LimitExceededError("ceiling", metric="cost_usd", scope_type="run")
    )

    assert status == 429
    assert "retry-after" not in headers
    details = problem["details"]
    assert isinstance(details, dict) and details["reason_code"] == "limit_exceeded"
