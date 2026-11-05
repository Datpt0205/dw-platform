"""Object definitions against PostgreSQL (custom-objects ticket 02).

Three parts. The catalog the revision made: the type CHECK against
`FieldType` (R2.1), the personal-data columns (R2.2), the slot set and its
indexes (R9.4), the hash partitions (R9.5), the composite keys across tenants
(R4.6), RLS on the four tables and every partition (R4.2), no DDL from
`dw_app` (CO2). Then the `object` kind's publish hook, called through its
registry entry in a transaction the test opens in place of agent-lifecycle
(the approval is the fixture's; ticket 06 runs the real path): the apply and
its idempotence (R1.1, R1.4), slots under the object's lock (R1.5), the
refusals of the live check (R2.4, R2.5), the soft delete it holds (R1.1).
Last, `seal` over the kind's validator (R1.6, R2.1, R2.2, R2.6) and the
offboarding lane over the three definition tables (R4.4).

A version goes `live` inside the hook's own transaction, as `dw_app` holds
`UPDATE (stage)`; a candidate is placed by the migrator, as
`LifecycleService` (agent-lifecycle/03) will.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
import sqlalchemy as sa
from pg_test_db import DatabaseUrls
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool
from tenant_wide_scopes import OFFBOARDING_SCOPES

from dw_kernel.errors import ConflictError
from dw_kernel.http_conditions import ExpectedVersion
from dw_kernel.ports import SystemClock, Uuid7Generator
from dw_platform.adapters.persistence.offboarding import SqlTenantOffboarding
from dw_platform.testing.personal_data import assert_field_tables_classified
from dw_platform.testing.rbac import (
    PlantedTenant,
    assign,
    plant_membership,
    plant_person,
    plant_role,
    plant_tenant,
)
from dw_studio.core.adapters.artifact_store import SqlArtifactStore, SqlArtifactTx
from dw_studio.core.application.registry import ArtifactKindEntry, ArtifactKindRegistry
from dw_studio.core.application.service import ArtifactService, SealResult
from dw_studio.core.domain.artifacts import DocumentInvalidError
from dw_studio.records.adapters.definition_store import (
    SqlObjectDefinitionReader,
    object_store_of,
)
from dw_studio.records.application.metadata import MetadataService
from dw_studio.records.domain.document import definition_of, parse_object
from dw_studio.records.domain.field_types import FIELD_TYPES, SLOTS
from dw_studio.records.domain.locks import object_lock_key
from dw_studio.records.domain.rules import ObjectVersionRejected
from dw_studio.testing.fixture_kinds import FIXTURE_KINDS, planted_fixture_kinds
from dw_studio.testing.lifecycle import move_for_test, publish_for_test, publish_on
from dw_studio.testing.objects import (
    object_document,
    object_field,
    plant_manager,
    running_kinds,
)
from dw_studio.testing.world import Person, StudioWorld, plant_world

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

_STUDIO_RELATIONS = (
    "SELECT count(*) AS n FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
    " WHERE n.nspname = 'studio'"
)


@dataclass
class World:
    studio: StudioWorld
    manager: Person
    outsider: Person

    @property
    def tenant(self) -> PlantedTenant:
        return self.studio.tenant


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def migrator(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.migrator, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def app_engine(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(studio_db.app, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def admin(studio_db: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """The superuser on this suite's database, for a probe role made and
    rolled back in one transaction."""
    url = studio_db.admin.rsplit("/", 1)[0] + "/" + studio_db.app.rsplit("/", 1)[1]
    engine = create_async_engine(url, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def world(migrator: AsyncEngine) -> AsyncIterator[World]:
    async with planted_fixture_kinds(migrator):
        async with migrator.begin() as conn:
            planted = await plant_world(conn)
            manager = await plant_manager(conn, planted.tenant)
            outsider = await plant_manager(conn, planted.other)
        yield World(planted, manager, outsider)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def sessions(app_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(app_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def service(sessions: async_sessionmaker[AsyncSession], world: World) -> ArtifactService:
    ids = Uuid7Generator()
    registry = ArtifactKindRegistry((*FIXTURE_KINDS, *running_kinds()))
    return ArtifactService(SqlArtifactStore(sessions, ids), registry, SystemClock(), ids)


def entry(service: ArtifactService) -> ArtifactKindEntry:
    found = service.registry.get("object")
    assert found is not None
    return found


def name() -> str:
    return f"o_{uuid.uuid4().hex[:12]}"


async def rows(engine: AsyncEngine, statement: str, **values: Any) -> list[Any]:
    async with engine.begin() as conn:
        result = await conn.execute(sa.text(statement), values)
        return list(result.all()) if result.returns_rows else []


def refused_by(exc: BaseException) -> str | None:
    cause = getattr(getattr(exc, "orig", None), "__cause__", None)
    return getattr(cause, "constraint_name", None) or getattr(cause, "sqlstate", None)


async def refusal(engine: AsyncEngine, statement: str, **values: Any) -> str | None:
    with pytest.raises(DBAPIError) as caught:
        await rows(engine, statement, **values)
    return refused_by(caught.value)


# ---- the path a version takes ----------------------------------------------------


async def create(service: ArtifactService, who: Person, document: Any) -> tuple[uuid.UUID, int]:
    row, draft = await service.create(
        who.context(), kind="object", api_name=name(), labels=[], document=document
    )
    return row.id, draft.row_version


async def seal(
    service: ArtifactService, who: Person, artifact_id: uuid.UUID, row_version: int
) -> SealResult:
    async with service.store.transaction(who.context()) as tx:
        return await service.seal(tx, artifact_id, row_version)


async def go_live(
    service: ArtifactService,
    who: Person,
    version_id: uuid.UUID,
) -> None:
    """The transaction agent-lifecycle opens to take a version `live`, with the
    kind's hook called through its registry entry (R1.1): the legal path of
    `dw_studio.testing.lifecycle` (an approved request, the live version
    retired `superseded` first), as `dw_app`, then the hook, in one go."""
    async with service.store.transaction(who.context()) as tx:
        assert isinstance(tx, SqlArtifactTx)
        await publish_on(tx.session, version_id)
        await entry(service).publish_hook(tx, version_id)


async def published(
    service: ArtifactService, who: Person, document: Any
) -> tuple[uuid.UUID, SealResult]:
    artifact_id, row_version = await create(service, who, document)
    sealed = await seal(service, who, artifact_id, row_version)
    await go_live(service, who, sealed.version_id)
    return artifact_id, sealed


async def sealed_next(
    service: ArtifactService, who: Person, artifact_id: uuid.UUID, document: Any
) -> SealResult:
    """A draft copied from the live version, saved with `document`, sealed."""
    context = who.context()
    row = await service.get(context, artifact_id)
    draft = await service.create_draft(context, artifact_id, ExpectedVersion(row.row_version))
    saved = (
        await service.save_draft(context, artifact_id, ExpectedVersion(draft.row_version), document)
    ).version
    return await seal(service, who, artifact_id, saved.row_version)


async def stored(
    sessions: async_sessionmaker[AsyncSession], who: Person, object_id: uuid.UUID
) -> Any:
    found = await SqlObjectDefinitionReader(sessions).read(who.tenant_id, object_id)
    assert found is not None
    return found


def twenty_fields() -> list[dict[str, Any]]:
    return [
        object_field("ten_cong_ty", indexed=True),
        object_field("email", "email", pd_category="basic", is_unique=True),
        object_field("dien_thoai", "phone", pd_category="basic", subject_identifier="phone"),
        object_field("website", "url"),
        object_field("so_nhan_vien", "number", indexed=True),
        object_field("diem", "number", number_mode="float"),
        object_field("ngan_sach", "currency", indexed=True, scale=0),
        object_field("ngay_lien_he", "date", indexed=True),
        object_field("lan_cuoi", "datetime"),
        object_field("dong_y", "boolean", indexed=True),
        object_field("giai_doan", "picklist", indexed=True, required=True),
        object_field("nguon", "picklist"),
        object_field("ghi_chu", max_length=200, ai_description="Ghi chú tự do của người bán"),
        object_field("thanh_pho", indexed=True),
        object_field("ma_so_thue", pd_category="basic", subject_identifier="tax_code"),
        object_field(
            "suc_khoe", pd_category="sensitive", sensitive_type="health", access_mode="secured"
        ),
        object_field("nganh"),
        object_field("quy_mo", "number", number_mode="exact", scale=2),
        object_field("han_chot", "date"),
        object_field("ma_noi_bo", is_unique=True),
    ]


# ================================================================ the catalog ==


async def test_r2_1_the_type_check_holds_the_field_types(migrator: AsyncEngine) -> None:
    """R2.1: `ck_field_defs_type` read from `pg_constraint` is `FieldType`."""
    found = await rows(
        migrator,
        "SELECT pg_get_constraintdef(oid) AS d FROM pg_constraint"
        " WHERE conname = 'ck_field_defs_type'",
    )
    assert set(re.findall(r"'([^']*)'::text", found[0].d)) == set(FIELD_TYPES)


async def test_r2_2_the_field_table_carries_the_kernels_classification(
    migrator: AsyncEngine,
) -> None:
    async with migrator.connect() as conn:
        await assert_field_tables_classified(conn, ["studio.field_defs"])


async def test_r9_4_the_slot_set_and_one_partial_index_per_slot(migrator: AsyncEngine) -> None:
    """R9.4: the slot columns of `pg_attribute` are `SLOTS`, each with its
    partial index `(tenant_id, object_id, <slot>, id)`, and each `u` slot
    unique among live records."""
    columns = {
        r.attname
        for r in await rows(
            migrator,
            "SELECT attname FROM pg_attribute WHERE attrelid = 'studio.records'::regclass"
            " AND attnum > 0 AND NOT attisdropped",
        )
        if re.fullmatch(r"[tuifdzb][0-9]{2}", r.attname)
    }
    assert columns == {slot for slots in SLOTS.values() for slot in slots}

    indexes = await rows(
        migrator,
        "SELECT i.indisunique AS uniq, pg_get_expr(i.indpred, i.indrelid) AS pred,"
        "  array_to_string(ARRAY(SELECT a.attname FROM unnest(i.indkey) WITH ORDINALITY k(n, o)"
        "    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = k.n"
        "    ORDER BY k.o), ',') AS cols"
        " FROM pg_index i WHERE i.indrelid = 'studio.records'::regclass",
    )
    for slot in columns:
        predicate = f"(({slot} IS NOT NULL) AND (deleted_at IS NULL))"
        plain = [i for i in indexes if i.cols == f"tenant_id,object_id,{slot},id" and not i.uniq]
        assert [i.pred for i in plain] == [predicate], slot
        unique = [i for i in indexes if i.cols == f"tenant_id,object_id,{slot}" and i.uniq]
        assert [i.pred for i in unique] == ([predicate] if slot.startswith("u") else []), slot


async def test_r9_5_records_are_four_hash_partitions_each_forced_and_closed(
    migrator: AsyncEngine,
) -> None:
    """R9.5 (the provisional DDL; ticket 07 keeps or changes it)."""
    strategy = await rows(
        migrator,
        "SELECT p.partstrat::text AS s, pg_get_partkeydef(p.partrelid) AS k"
        " FROM pg_partitioned_table p WHERE p.partrelid = 'studio.records'::regclass",
    )
    assert (strategy[0].s, strategy[0].k) == ("h", "HASH (tenant_id)")
    parts = await rows(
        migrator,
        "SELECT c.relname, c.relrowsecurity AS on_, c.relforcerowsecurity AS forced,"
        "  pg_get_expr(c.relpartbound, c.oid) AS bound,"
        "  has_table_privilege('dw_app', c.oid,"
        "    'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')"
        "  OR has_any_column_privilege('dw_app', c.oid, 'SELECT,INSERT,UPDATE') AS app"
        " FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid"
        " WHERE i.inhparent = 'studio.records'::regclass ORDER BY c.relname",
    )
    assert [p.relname for p in parts] == [f"records_p{n}" for n in range(4)]
    assert all(p.on_ and p.forced and not p.app for p in parts)
    assert [p.bound for p in parts] == [
        f"FOR VALUES WITH (modulus 4, remainder {n})" for n in range(4)
    ]


async def _object_rows(conn: Any, tenant: PlantedTenant) -> dict[str, uuid.UUID]:
    """An `object` artifact, its version, definition, one field and one record
    of `tenant`, written as the superuser past every policy. The record's owner
    is an active member of `tenant`, and the transaction is bound to it, as
    `ck_records_owner_in_tenant` requires (record-access ticket 03)."""
    ids = {key: uuid.uuid4() for key in ("artifact", "version", "field", "record")}
    await conn.execute(sa.text("SET SESSION AUTHORIZATION dw_migrator"))
    try:
        ids["owner"] = await plant_person(conn, tenant.tenant_id)
    finally:
        await conn.execute(sa.text("RESET SESSION AUTHORIZATION"))
    await conn.execute(
        sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant.tenant_id)}
    )
    statements = (
        "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name, owning_workspace_id,"
        " row_version) VALUES (:artifact, :t, 'object', :name, :w, 1)",
        "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage,"
        " document_schema, document, row_version, contributor_ids)"
        " VALUES (:version, :t, :artifact, 'draft', 'dw.object/v1', '{}', 1, ARRAY[:u]::uuid[])",
        "INSERT INTO studio.object_defs (id, tenant_id, api_name, labels, applied_version_id,"
        " schema_version, created_by, updated_by)"
        ' VALUES (:artifact, :t, :name, \'{"vi": "Đơn"}\', :version, 1, :u, :u)',
        "INSERT INTO studio.field_defs (id, tenant_id, object_id, api_name, labels, type,"
        " required, is_unique, indexed, pd_category, storage_kind, field_no, max_length,"
        " created_by, updated_by) VALUES (:field, :t, :artifact, 'ghi_chu',"
        " '{\"vi\": \"Ghi chú\"}', 'text', false, false, false, 'none', 'data', 1, 255, :u, :u)",
        "INSERT INTO studio.picklist_options (tenant_id, field_id, key, labels, position,"
        " active, created_by, updated_by)"
        " VALUES (:t, :field, 'mot', '{\"vi\": \"Một\"}', 0, true, :u, :u)",
        "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind,"
        " owner_id, name, created_by, updated_by)"
        " VALUES (:record, :t, :artifact, :w, 'user', :owner, 'Nguyễn Văn Đạt', :u, :u)",
    )
    for statement in statements:
        await conn.execute(
            sa.text(statement),
            {
                **ids,
                "t": tenant.tenant_id,
                "w": tenant.main,
                "u": uuid.uuid4(),
                "name": name(),
            },
        )
    # Unbound again: the caller's next statement chooses its own tenant.
    await conn.execute(sa.text("SELECT set_config('app.tenant_id', '', true)"))
    return ids


async def _plant_tenant(conn: Any) -> PlantedTenant:
    """`plant_tenant` as the migrator inside the superuser's transaction, which
    rolls back with it. Since tenant-rbac/03 every writer but `dw_migrator`,
    a superuser session included, is judged by `platform.rbac_guard()`, and
    installing a tenant's system roles has no person to name (`rbac_actor_missing`);
    fixtures are planted as the migrator, as tenant-rbac/03 moved its own."""
    await conn.execute(sa.text("SET SESSION AUTHORIZATION dw_migrator"))
    try:
        return await plant_tenant(conn)
    finally:
        await conn.execute(sa.text("RESET SESSION AUTHORIZATION"))


async def _tenant_in(conn: Any, remainder: int) -> PlantedTenant:
    """A planted tenant whose records hash to `records_p<remainder>`."""
    for _ in range(64):
        tenant = await _plant_tenant(conn)
        lands = await conn.scalar(
            sa.text(
                "SELECT satisfies_hash_partition("
                "'studio.records'::regclass, 4, :r, CAST(:t AS uuid))"
            ),
            {"r": remainder, "t": tenant.tenant_id},
        )
        if lands:
            return tenant
    raise AssertionError("no tenant hashed to the partition")


_DEFINITIONS = ("object_defs", "field_defs", "picklist_options")
_PARTS = tuple(f"records_p{n}" for n in range(4))


async def test_r4_2_the_tenant_policy_alone_narrows_records_and_definitions(
    admin: AsyncEngine,
) -> None:
    """R4.2 (CO1). No PERMISSIVE policy is on `studio.records` until
    record-access/03, so every row is refused already; a probe policy
    `USING (true)` for a probe role, in this transaction only, leaves the
    RESTRICTIVE tenant policy as the one thing that narrows. A NOBYPASSRLS
    probe that never sets a tenant reads nothing from the four tables nor from
    `records_p3` by name; under another tenant it cannot write this tenant's
    row; under this tenant it reads the row, so the zeros are isolation."""
    probe = f"probe_{uuid.uuid4().hex[:8]}"
    async with admin.connect() as conn:
        tx = await conn.begin()
        try:
            tenant = await _tenant_in(conn, 3)
            other = await _plant_tenant(conn)
            mine = await _object_rows(conn, tenant)
            for statement in (
                f"CREATE ROLE {probe} NOLOGIN NOBYPASSRLS",
                f"GRANT USAGE ON SCHEMA studio TO {probe}",
                *(
                    f"GRANT SELECT, INSERT ON studio.{table} TO {probe}"
                    for table in (*_DEFINITIONS, "records", *_PARTS)
                ),
                *(
                    f"CREATE POLICY probe_all ON studio.{table} TO {probe}"
                    " USING (true) WITH CHECK (true)"
                    for table in ("records", *_PARTS)
                ),
                f"SET LOCAL ROLE {probe}",
            ):
                await conn.execute(sa.text(statement))

            unscoped = {
                table: await conn.scalar(sa.text(f"SELECT count(*) FROM studio.{table}"))
                for table in (*_DEFINITIONS, "records", "records_p3")
            }
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(other.tenant_id)},
            )
            with pytest.raises(DBAPIError, match="row-level security"):
                async with conn.begin_nested():
                    await conn.execute(
                        sa.text(
                            "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id,"
                            " owner_kind, owner_id, name, created_by, updated_by)"
                            " VALUES (gen_random_uuid(), :t, :o, :w, 'user', :u, 'Khác', :u, :u)"
                        ),
                        {
                            "t": tenant.tenant_id,
                            "o": mine["artifact"],
                            "w": tenant.main,
                            "u": uuid.uuid4(),
                        },
                    )
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"),
                {"t": str(tenant.tenant_id)},
            )
            scoped = {
                table: await conn.scalar(sa.text(f"SELECT count(*) FROM studio.{table}"))
                for table in (*_DEFINITIONS, "records", "records_p3")
            }
        finally:
            await tx.rollback()

    assert unscoped == dict.fromkeys(unscoped, 0)
    assert scoped == dict.fromkeys(scoped, 1)


async def test_r4_2_dw_app_reads_no_partition_by_name(
    app_engine: AsyncEngine, world: World
) -> None:
    async with app_engine.connect() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.tenant_id', :t, true)"),
            {"t": str(world.tenant.tenant_id)},
        )
        with pytest.raises(DBAPIError, match="permission denied"):
            await conn.execute(sa.text("SELECT count(*) FROM studio.records_p3"))


@pytest.mark.parametrize("column", ["owner_kind", "owner_id", "workspace_id"])
async def test_r4_1_a_record_needs_its_owner_and_owning_workspace(
    admin: AsyncEngine, column: str
) -> None:
    async with admin.connect() as conn:
        tx = await conn.begin()
        try:
            tenant = await _plant_tenant(conn)
            ids = await _object_rows(conn, tenant)
            with pytest.raises(DBAPIError) as caught:
                await conn.execute(
                    sa.text(f"UPDATE studio.records SET {column} = NULL WHERE id = :r"),
                    {"r": ids["record"]},
                )
        finally:
            await tx.rollback()
    assert refused_by(caught.value) == "23502"


_ACROSS = {
    "records.object_id": (
        "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind,"
        " owner_id, name, created_by, updated_by) VALUES (gen_random_uuid(), :a, :b_artifact,"
        " :a_workspace, 'user', :u, 'Lan', :u, :u)",
        "fk_records_object_id_object_defs",
    ),
    "records.workspace_id": (
        "INSERT INTO studio.records (id, tenant_id, object_id, workspace_id, owner_kind,"
        " owner_id, name, created_by, updated_by) VALUES (gen_random_uuid(), :a, :a_artifact,"
        " :b_workspace, 'user', :u, 'Lan', :u, :u)",
        "fk_records_workspace_id_workspaces",
    ),
    "field_defs.object_id": (
        "INSERT INTO studio.field_defs (id, tenant_id, object_id, api_name, labels, type,"
        " required, is_unique, indexed, pd_category, storage_kind, field_no, max_length,"
        " created_by, updated_by) VALUES (gen_random_uuid(), :a, :b_artifact, 'khac',"
        " '{\"vi\": \"Khác\"}', 'text', false, false, false, 'none', 'data', 9, 255, :u, :u)",
        "fk_field_defs_object_id_object_defs",
    ),
    "picklist_options.field_id": (
        "INSERT INTO studio.picklist_options (tenant_id, field_id, key, labels, position,"
        " active, created_by, updated_by) VALUES (:a, :b_field, 'hai', '{\"vi\": \"Hai\"}',"
        " 1, true, :u, :u)",
        "fk_picklist_options_field_id_field_defs",
    ),
    "object_defs.id": (
        "INSERT INTO studio.object_defs (id, tenant_id, api_name, labels, applied_version_id,"
        " schema_version, created_by, updated_by) VALUES (:b_artifact, :a, 'muon',"
        ' \'{"vi": "Mượn"}\', :a_version, 1, :u, :u)',
        "fk_object_defs_id_artifacts",
    ),
    "object_defs.applied_version_id": (
        "INSERT INTO studio.object_defs (id, tenant_id, api_name, labels, applied_version_id,"
        " schema_version, created_by, updated_by) VALUES (:a_spare, :a, 'muon',"
        ' \'{"vi": "Mượn"}\', :b_version, 1, :u, :u)',
        "fk_object_defs_applied_version_id_artifact_versions",
    ),
    "dependencies.to_field_id": (
        "INSERT INTO studio.dependencies (id, tenant_id, from_artifact_id, from_version_id,"
        " to_kind, to_key, to_field_id, usage, path) VALUES (gen_random_uuid(), :a,"
        " :a_artifact, :a_version, 'field', :b_field_text, :b_field, 'read', '/x')",
        "fk_dependencies_to_field_id_field_defs",
    ),
}


@pytest.mark.parametrize("case", sorted(_ACROSS))
async def test_r4_6_no_key_points_into_another_company(admin: AsyncEngine, case: str) -> None:
    """R4.6 (CO1): as the migrator, which bypasses RLS, so only the composite
    key can stop the row."""
    statement, constraint = _ACROSS[case]
    async with admin.connect() as conn:
        tx = await conn.begin()
        try:
            a, b = await _plant_tenant(conn), await _plant_tenant(conn)
            mine, theirs = await _object_rows(conn, a), await _object_rows(conn, b)
            spare = uuid.uuid4()
            await conn.execute(
                sa.text(
                    "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name,"
                    " owning_workspace_id, row_version) VALUES (:s, :t, 'object', :n, :w, 1)"
                ),
                {"s": spare, "t": a.tenant_id, "n": name(), "w": a.main},
            )
            await conn.execute(sa.text("SET LOCAL ROLE dw_migrator"))
            # The owner check reads the bound tenant before the keys are asked.
            await conn.execute(
                sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(a.tenant_id)}
            )
            table = case.split(".", 1)[0]
            before = await conn.scalar(sa.text(f"SELECT count(*) FROM studio.{table}"))
            with pytest.raises(DBAPIError) as caught:
                async with conn.begin_nested():
                    await conn.execute(
                        sa.text(statement),
                        {
                            "a": a.tenant_id,
                            "a_workspace": a.main,
                            "a_artifact": mine["artifact"],
                            "a_version": mine["version"],
                            "a_spare": spare,
                            "b_artifact": theirs["artifact"],
                            "b_version": theirs["version"],
                            "b_field": theirs["field"],
                            "b_field_text": str(theirs["field"]),
                            "b_workspace": b.main,
                            "u": mine["owner"],
                        },
                    )
            after = await conn.scalar(sa.text(f"SELECT count(*) FROM studio.{table}"))
        finally:
            await tx.rollback()
    assert refused_by(caught.value) == constraint
    assert after == before


async def test_co2_dw_app_makes_no_table_and_no_index(app_engine: AsyncEngine) -> None:
    """R1.1 (CO2): no DDL at runtime."""
    for statement in (
        "CREATE TABLE studio.x (id uuid)",
        "CREATE INDEX ix_probe ON studio.records (tenant_id, name)",
    ):
        async with app_engine.connect() as conn:
            with pytest.raises(DBAPIError) as caught:
                await conn.execute(sa.text(statement))
        assert refused_by(caught.value) == "42501", statement


# ============================================================== the publish hook ==


async def test_r1_1_a_twenty_field_object_is_applied_in_the_publish_transaction(
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
) -> None:
    """R1.1 (CO2): the definition read back is `definition_of(document)`, at
    the version applied, with no relation made; the three system rows."""
    who = world.manager
    document = object_document(*twenty_fields(), ai_description="Khách hàng có thể mua")
    relations = (await rows(migrator, _STUDIO_RELATIONS))[0].n

    artifact_id, sealed = await published(service, who, document)

    found = await stored(sessions, who, artifact_id)
    assert found.definition == definition_of(document)
    assert (found.applied_version_id, found.schema_version) == (sealed.version_id, 1)
    assert (await rows(migrator, _STUDIO_RELATIONS))[0].n == relations
    system = await rows(
        migrator,
        "SELECT api_name, type, pd_category, storage_kind, slot, field_no FROM studio.field_defs"
        " WHERE object_id = :o AND storage_kind = 'system' ORDER BY api_name",
        o=artifact_id,
    )
    assert [tuple(r) for r in system] == [
        ("name", "text", "basic", "system", None, None),
        ("owner", "owner", "none", "system", None, None),
        ("workspace", "workspace", "none", "system", None, None),
    ]
    names = await rows(
        migrator,
        "SELECT o.api_name AS defined, a.api_name AS envelope FROM studio.object_defs o"
        " JOIN studio.artifacts a ON a.tenant_id = o.tenant_id AND a.id = o.id WHERE o.id = :o",
        o=artifact_id,
    )
    assert names[0].defined == names[0].envelope
    slots = {name: s.slot for name, s in found.storage.items() if s.slot}
    assert slots["email"].startswith("u") and slots["ma_noi_bo"].startswith("u")
    assert slots["ngan_sach"].startswith("i") and slots["dong_y"].startswith("b")
    assert len(set(slots.values())) == len(slots)
    data = sorted(s.field_no for s in found.storage.values() if s.storage_kind == "data")
    assert data == list(range(1, len(data) + 1))


async def _audits(migrator: AsyncEngine, object_id: uuid.UUID) -> list[Any]:
    return await rows(
        migrator,
        "SELECT action, details FROM platform.audit_events"
        " WHERE resource_type = 'studio_object' AND resource_id = :r ORDER BY occurred_at, id",
        r=str(object_id),
    )


async def _stamps(migrator: AsyncEngine, object_id: uuid.UUID) -> list[Any]:
    return await rows(
        migrator,
        "SELECT 'o' AS t, updated_at FROM studio.object_defs WHERE id = :o"
        " UNION ALL SELECT f.api_name, f.updated_at FROM studio.field_defs f WHERE object_id = :o"
        " UNION ALL SELECT p.key, p.updated_at FROM studio.picklist_options p"
        "  JOIN studio.field_defs f ON f.tenant_id = p.tenant_id AND f.id = p.field_id"
        "  WHERE f.object_id = :o ORDER BY 1, 2",
        o=object_id,
    )


async def test_r1_1_a_later_version_is_applied_whole_and_twice_is_once(
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
) -> None:
    """R1.1, R1.4: a version that narrows `default_access`, relabels a field
    and adds an option and a field is applied whole; the hook again for the
    same version changes no row and writes no audit."""
    who = world.manager
    first = object_document(
        object_field("giai_doan", "picklist", indexed=True),
        object_field("ghi_chu"),
        default_access="public_read_write",
    )
    artifact_id, _ = await published(service, who, first)
    second = object_document(
        object_field(
            "giai_doan",
            "picklist",
            indexed=True,
            options=[
                {"key": "moi", "labels": {"vi": "Mới"}, "position": 0},
                {"key": "da_lien_he", "labels": {"vi": "Đã gọi"}, "position": 1, "active": False},
                {"key": "thang", "labels": {"vi": "Thắng"}, "position": 2},
            ],
        ),
        object_field("ghi_chu", labels={"vi": "Ghi chú nội bộ"}, required=True),
        object_field("nguon", "picklist"),
        default_access="private",
    )
    v2 = await sealed_next(service, who, artifact_id, second)

    await go_live(service, who, v2.version_id)

    found = await stored(sessions, who, artifact_id)
    assert found.definition == definition_of(second)
    assert found.definition.default_access == "private"
    assert (found.applied_version_id, found.schema_version) == (v2.version_id, v2.version_no)
    audits = await _audits(migrator, artifact_id)
    stamps = await _stamps(migrator, artifact_id)
    assert {a.action for a in audits} == {
        "studio.object.created",
        "studio.object.updated",
        "studio.field.created",
        "studio.field.updated",
        "studio.picklist.updated",
    }
    for audit in audits:
        assert set(audit.details) <= {
            "object_id",
            "version_id",
            "version_no",
            "field_id",
            "api_name",
        }

    async with service.store.transaction(who.context()) as tx:
        await entry(service).publish_hook(tx, v2.version_id)

    assert await _audits(migrator, artifact_id) == audits
    assert await _stamps(migrator, artifact_id) == stamps


async def test_r1_4_default_access_defaults_to_private_and_the_check_names_itself(
    service: ArtifactService, migrator: AsyncEngine, world: World
) -> None:
    artifact_id, _ = await published(service, world.manager, object_document())
    found = await rows(
        migrator, "SELECT default_access FROM studio.object_defs WHERE id = :o", o=artifact_id
    )
    assert found[0].default_access == "private"
    refused = await refusal(
        migrator,
        "UPDATE studio.object_defs SET default_access = 'everyone' WHERE id = :o",
        o=artifact_id,
    )
    assert refused == "ck_object_defs_default_access"


async def test_r1_5_two_new_filtering_fields_never_share_a_slot(
    service: ArtifactService, world: World
) -> None:
    """R1.5 (CO4): each transaction takes the hook's lock, then the hook's
    slot step, holding the lock a while; the second gets the next slot."""
    who = world.manager
    artifact_id, _ = await published(service, who, object_document())
    metadata = MetadataService(object_store_of, SystemClock(), Uuid7Generator())
    parsed = parse_object(
        object_document(object_field("thanh_pho", indexed=True), object_field("quan", indexed=True))
    )

    async def add(n: int) -> str | None:
        async with service.store.transaction(who.context()) as tx:
            store = object_store_of(tx)
            await metadata.lock(store, artifact_id)
            placed = await metadata.add_field(store, artifact_id, parsed.fields[n], at="/fields/0")
            await asyncio.sleep(0.3)
            return placed.slot

    slots = await asyncio.gather(add(0), add(1))

    assert sorted(s or "" for s in slots) == ["t01", "t02"]


async def test_co4_the_slot_unique_refuses_a_second_field_in_one_slot(
    service: ArtifactService, migrator: AsyncEngine, world: World
) -> None:
    """CO4's second wall, on its own: a field written past the hook into a
    slot another field holds is refused by the partial UNIQUE."""
    artifact_id, _ = await published(
        service, world.manager, object_document(object_field("thanh_pho", indexed=True))
    )
    refused = await refusal(
        migrator,
        "INSERT INTO studio.field_defs (id, tenant_id, object_id, api_name, labels, type,"
        " required, is_unique, indexed, pd_category, storage_kind, slot, max_length,"
        " created_by, updated_by) SELECT gen_random_uuid(), tenant_id, object_id, 'quan',"
        " labels, type, false, false, true, 'none', 'slot', slot, 255, created_by, updated_by"
        " FROM studio.field_defs WHERE object_id = :o AND api_name = 'thanh_pho'",
        o=artifact_id,
    )
    assert refused == "uq_field_defs_tenant_id_object_id_slot"


async def test_r1_5_the_hook_waits_for_a_record_writers_shared_lock(
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    app_engine: AsyncEngine,
    migrator: AsyncEngine,
    world: World,
) -> None:
    who = world.manager
    artifact_id, v1 = await published(service, who, object_document())
    v2 = await sealed_next(service, who, artifact_id, object_document(object_field("moi")))
    key = object_lock_key(who.tenant_id, artifact_id)

    async with app_engine.connect() as holder:
        await holder.execute(sa.text("SELECT pg_advisory_xact_lock_shared(:k)"), {"k": key})
        task = asyncio.create_task(go_live(service, who, v2.version_id))
        for _ in range(200):
            assert not task.done(), "the hook did not wait"
            waiting = await rows(
                migrator,
                "SELECT count(*) AS n FROM pg_locks l JOIN pg_stat_activity a ON a.pid = l.pid"
                " WHERE NOT l.granted AND l.locktype = 'advisory'"
                " AND a.datname = current_database()",
            )
            if waiting[0].n:
                break
            await asyncio.sleep(0.05)
        else:
            raise AssertionError("nothing waited on the object's lock")
        assert (await stored(sessions, who, artifact_id)).applied_version_id == v1.version_id
        await holder.rollback()
    await task

    assert (await stored(sessions, who, artifact_id)).applied_version_id == v2.version_id


async def _rejected(
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    who: Person,
    live: Any,
    proposed: Any,
) -> list[tuple[str, str]]:
    """The live check's refusal through the hook: the publish rolls back,
    the definition and the version's stage are as before."""
    artifact_id, v1 = await published(service, who, live)
    v2 = await sealed_next(service, who, artifact_id, proposed)
    before = await stored(sessions, who, artifact_id)

    with pytest.raises(ObjectVersionRejected) as caught:
        await go_live(service, who, v2.version_id)

    after = await stored(sessions, who, artifact_id)
    assert after == before
    stages = await rows(
        migrator,
        "SELECT stage FROM studio.artifact_versions WHERE id = ANY(:v) ORDER BY version_no",
        v=[v1.version_id, v2.version_id],
    )
    assert [s.stage for s in stages] == ["live", "draft"]
    return [(p.pointer, p.code) for p in caught.value.problems]


