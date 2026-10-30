"""A work item: one piece of work on the queue people and Digital Workers share.

Decided here, without a database: which status may follow which, and by whose
hand (digital-worker R3.12, the spec's Dữ liệu section), what a hand-off packet
must hold (R4.2), and the hash a payload is known by (R3.4). The table below is
the one owner of the status pairs; every write of a status asks it, and the
database holds what a row must look like in each status.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final, Literal

from dw_kernel.errors import ConflictError, DomainError
from dw_kernel.pagination import canonical_json

WorkStatus = Literal[
    "open",
    "in_progress",
    "waiting_approval",
    "waiting_timer",
    "handed_off",
    "done",
    "failed",
    "cancelled",
]
HolderKind = Literal["digital_worker", "person"]

# Who moves an item, so a pair can only be asked for by the path that owns it.
Mover = Literal["lane", "runner", "hand_off", "holder", "retire"]

# R3.12: (from, to) -> who may make that move. Nothing leaves done, failed or
# cancelled.
TRANSITIONS: Final[Mapping[tuple[WorkStatus, WorkStatus], Mover]] = MappingProxyType(
    {
        ("open", "in_progress"): "lane",
        ("in_progress", "open"): "lane",
        ("in_progress", "waiting_approval"): "runner",
        ("in_progress", "waiting_timer"): "runner",
        ("waiting_approval", "in_progress"): "runner",
        ("waiting_timer", "in_progress"): "runner",
        ("in_progress", "handed_off"): "hand_off",
        ("waiting_approval", "handed_off"): "hand_off",
        ("waiting_timer", "handed_off"): "hand_off",
        ("in_progress", "done"): "runner",
        ("in_progress", "failed"): "runner",
        ("handed_off", "done"): "holder",
        ("open", "cancelled"): "retire",
    }
)
TERMINAL: Final[frozenset[WorkStatus]] = frozenset({"done", "failed", "cancelled"})
# R1.12: a DW cannot retire while it holds work in these.
IN_FLIGHT: Final[frozenset[WorkStatus]] = frozenset(
    {"in_progress", "waiting_approval", "waiting_timer"}
)

HANDOFF_FIELDS: Final[tuple[str, ...]] = ("problem", "context", "tried", "recommendation")
MAX_HANDOFF_FIELD = 4000


def sources_of(target: WorkStatus, mover: Mover) -> frozenset[WorkStatus]:
    """Every status `mover` may move an item from into `target`: what a
    conditional UPDATE names in its WHERE, so no write bypasses the table."""
    return frozenset(
        src for (src, dst), who in TRANSITIONS.items() if dst == target and who == mover
    )


def check_transition(current: str, target: WorkStatus, mover: Mover) -> None:
    if current not in sources_of(target, mover):
        raise ConflictError(
            "a work item cannot move between these states",
            details={"reason_code": "invalid_transition", "from": current, "to": target},
        )


def payload_hash(payload: Mapping[str, object]) -> str:
    """sha256 of the payload in canonical JSON (R3.1): two payloads equal as
    data hash alike, whatever order their keys came in."""
    return hashlib.sha256(canonical_json(payload).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class HandoffPacket:
    """What a DW hands a person with the work (ADR-0128 decision 7)."""

    problem: str
    context: str
    tried: str
    recommendation: str

    @classmethod
    def of(cls, raw: Mapping[str, object]) -> HandoffPacket:
        """R4.2: all four fields, each a non-blank string of at most 4,000
        characters, and nothing else."""
        unknown = sorted(set(raw) - set(HANDOFF_FIELDS))
        bad = [
            name
            for name in HANDOFF_FIELDS
            if not isinstance(raw.get(name), str)
            or not str(raw[name]).strip()
            or len(str(raw[name])) > MAX_HANDOFF_FIELD
        ]
        if bad or unknown:
            raise DomainError(
                "a hand-off packet holds problem, context, tried and recommendation,"
                f" each 1 to {MAX_HANDOFF_FIELD} characters",
                details={"reason_code": "handoff_packet_invalid", "fields": bad + unknown},
            )
        return cls(**{name: str(raw[name]) for name in HANDOFF_FIELDS})

    def as_dict(self) -> dict[str, str]:
        return {name: getattr(self, name) for name in HANDOFF_FIELDS}


@dataclass(frozen=True, slots=True)
class WorkItem:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    dw_id: uuid.UUID
    kind: str
    source_key: str
    payload: Mapping[str, object]
    payload_hash: str
    holder_kind: HolderKind
    holder_id: uuid.UUID
    status: WorkStatus
    available_at: datetime
    run_id: uuid.UUID | None
    wake_at: datetime | None
    handoff: HandoffPacket | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    closed_at: datetime | None
