"""The vault against Postgres (connections-and-vault 02: R1.1, R1.4-R1.10, R1.14,
R2.2; CV1, CV3, CV23, CV24).

`SecretStore` seals and opens through `SqlSecretEnvelopes` on a `dw_app`
transaction scoped to one tenant, the way ticket 04's routes will; every look
at the rows themselves is the migrator's, because `dw_app` holds nothing on
`platform.secret_envelopes` (`test_privileges.py`). Each test seeds its own
tenants: the database is shared by the session.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from tenant_wide_scopes import OFFBOARDING_SCOPES

from dw_kernel.errors import ConflictError, NotFoundError
from dw_kernel.ports import SystemClock, Uuid4Generator
from dw_kernel.secret import Secret
from dw_platform.adapters.kms import LocalDevKms, UnavailableKms
from dw_platform.adapters.persistence.digital_workers_repo import SqlScopedAudit
from dw_platform.adapters.persistence.offboarding import SqlTenantOffboarding
from dw_platform.adapters.persistence.secret_envelopes import SqlSecretEnvelopes
from dw_platform.adapters.persistence.tenant_session import TenantScope, tenant_session
from dw_platform.application.secrets import (
    CredentialRevokedError,
    DataKey,
    Envelope,
    KmsPort,
    KmsUnavailableError,
    OpenedSecret,
    SecretCaller,
    SecretKeyMismatchError,
    SecretStore,
    SecretSubject,
    SecretUnreadableError,
    WrappedKey,
    kek_ref_for,
)

pytestmark = pytest.mark.integration

CANARY = "canary-91b2-không-được-lộ"
MASTER = bytes(range(32))
PERSON = uuid.UUID(int=0x5EC)


@dataclass(frozen=True)
class Company:
    tenant_id: uuid.UUID
    workspace_id: uuid.UUID
    other_workspace_id: uuid.UUID
    connection: SecretSubject
    other_connection: SecretSubject

    @property
    def caller(self) -> SecretCaller:
        return SecretCaller(tenant_id=self.tenant_id, actor_id=PERSON)


@dataclass
class SpyKms:
    inner: KmsPort
    calls: list[str] = field(default_factory=list)

    async def generate_data_key(self, kek_ref: str) -> DataKey:
        self.calls.append("generate")
        return await self.inner.generate_data_key(kek_ref)

    async def decrypt_data_key(self, kek_ref: str, key: WrappedKey) -> bytes:
        self.calls.append("decrypt")
        return await self.inner.decrypt_data_key(kek_ref, key)

    async def rewrap(self, kek_ref: str, key: WrappedKey) -> WrappedKey:
        self.calls.append("rewrap")
        return await self.inner.rewrap(kek_ref, key)


@pytest.fixture
async def migrator(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(db_urls.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.fixture
async def sessions(db_urls: DatabaseUrls) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _store(sessions: async_sessionmaker[AsyncSession], kms: KmsPort | None = None) -> SecretStore:
    return SecretStore(
        kms=kms or LocalDevKms(MASTER),
        audit=SqlScopedAudit(sessions),
        clock=SystemClock(),
        id_generator=Uuid4Generator(),
    )


async def _company(migrator: AsyncEngine) -> Company:
    tenant, ws, ws2 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    first, second = uuid.uuid4(), uuid.uuid4()
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("INSERT INTO platform.tenants (id, slug, name) VALUES (:t, :s, :s)"),
            {"t": tenant, "s": f"vault-{tenant.hex[:12]}"},
        )
        for workspace, slug in ((ws, "main"), (ws2, "second")):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                    " VALUES (:w, :t, :s, :s)"
                ),
                {"w": workspace, "t": tenant, "s": slug},
            )
        for connection in (first, second):
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.connections (id, tenant_id, owning_workspace_id,"
                    " name, connector_key, connector_major, share_scope, status)"
                    " VALUES (:c, :t, :w, 'Thử', 'probe', 1, 'workspace', 'active')"
                ),
                {"c": connection, "t": tenant, "w": ws},
            )
    return Company(
        tenant_id=tenant,
        workspace_id=ws,
        other_workspace_id=ws2,
        connection=SecretSubject("connection", first),
        other_connection=SecretSubject("connection", second),
    )


async def _put(
    sessions: async_sessionmaker[AsyncSession],
    company: Company,
    subject: SecretSubject,
    secret_field: str,
    value: str,
    *,
    kms: KmsPort | None = None,
) -> int:
    async with tenant_session(sessions, TenantScope(tenant_id=company.tenant_id)) as session:
        return await _store(sessions, kms).put(
            SqlSecretEnvelopes(session), company.caller, subject, secret_field, Secret(value)
        )


async def _open(
    sessions: async_sessionmaker[AsyncSession],
    company: Company,
    subject: SecretSubject,
    secret_field: str,
    *,
    secret_version: int | None = None,
    kms: KmsPort | None = None,
) -> OpenedSecret:
    async with tenant_session(sessions, TenantScope(tenant_id=company.tenant_id)) as session:
        return await _store(sessions, kms).open(
            SqlSecretEnvelopes(session),
            company.caller,
            subject,
            secret_field,
            secret_version=secret_version,
        )


@dataclass(frozen=True)
class _Version:
    secret_version: int
    revoked_at: datetime | None
    replaced_at: datetime | None
    ciphertext: bytes


async def _versions(
    migrator: AsyncEngine, subject: SecretSubject, secret_field: str
) -> list[_Version]:
    async with migrator.connect() as conn:
        rows = await conn.execute(
            sa.text(
                "SELECT secret_version, revoked_at, replaced_at, ciphertext"
                " FROM platform.secret_envelopes WHERE connection_id = :c AND field = :f"
                " ORDER BY secret_version"
            ),
            {"c": subject.id, "f": secret_field},
        )
        return [_Version(r[0], r[1], r[2], bytes(r[3])) for r in rows]


async def _envelope_count(migrator: AsyncEngine, tenant_id: uuid.UUID) -> int:
    async with migrator.connect() as conn:
        return int(
            await conn.scalar(
                sa.text("SELECT count(*) FROM platform.secret_envelopes WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
            or 0
        )


def _sqlstate(error: DBAPIError) -> str | None:
    cause = getattr(error.orig, "__cause__", None)
    return getattr(cause, "sqlstate", None) or getattr(error.orig, "sqlstate", None)


# ---- R1.1 -------------------------------------------------------------------


async def test_a_secret_written_opens_and_the_table_holds_no_plain_value(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    company = await _company(migrator)
    assert await _put(sessions, company, company.connection, "api_key", CANARY) == 1
    opened = await _open(sessions, company, company.connection, "api_key")
    assert (opened.secret_version, opened.value.reveal()) == (1, CANARY)
    async with migrator.connect() as conn:
        whole_row = await conn.scalar(
            sa.text(
                "SELECT string_agg(row_to_json(e)::text || encode(e.ciphertext, 'escape'), '')"
                " FROM platform.secret_envelopes e WHERE tenant_id = :t"
            ),
            {"t": company.tenant_id},
        )
    assert whole_row and CANARY not in whole_row

    [first] = await _versions(migrator, company.connection, "api_key")
    assert await _put(sessions, company, company.connection, "api_key", "second") == 2
    old, new = await _versions(migrator, company.connection, "api_key")
    assert old.ciphertext == first.ciphertext
    assert (new.secret_version, new.revoked_at, new.replaced_at) == (2, None, None)


async def test_a_version_already_taken_is_refused_by_the_unique(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Two writers that read the same next number: the second is a conflict."""
    company = await _company(migrator)
    await _put(sessions, company, company.connection, "api_key", CANARY)
    taken = Envelope(
        secret_version=1,
        alg="aes-256-gcm",
        nonce=bytes(12),
        kek_ref=kek_ref_for(company.tenant_id),
        key=WrappedKey(bytes(40), 1),
        ciphertext=b"x",
    )
    with pytest.raises(ConflictError):
        async with tenant_session(sessions, TenantScope(tenant_id=company.tenant_id)) as session:
            await SqlSecretEnvelopes(session).put(company.connection, "api_key", taken)
    assert [v.secret_version for v in await _versions(migrator, company.connection, "api_key")] == [
        1
    ]