async def test_r2_4_the_hook_refuses_a_version_that_drops_or_retypes_a_field(
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
) -> None:
    """R2.4 (CO6): a field renamed (gone under its old name) and another
    retyped; the 422 at submit is ticket 06's."""
    live = object_document(object_field("ghi_chu"), object_field("diem", "number"))
    proposed = object_document(
        object_field("ghi_chu_moi"), object_field("diem", "number", number_mode="float")
    )
    found = await _rejected(service, sessions, migrator, world.manager, live, proposed)
    assert found == [
        ("/fields", "field_removed"),
        ("/fields/1/number_mode", "field_immutable"),
        ("/fields/1/scale", "field_immutable"),
    ]


async def test_r2_5_the_hook_refuses_an_open_new_field_and_a_lowered_category(
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
) -> None:
    """R2.5 (CO24)."""
    sensitive = {"labels": {"vi": "Họ tên"}, "pd_category": "sensitive", "sensitive_type": "health"}
    live = object_document(
        object_field("benh_an", pd_category="sensitive", sensitive_type="health"),
        name_field=sensitive,
    )
    proposed = object_document(
        object_field("benh_an", pd_category="none"),
        object_field("email", "email", pd_category="basic", access_mode="open"),
        name_field={"labels": {"vi": "Họ tên"}, "pd_category": "none"},
    )
    found = await _rejected(service, sessions, migrator, world.manager, live, proposed)
    assert found == [
        ("/name_field/pd_category", "pd_category_lowered"),
        ("/fields/0/pd_category", "pd_category_lowered"),
        ("/fields/1/access_mode", "personal_data_field_open"),
    ]


