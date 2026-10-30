"""Integration: the Send floor on real PostgreSQL, as `dw_app` (compliance-pdpl
ticket 08; ADR-0124).

R3.1 (CP7), R3.3, R3.7, R3.8 (CP18), R3.10, R3.11 (CP24), R5.6 (CP19), CP27.
The ToolExecutor's half (R3.2, R3.9) is `dw_agent_runtime`'s
`test_send_floor_executor_db.py`; the unsubscribe door's is the API's.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from dw_kernel.ports import FixedClock, Uuid4Generator
from dw_platform.adapters.persistence.marketing_send_repo import (
    SqlConsentStore,
    SqlSendFloorStore,
    SqlSuppressionStore,
)
from dw_platform.application.marketing_send import (
    ConsentLedger,
    MarketingSendPolicy,
    SendRequest,
    UnsubscribeLinks,
    UnsubscribeService,
    address_hash,
    load_send_floor_policy,
)
from dw_platform.application.work_queue import WorkScope

pytestmark = pytest.mark.integration

ROOT = Path(__file__).resolve().parents[5]
POLICY = load_send_floor_policy(ROOT / "configs" / "policies" / "marketing_send@1.0.0.yaml")
# 10:00 in Hanoi: inside the sending hours.
DAYTIME = datetime(2026, 10, 30, 3, 0, tzinfo=UTC)
SECRET = b"integration-unsubscribe-secret-0123456789"


@dataclass
class Tenant:
    id: uuid.UUID
    workspace: uuid.UUID
    other_workspace: uuid.UUID
    actor: uuid.UUID

    def scope(self, *, other: bool = False) -> WorkScope:
        return WorkScope(
            tenant_id=self.id, workspace_id=self.other_workspace if other else self.workspace
        )


@pytest.fixture
async def engines(db_urls: DatabaseUrls) -> AsyncIterator[tuple[AsyncEngine, AsyncEngine]]:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    app = create_async_engine(db_urls.app, poolclass=NullPool)
    yield migrator, app
    await migrator.dispose()
    await app.dispose()


async def seed(migrator: AsyncEngine, *, status: str = "active") -> Tenant:
    t = Tenant(uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO platform.tenants (id, slug, name, status) VALUES (:t, :s, :s, :st)"
            ),
            {"t": t.id, "s": f"msf-{t.id.hex[:12]}", "st": status},
        )
        for workspace, slug in ((t.workspace, "main"), (t.other_workspace, "other")):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                    " VALUES (:w, :t, :s, :s)"
                ),
                {"w": workspace, "t": t.id, "s": slug},
            )
        await conn.execute(
            sa.text("INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'a')"),
            {"u": t.actor, "s": f"msf-{t.actor}"},
        )
    return t


@dataclass
class Floor:
    policy: MarketingSendPolicy
    ledger: ConsentLedger
    unsubscribe: UnsubscribeService
    clock: FixedClock


def floor(app: AsyncEngine, at: datetime = DAYTIME) -> Floor:
    sessions = async_sessionmaker(app, expire_on_commit=False)
    clock = FixedClock(at)
    ids = Uuid4Generator()
    links = UnsubscribeLinks(secret=SECRET, base_url="https://app.example.com", clock=clock)
    return Floor(
        policy=MarketingSendPolicy(
            store=SqlSendFloorStore(sessions), policy=POLICY, links=links, clock=clock, ids=ids
        ),
        ledger=ConsentLedger(store=SqlConsentStore(sessions), clock=clock, ids=ids),
        unsubscribe=UnsubscribeService(links=links, store=SqlSuppressionStore(sessions)),
        clock=clock,
    )


def request(t: Tenant, address: str, key: str, **kw: Any) -> SendRequest:
    return SendRequest(
        scope=kw.pop("scope", t.scope()),
        actor_id=t.actor,
        channel="email",
        address=address,
        idempotency_key=key,
        tool_name="email.send",
        tool_version="1.0.0",
        run_id=kw.pop("run_id", None),
        root_run_id=kw.pop("root_run_id", None),
    )


async def consent(f: Floor, t: Tenant, address: str, state: str = "granted") -> uuid.UUID:
    return await f.ledger.record(
        t.scope(),
        subject=address,
        channel="email",
        state=state,  # type: ignore[arg-type]
        source="web_form",
        notice_version="1.0",
    )


async def log_rows(migrator: AsyncEngine, t: Tenant) -> list[Any]:
    async with migrator.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT outcome, blocked_reason, consent_record_id, idempotency_key,"
                        " workspace_id FROM platform.marketing_send_log WHERE tenant_id = :t"
                        " ORDER BY created_at, id"
                    ),
                    {"t": t.id},
                )
            ).all()
        )


async def audits(migrator: AsyncEngine, t: Tenant, action: str) -> list[dict[str, Any]]:
    async with migrator.connect() as conn:
        return [
            dict(r.details)
            for r in (
                await conn.execute(
                    sa.text(
                        "SELECT details FROM platform.audit_events"
                        " WHERE tenant_id = :t AND action = :a ORDER BY occurred_at"
                    ),
                    {"t": t.id, "a": action},
                )
            ).all()
        ]


async def test_the_floor_refuses_in_its_order_and_names_the_reason(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R3.1 (CP7), R3.7: no consent, a withdrawn one, a suppressed address;
    each a blocked row with its reason and one refusal event, nothing sent."""
    migrator, app = engines
    t = await seed(migrator)
    f = floor(app)
    assert (await f.policy.admit(request(t, "a@khach.vn", "k1"))).reason == "no_consent"
    await consent(f, t, "b@khach.vn")
    await consent(f, t, "B@khach.vn ", state="withdrawn")
    assert (await f.policy.admit(request(t, "b@khach.vn", "k2"))).reason == "consent_withdrawn"
    await consent(f, t, "c@khach.vn")
    link = f.policy.links.link(t.id, "email", "c@khach.vn")
    assert await f.unsubscribe.confirm(link.rsplit("/", 1)[1]) is not None
    assert (await f.policy.admit(request(t, "c@khach.vn", "k3"))).reason == "suppressed"
    rows = await log_rows(migrator, t)
    assert [(r.outcome, r.blocked_reason) for r in rows] == [
        ("blocked", "no_consent"),
        ("blocked", "consent_withdrawn"),
        ("blocked", "suppressed"),
    ]
    refused = await audits(migrator, t, "marketing.send_refused")
    assert [e["reason_code"] for e in refused] == ["no_consent", "consent_withdrawn", "suppressed"]


