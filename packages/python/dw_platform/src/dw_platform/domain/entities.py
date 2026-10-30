"""Platform domain entities: tenancy, membership, plans.

Pure dataclasses with invariants — no framework imports (enforced by
architecture tests).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from dw_kernel.ids import EntityId, TenantId, UserId, WorkspaceId


@dataclass(slots=True)
class User:
    """A platform user; identity comes from the verified token subject."""

    id: UserId
    subject: str
    email: str | None
    display_name: str

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("user subject must not be blank")
        if not self.display_name.strip():
            raise ValueError("user display_name must not be blank")


@dataclass(frozen=True, slots=True)
class Role:
    """A named bundle of scopes. Role keys are stable identifiers."""

    key: str
    name: str
    scopes: frozenset[str]

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,62}", self.key):
            raise ValueError(f"role key must be snake_case, got {self.key!r}")


@dataclass(slots=True)
class Membership:
    """Grants a user access to one workspace of one tenant with roles."""

    id: EntityId
    tenant_id: TenantId
    workspace_id: WorkspaceId
    user_id: UserId
    role_keys: frozenset[str]
    clearance: str = "internal"

    def __post_init__(self) -> None:
        if not self.role_keys:
            raise ValueError("membership requires at least one role")


@dataclass(frozen=True, slots=True)
class Plan:
    """A subscription plan: features + quotas. Entitlement != authorization."""

    plan_id: str
    name: str
    features: frozenset[str]
    quotas: dict[str, int] = field(default_factory=dict)
    # Separate from `quotas` rather than another int in that dict: a dollar
    # ceiling needs decimal precision, not integer counting, and `None` here
    # means "no business decision yet" — every plan ships that way today. See
    # dw_agent_runtime.ports.RunAllowancePort.spend_usd_per_day.
    spend_usd_per_day: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.plan_id.strip():
            raise ValueError("plan_id must not be blank")
        for key, value in self.quotas.items():
            if value < 0:
                raise ValueError(f"quota {key!r} must be >= 0")
        if self.spend_usd_per_day is not None and self.spend_usd_per_day < 0:
            raise ValueError("spend_usd_per_day must be >= 0")


@dataclass(slots=True)
class Entitlement:
    """Binds a tenant to a plan, with optional per-tenant feature overrides."""

    id: EntityId
    tenant_id: TenantId
    plan_id: str
    feature_overrides: frozenset[str] = frozenset()

    def effective_features(self, plan: Plan) -> frozenset[str]:
        if plan.plan_id != self.plan_id:
            raise ValueError("plan does not match entitlement")
        return plan.features | self.feature_overrides