async def test_tenant_rbac_r9_9_a_field_a_service_account_reads_does_not_become_sensitive(
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
) -> None:
    """tenant-rbac R9.9 (RB44): a role holding `fld.*` on `ghi_chu` is held by
    a service account; the version making `ghi_chu` sensitive is refused at
    the hook with its reason, and the publish rolls back (V4.18)."""
    who = world.manager
    live = object_document(object_field("ghi_chu", pd_category="basic"))
    artifact_id, _ = await published(service, who, live)
    async with migrator.begin() as conn:
        field = await conn.scalar(
            sa.text(
                "SELECT id FROM studio.field_defs WHERE object_id = :o AND api_name = 'ghi_chu'"
            ),
            {"o": artifact_id},
        )
        role = await plant_role(conn, who.tenant_id, f"svc_{uuid.uuid4().hex[:10]}", {})
        await conn.execute(
            sa.text(
                "INSERT INTO studio.field_permissions (tenant_id, role_id, field_id, access)"
                " VALUES (:t, :r, :f, 'read')"
            ),
            {"t": who.tenant_id, "r": role, "f": field},
        )
        account = await plant_person(conn, who.tenant_id, kind="service")
        await conn.execute(
            sa.text(
                "INSERT INTO platform.service_principals (user_id, tenant_id, name,"
                " owner_user_id, owning_workspace_id) VALUES (:u, :t, :n, :o, :w)"
            ),
            {
                "u": account,
                "t": who.tenant_id,
                "n": f"svc-{account.hex[:8]}",
                "o": who.id,
                "w": who.workspace_id,
            },
        )
        membership = await plant_membership(conn, who.tenant_id, who.workspace_id, account)
        await assign(conn, who.tenant_id, who.workspace_id, membership, role)
    proposed = object_document(
        object_field("ghi_chu", pd_category="sensitive", sensitive_type="identity_credentials")
    )
    v2 = await sealed_next(service, who, artifact_id, proposed)
    before = await stored(sessions, who, artifact_id)

    with pytest.raises(ObjectVersionRejected) as caught:
        await go_live(service, who, v2.version_id)

    assert [p.code for p in caught.value.problems] == ["field_held_by_service_account"]
    assert await stored(sessions, who, artifact_id) == before
    stage = await rows(
        migrator, "SELECT stage FROM studio.artifact_versions WHERE id = :v", v=v2.version_id
    )
    assert stage[0].stage == "draft"


