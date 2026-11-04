"""The doors a step's effect leaves through, and the fake provider behind them.

External effects go through the platform's real `ToolExecutor` with the SQL
claims and the dispatch log of runtime-hardening/01 (`SqlToolClaims`,
`SqlToolExecutionStore`), wired as `test_tool_claims.py` wires them. The tool's
handler calls a fake provider in one of three delivery modes (V4.30):

- `keyed`: deduplicates on the key it receives (ADR-0116 `provider_key`);
- `lookup`: applies every call, and answers whether a ref was received;
- `none`: applies every call and answers nothing, as SMTP.

The provider is an outside system: its own connection, committed at once, so
it survives the worker that called it. `on_unknown` follows the mode as the
`delivery` block of ADR-0116 would declare it: `resend_same_key`,
`lookup_then_resend`, `review`. A resend first closes the unknown dispatch with
`failed` `resend_requested`, as workflow-engine/08 R6.33 does.

An internal effect (ADR-0108 decision 6) writes its row and its key in one
transaction fenced by the run's lease, and replays by key.

Crash points are armed by `SRT_CRASH` (`K1:<step>`, ...) and stalls by
`SRT_STALL` (`Sa:<step>:<seconds>`), in one worker process only.
"""

from __future__ import annotations

import os
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from dw_agent_runtime.adapters.tool_claims import SqlToolClaims
from dw_agent_runtime.adapters.tool_execution_store import SqlToolExecutionStore
from dw_agent_runtime.adapters.wflite_host import build_tool_executor_steps
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.dispatch import DispatchRecord, OutcomeUnknownError
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.testing.run_control import OpenRunControl
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry, pydantic_behaviour
from dw_kernel.dispatch import NotDispatchedError, RejectedError
from dw_kernel.errors import ConflictError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory

from .compiler import LeaseLostError, ParkError, RunCtx
from .doc import SrtStep
from .savers import _BIND_FUSED

DIED = 17
TOOL = "prov.send"
VERSION = "1.0.0"
TIMEOUT_SECONDS = 5  # the claim lives 5 x 1 + 30 = 35 s, under the run lease of 60 s


# ------------------------------------------------------------- crashes --


@dataclass
class Crash:
    """`os._exit` at a named point: no `finally`, no flush (wf-lite/02)."""

    armed: dict[tuple[str, str], float] = field(default_factory=dict)
    log: Any = None

    @classmethod
    def from_env(cls) -> Crash:
        armed: dict[tuple[str, str], float] = {}
        for spec in filter(None, os.environ.get("SRT_CRASH", "").split(",")):
            point, step = spec.split(":", 1)
            armed[(point, step)] = 0.0
        for spec in filter(None, os.environ.get("SRT_STALL", "").split(",")):
            point, step, seconds = spec.split(":", 2)
            armed[(point, step)] = float(seconds)
        return cls(armed)

    def at(self, point: str, step_id: str, ctx: RunCtx | None) -> None:
        seconds = self.armed.pop((point, step_id), None)
        if seconds is None:
            return
        if self.log is not None:
            self.log("crash_point", point=point, step=step_id, stall=seconds)
        if seconds > 0:
            time.sleep(seconds)  # the whole process stalls, heartbeat included
            return
        os._exit(DIED)


# ------------------------------------------------------------ provider --


class SendInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    mode: str
    ref: str
    step_id: str
    payload: dict[str, Any] = {}
    fault: dict[str, Any] = {}


class SendOutput(BaseModel):
    message_id: str
    applied: bool


