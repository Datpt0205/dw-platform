"""The autonomy levels a Digital Worker can run at.

In the kernel, and nowhere else, because two layers must agree on them and
neither may import the other: the agent runtime decides what each level permits,
and the platform stores the ceiling a tenant sets. A second copy of this list in
either one is how a tenant comes to be offered a level the runtime has never
heard of — or refused one it would have honoured.

The database holds the same five values as a CHECK constraint, and that is the
guarantee; this is the list the code reads.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, Literal, get_args

AutonomyLevel = Literal["A0", "A1", "A2", "A3", "A4"]

# Lowest to highest. The order IS the meaning: a later level may do everything an
# earlier one may, and more.
AUTONOMY_LEVELS: Final[tuple[AutonomyLevel, ...]] = get_args(AutonomyLevel)

# What a tenant with no ceiling of its own is held to: nothing beyond what the
# worker was built for. Not a permission — the worker's declared level still
# caps every run — only the absence of an extra restriction.
NO_TENANT_CEILING: Final[AutonomyLevel] = "A4"

# The level to assume when a ceiling should exist and cannot be read. The most
# restrictive, because refusing a legitimate action is recoverable and taking an
# illegitimate one is not.
FAIL_CLOSED_LEVEL: Final[AutonomyLevel] = "A0"


def is_autonomy_level(value: object) -> bool:
    return value in AUTONOMY_LEVELS


def lower_autonomy(first: AutonomyLevel, second: AutonomyLevel) -> AutonomyLevel:
    """The more restrictive of two levels.

    How a ceiling combines with a level below it: a tenant may hold a worker
    below what it was built for, and never lift it above. A Digital Worker's
    effective level for a decision class is this, applied twice.
    """
    return first if AUTONOMY_LEVELS.index(first) <= AUTONOMY_LEVELS.index(second) else second


# The ladder of effects, lowest to highest, and the highest rung each level runs
# without asking a person (the table recorded 2026-09-17, written out in
# `dw_agent_runtime.autonomy`). Here and nowhere else, because a tool call and a
# Digital Worker's decision class are gated by the same ladder (digital-worker
# R2.4): two tables are two answers to one question.
#
# "external_repeatable" is not an effect anything declares: an external effect
# that is safe to repeat (an idempotent tool, a reversible decision class) is
# ranked on it, one rung below plain "external", so A3 reaches it and stops.
_RUNG: Final[Mapping[str, int]] = {
    "none": 0,
    "internal": 1,
    "external_repeatable": 2,
    "external": 3,
    "critical": 4,
}

# -1 is below every rung: A0 reaches nothing. No level reaches `critical`, which
# makes it a floor by construction and not only by the check in
# `requires_person`.
_REACH: Final[Mapping[AutonomyLevel, int]] = {
    "A0": -1,
    "A1": _RUNG["none"],
    "A2": _RUNG["internal"],
    "A3": _RUNG["external_repeatable"],
    "A4": _RUNG["external"],
}


def effect_rung(effect_level: str, *, repeatable: bool) -> str:
    """The rung an effect stands on. An unknown effect level stands on
    `critical`: what nobody declared is not something to do unasked."""
    if effect_level not in _RUNG or effect_level == "external_repeatable":
        return "critical"
    if effect_level == "external" and repeatable:
        return "external_repeatable"
    return effect_level


def requires_person(rung: str, level: AutonomyLevel | None) -> bool:
    """Whether an effect on `rung` waits for a person at `level`.

    `critical` always does, whatever the level. A level that was never resolved
    (None) or is not one of the five asks too: refusing is recoverable, acting
    on a guess is not.
    """
    if rung == "critical" or rung not in _RUNG:
        return True
    if level is None or level not in _REACH:
        return True
    return _RUNG[rung] > _REACH[level]