async def test_the_reader_answers_for_its_own_tenant_only(
    service: ArtifactService, sessions: async_sessionmaker[AsyncSession], world: World
) -> None:
    artifact_id, _ = await published(service, world.manager, object_document(object_field("x1")))
    reader = SqlObjectDefinitionReader(sessions)
    assert await reader.read(world.manager.tenant_id, artifact_id) is not None
    assert await reader.read(world.outsider.tenant_id, artifact_id) is None


# ============================================================ the soft delete ==


async def _soft_delete(service: ArtifactService, who: Person, artifact_id: uuid.UUID) -> None:
    row = await service.get(who.context(), artifact_id)
    await service.soft_delete(who.context(), artifact_id, ExpectedVersion(row.row_version))


async def _deleted_at(migrator: AsyncEngine, artifact_id: uuid.UUID) -> Any:
    found = await rows(
        migrator, "SELECT deleted_at FROM studio.artifacts WHERE id = :a", a=artifact_id
    )
    return found[0].deleted_at


@pytest.mark.parametrize("state", ["defined", "candidate"])
async def test_r1_1_an_object_with_a_definition_or_a_candidate_is_not_deleted(
    service: ArtifactService, migrator: AsyncEngine, world: World, state: str
) -> None:
    who = world.manager
    if state == "defined":
        artifact_id, _ = await published(service, who, object_document())
    else:
        artifact_id, row_version = await create(service, who, object_document())
        sealed = await seal(service, who, artifact_id, row_version)
        await move_for_test(migrator, sealed.version_id, "awaiting_approval")

    with pytest.raises(ConflictError) as caught:
        await _soft_delete(service, who, artifact_id)

    assert caught.value.details["reason_code"] == "artifact_in_use"
    assert await _deleted_at(migrator, artifact_id) is None