@dataclass
class Provider:
    engine: AsyncEngine  # the outside system's own connection

    async def send(self, data: SendInput, run_id: uuid.UUID) -> SendOutput:
        key = uuid.uuid5(uuid.NAMESPACE_URL, data.ref).hex  # a hash of the wf: key
        async with self.engine.begin() as conn:
            n = (
                await conn.execute(
                    sa.text(
                        "INSERT INTO srt.provider_calls (provider, ref, n) VALUES (:p, :r, 1)"
                        " ON CONFLICT (provider, ref) DO UPDATE SET n = srt.provider_calls.n + 1"
                        " RETURNING n"
                    ),
                    {"p": data.provider, "r": data.ref},
                )
            ).scalar_one()
            fault = data.fault
            if fault.get("not_dispatched", 0) >= n:
                raise NotDispatchedError("connection refused before a byte left")
            if fault.get("reject_times", 0) >= n:
                raise RejectedError("provider refused", provider_code=str(fault.get("code", "503")))
            if fault.get("until_fixed"):
                fixed = (
                    await conn.execute(
                        sa.text("SELECT 1 FROM srt.provider_fixed WHERE provider = :p"),
                        {"p": data.provider},
                    )
                ).first()
                if fixed is None:
                    raise RejectedError("provider down", provider_code="503")
            applied = True
            if data.mode == "keyed":
                inserted = (
                    await conn.execute(
                        sa.text(
                            "INSERT INTO srt.provider_keys (provider, provider_key, result)"
                            " VALUES (:p, :k, '{}') ON CONFLICT DO NOTHING RETURNING provider_key"
                        ),
                        {"p": data.provider, "k": key},
                    )
                ).first()
                applied = inserted is not None
            if applied:
                await conn.execute(
                    sa.text(
                        "INSERT INTO srt.provider_applied (provider, mode, provider_key, ref,"
                        " run_id, step_id) VALUES (:p, :m, :k, :r, :run, :s)"
                    ),
                    {
                        "p": data.provider,
                        "m": data.mode,
                        "k": key,
                        "r": data.ref,
                        "run": run_id,
                        "s": data.step_id,
                    },
                )
        if fault.get("lose_times", 0) >= n:
            raise TimeoutError("the answer was lost after the provider applied the call")
        return SendOutput(message_id=f"{data.provider}-{key[:12]}-{n}", applied=applied)

    async def lookup(self, provider: str, ref: str) -> bool:
        async with self.engine.connect() as conn:
            found = (
                await conn.execute(
                    sa.text("SELECT 1 FROM srt.provider_applied WHERE provider = :p AND ref = :r"),
                    {"p": provider, "r": ref},
                )
            ).first()
        return found is not None


# ---------------------------------------------------------------- claims --


@dataclass(frozen=True)
class HookedClaims(SqlToolClaims):
    """The platform's claims, with the crash points between its steps, and
    the control case of T3: `dispatch_log=False` removes the `dispatched` row."""

    crash: Crash = field(default_factory=Crash)
    dispatch_log: bool = True

    async def claim(
        self,
        run_context: RunContext,
        tool_name: str,
        idempotency_key: str,
        *,
        lease_seconds: float,
    ) -> uuid.UUID | None:
        token = await super().claim(
            run_context, tool_name, idempotency_key, lease_seconds=lease_seconds
        )
        step = idempotency_key.split(":")[2]
        self.crash.at("K2", step, None)
        self.crash.at("Sa", step, None)
        return token

    async def dispatch(
        self,
        run_context: RunContext,
        tool_name: str,
        idempotency_key: str,
        token: uuid.UUID,
        record: DispatchRecord,
    ) -> bool:
        if not self.dispatch_log:
            return True
        done = await super().dispatch(run_context, tool_name, idempotency_key, token, record)
        self.crash.at("Sb", idempotency_key.split(":")[2], None)
        if done and os.environ.get("SRT_PRESEND"):
            # The mitigation measured for lookup_then_resend: the claim is
            # checked again right before the call leaves.
            async with self.session_factory() as session, session.begin():
                await session.execute(
                    sa.text("SELECT set_config('app.tenant_id', :t, true)"),
                    {"t": str(run_context.tenant_id)},
                )
                held = (
                    await session.execute(
                        sa.text(
                            "SELECT 1 FROM platform.tool_execution_claims WHERE tenant_id = :t"
                            " AND tool_name = :n AND idempotency_key = :k"
                            " AND claim_token = :tok AND expires_at > now()"
                        ),
                        {
                            "t": run_context.tenant_id,
                            "n": tool_name,
                            "k": idempotency_key,
                            "tok": token,
                        },
                    )
                ).first()
            if held is None:
                raise ConflictError("the claim expired while this call was stalled")
        return done


