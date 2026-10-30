"""Claims and the dispatch log on real PostgreSQL (runtime-hardening ticket 01).

Each test drives `ToolExecutor` directly, not through a graph, with the SQL
adapters wired as the API wires them and a fake provider that counts what it
received. A claim is expired by ageing its row from the migrator connection,
the way the data-model rules allow a test to age a row, rather than by a timer
knob that only tests would turn.

"The process dies" is a handler that raises a `BaseException` the executor does
not catch, through a claims port whose release does nothing: a dead process
neither records an outcome nor gives its claim back.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field

import pytest
import sqlalchemy as sa
from pydantic import BaseModel
from runtime_harness import (
    TENANT_A,
    TENANT_B,
    WORKSPACE_A,
    WORKSPACE_B,
    RuntimeUrls,
    make_run_context,
)
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from dw_agent_runtime.adapters.tool_claims import SqlToolClaimRetention, SqlToolClaims
from dw_agent_runtime.adapters.tool_execution_store import SqlToolExecutionStore
from dw_agent_runtime.autonomy import AutonomyApprovalPolicy
from dw_agent_runtime.contracts import RunContext, ToolDefinition
from dw_agent_runtime.dispatch import (
    DispatchRecord,
    NotDispatchedError,
    OutcomeUnknownError,
    RejectedError,
)
from dw_agent_runtime.executor import ToolExecutor
from dw_agent_runtime.tools import RegisteredTool, ToolRegistry
from dw_kernel.errors import ConflictError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_platform.adapters.persistence.uow import SqlPlatformUnitOfWorkFactory

pytestmark = pytest.mark.integration

TOOL = "mail.send"


class SendInput(BaseModel):
    to: str


class SendOutput(BaseModel):
    message_id: str


class _ProcessDied(BaseException):
    """Stands in for a crash: not an `Exception`, so nothing records it."""


@dataclass
class FakeProvider:
    """Counts the calls that reached the outside world."""

    received: list[str] = field(default_factory=list)

    def accept(self, to: str) -> SendOutput:
        self.received.append(to)
        return SendOutput(message_id=f"msg-{len(self.received)}")


Handler = Callable[[BaseModel, RunContext], Awaitable[SendOutput]]


@dataclass(frozen=True)
class _DeadOnRelease(SqlToolClaims):
    """A process that dies keeps its claim: release does nothing."""

    async def release(self, *args: object, **kwargs: object) -> None:
        return None


@pytest.fixture
async def sessions(urls: RuntimeUrls) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(urls.app, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def migrator(urls: RuntimeUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


def _executor(
    sessions: async_sessionmaker[AsyncSession],
    handler: Handler,
    *,
    claims: SqlToolClaims | None = None,
    timeout_seconds: int = 10,
) -> ToolExecutor:
    registry = ToolRegistry()
    registry.register(
        RegisteredTool(
            definition=ToolDefinition(
                name=TOOL,
                version="1.0.0",
                description="Send a message",
                input_schema_ref="contracts/tools/mail.send/input.json",
                output_schema_ref="contracts/tools/mail.send/output.json",
                required_scopes=frozenset({"demo.write"}),
                side_effect_level="external",
                approval_policy="conditional",
                timeout_seconds=timeout_seconds,
                max_retries=0,
                idempotent=True,
                data_classification=frozenset({"internal"}),
            ),
            input_model=SendInput,
            output_model=SendOutput,
            handler=handler,
        )
    )
    return ToolExecutor(
        registry=registry,
        execution_store=SqlToolExecutionStore(sessions),
        uow_factory=SqlPlatformUnitOfWorkFactory(sessions),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
        approval_policy=AutonomyApprovalPolicy(),
        claims=claims or SqlToolClaims(sessions),
    )


def _sending(provider: FakeProvider) -> Handler:
    async def handler(payload: BaseModel, run_context: RunContext) -> SendOutput:
        assert isinstance(payload, SendInput)
        return provider.accept(payload.to)

    return handler


def _dying_after_send(provider: FakeProvider) -> Handler:
    async def handler(payload: BaseModel, run_context: RunContext) -> SendOutput:
        assert isinstance(payload, SendInput)
        provider.accept(payload.to)  # the provider applied it and answered 2xx
        raise _ProcessDied

    return handler


async def _send(
    executor: ToolExecutor, key: str, *, context: RunContext | None = None, to: str = "a@x.vn"
) -> BaseModel:
    return await executor.execute(
        name=TOOL,
        version="1.0.0",
        raw_input={"to": to},
        run_context=context or make_run_context(),
        idempotency_key=key,
    )


async def _expire_claim(migrator: AsyncEngine, key: str) -> None:
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.tool_execution_claims"
                " SET claimed_at = now() - interval '2 hours',"
                "     expires_at = now() - interval '1 hour'"
                " WHERE tool_name = :tool AND idempotency_key = :key"
            ),
            {"tool": TOOL, "key": key},
        )


async def _rows(migrator: AsyncEngine, key: str, tenant: uuid.UUID = TENANT_A) -> list[str]:
    async with migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT status FROM platform.tool_executions"
                " WHERE tenant_id = :tenant AND tool_name = :tool AND idempotency_key = :key"
                " ORDER BY started_at, finished_at NULLS FIRST"
            ),
            {"tenant": tenant, "tool": TOOL, "key": key},
        )
        return [row.status for row in rows]


async def _claims(migrator: AsyncEngine, key: str) -> list[uuid.UUID]:
    async with migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT claim_token FROM platform.tool_execution_claims"
                " WHERE tool_name = :tool AND idempotency_key = :key"
            ),
            {"tool": TOOL, "key": key},
        )
        return [row.claim_token for row in rows]


def _key() -> str:
    return f"k-{uuid.uuid4()}"


# ---- R6.1, R6.2: one live claim per key, released by its own token -------------


async def test_two_calls_with_one_key_at_once_send_once(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """R6.1 (RH15)."""
    provider = FakeProvider()

    async def slow(payload: BaseModel, run_context: RunContext) -> SendOutput:
        await asyncio.sleep(0.5)
        return await _sending(provider)(payload, run_context)

    executor = _executor(sessions, slow)
    key = _key()
    context = make_run_context()
    results = await asyncio.gather(
        _send(executor, key, context=context),
        _send(executor, key, context=context),
        return_exceptions=True,
    )
    assert len(provider.received) == 1
    outcomes = sorted(type(r).__name__ for r in results)
    assert outcomes in (["ConflictError", "SendOutput"], ["SendOutput", "SendOutput"])


async def test_a_taken_over_holder_cannot_release_the_new_claim(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R6.2 (RH15)."""
    claims = SqlToolClaims(sessions)
    context = make_run_context()
    key = _key()
    old = await claims.claim(context, TOOL, key, lease_seconds=60)
    assert old is not None
    await _expire_claim(migrator, key)
    new = await claims.claim(context, TOOL, key, lease_seconds=60)
    assert new is not None and new != old

    await claims.release(context, TOOL, key, old)

    assert await _claims(migrator, key) == [new]