async def test_r1_1_a_draft_object_and_an_unused_fixture_are_deleted(
    service: ArtifactService, migrator: AsyncEngine, world: World
) -> None:
    """The trigger is the `object` kind's alone (tenant-config R3.3 stays)."""
    artifact_id, _ = await create(service, world.manager, object_document())
    await _soft_delete(service, world.manager, artifact_id)
    assert await _deleted_at(migrator, artifact_id) is not None

    writer = world.studio["writer"]
    row, draft = await service.create(
        writer.context(),
        kind="fixture_gateless",
        api_name=name(),
        labels=[],
        document={"title": "Mẫu"},
    )
    sealed = await seal(service, writer, row.id, draft.row_version)
    await publish_for_test(migrator, sealed.version_id)
    await _soft_delete(service, writer, row.id)
    assert await _deleted_at(migrator, row.id) is not None


# =============================================================== seal's validator ==


async def _seal_refused(
    service: ArtifactService, migrator: AsyncEngine, who: Person, document: Any
) -> list[tuple[str, str]]:
    """The kind's validator in `seal`: a 422 and no version number (R2.2)."""
    artifact_id, row_version = await create(service, who, document)
    with pytest.raises(DocumentInvalidError) as caught:
        await seal(service, who, artifact_id, row_version)
    numbered = await rows(
        migrator,
        "SELECT a.last_version_no AS last, v.version_no AS no FROM studio.artifacts a"
        " JOIN studio.artifact_versions v ON v.artifact_id = a.id WHERE a.id = :a",
        a=artifact_id,
    )
    assert [(r.last, r.no) for r in numbered] == [(0, None)]
    return [(p.pointer, p.code) for p in caught.value.problems]


