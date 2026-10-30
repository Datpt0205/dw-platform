"""A Digital Worker: company data with a principal, four people and decision classes.

What is decided here, without a database: the shape a DW's configuration must
have (digital-worker R1.3, R2.2), and which state may follow which (R1.7). Who
may do what to a DW, and whether the people are members, is the application's;
the tables repeat every rule here as a CHECK, so a row the code did not shape
cannot exist either.

A refusal names its `reason_code` in `details`, the field the web branches on.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final, Literal

from dw_kernel.autonomy import AUTONOMY_LEVELS, AutonomyLevel, is_autonomy_level
from dw_kernel.errors import ConflictError, DomainError

DwState = Literal["draft", "operating", "paused", "retired"]
EffectLevel = Literal["none", "internal", "external", "critical"]

DW_STATES: Final[tuple[DwState, ...]] = ("draft", "operating", "paused", "retired")
EFFECT_LEVELS: Final[tuple[EffectLevel, ...]] = ("none", "internal", "external", "critical")

# R1.7: every move a DW's state may make. `retired` is the end.
TRANSITIONS: Final[Mapping[DwState, frozenset[DwState]]] = MappingProxyType(
    {
        "draft": frozenset({"operating", "retired"}),
        "operating": frozenset({"paused", "retired"}),
        "paused": frozenset({"operating", "retired"}),
        "retired": frozenset(),
    }
)

# The same patterns as the CHECK constraints of migration be93e0c26a4c.
_DW_KEY = re.compile(r"[a-z][a-z0-9_]{1,39}")
_CLASS_KEY = re.compile(r"[a-z][a-z0-9_.]{1,63}")
_SEMVER = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")
MAX_NAME = 120
MAX_MANDATE = 2000


def refused(message: str, reason_code: str, **details: object) -> DomainError:
    """A 422 whose `details.reason_code` names the rule."""
    return DomainError(message, details={"reason_code": reason_code, **details})


@dataclass(frozen=True, slots=True)
class DecisionClass:
    """One kind of decision a DW takes, with its own ceiling and earned level
    (ADR-0128 decision 3)."""

    key: str
    effect_level: EffectLevel
    reversible: bool
    ceiling: AutonomyLevel
    earned_level: AutonomyLevel

    def __post_init__(self) -> None:
        if not _CLASS_KEY.fullmatch(self.key):
            raise refused("a decision class key is a lowercase name", "class_key_invalid")
        if self.effect_level not in EFFECT_LEVELS:
            raise refused("unknown effect level", "effect_level_invalid", key=self.key)
        if not (is_autonomy_level(self.ceiling) and is_autonomy_level(self.earned_level)):
            raise refused("levels are A0 to A4", "level_invalid", key=self.key)
        if AUTONOMY_LEVELS.index(self.earned_level) > AUTONOMY_LEVELS.index(self.ceiling):
            raise refused(
                "the earned level is above the class's ceiling", "above_ceiling", key=self.key
            )


@dataclass(frozen=True, slots=True)
class DwPeople:
    """The four people a DW answers to (ADR-0128 decision 2). The Business
    Owner is None only once that person's user row is gone (ON DELETE SET
    NULL); a DW without one takes no work (spec, Quyết định of gate round 2)."""

    business_owner_id: uuid.UUID | None
    technical_owner_id: uuid.UUID
    work_assigner_id: uuid.UUID
    validator_id: uuid.UUID

    def owners(self) -> frozenset[uuid.UUID]:
        """Who may change the DW's state and people (R1.6, R1.13)."""
        owners = {self.technical_owner_id}
        if self.business_owner_id is not None:
            owners.add(self.business_owner_id)
        return frozenset(owners)


@dataclass(frozen=True, slots=True)
class DwConfiguration:
    """What a DW is made with, fixed for its life: changing it is making a new
    DW (spec, Quyết định of gate round 2)."""

    key: str
    name: str
    mandate: str
    work_kinds: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    workflow_key: str
    workflow_version: str
    parameters: Mapping[str, object]
    # The principal's roles: given at creation, then read from its membership.
    role_keys: frozenset[str]
    decision_classes: tuple[DecisionClass, ...]

    def __post_init__(self) -> None:
        if not _DW_KEY.fullmatch(self.key):
            raise refused("a DW key is a lowercase name of 2 to 40 characters", "dw_key_invalid")
        if not 1 <= len(self.name.strip()) <= MAX_NAME:
            raise refused(f"a DW name has 1 to {MAX_NAME} characters", "name_invalid")
        if not 1 <= len(self.mandate.strip()) <= MAX_MANDATE:
            raise refused(f"a mandate has 1 to {MAX_MANDATE} characters", "mandate_invalid")
        if not self.work_kinds or any(not kind.strip() for kind in self.work_kinds):
            raise refused("a DW holds at least one kind of work", "work_kinds_empty")
        if not self.workflow_key.strip() or not _SEMVER.fullmatch(self.workflow_version):
            raise refused("a workflow is pinned by key and semver", "workflow_invalid")
        keys = [c.key for c in self.decision_classes]
        if len(keys) != len(set(keys)):
            raise refused("a decision class is named once", "class_key_duplicate")


@dataclass(frozen=True, slots=True)
class DigitalWorker:
    id: uuid.UUID
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    principal_user_id: uuid.UUID
    configuration: DwConfiguration
    people: DwPeople
    state: DwState
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime


def check_transition(current: DwState, target: DwState) -> None:
    """R1.7: refuse a move the table does not hold, as 409 `invalid_transition`."""
    if target not in TRANSITIONS.get(current, frozenset()):
        raise ConflictError(
            "a digital worker cannot move between these states",
            details={"reason_code": "invalid_transition", "from": current, "to": target},
        )
