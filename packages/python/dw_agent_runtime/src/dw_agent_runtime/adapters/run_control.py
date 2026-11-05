"""`RunControlPort` over PostgreSQL: a per-tenant snapshot of the open switches
that refuses when it cannot be refreshed (agent-lifecycle R7.1-R7.3, R9;
ADR-0120 decision 6, amended 2026-11-04).

The switches live in `platform.control_switches` (a company's, under its RLS)
and `platform.platform_freezes` (the operators'). Every door asks this object
before it acts, so the read is a snapshot: kept for `ttl_seconds` (5 s), and
dropped at once when `pg_notify('dw_control_switch', ...)` says a switch of
that company changed (`{"tenant_id", "id"}`) or a platform freeze did
(`{"platform": true}`, every snapshot). The NOTIFY is the fast path; the TTL is
what still holds when a notification is lost.

Fail closed, the opposite of the access-context cache (ADR-0024 decision 4): a
refresh that fails is answered from the last snapshot only while it is younger
than `stale_after_seconds` (30 s), and with `control_state_unavailable` after
that, or at once when a notification had already said the snapshot was stale.

The principal's standing and the company's status are not in the snapshot:
they are read at `admission`, `start` and `resume` only, one query each time
(R9.1, R9.2). A run whose principal is a lane's own actor (`system_actor`,
ADR-0011) is not asked about a membership it never has.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, NoReturn

import asyncpg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from dw_agent_runtime.contracts import RunContext
from dw_agent_runtime.run_control import (
    PRINCIPAL_DOORS,
    HaltReason,
    RunControlDoor,
    RunHaltedError,
)
from dw_kernel.ports import UtcClock
from dw_observability.metrics import DW_CONTROL_REFUSALS_TOTAL
from dw_observability.telemetry import TelemetryPort

__all__ = ["CONTROL_SWITCH_CHANNEL", "SqlRunControl", "reached_components"]

logger = logging.getLogger(__name__)

# The migration's trigger functions NOTIFY on this channel (8efd60e59d32).
CONTROL_SWITCH_CHANNEL = "dw_control_switch"

_RECONNECT_DELAY_SECONDS = 2.0

_SET_TENANT = text("SELECT set_config('app.tenant_id', :tenant_id, true)")

# Every open switch of the company (RLS) and the open platform freeze.
_OPEN_SWITCHES = text(
    "SELECT s.id, s.scope_type, s.target_id, s.origin, s.set_by"
    " FROM platform.control_switches s WHERE s.lifted_at IS NULL"
    " UNION ALL"
    " SELECT f.id, 'platform', NULL, 'platform', f.set_by"
    " FROM platform.platform_freezes f WHERE f.lifted_at IS NULL"
)

# The company's status and the principal's standing in it, in one query.
_STANDING = text(
    "SELECT t.status AS tenant_status,"
    " (SELECT m.status FROM platform.tenant_members m"
    "  WHERE m.tenant_id = t.id AND m.user_id = :principal) AS member_status"
    " FROM platform.tenants t WHERE t.id = :tenant_id"
)

_TENANT_STATUS: Mapping[str, HaltReason] = {
    "locked": HaltReason.TENANT_LOCKED,
    "offboarding": HaltReason.TENANT_OFFBOARDING,
    "offboarded": HaltReason.TENANT_OFFBOARDING,
}


@dataclass(frozen=True, slots=True)
class _Switch:
    id: uuid.UUID
    set_by: uuid.UUID


@dataclass(frozen=True, slots=True)
class _Refusal:
    reason: HaltReason
    switch: _Switch


@dataclass(frozen=True, slots=True)
class _Snapshot:
    """What one company's doors are told, read at `read_at`. A freeze set by
    an operator answers before the company's own; a platform freeze before
    both (ticket 05's precedence)."""

    platform_freeze: _Switch | None
    tenant_freezes: tuple[_Switch, ...]
    kills: Mapping[uuid.UUID, _Switch]
    read_at: datetime

    def refusal(self, artifacts: Sequence[uuid.UUID], *, kill_first: bool) -> _Refusal | None:
        killed = next(
            (
                _Refusal(HaltReason.ARTIFACT_KILLED, self.kills[a])
                for a in artifacts
                if a in self.kills
            ),
            None,
        )
        frozen = None
        if self.platform_freeze is not None:
            frozen = _Refusal(HaltReason.PLATFORM_FROZEN, self.platform_freeze)
        elif self.tenant_freezes:
            frozen = _Refusal(HaltReason.TENANT_FROZEN, self.tenant_freezes[0])
        # At admission a killed component's queued run is cancelled rather than
        # held by a freeze (spec R8.1).
        if kill_first:
            return killed or frozen
        return frozen or killed


def _snapshot_of(rows: Sequence[Any], read_at: datetime) -> _Snapshot:
    platform: _Switch | None = None
    operator: list[_Switch] = []
    company: list[_Switch] = []
    kills: dict[uuid.UUID, _Switch] = {}
    for row in rows:
        switch = _Switch(id=row.id, set_by=row.set_by)
        if row.scope_type == "platform":
            platform = switch
        elif row.scope_type == "tenant":
            (operator if row.origin == "platform" else company).append(switch)
        elif row.target_id is not None:
            kills.setdefault(row.target_id, switch)
    return _Snapshot(
        platform_freeze=platform,
        tenant_freezes=(*operator, *company),
        kills=kills,
        read_at=read_at,
    )


def reached_components(
    run_context: RunContext, artifacts: Sequence[uuid.UUID]
) -> tuple[uuid.UUID, ...]:
    """The components whose kill refuses this call, in the order a refusal
    names one (agent-lifecycle R8.1, R8.5): the run's own first, then those
    the door names (a linked agent). None for a `simulate` run, which a kill
    never stops, so a fix can be evaluated (ADR-0120 decision 7)."""
    if run_context.run_mode == "simulate":
        return ()
    own = () if run_context.artifact_id is None else (run_context.artifact_id,)
    return (*own, *artifacts)


class SqlRunControl:
    """Implements `RunControlPort`. One per process: the API and the worker
    each hand this instance to every door they build."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        clock: UtcClock,
        telemetry: TelemetryPort,
        listen_dsn: str | None,
        system_actors: frozenset[uuid.UUID],
        ttl_seconds: float = 5.0,
        stale_after_seconds: float = 30.0,
        read_timeout_seconds: float = 5.0,
    ) -> None:
        self._sessions = session_factory
        self._clock = clock
        self._telemetry = telemetry
        self._dsn = listen_dsn
        # The lanes that ask for a run as themselves (ADR-0011), named at the
        # composition root: no membership is asked of them.
        self._system_actors = system_actors
        self._ttl = timedelta(seconds=ttl_seconds)
        self._stale_after = timedelta(seconds=stale_after_seconds)
        self._read_timeout = read_timeout_seconds
        self._snapshots: dict[uuid.UUID, _Snapshot] = {}
        self._listener: asyncio.Task[None] | None = None
        self._connection: asyncpg.Connection[Any] | None = None

    # ---- the port --------------------------------------------------------

    async def require_open(
        self,
        run_context: RunContext,
        *,
        door: RunControlDoor,
        artifacts: Sequence[uuid.UUID] = (),
    ) -> None:
        tenant_id = run_context.tenant_id
        if door in PRINCIPAL_DOORS:
            principal = run_context.run_as_principal_id or run_context.actor_id
            standing = await self._standing(tenant_id, principal, door)
            if standing is not None:
                self._refuse(standing, door)
        snapshot = await self._snapshot(tenant_id, door)
        refusal = snapshot.refusal(
            reached_components(run_context, artifacts),
            kill_first=door is RunControlDoor.ADMISSION,
        )
        if refusal is not None:
            self._refuse(refusal.reason, door, refusal.switch)

    async def admission_state(
        self, tenant_id: uuid.UUID, artifacts: Sequence[uuid.UUID] = ()
    ) -> HaltReason | None:
        door = RunControlDoor.ADMISSION
        try:
            reason = await self._standing(tenant_id, None, door)
            if reason is None:
                refusal = (await self._snapshot(tenant_id, door)).refusal(
                    artifacts, kill_first=True
                )
                reason = None if refusal is None else refusal.reason
        except RunHaltedError as halted:
            # Already counted where it was raised.
            return halted.reason
        if reason is not None:
            self._count(reason, door)
        return reason

    # ---- the listener ----------------------------------------------------

    async def close(self) -> None:
        """Stop listening; the next door starts it again."""
        if self._listener is not None:
            self._listener.cancel()
            with contextlib.suppress(asyncio.CancelledError, RuntimeError):
                await self._listener
            self._listener = None
        await self._close_connection()

    def _ensure_listening(self) -> None:
        """Started by the first door that asks, on the loop that asks: a
        composition root that is synchronous cannot open a connection."""
        if self._dsn is None:
            return
        task = self._listener
        loop = asyncio.get_running_loop()
        if task is not None and not task.done() and task.get_loop() is loop:
            return
        self._listener = loop.create_task(self._listen(), name="control-switch-listener")

    async def _listen(self) -> None:
        while True:
            try:
                assert self._dsn is not None
                self._connection = await asyncpg.connect(self._dsn)
                await self._connection.add_listener(CONTROL_SWITCH_CHANNEL, self._on_notify)
                # Whatever changed while nobody listened is unknown: read again.
                self._snapshots.clear()
                while not self._connection.is_closed():
                    await asyncio.sleep(_RECONNECT_DELAY_SECONDS)
                raise ConnectionError("listening connection closed")
            except asyncio.CancelledError:
                raise
            except (OSError, asyncpg.PostgresError, ConnectionError) as exc:
                # Until it is back the TTL bounds how late a switch is seen.
                logger.warning("control-switch listener reconnecting: %s", exc)
                await self._close_connection()
                await asyncio.sleep(_RECONNECT_DELAY_SECONDS)

    def _on_notify(self, _conn: object, _pid: int, _channel: str, payload: str) -> None:
        self.invalidate(payload)

    def invalidate(self, payload: str) -> None:
        """Drop the snapshot a notification names; all of them for a platform
        freeze or a payload this process cannot read."""
        try:
            raw = json.loads(payload)
            if raw.get("platform") is True:
                self._snapshots.clear()
                return
            self._snapshots.pop(uuid.UUID(str(raw["tenant_id"])), None)
        except (ValueError, KeyError, TypeError, AttributeError):
            logger.warning("unreadable control-switch notification; every snapshot dropped")
            self._snapshots.clear()

    async def _close_connection(self) -> None:
        if self._connection is not None:
            with contextlib.suppress(OSError, asyncpg.PostgresError):
                await self._connection.close()
            self._connection = None

    # ---- reads -----------------------------------------------------------

    async def _snapshot(self, tenant_id: uuid.UUID, door: RunControlDoor) -> _Snapshot:
        self._ensure_listening()
        now = self._clock.now()
        current = self._snapshots.get(tenant_id)
        if current is not None and now - current.read_at < self._ttl:
            return current
        try:
            async with asyncio.timeout(self._read_timeout):
                rows = await self._read(tenant_id, _OPEN_SWITCHES, {})
        except Exception:
            # Broad on purpose and closed either way: whatever stopped the read,
            # the answer past the grace is a refusal, never an open door.
            if current is not None and now - current.read_at <= self._stale_after:
                logger.warning("control state not refreshed; answering from the last snapshot")
                return current
            logger.warning("control state unavailable", exc_info=True)
            self._refuse(HaltReason.CONTROL_STATE_UNAVAILABLE, door)
        fresh = _snapshot_of(rows, now)
        self._forget_stale(now)
        self._snapshots[tenant_id] = fresh
        return fresh

    async def _standing(
        self, tenant_id: uuid.UUID, principal: uuid.UUID | None, door: RunControlDoor
    ) -> HaltReason | None:
        try:
            async with asyncio.timeout(self._read_timeout):
                rows = await self._read(
                    tenant_id, _STANDING, {"tenant_id": tenant_id, "principal": principal}
                )
        except Exception:
            logger.warning("company and principal standing unavailable", exc_info=True)
            self._refuse(HaltReason.CONTROL_STATE_UNAVAILABLE, door)
        if not rows:
            # The company's row is not readable under its own id: nothing to
            # run under, and nothing that says it may.
            self._refuse(HaltReason.CONTROL_STATE_UNAVAILABLE, door)
        row = rows[0]
        tenant_reason = _TENANT_STATUS.get(row.tenant_status)
        if tenant_reason is not None:
            return tenant_reason
        if principal is None or principal in self._system_actors:
            return None
        # No row is not active: closed when missing (R9.1).
        if row.member_status != "active":
            return HaltReason.PRINCIPAL_INACTIVE
        return None

    async def _read(
        self, tenant_id: uuid.UUID, statement: Any, values: Mapping[str, object]
    ) -> Sequence[Any]:
        async with self._sessions() as session, session.begin():
            await session.execute(_SET_TENANT, {"tenant_id": str(tenant_id)})
            return (await session.execute(statement, dict(values))).all()

    def _forget_stale(self, now: datetime) -> None:
        """A company not asked about for longer than the grace is read again
        anyway; its entry goes, so the map holds the companies in use."""
        for tenant_id in [
            t for t, s in self._snapshots.items() if now - s.read_at > self._stale_after
        ]:
            del self._snapshots[tenant_id]

    # ---- refusals --------------------------------------------------------

    def _count(self, reason: HaltReason, door: RunControlDoor) -> None:
        # No tenant label: a label per company is unbounded cardinality.
        self._telemetry.add_metric(
            DW_CONTROL_REFUSALS_TOTAL, 1, {"door": door.value, "reason_code": reason.value}
        )

    def _refuse(
        self, reason: HaltReason, door: RunControlDoor, switch: _Switch | None = None
    ) -> NoReturn:
        self._count(reason, door)
        raise RunHaltedError(
            reason,
            door=door,
            set_by=None if switch is None else switch.set_by,
            switch_id=None if switch is None else switch.id,
        )
