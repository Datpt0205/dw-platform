"""Open a database session with the RLS tenant context already bound.

Every tenant-scoped adapter needs the same three steps in the same order:
acquire a session, open a transaction, bind the `app.*` GUCs. Hand-rolling that
sequence is what produced four connection leaks, because acquiring the pooled
session before entering a cleanup guard loses it when `begin()` or the bind
raises. Here the guard is entered first, so there is no window in which a
connection is held by nothing.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession, async_sessionmaker

from dw_platform.application.access_context import AccessContext

_BIND_SCOPE = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true),"
    "       set_config('app.workspace_id', :workspace_id, true),"
    "       set_config('app.user_id', :user_id, true)"
)


@dataclass(frozen=True)
class TenantScope:
    """The identifiers an RLS policy may read, and nothing else."""

    tenant_id: uuid.UUID
    workspace_id: uuid.UUID | None = None
    principal_id: uuid.UUID | None = None

    @classmethod
    def from_access_context(cls, context: AccessContext) -> TenantScope:
        return cls(
            tenant_id=context.tenant_id,
            workspace_id=context.workspace_id,
            principal_id=context.principal_id,
        )


async def bind_tenant(session: AsyncSession | AsyncConnection, scope: TenantScope) -> None:
    """Bind the scope for the session's open transaction only.

    An absent identifier is bound as the empty string rather than skipped: every
    policy reads its GUC through ``NULLIF(..., '')``, so a scope that does not
    name a workspace denies a workspace-keyed policy instead of inheriting
    whatever the previous caller on this connection had set.
    """
    # Consume result to force execution; SELECT set_config(...) is lazy otherwise.
    (
        await session.execute(
            _BIND_SCOPE,
            {
                "tenant_id": str(scope.tenant_id),
                "workspace_id": str(scope.workspace_id) if scope.workspace_id else "",
                "user_id": str(scope.principal_id) if scope.principal_id else "",
            },
        )
    ).first()


@asynccontextmanager
async def tenant_session(
    session_factory: async_sessionmaker[AsyncSession], scope: TenantScope
) -> AsyncIterator[AsyncSession]:
    """Yield a session inside a transaction bound to ``scope``.

    Commits on a clean exit and rolls back on an exception, both by way of
    ``session.begin()``.
    """
    async with session_factory() as session, session.begin():
        await bind_tenant(session, scope)
        yield session


# -- the actor (record-access tickets 03 and 04; ADR-0105 decision 6) ------------

ActorKind = Literal["user", "agent", "workflow"]
_RUN_KINDS: frozenset[str] = frozenset({"agent", "workflow"})


class ActorBindingRefusedError(Exception):
    """A run's actor was asked for a run this transaction cannot read, or for a
    principal other than the one its run row acts as. Nothing was bound."""


# The three settings together, for this transaction only (`true`): a pooled
# connection carries none of them into whoever borrows it next (R6.6).
_BIND_ACTOR = text(
    "SELECT set_config('app.actor_kind', :kind, true),"
    "       set_config('app.boundary_id', :boundary, true),"
    "       set_config('app.run_mode', :mode, true)"
)

# A run's principal, mode and boundaries, from its row under the bound tenant:
# never from `RunContext` or a checkpoint (gate (d), (e)). `studio.boundary_chain`
# is the one answer to which boundaries a run reads under, root first (gate (b),
# (f), (k)); a run with no Studio root has none and reads no record.
_RUN_ACTOR = text(
    "SELECT r.run_mode, coalesce(r.run_as_principal_id, r.requested_by) AS principal,"
    "       NULLIF(current_setting('app.user_id', true), '')::uuid AS bound,"
    "       array_to_string(studio.boundary_chain(r.id), ',') AS chain"
    " FROM platform.worker_runs r"
    " WHERE r.tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid"
    "   AND r.id = :run"
)


async def bind_actor(
    session: AsyncSession | AsyncConnection,
    kind: ActorKind,
    *,
    run_id: uuid.UUID | None = None,
) -> None:
    """Bind `app.actor_kind`, `app.boundary_id` and `app.run_mode` for the open
    transaction only; the one setter of all three.

    `user` binds no run, and clears the other two. `agent` and `workflow` read
    the run's row under the bound tenant: its mode becomes `app.run_mode`, its
    boundary chain `app.boundary_id`, and the principal bound by `bind_tenant`
    must be the one the run acts as (`run_as_principal_id`, else
    `requested_by`; ADR-0103), or nothing is bound. The record policies admit a
    row only to a bound actor kind, so a transaction that never comes through
    here reads no Studio record. Which modules may call this, and with which
    kind, is `test_session_setting_scan.py`'s list.
    """
    if kind == "user":
        if run_id is not None:
            raise ValueError("the actor kind `user` binds no run")
        boundary, mode = "", ""
    elif kind in _RUN_KINDS:
        if run_id is None:
            raise ValueError(f"the actor kind {kind!r} binds a run")
        row = (await session.execute(_RUN_ACTOR, {"run": run_id})).one_or_none()
        if row is None:
            raise ActorBindingRefusedError(f"no run {run_id} under the bound tenant")
        if row.bound is None or row.bound != row.principal:
            raise ActorBindingRefusedError(
                f"run {run_id} acts as its own principal, not the one this transaction bound"
            )
        boundary, mode = str(row.chain), str(row.run_mode)
    else:
        raise ValueError(f"unknown actor kind {kind!r}")
    (await session.execute(_BIND_ACTOR, {"kind": kind, "boundary": boundary, "mode": mode})).first()


# -- the tenant-wide scope (record-access ticket 03, step 6; ADR-0105 decision 5) --

_LANE_NAME = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


@dataclass(frozen=True)
class TenantWideLane:
    """One lane allowed every row of the tenant it is bound to, and why.

    `reads_private_tables` says whether the lane needs the tables narrowed to
    one person (ADR-0117), which the scope opens to it as well: a lane that
    needs records only is reviewed as if it read conversations (ADR-0105
    decision 5). Both are required, with no default.
    """

    lane: str
    reason: str
    reads_private_tables: bool

    def __post_init__(self) -> None:
        if not _LANE_NAME.fullmatch(self.lane):
            raise ValueError(f"a tenant-wide lane is named like a worker lane, not {self.lane!r}")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError(f"tenant-wide lane {self.lane!r} has no reason")
        if not isinstance(self.reads_private_tables, bool):
            raise ValueError(
                f"tenant-wide lane {self.lane!r} does not say whether it reads"
                " the tables private to one person"
            )


class TenantWideScopeRegistry:
    """The lanes `tenant_wide_scope` serves, frozen when built.

    Built once, at the worker's composition root, and injected into the lane
    that uses it; the API process builds none (`test_session_setting_scan.py`).
    """

    def __init__(self, *lanes: TenantWideLane) -> None:
        entries: dict[str, TenantWideLane] = {}
        for entry in lanes:
            if not isinstance(entry, TenantWideLane):
                raise ValueError(f"not a TenantWideLane: {entry!r}")
            if entry.lane in entries:
                raise ValueError(f"tenant-wide lane {entry.lane!r} is listed twice")
            entries[entry.lane] = entry
        self._lanes: Mapping[str, TenantWideLane] = MappingProxyType(entries)

    def get(self, lane: str) -> TenantWideLane | None:
        return self._lanes.get(lane)

    def lanes(self) -> tuple[TenantWideLane, ...]:
        return tuple(self._lanes.values())


class TenantWideScopeRefusedError(Exception):
    """A lane asked for the tenant-wide scope without being registered."""


# The tenant and the scope together, for this transaction only (`true`): a
# pooled connection carries neither into whoever borrows it next.
_BIND_TENANT_WIDE = text(
    "SELECT set_config('app.tenant_id', :tenant_id, true),"
    "       set_config('app.workspace_scope', 'tenant', true)"
)


async def tenant_wide_scope(
    session: AsyncSession | AsyncConnection,
    tenant_id: uuid.UUID,
    lane: str,
    registry: TenantWideScopeRegistry,
) -> None:
    """Bind ``tenant_id`` and every row of it, record reach included, for the
    open transaction only; the one setter of `app.workspace_scope`.

    A lane missing from ``registry`` is refused before anything is set.
    """
    if registry.get(lane) is None:
        raise TenantWideScopeRefusedError(f"lane {lane!r} is not registered for the tenant scope")
    (await session.execute(_BIND_TENANT_WIDE, {"tenant_id": str(tenant_id)})).first()