# ---- R6.3: the record is appended, its status is checked ------------------------


async def test_the_application_appends_records_it_cannot_rewrite(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """R6.3 (RH16)."""

    async def insert(status: str) -> None:
        async with sessions() as session, session.begin():
            await session.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)}
            )
            await session.execute(
                sa.text(
                    "INSERT INTO platform.tool_executions (id, tenant_id, workspace_id, tool_name,"
                    " tool_version, status, input_hash, started_at)"
                    " VALUES (gen_random_uuid(), :t, :w, :tool, '1', :status, 'h', now())"
                ),
                {"t": TENANT_A, "w": WORKSPACE_A, "tool": TOOL, "status": status},
            )

    await insert("dispatched")
    await insert("outcome_unknown")
    with pytest.raises(IntegrityError, match="ck_tool_executions_status"):
        await insert("bogus")
    async with sessions() as session:
        with pytest.raises(DBAPIError, match="permission denied"):
            async with session.begin():
                await session.execute(
                    sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(TENANT_A)}
                )
                await session.execute(
                    sa.text("UPDATE platform.tool_executions SET status = 'succeeded'")
                )


# ---- R6.7: the lane removes what no call took over ---------------------------------


async def test_the_lane_removes_expired_claims_and_keeps_live_ones(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R6.7 (RH19)."""
    claims = SqlToolClaims(sessions)
    context = make_run_context()
    expired, live = _key(), _key()
    assert await claims.claim(context, TOOL, expired, lease_seconds=60)
    assert await claims.claim(context, TOOL, live, lease_seconds=60)
    await _expire_claim(migrator, expired)

    await SqlToolClaimRetention(sessions).prune()

    assert await _claims(migrator, expired) == []
    assert len(await _claims(migrator, live)) == 1


# ---- R6.8, R6.14: no tenant reaches another's workspace, claim or record -----------


async def test_a_claim_cannot_name_another_tenants_workspace(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R6.8 (RH32): the composite foreign key, which RLS does not stand in for."""
    key = _key()
    with pytest.raises(IntegrityError) as raised:
        await SqlToolClaims(sessions).claim(
            make_run_context(tenant=TENANT_A, workspace=WORKSPACE_B), TOOL, key, lease_seconds=60
        )
    orig = raised.value.orig
    assert (getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)) == "23503"
    assert "fk_tool_execution_claims_tenant_id_workspaces" in str(raised.value)
    assert await _claims(migrator, key) == []