async def test_r2_1_r2_2_seal_refuses_a_bad_type_and_a_missing_category(
    service: ArtifactService, migrator: AsyncEngine, world: World
) -> None:
    no_category = object_field("ghi_chu")
    del no_category["pd_category"]
    document = object_document(object_field("du_lieu", "json"))
    assert await _seal_refused(service, migrator, world.manager, document) == [
        ("/fields/0/type", "value_not_allowed")
    ]
    document = object_document(no_category)
    del document["name_field"]["pd_category"]
    assert await _seal_refused(service, migrator, world.manager, document) == [
        ("/name_field/pd_category", "pd_category_required"),
        ("/fields/0", "pd_category_required"),
    ]


async def test_r1_6_r2_6_seal_refuses_a_full_family_a_bad_unique_and_a_long_description(
    service: ArtifactService, migrator: AsyncEngine, world: World
) -> None:
    fields = [object_field(f"loc_{n}", indexed=True) for n in range(25)]
    fields.append(object_field("so_luong", "number", is_unique=True))
    fields.append(object_field("mo_ta", ai_description="ư" * 501))
    found = await _seal_refused(service, migrator, world.manager, object_document(*fields))
    assert found == [
        ("/fields/25/is_unique", "unique_not_supported"),
        ("/fields/26/ai_description", "ai_description_too_long"),
        ("/fields/24", "slot_budget_exceeded"),
    ]


