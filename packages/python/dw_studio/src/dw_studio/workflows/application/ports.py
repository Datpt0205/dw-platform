"""What the `workflow` kind asks of the rest of the platform, declared here by
its consumer (CLAUDE.md, Non-negotiable architecture): its publish hook's
trigger activation, and a running step's record doors."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from dw_agent_runtime.contracts import RunContext
from dw_kernel.run_mode import RunMode
from dw_studio.core.application.ports import ArtifactTx


class TriggerActivationPort(Protocol):
    """The trigger subscriptions of a workflow version that goes `live`
    (workflow-engine R1.6; ADR-0109 decision 1). workflow-triggers/01
    satisfies it by writing `studio.trigger_subscriptions`.

    - After the call, the artifact's `active` subscriptions are exactly the
      version's, and those of the version it replaces are `retired`.
    - A second call for the same version changes nothing: the outbox may
      deliver `.decided` again.
    - Everything happens on `tx`, the publish transaction agent-lifecycle/04
      opens and hands the hook, so the version and its subscriptions commit
      or roll back together; an error is raised, never swallowed, and rolls
      the publish back.
    """

    async def activate(self, tx: ArtifactTx, version_id: uuid.UUID) -> None: ...


# ---- the record doors of a step (workflow-engine/03 step 12; H-30) ----------------
#
# Declared here by their first consumer, the node wrapper's `records` and
# `assign` doors (`dw_studio.workflows.application.doors`); workflow-nodes/04
# satisfies them with `RecordService` and record-access/05's
# `AssignRecordService` and runs `dw_studio.workflows.testing.
# records_port_contract` against both, as this ticket runs it against the
# fakes, so a fake cannot drift from the real door.

RecordCommandName = Literal["read", "create", "update", "delete"]


@dataclass(frozen=True, slots=True)
class RecordRequest:
    """One record command a step sends: on `api_name`'s records, the record
    `record_id` names (none for `create`), with `values`."""

    command: RecordCommandName
    api_name: str
    record_id: uuid.UUID | None
    values: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RecordAnswer:
    """What the door answers (custom-objects R5.10): the record as the run may
    see it, and for a replayed key the answer the first write gave."""

    record: Mapping[str, Any]
    created: bool
    version: int
    replayed: bool = False


@dataclass(frozen=True, slots=True)
class AssignAnswer:
    assignee_id: uuid.UUID
    replayed: bool = False


class RecordsPort(Protocol):
    """A step's record command (workflow-nodes R5.1, R5.5; custom-objects
    R5.4, R5.9-R5.11).

    - `write_key` is the wrapper's `wf:` key, the same on every attempt and
      every run again; a write already made under it is not made again: its
      first answer comes back with `replayed` true;
    - the same key from a principal other than the one that used it is
      refused, `IdempotencyConflictError` (409 `idempotency_conflict`);
    - in `simulate` nothing is written: the answer is what the write would
      have given, and the key keeps nothing;
    - the run acts as its row's principal, within its boundary, in the
      transaction the real door opens (`bind_actor('workflow')`)."""

    async def run(
        self, run: RunContext, request: RecordRequest, *, write_key: str, run_mode: RunMode
    ) -> RecordAnswer: ...


class RecordAssignPort(Protocol):
    """A step's assignment of a record to the next person of its rotation
    (workflow-nodes R6.5; record-access R8.11, R8.12): replayed by key with
    the person the first call gave (`replayed` true), refused for another
    principal's key, and changing nothing in `simulate`."""

    async def assign(
        self,
        run: RunContext,
        api_name: str,
        record_id: uuid.UUID,
        *,
        write_key: str,
        run_mode: RunMode,
    ) -> AssignAnswer: ...
