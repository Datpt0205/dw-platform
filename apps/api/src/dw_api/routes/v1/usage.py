"""The company's usage summary (usage-and-limits R3.5, R3.12).

`platform.usage.read` is checked by `UsageReads.summary` before anything is
read; without it the answer is 403 and no row of `platform.usage_daily` is
touched. The key is held at company depth only, so the summary is the whole
company's, the calls of no workspace grouped as the company-level group.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Query

from dw_api.dependencies.auth import RequireAccessContext
from dw_api.dependencies.services import RequireContainer
from dw_kernel.errors import InfrastructureError
from dw_usage.presentation.views import UsageSummaryView, usage_summary_view

router = APIRouter(prefix="/usage", tags=["usage"])


@router.get("/summary", response_model=UsageSummaryView)
async def get_usage_summary(
    context: RequireAccessContext,
    container: RequireContainer,
    group_by: Literal["workspace", "artifact", "purpose"] = "workspace",
    first_day: Annotated[date | None, Query(alias="from")] = None,
    last_day: Annotated[date | None, Query(alias="to")] = None,
    workspace_id: uuid.UUID | None = None,
    artifact_kind: Literal["agent", "workflow"] | None = None,
    artifact_id: uuid.UUID | None = None,
) -> UsageSummaryView:
    """Totals over `[from, to]`, days cut in the company's time zone (the
    current month when neither is given, at most 400 days), grouped by
    workspace, agent or workflow, or purpose; never by person in W1 (DO-51.2)."""
    if container.usage is None:
        raise InfrastructureError("database is not configured")
    summary = await container.usage.summary(
        context,
        group_by=group_by,
        first_day=first_day,
        last_day=last_day,
        workspace_id=workspace_id,
        artifact_kind=artifact_kind,
        artifact_id=artifact_id,
    )
    return usage_summary_view(summary)
