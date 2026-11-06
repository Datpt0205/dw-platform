"""`RecordObjectData`: the runtime's `ObjectDataPort` and `ObjectFieldsPort`
over `RecordService` (tools-and-skills ticket 03; R6.2, R6.4, R6.6, R6.7).

An agent's object tool is one more door to the one service, beside the REST
routes and a workflow step: ``door`` makes each call's `RecordDoor` from the
run (the composition root hands `agent_record_session`, which binds the run's
company, principal, the actor `agent` within the run's data boundary and the
reach row, per transaction), so who may read what is asked again at every
call and decided by the record policies and the field decision, never here.

What a tool returns is a record as the records API shows it
(`views.record_out`, the one owner of that shape) less `permissions` and
`hidden_fields` (field-security R4.2): a hidden field is absent, its name too.
Only the fields of the object version the run pinned come back, asked of the
service as the list's `fields`, so a field published after the pin never
reaches the model. A record the actor cannot see, another company's or none
at all is RecordService's one `not_found` (R5.7). A refused query keeps its
reason codes (`field_not_readable` for a hidden or soft-deleted field, R6.7)
and never a value.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.ports import ObjectSearch
from dw_kernel.errors import DomainError
from dw_kernel.filters import ID_FIELD, ListQuery, QueryError, QuerySchema, parse_query
from dw_studio.records.application.record_service import RecordDoor, RecordService
from dw_studio.records.application.record_views import RecordView
from dw_studio.records.presentation.views import record_out

# What a tool's record leaves out of the records API's (field-security R4.2).
_LEFT_OUT: Final = frozenset({"permissions", "hidden_fields"})


def tool_record(view: RecordView, fields: frozenset[str] | None = None) -> dict[str, Any]:
    """``view`` as an object tool returns it; with ``fields``, only those of
    its values (`get`, which RecordService answers with every readable one).
    A search page is cut by RecordService itself, from the list's `fields`."""
    shown = record_out(view).model_dump(mode="json", exclude=set(_LEFT_OUT))
    if fields is not None:
        shown["fields"] = {k: v for k, v in shown["fields"].items() if k in fields}
    return shown


def _refused(error: QueryError) -> DomainError:
    codes = sorted({problem.code.value for problem in error.problems})
    return DomainError(
        f"the search was refused: {', '.join(codes)}",
        details={"reason_codes": codes},
    )


@dataclass(frozen=True)
class RecordObjectData:
    """``door`` opens one call's transactions as the run's actor."""

    records: RecordService
    door: Callable[[RunContext], RecordDoor]

    async def search(
        self, run: RunContext, api_name: str, request: ObjectSearch
    ) -> Mapping[str, Any]:
        def parse(schema: QuerySchema) -> ListQuery:
            # The pinned fields this caller reads now; `id` alone when none,
            # since no `fields` would be every field, a later one included.
            chosen = sorted(name for name in request.fields if schema.get(name) is not None)
            return parse_query(
                schema,
                route=f"/agent/objects/{api_name}/search",
                tenant=run.tenant_id,
                workspace=run.workspace_id,
                filter=request.filter,
                order_by=request.order_by,
                fields=",".join(chosen) or ID_FIELD,
                cursor=request.cursor,
                limit=request.limit,
            )

        try:
            page = await self.records.query(self.door(run), api_name, parse)
        except QueryError as exc:
            raise _refused(exc) from None
        return {
            "next_cursor": page.next_cursor,
            "items": [tool_record(view) for view in page.items],
        }

    async def get(
        self, run: RunContext, api_name: str, record_id: uuid.UUID, fields: frozenset[str]
    ) -> Mapping[str, Any]:
        view = await self.records.get(self.door(run), api_name, record_id)
        return tool_record(view, fields)

    async def readable(self, run: RunContext, api_name: str) -> frozenset[str]:
        return await self.records.readable(self.door(run), api_name)