# ------------------------------------------------------------------ door --


def run_context(ctx: RunCtx) -> RunContext:
    return RunContext(
        run_id=uuid.UUID(ctx.run_id),
        run_mode="live",
        thread_id=uuid.UUID(ctx.run_id),
        tenant_id=uuid.UUID(ctx.tenant_id),
        workspace_id=uuid.UUID(ctx.workspace_id),
        actor_id=uuid.UUID(int=0x5E),
        worker_id="srt",
        worker_version="1.0.0",
        channel="web",
        plan_id="professional",
        roles=frozenset({"member"}),
        scopes=frozenset({"demo.write", "demo.read"}),
        trace_id=f"srt-{ctx.run_id[:8]}",
        autonomy_ceiling="A4",
        autonomy_level="A4",
    )


class Door:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        provider: Provider,
        crash: Crash,
        *,
        dispatch_log: bool = True,
    ) -> None:
        self.sessions = sessions
        self.provider = provider
        self.crash = crash
        self.store = SqlToolExecutionStore(sessions)

        async def handler(payload: BaseModel, rc: RunContext) -> SendOutput:
            assert isinstance(payload, SendInput)
            answer = await provider.send(payload, rc.run_id)
            crash.at("K4", payload.step_id, None)  # 2xx came back, nothing recorded yet
            return answer

        registry = ToolRegistry()
        registry.register(
            RegisteredTool(
                definition=ToolDefinition(
                    name=TOOL,
                    version=VERSION,
                    description="Send through a fake provider",
                    input_schema_ref="contracts/tools/prov.send/input.json",
                    output_schema_ref="contracts/tools/prov.send/output.json",
                    required_scopes=frozenset({"demo.write"}),
                    side_effect_level="external",
                    approval_policy="conditional",
                    timeout_seconds=TIMEOUT_SECONDS,
                    max_retries=0,
                    idempotent=True,
                    data_classification=frozenset({"internal"}),
                ),
                behaviour=pydantic_behaviour(SendInput, SendOutput, handler),
            )
        )
        self.executor = ToolExecutor(
            registry=registry,
            execution_store=self.store,
            uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
            clock=SystemClock(),
            id_generator=Uuid4Generator(),
            approval_policy=AutonomyApprovalPolicy(),
            claims=HookedClaims(sessions, crash=crash, dispatch_log=dispatch_log),
            steps=build_tool_executor_steps(),
            run_control=OpenRunControl(),
        )

    async def external(
        self, ctx: RunCtx, step: SrtStep, key: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        config = step.config
        faults = (ctx.run_input.get("faults") or {}).get(step.id) or {}
        mode = str(faults.get("mode", config.get("mode", "none")))
        provider = str(config.get("provider", "crm"))
        raw: dict[str, Any] = {
            "provider": provider,
            "mode": mode,
            "ref": key,
            "step_id": step.id,
            "payload": dict(payload) if isinstance(payload, Mapping) else {},
            "fault": {k: v for k, v in faults.items() if k != "mode"},
        }
        self.crash.at("K1", step.id, ctx)
        rc = run_context(ctx)
        try:
            return await self._execute(rc, raw)
        except OutcomeUnknownError:
            pass
        if mode == "none":  # on_unknown: review
            raise ParkError("outcome_review", {"idempotency_key": key})
        if mode == "lookup" and await self.provider.lookup(provider, key):
            output = {"message_id": f"lookup:{key[-12:]}", "applied": True}
            await self._close_unknown(rc, key, "succeeded", output)
            return output
        await self._close_unknown(rc, key, "failed", None)  # resend_requested
        try:
            return await self._execute(rc, raw)
        except OutcomeUnknownError as exc:
            raise ParkError("outcome_review", {"idempotency_key": key}) from exc

    async def _execute(self, rc: RunContext, raw: dict[str, Any]) -> dict[str, Any]:
        result = await self.executor.execute(
            name=TOOL, version=VERSION, raw_input=raw, run_context=rc, idempotency_key=raw["ref"]
        )
        return result.model_dump(mode="json")

    async def _close_unknown(
        self, rc: RunContext, key: str, status: str, output: dict[str, Any] | None
    ) -> None:
        async with self.sessions() as session, session.begin():
            await session.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(rc.tenant_id)}
            )
            row = (
                await session.execute(
                    sa.text(
                        "SELECT d.id, d.input_hash FROM platform.tool_executions d"
                        " WHERE d.tenant_id = :t AND d.tool_name = :tool AND d.idempotency_key = :k"
                        " AND d.status = 'dispatched' AND NOT EXISTS (SELECT 1 FROM"
                        " platform.tool_executions e WHERE e.tenant_id = d.tenant_id"
                        " AND e.dispatch_id = d.id AND e.status IN ('succeeded', 'failed'))"
                        " ORDER BY d.started_at DESC LIMIT 1"
                    ),
                    {"t": rc.tenant_id, "tool": TOOL, "k": key},
                )
            ).first()
        if row is None:
            return
        now = datetime.now(UTC)
        await self.store.record(
            rc,
            execution_id=uuid.uuid4(),
            tool_name=TOOL,
            tool_version=VERSION,
            status=status,
            input_hash=row.input_hash,
            output_hash=None,
            output=output,
            idempotency_key=key,
            error=None if status == "succeeded" else "resend_requested",
            attempts=1,
            started_at=now,
            finished_at=now,
            dispatch_id=row.id,
        )

    async def internal(
        self, ctx: RunCtx, step: SrtStep, key: str, payload: Mapping[str, Any]
    ) -> dict[str, Any]:
        """The record and its key in one transaction under the lease
        (ADR-0108 decision 6). `internal: separate` in the run input is T3's
        control: the record first, its key in a second transaction."""
        self.crash.at("K1", step.id, ctx)
        separate = ctx.run_input.get("internal") == "separate"
        values = {"tenant_id": ctx.tenant_id, "workspace_id": ctx.workspace_id}
        lease = {"run": ctx.run_id, "token": ctx.token}
        result = {"written": key}
        async with self.sessions() as session, session.begin():
            held = (await session.execute(sa.text(_BIND_FUSED), {**values, **lease})).one()
            if not held.held:
                raise LeaseLostError(ctx.run_id)
            found = (
                await session.execute(
                    sa.text("SELECT result FROM srt.internal_keys WHERE effect_key = :k"),
                    {"k": key},
                )
            ).first()
            if found is not None:
                return dict(found.result)
            await session.execute(
                sa.text(
                    "INSERT INTO srt.records (tenant_id, run_id, effect_key, payload)"
                    " VALUES (:t, :r, :k, CAST(:p AS jsonb))"
                ),
                {"t": ctx.tenant_id, "r": ctx.run_id, "k": key, "p": _json(payload)},
            )
            if not separate:
                await _remember(session, ctx, key, result)
        if separate:
            self.crash.at("K4", step.id, ctx)
            async with self.sessions() as session, session.begin():
                await session.execute(sa.text(_BIND_FUSED), {**values, **lease})
                await _remember(session, ctx, key, result)
        return result


async def _remember(session: AsyncSession, ctx: RunCtx, key: str, result: dict[str, Any]) -> None:
    await session.execute(
        sa.text(
            "INSERT INTO srt.internal_keys (tenant_id, effect_key, result)"
            " VALUES (:t, :k, CAST(:r AS jsonb)) ON CONFLICT DO NOTHING"
        ),
        {"t": ctx.tenant_id, "k": key, "r": _json(result)},
    )


def _json(value: Any) -> str:
    import json

    return json.dumps(value, default=str)