@pytest.mark.parametrize(
    ("assignment", "constraint"),
    [
        ("storage_kind = 'slot', field_no = NULL, indexed = true", "ck_field_defs_slot_storage"),
        ("field_no = NULL", "ck_field_defs_data_storage"),
        ("ai_description = repeat('ư', 501)", "ck_field_defs_ai_description"),
    ],
)
async def test_r1_6_r2_6_the_storage_and_length_checks_refuse_a_row_written_by_hand(
    service: ArtifactService, migrator: AsyncEngine, world: World, assignment: str, constraint: str
) -> None:
    artifact_id, _ = await published(service, world.manager, object_document(object_field("ghi")))
    refused = await refusal(
        migrator,
        f"UPDATE studio.field_defs SET {assignment} WHERE object_id = :o AND api_name = 'ghi'",
        o=artifact_id,
    )
    assert refused == constraint


async def test_r2_6_the_object_description_check_counts_characters(
    service: ArtifactService, migrator: AsyncEngine, world: World
) -> None:
    artifact_id, _ = await published(service, world.manager, object_document())
    await rows(
        migrator,
        "UPDATE studio.object_defs SET ai_description = repeat('ư', 500) WHERE id = :o",
        o=artifact_id,
    )
    refused = await refusal(
        migrator,
        "UPDATE studio.object_defs SET ai_description = repeat('ư', 501) WHERE id = :o",
        o=artifact_id,
    )
    assert refused == "ck_object_defs_ai_description"