@pytest.mark.parametrize("missing", ["nonce", "ciphertext"])
async def test_an_envelope_without_its_nonce_or_ciphertext_is_refused(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession], missing: str
) -> None:
    company = await _company(migrator)
    values = {
        "id": company.connection.id,
        "nonce": None if missing == "nonce" else bytes(12),
        "ciphertext": None if missing == "ciphertext" else b"x",
    }
    with pytest.raises(IntegrityError) as refused:
        async with tenant_session(sessions, TenantScope(tenant_id=company.tenant_id)) as session:
            await session.execute(
                sa.text(
                    "SELECT platform.put_secret('connection', :id, 'api_key', 1, 'aes-256-gcm',"
                    " :nonce, 'tenant-x', 1, '\\x00'::bytea, :ciphertext)"
                ),
                values,
            )
    assert _sqlstate(refused.value) == "23502"
    assert await _envelope_count(migrator, company.tenant_id) == 0


# ---- R1.4 (CV1) ---------------------------------------------------------------


_COPY = """
    INSERT INTO platform.secret_envelopes (id, tenant_id, connection_id, field, secret_version,
        alg, nonce, kek_ref, kek_version, wrapped_data_key, ciphertext)
    SELECT gen_random_uuid(), :tenant, :connection, :field, :version,
        alg, nonce, kek_ref, kek_version, wrapped_data_key, ciphertext
    FROM platform.secret_envelopes
    WHERE connection_id = :source AND field = 'api_key' AND secret_version = 1
"""