async def test_another_tenants_key_neither_blocks_nor_replays(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R6.14 (RH36): tenant A holds a live claim, a success and a send of unknown
    outcome under the key; tenant B's call with the same key runs as new."""
    key = _key()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tool_execution_claims"
                " (tenant_id, workspace_id, tool_name, idempotency_key, run_id, expires_at)"
                " VALUES (:t, :w, :tool, :key, gen_random_uuid(), now() + interval '1 hour')"
            ),
            {"t": TENANT_A, "w": WORKSPACE_A, "tool": TOOL, "key": key},
        )
        for status, output in (("succeeded", '{"message_id": "A-secret"}'), ("dispatched", None)):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.tool_executions (id, tenant_id, workspace_id, tool_name,"
                    " tool_version, status, idempotency_key, input_hash, output, started_at)"
                    " VALUES (gen_random_uuid(), :t, :w, :tool, '1.0.0', :status, :key, 'h',"
                    " CAST(:output AS jsonb), now())"
                ),
                {
                    "t": TENANT_A,
                    "w": WORKSPACE_A,
                    "tool": TOOL,
                    "status": status,
                    "key": key,
                    "output": output,
                },
            )
    provider = FakeProvider()

    result = await _send(
        _executor(sessions, _sending(provider)),
        key,
        context=make_run_context(tenant=TENANT_B, workspace=WORKSPACE_B),
    )

    assert provider.received == ["a@x.vn"]
    assert result == SendOutput(message_id="msg-1")
    assert await _rows(migrator, key, TENANT_B) == ["dispatched", "succeeded"]


# ---- R6.9, R6.10, R6.11: a send of unknown outcome is never made again --------------


