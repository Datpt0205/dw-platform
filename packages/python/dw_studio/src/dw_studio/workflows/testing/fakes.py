"""`FakeRecordsPort` and `FakeRecordAssignPort`: the two record doors of a
Studio step in memory, honouring the contracts their Protocols state
(workflow-engine/03 step 12; H-7, V4.31), which `records_port_contract` checks
against them here and against `RecordService` and `AssignRecordService` in
workflow-nodes/04.

Both take the wrapper's key; write nothing in `simulate`; replay a key with
the first answer and `replayed` true; and refuse a key another principal used
(`IdempotencyConflictError`). A test makes them fail on purpose:
`fail_before` raises before anything is applied, `fail_after_apply` applies
and then raises, as a crash between the door's commit and its answer would
(K3/K4 of discovery/14's matrix).
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Any

from dw_agent_runtime.contracts import RunContext
from dw_kernel.errors import IdempotencyConflictError, NotFoundError
from dw_kernel.run_mode import RunMode
from dw_studio.workflows.application.ports import AssignAnswer, RecordAnswer, RecordRequest


def principal_of(run: RunContext) -> uuid.UUID:
    return run.run_as_principal_id or run.requested_by or run.actor_id


def _conflict() -> IdempotencyConflictError:
    return IdempotencyConflictError(
        "this key was used by another principal",
        details={"reason_code": "idempotency_conflict"},
    )


@dataclass
class FakeRecordsPort:
    records: dict[uuid.UUID, dict[str, Any]] = field(default_factory=dict)
    versions: dict[uuid.UUID, int] = field(default_factory=dict)
    keys: dict[str, tuple[uuid.UUID, RecordAnswer]] = field(default_factory=dict)
    calls: list[tuple[RecordRequest, str, RunMode]] = field(default_factory=list)
    applied: int = 0
    fail_before: int = 0
    fail_after_apply: int = 0

    def plant(self, values: dict[str, Any] | None = None) -> uuid.UUID:
        record_id = uuid.uuid4()
        self.records[record_id] = dict(values or {})
        self.versions[record_id] = 1
        return record_id

    def _answer(self, record_id: uuid.UUID, *, created: bool) -> RecordAnswer:
        return RecordAnswer(
            record={"id": str(record_id), **self.records[record_id]},
            created=created,
            version=self.versions[record_id],
        )

    async def run(
        self, run: RunContext, request: RecordRequest, *, write_key: str, run_mode: RunMode
    ) -> RecordAnswer:
        self.calls.append((request, write_key, run_mode))
        if self.fail_before:
            self.fail_before -= 1
            raise RuntimeError("the record store did not answer")
        if request.command == "read":
            if request.record_id not in self.records:
                raise NotFoundError("record not found")
            return self._answer(request.record_id, created=False)
        if run_mode != "live":
            # Simulated at the door (custom-objects R5.4): nothing is kept.
            found = self.records.get(request.record_id or uuid.uuid4(), {})
            return RecordAnswer(
                record={"id": str(request.record_id or uuid.uuid4()), **found, **request.values},
                created=request.command == "create",
                version=1,
            )
        held = self.keys.get(write_key)
        principal = principal_of(run)
        if held is not None:
            if held[0] != principal:
                raise _conflict()
            return replace(held[1], replayed=True)
        answer = self._apply(request)
        self.applied += 1
        self.keys[write_key] = (principal, answer)
        if self.fail_after_apply:
            self.fail_after_apply -= 1
            raise RuntimeError("the answer was lost after the write")
        return answer

    def _apply(self, request: RecordRequest) -> RecordAnswer:
        if request.command == "create":
            record_id = self.plant(dict(request.values))
            return self._answer(record_id, created=True)
        if request.record_id not in self.records:
            raise NotFoundError("record not found")
        record_id = request.record_id
        if request.command == "update":
            self.records[record_id].update(request.values)
        else:
            self.records[record_id]["deleted"] = True
        self.versions[record_id] += 1
        return self._answer(record_id, created=False)


@dataclass
class FakeRecordAssignPort:
    """Assigns each record to the next person of `rotation`, in turn."""

    rotation: Sequence[uuid.UUID] = field(default_factory=lambda: [uuid.uuid4(), uuid.uuid4()])
    owners: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)
    keys: dict[str, tuple[uuid.UUID, AssignAnswer]] = field(default_factory=dict)
    calls: list[tuple[uuid.UUID, str, RunMode]] = field(default_factory=list)
    turn: int = 0
    fail_before: int = 0
    fail_after_apply: int = 0

    async def assign(
        self,
        run: RunContext,
        api_name: str,
        record_id: uuid.UUID,
        *,
        write_key: str,
        run_mode: RunMode,
    ) -> AssignAnswer:
        self.calls.append((record_id, write_key, run_mode))
        if self.fail_before:
            self.fail_before -= 1
            raise RuntimeError("the assignment store did not answer")
        nxt = self.rotation[self.turn % len(self.rotation)]
        if run_mode != "live":
            return AssignAnswer(nxt)
        held = self.keys.get(write_key)
        principal = principal_of(run)
        if held is not None:
            if held[0] != principal:
                raise _conflict()
            return replace(held[1], replayed=True)
        self.turn += 1
        self.owners[record_id] = nxt
        answer = AssignAnswer(nxt)
        self.keys[write_key] = (principal, answer)
        if self.fail_after_apply:
            self.fail_after_apply -= 1
            raise RuntimeError("the answer was lost after the assignment")
        return answer


@dataclass
class RecordingBoundaries:
    """`ActorBoundaryPort` that records each call and writes nothing, for a
    unit test of a hook or a door that hands it the caller's session."""

    calls: list[tuple[str, Any, str, uuid.UUID, str, tuple[Any, ...], tuple[Any, ...]]] = field(
        default_factory=list
    )

    async def record(
        self,
        session: Any,
        kind: Any,
        version_id: uuid.UUID,
        definition_hash: str,
        objects: Sequence[Any],
        fields: Sequence[Any],
    ) -> uuid.UUID:
        self.calls.append(
            ("record", session, kind, version_id, definition_hash, tuple(objects), tuple(fields))
        )
        return uuid.uuid4()

    async def record_provisional(
        self,
        session: Any,
        kind: Any,
        run_id: uuid.UUID,
        version_id: uuid.UUID,
        pinned_hash: str,
        objects: Sequence[Any],
        fields: Sequence[Any],
    ) -> uuid.UUID:
        self.calls.append(
            ("provisional", session, kind, version_id, pinned_hash, tuple(objects), tuple(fields))
        )
        return uuid.uuid4()