@pytest.mark.parametrize(
    "target", ["another connection", "another field", "another version", "another tenant"]
)
async def test_a_copied_envelope_does_not_open(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession], target: str
) -> None:
    company, other = await _company(migrator), await _company(migrator)
    await _put(sessions, company, company.connection, "api_key", CANARY)
    owner, subject, secret_field, version = {
        "another connection": (company, company.other_connection, "api_key", 1),
        "another field": (company, company.connection, "password", 1),
        "another version": (company, company.connection, "api_key", 2),
        "another tenant": (other, other.connection, "api_key", 1),
    }[target]
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(_COPY),
            {
                "tenant": owner.tenant_id,
                "connection": subject.id,
                "field": secret_field,
                "version": version,
                "source": company.connection.id,
            },
        )

    # Another tenant's copy still names this tenant's key: refused before any
    # decryption. Renamed to that tenant's key, the data key does not unwrap.
    refused = SecretKeyMismatchError if target == "another tenant" else SecretUnreadableError
    with pytest.raises(refused):
        await _open(sessions, owner, subject, secret_field)
    if target == "another tenant":
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "UPDATE platform.secret_envelopes SET kek_ref = :k WHERE connection_id = :c"
                ),
                {"k": kek_ref_for(other.tenant_id), "c": subject.id},
            )
        with pytest.raises(SecretUnreadableError):
            await _open(sessions, owner, subject, secret_field)