# ================================================================== offboarding ==


async def test_r4_4_offboarding_exports_each_definition_row_once_then_purges_them(
    service: ArtifactService,
    sessions: async_sessionmaker[AsyncSession],
    migrator: AsyncEngine,
    world: World,
) -> None:
    """R4.4: two objects with fields and options, and a dependency on a field;
    the lane's own order deletes the dependency before the field and the
    definitions before their versions. The other company keeps its rows."""
    async with migrator.begin() as conn:
        leaving = await plant_tenant(conn)
        who = await plant_manager(conn, leaving)
    first, v1 = await published(
        service, who, object_document(object_field("giai_doan", "picklist"), object_field("ab"))
    )
    second, _ = await published(service, who, object_document(object_field("bc", indexed=True)))
    target = (await stored(sessions, who, second)).storage["bc"].field_id
    await rows(
        migrator,
        "INSERT INTO studio.dependencies (id, tenant_id, from_artifact_id, from_version_id,"
        " to_kind, to_key, to_field_id, usage, path)"
        " VALUES (gen_random_uuid(), :t, :a, :v, 'field', :k, :f, 'read', '/fields/0')",
        t=who.tenant_id,
        a=first,
        v=v1.version_id,
        k=str(target),
        f=target,
    )
    staying, _ = await published(service, world.manager, object_document(object_field("cd")))
    counts = (
        "SELECT (SELECT count(*) FROM studio.object_defs WHERE tenant_id = :t) AS o,"
        " (SELECT count(*) FROM studio.field_defs WHERE tenant_id = :t) AS f,"
        " (SELECT count(*) FROM studio.picklist_options WHERE tenant_id = :t) AS p"
    )
    planted = tuple((await rows(migrator, counts, t=who.tenant_id))[0])
    kept = tuple((await rows(migrator, counts, t=world.manager.tenant_id))[0])
    await rows(
        migrator,
        "UPDATE platform.tenants SET status = 'offboarding' WHERE id = :t",
        t=who.tenant_id,
    )
    lane = SqlTenantOffboarding(session_factory=sessions, scopes=OFFBOARDING_SCOPES)

    exported: dict[str, list[Any]] = {}
    async for batch in lane.export_rows(who.tenant_id):
        exported.setdefault(f"{batch.schema}.{batch.table}", []).extend(batch.rows)
    async with migrator.connect() as conn, AsyncSession(bind=conn) as session:
        order = await lane.purge_order(session)
    await lane.purge_rows(who.tenant_id)

    keys = {
        "studio.object_defs": ("id",),
        "studio.field_defs": ("id",),
        "studio.picklist_options": ("field_id", "key"),
    }
    for (table, key), expected in zip(keys.items(), planted, strict=True):
        seen = [tuple(row[k] for k in key) for row in exported.get(table, [])]
        assert len(seen) == len(set(seen)) == expected, table
    assert tuple((await rows(migrator, counts, t=who.tenant_id))[0]) == (0, 0, 0)
    assert tuple((await rows(migrator, counts, t=world.manager.tenant_id))[0]) == kept
    assert staying
    at = {table: order.index(table) for table in order}
    assert at["studio.dependencies"] < at["studio.field_defs"]
    assert at["studio.records"] < at["studio.object_defs"]
    assert at["studio.object_defs"] < at["studio.artifact_versions"]
    assert at["studio.object_defs"] < at["studio.artifacts"]
