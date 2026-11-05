"""The company's limits (usage-and-limits R4.5, R4.6, R4.8, R4.9, R4.14, R4.15).

`GET /limits` (`platform.usage.read`): every limit with its effective number,
the current period's counter and when it resets. `PUT` and `DELETE` of one
policy at `/limits/{scope_type}/{scope_id}/{metric}/{window_kind}`
(`platform.limits.manage`, `Idempotency-Key`): the company is always the
caller's, a `tenant` scope id that is not is 404, never read from the path;
`If-Match` carries the policy's `version` once it exists (428 without, 412
stale). Lowering or setting a limit applies at once with one person; raising or
removing one is 409 `second_person_required` in W1; above the plan's cap is 422
`limit_above_plan`. Every rule is `LimitPolicyService`'s and its store's.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Response
from pydantic import BaseModel, ConfigDict, Field

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.idempotency import IdempotentOperation, idempotent
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_kernel.http_conditions import ExpectedVersion, etag_of, parse_if_match
from dw_usage.application.limits import LIMITS_MANAGE, LimitPolicyService
from dw_usage.presentation.views import (
    LimitLineView,
    LimitPolicyView,
    limit_line_view,
    limit_policy_view,
)

router = APIRouter(prefix="/limits", tags=["limits"])

_PATH = "/{scope_type}/{scope_id}/{metric}/{window_kind}"

PutIdempotency = Annotated[
    IdempotentOperation, idempotent(LIMITS_MANAGE, operation=f"PUT /limits{_PATH}")
]
DeleteIdempotency = Annotated[
    IdempotentOperation, idempotent(LIMITS_MANAGE, operation=f"DELETE /limits{_PATH}")
]


# A list, so a repeated header reaches the parser instead of FastAPI keeping one.
_IF_MATCH_HEADER = Header(
    default=None,
    alias="If-Match",
    description=(
        'The version of the policy as a strong ETag, for example "3": required once the'
        " policy exists (428 without it, 412 when stale); absent to set a new one."
    ),
)


async def _if_match(if_match: list[str] | None = _IF_MATCH_HEADER) -> ExpectedVersion | None:
    return None if not if_match else parse_if_match(if_match)


IfMatchOnce = Annotated[ExpectedVersion | None, Depends(_if_match)]


class LimitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit_value: Decimal = Field(description="USD for `cost_usd`, a count otherwise; >= 0.")
    kind: str = Field(description="`hard`, the only kind of W1 (`soft` comes in W2).")


def _service(container: Any) -> LimitPolicyService:
    service: LimitPolicyService | None = container.limits
    if service is None:
        raise InfrastructureError("database is not configured")
    return service


@router.get("", response_model=list[LimitLineView])
async def list_limits(
    context: RequireAccessContext, container: RequireContainer
) -> list[LimitLineView]:
    """Every limit of the company: the plan's caps at the company and every
    policy, each with its effective limit and the current period's counter."""
    return [limit_line_view(line) for line in await _service(container).lines(context)]


@router.put(_PATH, response_model=LimitPolicyView)
async def put_limit(
    scope_type: str,
    scope_id: uuid.UUID,
    metric: str,
    window_kind: str,
    body: LimitBody,
    context: RequireAccessContext,
    container: RequireContainer,
    response: Response,
    idempotency: PutIdempotency,
    expected: IfMatchOnce,
) -> LimitPolicyView:
    """Set a new limit or lower one, at once and audited (`limits.policy.set`)."""
    await idempotency.start()
    written = await _service(container).put(
        context,
        scope_type=scope_type,
        scope_id=scope_id,
        metric=metric,
        window_kind=window_kind,
        limit_value=body.limit_value,
        kind=body.kind,
        expected=expected,
    )
    view = limit_policy_view(written)
    response.headers["ETag"] = etag_of(view.version)
    return await idempotency.record(view, headers={"ETag": etag_of(view.version)})


@router.delete(_PATH, status_code=204)
async def delete_limit(
    scope_type: str,
    scope_id: uuid.UUID,
    metric: str,
    window_kind: str,
    context: RequireAccessContext,
    container: RequireContainer,
    idempotency: DeleteIdempotency,
    expected: IfMatchOnce,
) -> None:
    """Removing a limit loosens it: 409 `second_person_required` in W1, once
    the policy and its `If-Match` are checked; nothing is changed."""
    await idempotency.start()
    await _service(container).delete(
        context,
        scope_type=scope_type,
        scope_id=scope_id,
        metric=metric,
        window_kind=window_kind,
        expected=expected,
    )
    await idempotency.record_no_content()