async def test_a_rewrapped_envelope_still_opens(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """R1.4: the rotation lane's step (ticket 06) changes only the wrapped
    data key and `kek_version`, neither in the AAD."""
    company = await _company(migrator)
    await _put(sessions, company, company.connection, "api_key", CANARY)
    rotated = LocalDevKms(MASTER, current_version=2)
    async with migrator.begin() as conn:
        kek_ref, wrapped, kek_version = (
            await conn.execute(
                sa.text(
                    "SELECT kek_ref, wrapped_data_key, kek_version FROM platform.secret_envelopes"
                    " WHERE connection_id = :c"
                ),
                {"c": company.connection.id},
            )
        ).one()
        moved = await rotated.rewrap(kek_ref, WrappedKey(bytes(wrapped), kek_version))
        await conn.execute(
            sa.text(
                "UPDATE platform.secret_envelopes SET wrapped_data_key = :w, kek_version = :v"
                " WHERE connection_id = :c"
            ),
            {"w": moved.wrapped, "v": moved.kek_version, "c": company.connection.id},
        )
    assert moved.kek_version == 2
    opened = await _open(sessions, company, company.connection, "api_key", kms=rotated)
    assert opened.value.reveal() == CANARY


# ---- R1.5 (CV3) ---------------------------------------------------------------


async def test_another_tenants_subject_is_not_there(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    mine, theirs = await _company(migrator), await _company(migrator)
    await _put(sessions, theirs, theirs.connection, "api_key", CANARY)
    with pytest.raises(CredentialRevokedError):
        await _open(sessions, mine, theirs.connection, "api_key")
    async with tenant_session(sessions, TenantScope(tenant_id=mine.tenant_id)) as session:
        opened = await session.execute(
            sa.text("SELECT * FROM platform.open_secret('connection', :c, 'api_key', NULL)"),
            {"c": theirs.connection.id},
        )
        assert opened.all() == []
        status = await session.execute(
            sa.text("SELECT * FROM platform.secret_status('connection', :c, 'api_key')"),
            {"c": theirs.connection.id},
        )
        assert status.all() == []
    # No tenant set at all: nothing either.
    async with sessions() as session, session.begin():
        unscoped = await session.execute(
            sa.text("SELECT * FROM platform.open_secret('connection', :c, 'api_key', NULL)"),
            {"c": theirs.connection.id},
        )
        assert unscoped.all() == []
        with pytest.raises(DBAPIError, match=r"app\.tenant_id is not set"):
            await session.execute(
                sa.text(
                    "SELECT platform.put_secret('connection', :c, 'api_key', 9, 'aes-256-gcm',"
                    " '\\x000000000000000000000000'::bytea, 'tenant-x', 1, '\\x00'::bytea,"
                    " '\\x00'::bytea)"
                ),
                {"c": theirs.connection.id},
            )


async def test_a_row_under_another_tenants_key_is_refused_and_audited(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """The comparison runs before the key service is asked, and the audit row
    survives the caller's rollback without naming the other tenant's key."""
    company, other = await _company(migrator), await _company(migrator)
    await _put(sessions, company, company.connection, "api_key", CANARY)
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.secret_envelopes SET kek_ref = :k WHERE connection_id = :c"),
            {"k": kek_ref_for(other.tenant_id), "c": company.connection.id},
        )
    kms = SpyKms(LocalDevKms(MASTER))

    with pytest.raises(SecretKeyMismatchError) as refused:
        await _open(sessions, company, company.connection, "api_key", kms=kms)

    assert kms.calls == []
    assert CANARY not in str(refused.value)
    async with migrator.connect() as conn:
        rows = (
            await conn.execute(
                sa.text(
                    "SELECT actor_id, workspace_id, resource_type, resource_id, details::text"
                    " FROM platform.audit_events"
                    " WHERE tenant_id = :t AND action = 'secret.key_mismatch'"
                ),
                {"t": company.tenant_id},
            )
        ).all()
    [(actor, workspace, resource_type, resource_id, details)] = rows
    assert (actor, workspace) == (PERSON, company.workspace_id)
    assert (resource_type, resource_id) == ("connection", str(company.connection.id))
    assert str(other.tenant_id) not in details and "kek_ref" not in details
    assert CANARY not in details


# ---- R1.6 (CV2) ---------------------------------------------------------------


async def test_offboarding_never_exports_an_envelope_and_deletes_them_through_connections(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    mine, theirs = await _company(migrator), await _company(migrator)
    for company in (mine, theirs):
        await _put(sessions, company, company.connection, "api_key", CANARY)
        await _put(sessions, company, company.other_connection, "password", CANARY)
    offboarding = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)
    async with sessions() as session, session.begin():
        exportable = await offboarding._exportable_tables(session)
        purgeable = await offboarding._purgeable_tables(session)
    assert ("platform", "secret_envelopes") not in exportable
    assert ("platform", "connections") in exportable
    assert ("platform", "connections") in purgeable

    async with migrator.begin() as conn:
        await conn.execute(
            sa.text("UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t"),
            {"t": mine.tenant_id},
        )
    await offboarding.purge_rows(mine.tenant_id)

    assert await _envelope_count(migrator, mine.tenant_id) == 0
    assert await _envelope_count(migrator, theirs.tenant_id) == 2
    assert (await _open(sessions, theirs, theirs.connection, "api_key")).value.reveal() == CANARY


# ---- R1.7 (CV1) ---------------------------------------------------------------


async def test_a_connections_owning_workspace_never_changes(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """Two layers, each tested: `dw_app` holds no UPDATE on the column, and the
    trigger refuses even the table's owner."""
    company = await _company(migrator)
    await _put(sessions, company, company.connection, "api_key", CANARY)
    move = sa.text("UPDATE platform.connections SET owning_workspace_id = :w WHERE id = :c")
    values = {"w": company.other_workspace_id, "c": company.connection.id}

    with pytest.raises(DBAPIError, match="permission denied"):
        async with tenant_session(sessions, TenantScope(tenant_id=company.tenant_id)) as session:
            await session.execute(move, values)
    with pytest.raises(IntegrityError, match="owning workspace does not change"):
        async with migrator.begin() as conn:
            await conn.execute(move, values)

    async with migrator.connect() as conn:
        owner = await conn.scalar(
            sa.text("SELECT owning_workspace_id FROM platform.connections WHERE id = :c"),
            {"c": company.connection.id},
        )
    assert owner == company.workspace_id
    assert (await _open(sessions, company, company.connection, "api_key")).value.reveal() == CANARY

    # Any other column of the row: accepted, from the application's own role.
    async with tenant_session(sessions, TenantScope(tenant_id=company.tenant_id)) as session:
        changed = await session.execute(
            sa.text("UPDATE platform.connections SET status = 'needs_reauth' WHERE id = :c"),
            {"c": company.connection.id},
        )
        assert changed.rowcount == 1  # type: ignore[attr-defined]


# ---- R1.8 (CV23) --------------------------------------------------------------


async def test_an_envelope_cannot_name_another_tenants_connection(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    mine, theirs = await _company(migrator), await _company(migrator)
    with pytest.raises(IntegrityError) as refused:
        async with tenant_session(sessions, TenantScope(tenant_id=mine.tenant_id)) as session:
            await session.execute(
                sa.text(
                    "SELECT platform.put_secret('connection', :c, 'api_key', 1, 'aes-256-gcm',"
                    " '\\x000000000000000000000000'::bytea, :k, 1, '\\x00'::bytea, '\\x00'::bytea)"
                ),
                {"c": theirs.connection.id, "k": kek_ref_for(mine.tenant_id)},
            )
    assert _sqlstate(refused.value) == "23503"
    assert await _envelope_count(migrator, mine.tenant_id) == 0
    assert await _envelope_count(migrator, theirs.tenant_id) == 0
    # Through the broker it is not even found under this tenant's RLS.
    with pytest.raises(NotFoundError):
        await _put(sessions, mine, theirs.connection, "api_key", CANARY)


async def test_deleting_a_connection_deletes_its_envelopes(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    company = await _company(migrator)
    await _put(sessions, company, company.connection, "api_key", CANARY)
    await _put(sessions, company, company.connection, "api_key", "second")
    await _put(sessions, company, company.other_connection, "api_key", CANARY)
    async with tenant_session(sessions, TenantScope(tenant_id=company.tenant_id)) as session:
        await session.execute(
            sa.text("DELETE FROM platform.connections WHERE id = :c"),
            {"c": company.connection.id},
        )
    assert await _versions(migrator, company.connection, "api_key") == []
    assert len(await _versions(migrator, company.other_connection, "api_key")) == 1


# ---- R1.9, R1.10, R1.14 (CV24) ----------------------------------------------------


async def _now_and_put(
    sessions: async_sessionmaker[AsyncSession],
    company: Company,
    subject: SecretSubject,
    secret_field: str,
    value: str,
) -> datetime:
    """A write, and `now()` of the transaction it ran in."""
    async with tenant_session(sessions, TenantScope(tenant_id=company.tenant_id)) as session:
        await _store(sessions).put(
            SqlSecretEnvelopes(session), company.caller, subject, secret_field, Secret(value)
        )
        now = await session.scalar(sa.text("SELECT now()"))
    assert isinstance(now, datetime)
    return now


async def test_a_new_value_replaces_the_old_one_in_its_own_transaction(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    company = await _company(migrator)
    await _put(sessions, company, company.connection, "api_key", "one")
    await _put(sessions, company, company.connection, "password", "pw")
    await _put(sessions, company, company.other_connection, "api_key", "theirs")

    written_at = await _now_and_put(sessions, company, company.connection, "api_key", "two")

    old, new = await _versions(migrator, company.connection, "api_key")
    assert (old.revoked_at, old.replaced_at) == (written_at, written_at)
    assert (new.revoked_at, new.replaced_at) == (None, None)
    for subject, secret_field in (
        (company.connection, "password"),
        (company.other_connection, "api_key"),
    ):
        [untouched] = await _versions(migrator, subject, secret_field)
        assert (untouched.revoked_at, untouched.replaced_at) == (None, None)


async def test_a_write_that_rolls_back_replaces_nothing(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    company = await _company(migrator)
    await _put(sessions, company, company.connection, "api_key", "one")

    class _AbandonedError(Exception):
        pass

    with pytest.raises(_AbandonedError):
        async with tenant_session(sessions, TenantScope(tenant_id=company.tenant_id)) as session:
            await _store(sessions).put(
                SqlSecretEnvelopes(session),
                company.caller,
                company.connection,
                "api_key",
                Secret("two"),
            )
            raise _AbandonedError

    [only] = await _versions(migrator, company.connection, "api_key")
    assert (only.secret_version, only.revoked_at, only.replaced_at) == (1, None, None)


async def test_a_signing_secret_overlaps_for_24_hours_and_a_second_rotation_moves_nothing(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    company = await _company(migrator)
    await _put(sessions, company, company.connection, "signing_secret", "one")
    first_at = await _now_and_put(sessions, company, company.connection, "signing_secret", "two")
    v1, v2 = await _versions(migrator, company.connection, "signing_secret")
    assert v1.replaced_at == first_at
    assert v1.revoked_at is not None and (v1.revoked_at - first_at).total_seconds() == 24 * 3600
    assert (v2.revoked_at, v2.replaced_at) == (None, None)

    # Still inside the overlap: the old version opens by its number, the
    # latest without one.
    assert (
        await _open(sessions, company, company.connection, "signing_secret", secret_version=1)
    ).value.reveal() == "one"
    assert (
        await _open(sessions, company, company.connection, "signing_secret")
    ).secret_version == 2

    second_at = await _now_and_put(sessions, company, company.connection, "signing_secret", "three")
    again1, again2, v3 = await _versions(migrator, company.connection, "signing_secret")
    assert (again1.revoked_at, again1.replaced_at) == (v1.revoked_at, v1.replaced_at)
    assert again2.replaced_at == second_at
    assert again2.revoked_at is not None
    assert (again2.revoked_at - second_at).total_seconds() == 24 * 3600
    assert (v3.revoked_at, v3.replaced_at) == (None, None)

    # The overlap ends: the old version is refused from then on.
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.secret_envelopes SET revoked_at = now() - interval '1 second'"
                " WHERE connection_id = :c AND field = 'signing_secret' AND secret_version = 1"
            ),
            {"c": company.connection.id},
        )
    with pytest.raises(CredentialRevokedError):
        await _open(sessions, company, company.connection, "signing_secret", secret_version=1)


async def test_a_revoked_or_missing_version_does_not_open(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    company = await _company(migrator)
    await _put(sessions, company, company.connection, "api_key", "one")
    await _put(sessions, company, company.connection, "api_key", "two")

    for version in (1, 99):
        with pytest.raises(CredentialRevokedError) as refused:
            await _open(sessions, company, company.connection, "api_key", secret_version=version)
        assert refused.value.details["reason_code"] == "credential_revoked"
        assert "one" not in str(refused.value.details.values())

    async with tenant_session(sessions, TenantScope(tenant_id=company.tenant_id)) as session:
        status = (
            (
                await session.execute(
                    sa.text("SELECT * FROM platform.secret_status('connection', :c, 'api_key')"),
                    {"c": company.connection.id},
                )
            )
            .mappings()
            .all()
        )
    assert [set(row) for row in status] == [{"secret_version", "revoked_at", "replaced_at"}] * 2
    assert status[0]["revoked_at"] is not None and status[0]["replaced_at"] is not None
    assert (status[1]["revoked_at"], status[1]["replaced_at"]) == (None, None)

    # Every version gone: as revoked as every version revoked.
    async with tenant_session(sessions, TenantScope(tenant_id=company.tenant_id)) as session:
        deleted = await session.scalar(
            sa.text("SELECT platform.delete_secret('connection', :c, 'api_key')"),
            {"c": company.connection.id},
        )
    assert deleted == 2
    with pytest.raises(CredentialRevokedError):
        await _open(sessions, company, company.connection, "api_key")


async def test_the_latest_version_opens_and_a_revoked_latest_never_falls_back(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    """R1.14: no run pins a version (V4.35); a revoked latest is the end."""
    company = await _company(migrator)
    for value in ("pw1", "pw2", "pw3"):
        await _put(sessions, company, company.connection, "password", value)
    opened = await _open(sessions, company, company.connection, "password")
    assert (opened.secret_version, opened.value.reveal()) == (3, "pw3")

    # Ticket 04's revoke-for-compromise does not exist yet: the migrator plays it.
    async with migrator.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE platform.secret_envelopes SET revoked_at = now() - interval '1 second'"
                " WHERE connection_id = :c AND field = 'password' AND secret_version = 3"
            ),
            {"c": company.connection.id},
        )
    with pytest.raises(CredentialRevokedError):
        await _open(sessions, company, company.connection, "password")


# ---- R2.2 (CV5) ---------------------------------------------------------------


async def test_without_a_key_service_no_envelope_is_written(
    migrator: AsyncEngine, sessions: async_sessionmaker[AsyncSession]
) -> None:
    company = await _company(migrator)
    with pytest.raises(KmsUnavailableError):
        await _put(sessions, company, company.connection, "api_key", CANARY, kms=UnavailableKms())
    assert await _envelope_count(migrator, company.tenant_id) == 0