@pytest.mark.parametrize(
    ("at", "admitted"),
    [
        (datetime(2026, 10, 30, 13, 1, tzinfo=UTC), False),  # 20:01 in Hanoi
        (datetime(2026, 10, 30, 0, 59, tzinfo=UTC), False),  # 07:59
        (datetime(2026, 10, 30, 1, 0, tzinfo=UTC), True),  # 08:00
    ],
)
async def test_the_sending_hours_are_hanoi_time(
    engines: tuple[AsyncEngine, AsyncEngine], at: datetime, admitted: bool
) -> None:
    """R3.1 (CP7): the window is `Asia/Ho_Chi_Minh` whatever the company's
    time zone, which the floor never reads."""
    migrator, app = engines
    t = await seed(migrator)
    f = floor(app, at)
    await consent(f, t, "a@khach.vn")
    answer = await f.policy.admit(request(t, "a@khach.vn", "k1"))
    assert answer.admitted is admitted
    if not admitted:
        assert answer.reason == "quiet_hours"


async def test_an_admitted_send_is_a_dispatching_row_with_its_consent_and_link(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R3.3: the row names the consent it relied on; the admission carries a
    link signed for this tenant, channel and address."""
    migrator, app = engines
    t = await seed(migrator)
    f = floor(app)
    consent_id = await consent(f, t, "a@khach.vn")
    answer = await f.policy.admit(request(t, " A@Khach.vn", "k1"))
    assert answer.admitted and answer.consent_record_id == consent_id
    [row] = await log_rows(migrator, t)
    assert (row.outcome, row.consent_record_id, row.idempotency_key) == (
        "dispatching",
        consent_id,
        "k1",
    )
    assert answer.unsubscribe_url is not None
    claim = f.policy.links.verify(answer.unsubscribe_url.rsplit("/", 1)[1])
    assert claim is not None
    assert (claim.tenant_id, claim.address_hash) == (
        t.id,
        address_hash(t.id, "email", "a@khach.vn"),
    )


async def test_the_frequency_cap_counts_every_workspace_and_a_send_in_flight(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R3.10 (CP24): a second send to one address within 24 hours, with
    another key and from another workspace of the tenant, is refused."""
    migrator, app = engines
    t = await seed(migrator)
    f = floor(app)
    await consent(f, t, "a@khach.vn")
    assert (await f.policy.admit(request(t, "a@khach.vn", "k1"))).admitted
    second = await f.policy.admit(request(t, "a@khach.vn", "k2", scope=t.scope(other=True)))
    assert second.reason == "frequency_cap"


async def test_two_sends_to_one_address_at_once_dispatch_one(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R3.10 (CP24): the address's advisory lock serialises them."""
    migrator, app = engines
    t = await seed(migrator)
    f = floor(app)
    await consent(f, t, "a@khach.vn")
    answers = await asyncio.gather(
        f.policy.admit(request(t, "a@khach.vn", "k1")),
        f.policy.admit(request(t, "a@khach.vn", "k2")),
    )
    assert sorted(a.admitted for a in answers) == [False, True]
    assert [r.outcome for r in await log_rows(migrator, t)].count("dispatching") == 1


async def test_a_replay_of_a_dispatched_key_writes_nothing_but_asks_again(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R3.11, R3.7 (CP24): the same key again is admitted without a second
    row or a count against the caps; once the person opted out in between it is
    refused, with only its event (`replay: true`)."""
    migrator, app = engines
    t = await seed(migrator)
    f = floor(app)
    await consent(f, t, "a@khach.vn")
    assert (await f.policy.admit(request(t, "a@khach.vn", "k1"))).admitted
    again = await f.policy.admit(request(t, "a@khach.vn", "k1"))
    assert again.admitted and again.replay
    assert len(await log_rows(migrator, t)) == 1
    link = f.policy.links.link(t.id, "email", "a@khach.vn")
    await f.unsubscribe.confirm(link.rsplit("/", 1)[1])
    refused = await f.policy.admit(request(t, "a@khach.vn", "k1"))
    assert (refused.admitted, refused.reason, refused.replay) == (False, "suppressed", True)
    assert len(await log_rows(migrator, t)) == 1
    [event] = await audits(migrator, t, "marketing.send_refused")
    assert event["replay"] is True


async def test_the_recipient_cap_of_a_root_run(engines: tuple[AsyncEngine, AsyncEngine]) -> None:
    """R3.8 (CP18): 199 recipients sent, the 200th is sent, a message to one
    already sent is not counted, the 201st is refused."""
    migrator, app = engines
    t = await seed(migrator)
    f = floor(app)
    root = uuid.uuid4()
    async with migrator.begin() as conn:
        for n in range(199):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.marketing_send_log (id, tenant_id, workspace_id,"
                    " created_at, channel, address_hash, outcome, idempotency_key, root_run_id,"
                    " consent_record_id, tool_name, tool_version) VALUES (:i, :t, :w,"
                    " now() - interval '2 days', 'email', :h, 'dispatching', :k, :r, :c,"
                    " 'email.send', '1.0.0')"
                ),
                {
                    "i": uuid.uuid4(),
                    "t": t.id,
                    "w": t.workspace,
                    "h": address_hash(t.id, "email", f"r{n}@khach.vn"),
                    "k": f"seed-{n}",
                    "r": root,
                    "c": uuid.uuid4(),
                },
            )
    await consent(f, t, "r200@khach.vn")
    await consent(f, t, "r201@khach.vn")
    assert (await f.policy.admit(request(t, "r200@khach.vn", "k200", root_run_id=root))).admitted
    late = await f.policy.admit(request(t, "r201@khach.vn", "k201", root_run_id=root))
    assert late.reason == "recipient_cap"


async def test_a_suppression_outlives_everything_but_offboarding(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """R5.6 (CP19): `dw_app` cannot DELETE a suppression of an active tenant
    (23514) and the row stays; the purge function refuses an active tenant and
    deletes nothing; once the tenant is offboarding both go through."""
    migrator, app = engines
    t = await seed(migrator)
    f = floor(app)
    await consent(f, t, "a@khach.vn")
    link = f.policy.links.link(t.id, "email", "a@khach.vn")
    await f.unsubscribe.confirm(link.rsplit("/", 1)[1])

    async def as_app(statement: str) -> None:
        async with app.begin() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(t.id)}
            )
            await conn.execute(sa.text(statement), {"t": t.id})

    with pytest.raises(DBAPIError) as refused:
        await as_app("DELETE FROM platform.contact_suppressions WHERE tenant_id = :t")
    assert getattr(refused.value.orig, "sqlstate", None) == "23514"
    with pytest.raises(DBAPIError):
        await as_app("SELECT platform.purge_tenant_marketing(:t)")

    async def counts() -> tuple[int, int]:
        async with migrator.connect() as conn:
            return (
                int(
                    await conn.scalar(
                        sa.text(
                            "SELECT count(*) FROM platform.contact_suppressions"
                            " WHERE tenant_id = :t"
                        ),
                        {"t": t.id},
                    )
                ),
                int(
                    await conn.scalar(
                        sa.text(
                            "SELECT count(*) FROM platform.consent_records WHERE tenant_id = :t"
                        ),
                        {"t": t.id},
                    )
                ),
            )

    assert await counts() == (1, 1)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": t.id},
        )
    await as_app("DELETE FROM platform.contact_suppressions WHERE tenant_id = :t")
    await as_app("SELECT platform.purge_tenant_marketing(:t)")
    assert await counts() == (0, 0)


async def test_one_tenant_reaches_nothing_of_another(
    engines: tuple[AsyncEngine, AsyncEngine],
) -> None:
    """CP27: B's send to an address A has consent for is `no_consent`; A's
    unsubscribe token suppresses only for A; B reads none of A's rows; B cannot
    write a row of A into the three tables; the counts refuse an unset tenant."""
    migrator, app = engines
    a, b = await seed(migrator), await seed(migrator)
    f = floor(app)
    await consent(f, a, "x@khach.vn")
    assert (await f.policy.admit(request(a, "x@khach.vn", "ka"))).admitted
    assert (await f.policy.admit(request(b, "x@khach.vn", "kb"))).reason == "no_consent"
    link = f.policy.links.link(a.id, "email", "x@khach.vn")
    await f.unsubscribe.confirm(link.rsplit("/", 1)[1])

    async with app.begin() as conn:
        await conn.execute(
            sa.text(
                "SELECT set_config('app.tenant_id', :t, true),"
                " set_config('app.workspace_id', :w, true)"
            ),
            {"t": str(b.id), "w": str(b.workspace)},
        )
        for table in ("consent_records", "contact_suppressions", "marketing_send_log"):
            seen = await conn.scalar(
                sa.text(f"SELECT count(*) FROM platform.{table} WHERE tenant_id = :t"),
                {"t": a.id},
            )
            assert seen == 0, table
    writes = {
        "consent_records": (
            "INSERT INTO platform.consent_records (id, tenant_id, subject_ref, purpose, channel,"
            " state, source, notice_version) VALUES (gen_random_uuid(), :t, 'x', 'marketing',"
            " 'email', 'granted', 's', '1')"
        ),
        "contact_suppressions": (
            "INSERT INTO platform.contact_suppressions (tenant_id, channel, address_hash, source)"
            " VALUES (:t, 'email', repeat('b', 64), 'operator')"
        ),
        "marketing_send_log": (
            "INSERT INTO platform.marketing_send_log (id, tenant_id, workspace_id, channel,"
            " address_hash, outcome, blocked_reason, tool_name, tool_version) VALUES"
            " (gen_random_uuid(), :t, :w, 'email', repeat('b', 64), 'blocked', 'no_consent',"
            " 'email.send', '1.0.0')"
        ),
    }
    for table, statement in writes.items():
        with pytest.raises(DBAPIError, match="row-level security"):
            async with app.begin() as conn:
                await conn.execute(
                    sa.text(
                        "SELECT set_config('app.tenant_id', :b, true),"
                        " set_config('app.workspace_id', :bw, true)"
                    ),
                    {"b": str(b.id), "bw": str(b.workspace)},
                )
                await conn.execute(sa.text(statement), {"t": a.id, "w": a.workspace})
        assert table
    async with app.connect() as conn:
        with pytest.raises(DBAPIError, match=r"app\.tenant_id"):
            await conn.execute(
                sa.text("SELECT platform.marketing_sends_since('email', repeat('a', 64), now())")
            )
    async with migrator.connect() as conn:
        suppressed_for = (
            (
                await conn.execute(
                    sa.text(
                        "SELECT tenant_id FROM platform.contact_suppressions"
                        " WHERE tenant_id IN (:a, :b)"
                    ),
                    {"a": a.id, "b": b.id},
                )
            )
            .scalars()
            .all()
        )
    assert list(suppressed_for) == [a.id]