async def test_a_send_that_died_after_the_provider_applied_it_is_never_resent(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R6.9 (RH33), K4: with the claim expired, and again after the lane removed it."""
    provider = FakeProvider()
    key = _key()
    with pytest.raises(_ProcessDied):
        await _send(
            _executor(sessions, _dying_after_send(provider), claims=_DeadOnRelease(sessions)),
            key,
        )
    await _expire_claim(migrator, key)
    survivor = _executor(sessions, _sending(provider))

    with pytest.raises(OutcomeUnknownError):
        await _send(survivor, key)
    await _expire_claim(migrator, key)
    await SqlToolClaimRetention(sessions).prune()
    with pytest.raises(OutcomeUnknownError):
        await _send(survivor, key)

    assert provider.received == ["a@x.vn"]
    assert await _rows(migrator, key) == ["dispatched"]


async def test_a_send_that_ended_unknown_is_never_resent(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R6.9 (RH33): the terminal row `outcome_unknown` closes nothing."""
    provider = FakeProvider()

    async def reset_after_send(payload: BaseModel, run_context: RunContext) -> SendOutput:
        await _sending(provider)(payload, run_context)
        raise OutcomeUnknownError("connection reset after DATA")

    key = _key()
    with pytest.raises(OutcomeUnknownError):
        await _send(_executor(sessions, reset_after_send), key)
    with pytest.raises(OutcomeUnknownError):
        await _send(_executor(sessions, _sending(provider)), key)

    assert provider.received == ["a@x.vn"]
    assert await _rows(migrator, key) == ["dispatched", "outcome_unknown"]


@pytest.mark.parametrize("before", ["no dispatch", "failed"])
async def test_an_expired_claim_with_every_send_known_is_taken_over_and_runs(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine, before: str
) -> None:
    """R6.10 (RH33)."""
    provider = FakeProvider()
    key = _key()
    context = make_run_context()
    if before == "no dispatch":
        assert await SqlToolClaims(sessions).claim(context, TOOL, key, lease_seconds=60)
    else:

        async def refused(payload: BaseModel, run_context: RunContext) -> SendOutput:
            raise NotDispatchedError("no byte left")

        with pytest.raises(NotDispatchedError):
            await _send(_executor(sessions, refused, claims=_DeadOnRelease(sessions)), key)
    await _expire_claim(migrator, key)

    await _send(_executor(sessions, _sending(provider)), key, context=context)

    assert provider.received == ["a@x.vn"]
    expected = ["dispatched", "succeeded"]
    assert await _rows(migrator, key) == (
        expected if before == "no dispatch" else ["dispatched", "failed", *expected]
    )


async def test_the_dispatch_row_is_committed_before_the_call_leaves(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R6.11 (RH34): a second connection sees it while the provider holds the call."""
    seen: list[list[str]] = []
    key = _key()

    async def provider_reads(payload: BaseModel, run_context: RunContext) -> SendOutput:
        seen.append(await _rows(migrator, key))
        return SendOutput(message_id="m")

    await _send(_executor(sessions, provider_reads), key)

    assert seen == [["dispatched"]]


# ---- R6.12: one terminal row per send, from the typed result -----------------------


@pytest.mark.parametrize(
    ("outcome", "status", "error"),
    [
        ("returns", "succeeded", None),
        ("not_dispatched", "failed", "not_dispatched"),
        ("rejected", "failed", "rejected:550"),
        ("untyped", "outcome_unknown", "outcome_unknown"),
        ("timeout", "outcome_unknown", "outcome_unknown"),
    ],
)
async def test_each_send_ends_in_exactly_one_row_its_typed_result_decides(
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    outcome: str,
    status: str,
    error: str | None,
) -> None:
    """R6.12 (RH34), with case T: applied, then the answer timed out."""
    provider = FakeProvider()

    async def handler(payload: BaseModel, run_context: RunContext) -> SendOutput:
        result = await _sending(provider)(payload, run_context)
        if outcome == "not_dispatched":
            raise NotDispatchedError("no byte left")
        if outcome == "rejected":
            raise RejectedError("refused", provider_code="550")
        if outcome == "untyped":
            raise RuntimeError("socket closed")
        if outcome == "timeout":
            await asyncio.sleep(5)
        return result

    key = _key()
    executor = _executor(sessions, handler, timeout_seconds=1)
    if outcome == "returns":
        await _send(executor, key)
    else:
        with pytest.raises((NotDispatchedError, RejectedError, OutcomeUnknownError)):
            await _send(executor, key)

    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT id, status, error, dispatch_id FROM platform.tool_executions"
                    " WHERE tool_name = :tool AND idempotency_key = :key"
                ),
                {"tool": TOOL, "key": key},
            )
        ).all()
    dispatched = [r for r in rows if r.status == "dispatched"]
    finished = [r for r in rows if r.status != "dispatched"]
    assert len(dispatched) == 1 and len(finished) == 1
    assert (finished[0].status, finished[0].error) == (status, error)
    assert finished[0].dispatch_id == dispatched[0].id
    assert len(provider.received) == 1


# ---- R6.13: a holder taken over before it dispatched never sends --------------------


async def test_a_stalled_holder_does_not_send_beside_the_one_that_replaced_it(
    sessions: async_sessionmaker[AsyncSession], migrator: AsyncEngine
) -> None:
    """R6.13 (RH35), case S."""
    provider = FakeProvider()
    key = _key()
    stalled = asyncio.Event()
    resume = asyncio.Event()

    @dataclass(frozen=True)
    class _StallsBeforeDispatch(SqlToolClaims):
        async def dispatch(
            self,
            run_context: RunContext,
            tool_name: str,
            idempotency_key: str,
            token: uuid.UUID,
            record: DispatchRecord,
        ) -> bool:
            stalled.set()
            await resume.wait()
            return await super().dispatch(run_context, tool_name, idempotency_key, token, record)

    old = asyncio.create_task(
        _send(_executor(sessions, _sending(provider), claims=_StallsBeforeDispatch(sessions)), key)
    )
    await stalled.wait()
    await _expire_claim(migrator, key)
    await _send(_executor(sessions, _sending(provider)), key)
    resume.set()

    with pytest.raises(ConflictError):
        await old
    assert provider.received == ["a@x.vn"]
    assert await _rows(migrator, key) == ["dispatched", "succeeded"]


# ---- step 5: the unique index answers a second success with the first ------------


async def test_a_second_success_for_one_key_returns_the_first(
    sessions: async_sessionmaker[AsyncSession],
) -> None:
    """The backstop behind the claim: `uq_tool_executions_idempotency` refuses a
    second `succeeded` row, and the store answers with the row already there."""
    store = SqlToolExecutionStore(sessions)
    context = make_run_context()
    key = _key()

    async def record(output: str) -> object | None:
        now = SystemClock().now()
        return await store.record(
            context,
            execution_id=uuid.uuid4(),
            tool_name=TOOL,
            tool_version="1.0.0",
            status="succeeded",
            input_hash="h",
            output_hash=output,
            output={"message_id": output},
            idempotency_key=key,
            error=None,
            attempts=1,
            started_at=now,
            finished_at=now,
        )

    assert await record("first") is None
    earlier = await record("second")

    assert earlier is not None
    assert getattr(earlier, "output", None) == {"message_id": "first"}
