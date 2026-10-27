"""Integration: what the application role may and may not do.

A schema with no grants passes every health check and fails on the first real
query — the probe runs ``SELECT 1``, which needs no table privilege. That is
exactly how a baseline built with ``pg_dump --no-privileges`` shipped once:
green everywhere, and an application that could not read a row.

So the privilege model is asserted, not assumed. Three claims:

* ``dw_app`` can read and write the tables it serves;
* ``dw_app`` CANNOT rewrite the audit log — append-only is a grant, not a
  convention somebody could code around;
* ``dw_app`` cannot touch the provisioning record, which belongs to a different
  role making a different decision.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls, admin_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from studio_catalog import registry_violations, studio_schema_violations
from test_rls_coverage import tenant_schemas

pytestmark = pytest.mark.integration


@pytest.fixture
async def app_engine(db_urls: DatabaseUrls) -> AsyncIterator[AsyncEngine]:
    """A connection as the runtime role, not as the migrator.

    The migrator holds BYPASSRLS and owns every object, so a test that connects
    as the migrator proves nothing about what the application is allowed to do.
    """
    engine = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        yield engine
    finally:
        await engine.dispose()


async def test_the_application_can_read_the_tables_it_serves(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        for table in (
            "platform.tenants",
            "platform.workspaces",
            "platform.users",
            "platform.memberships",
            "knowledge.documents",
            "memory.items",
        ):
            # The count is irrelevant; being allowed to ask is the assertion.
            await conn.execute(sa.text(f"SELECT count(*) FROM {table}"))


async def test_the_application_can_enter_every_tenant_schema(db_urls: DatabaseUrls) -> None:
    """Without USAGE on its schema no table grant is reachable: the first real
    query fails with "permission denied for schema" while `SELECT 1` stays green.

    The schemas come from the catalog — `tenant_schemas`, the same discovery the
    RLS coverage test uses — not from a list here. `0001_platform_grants.sql`
    grants USAGE on the schemas that existed when it was written; a schema added
    later needs its own grant, and a hand-kept list would be blind to exactly
    that schema.
    """
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            schemas = await tenant_schemas(conn)
            result = await conn.execute(
                sa.text(
                    "SELECT s FROM unnest(CAST(:schemas AS text[])) AS s"
                    " WHERE NOT has_schema_privilege('dw_app', s, 'USAGE')"
                    " ORDER BY s"
                ),
                {"schemas": schemas},
            )
            unreachable = result.scalars().all()
    finally:
        await migrator.dispose()
    assert unreachable == [], f"dw_app has no USAGE on tenant schemas: {unreachable}"


async def test_the_application_cannot_rewrite_the_audit_log(app_engine: AsyncEngine) -> None:
    """Append-only, enforced by the database.

    An UPDATE that the code would never issue is still an UPDATE the database
    must refuse: credentials reach further than the code that was reviewed.
    """
    async with app_engine.connect() as conn:
        with pytest.raises(Exception, match="permission denied"):
            await conn.execute(sa.text("UPDATE platform.audit_events SET action = 'x'"))
        await conn.rollback()
        with pytest.raises(Exception, match="permission denied"):
            await conn.execute(sa.text("DELETE FROM platform.audit_events"))


async def test_a_decision_cannot_be_rewritten(db_urls: DatabaseUrls) -> None:
    """Written once, rewritten by nothing (migration ecb47f78702c): who decided
    is also on the append-only audit log, and this copy must not disagree.
    DELETE stays, for offboarding's purge."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {
                verb: await conn.scalar(
                    sa.text(
                        "SELECT has_table_privilege('dw_app', 'platform.approval_decisions', :v)"
                    ),
                    {"v": verb},
                )
                for verb in ("SELECT", "INSERT", "UPDATE", "DELETE")
            }
    finally:
        await migrator.dispose()
    assert held == {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": True}


async def test_the_application_cannot_update_a_decision(app_engine: AsyncEngine) -> None:
    async with app_engine.connect() as conn:
        with pytest.raises(Exception, match="permission denied"):
            await conn.execute(sa.text("UPDATE platform.approval_decisions SET comment = 'x'"))


_CATALOGUE = ("platform.roles", "platform.permission_sets")


async def test_the_application_cannot_rewrite_the_role_catalogue(app_engine: AsyncEngine) -> None:
    """Which scopes a membership carries changes in migrations alone.

    No application code writes these tables, so a write under application
    credentials could only be someone widening a role past a
    separation-of-duty rule (migration 648e2f7c3edb).
    """
    async with app_engine.connect() as conn:
        for table in _CATALOGUE:
            await conn.execute(sa.text(f"SELECT count(*) FROM {table}"))
            await conn.rollback()
            for statement in (
                f"UPDATE {table} SET scopes = scopes || '[\"platform.admin\"]'::jsonb",
                f"DELETE FROM {table}",
                f"INSERT INTO {table} (key, name, scopes) VALUES ('probe', 'Probe', '[]')",
            ):
                with pytest.raises(Exception, match="permission denied"):
                    await conn.execute(sa.text(statement))
                await conn.rollback()


async def test_no_application_role_can_write_the_role_catalogue(db_urls: DatabaseUrls) -> None:
    """Asked of the catalog, so every verb and every runtime role is covered,
    `dw_provisioner` included: it is granted SELECT on roles and no more."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            writable = (
                await conn.execute(
                    sa.text(
                        """
                        SELECT r.rolname, t.tbl, v.verb
                        FROM pg_roles r
                        CROSS JOIN unnest(CAST(:tables AS text[])) AS t(tbl)
                        CROSS JOIN unnest(ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'])
                            AS v(verb)
                        WHERE r.rolname IN ('dw_app', 'dw_provisioner', 'dw_agent_ro')
                          AND has_table_privilege(r.rolname, t.tbl, v.verb)
                        """
                    ),
                    {"tables": list(_CATALOGUE)},
                )
            ).all()
    finally:
        await migrator.dispose()
    assert writable == []


async def test_the_application_cannot_write_the_retention_terms(
    app_engine: AsyncEngine, db_urls: DatabaseUrls
) -> None:
    """telemetry-and-audit R5.11: the terms change only through the loader, as
    `dw_provisioner` (82e168f6d189). Under application credentials a write could
    only be someone shortening a term, or lengthening one past what was promised."""
    async with app_engine.connect() as conn:
        await conn.execute(sa.text("SELECT count(*) FROM platform.retention_terms"))
        for statement in (
            "INSERT INTO platform.retention_terms VALUES ('platform.probe', 1)",
            "UPDATE platform.retention_terms SET term_days = 1",
            "DELETE FROM platform.retention_terms",
        ):
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(sa.text(statement))
            await conn.rollback()
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {
                (row.rolname, row.verb)
                for row in await conn.execute(
                    sa.text(
                        """
                        SELECT r.rolname, v.verb
                        FROM pg_roles r
                        CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE',
                                                'TRUNCATE']) AS v(verb)
                        WHERE r.rolname IN ('dw_app', 'dw_provisioner', 'dw_agent_ro')
                          AND has_table_privilege(r.rolname, 'platform.retention_terms', v.verb)
                        """
                    )
                )
            }
            terms = await conn.scalar(sa.text("SELECT count(*) FROM platform.retention_terms"))
    finally:
        await migrator.dispose()
    assert {verb for role, verb in held if role == "dw_app"} == {"SELECT"}
    assert {verb for role, verb in held if role == "dw_provisioner"} == {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
    }
    # The table is as the loader left it: none of the refused writes landed.
    assert terms == 1


async def test_the_application_cannot_read_the_provisioning_record(
    app_engine: AsyncEngine,
) -> None:
    async with app_engine.connect() as conn:
        with pytest.raises(Exception, match="permission denied"):
            await conn.execute(sa.text("SELECT count(*) FROM platform.provisioning_audit"))


async def test_a_table_added_later_is_readable_without_a_new_grant(
    app_engine: AsyncEngine, db_urls: DatabaseUrls
) -> None:
    """Default privileges carry, so "somebody forgot the GRANT" cannot ship.

    Written as a real table created by the migrator, because that is the case
    that goes wrong: every later migration adds tables, and each one relying on
    a hand-written grant is one release away from the failure above.
    """
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.begin() as conn:
            await conn.execute(sa.text("CREATE TABLE platform.grant_probe (id uuid PRIMARY KEY)"))
        async with app_engine.connect() as conn:
            await conn.execute(sa.text("SELECT count(*) FROM platform.grant_probe"))
        async with migrator.begin() as conn:
            await conn.execute(sa.text("DROP TABLE platform.grant_probe"))
    finally:
        await migrator.dispose()


async def test_the_application_may_only_mark_a_link_nonce_used(db_urls: DatabaseUrls) -> None:
    """`platform.channel_link_nonces` (migration 02930a73bbdf): `dw_app` issues,
    consumes and prunes nonces, and the consume may set `used_at` and nothing
    else — never move a nonce to another user or stretch its expiry. Asked of the
    catalog, so a migration that dropped the column-level grant goes red here."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:

            async def table(verb: str) -> bool:
                return bool(
                    await conn.scalar(
                        sa.text(
                            "SELECT has_table_privilege('dw_app',"
                            " 'platform.channel_link_nonces', :verb)"
                        ),
                        {"verb": verb},
                    )
                )

            async def column(name: str, verb: str) -> bool:
                return bool(
                    await conn.scalar(
                        sa.text(
                            "SELECT has_column_privilege('dw_app',"
                            " 'platform.channel_link_nonces', :col, :verb)"
                        ),
                        {"col": name, "verb": verb},
                    )
                )

            assert await table("SELECT")
            assert await table("INSERT")
            assert await table("DELETE")
            assert not await table("UPDATE")  # no table-wide UPDATE
            assert not await table("TRUNCATE")
            assert await column("used_at", "UPDATE")
            for name in ("jti", "channel", "user_id", "expires_at", "created_at"):
                assert not await column(name, "UPDATE"), name
    finally:
        await migrator.dispose()


async def test_the_application_may_only_settle_an_inbound_message_and_choose_a_workspace(
    db_urls: DatabaseUrls,
) -> None:
    """Migration 9f2becb1bf80. `channel_inbound_messages`: `dw_app` claims
    (INSERT), reads, settles (UPDATE of `outcome` only) and prunes (DELETE) —
    it can never move a claimed id to another user or re-date it.
    `channel_preferences`: `dw_app` reads, inserts and updates the chosen
    tenant/workspace, never the owning `user_id`, and never deletes (the row
    goes with the membership, by cascade). Asked of the catalog."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:

            async def table(name: str, verb: str) -> bool:
                return bool(
                    await conn.scalar(
                        sa.text("SELECT has_table_privilege('dw_app', :t, :verb)"),
                        {"t": f"platform.{name}", "verb": verb},
                    )
                )

            async def column(name: str, col: str, verb: str) -> bool:
                return bool(
                    await conn.scalar(
                        sa.text("SELECT has_column_privilege('dw_app', :t, :col, :verb)"),
                        {"t": f"platform.{name}", "col": col, "verb": verb},
                    )
                )

            inbound = "channel_inbound_messages"
            for verb in ("SELECT", "INSERT", "DELETE"):
                assert await table(inbound, verb), verb
            assert not await table(inbound, "UPDATE")
            assert not await table(inbound, "TRUNCATE")
            assert await column(inbound, "outcome", "UPDATE")
            for col in ("channel", "external_message_id", "user_id", "received_at"):
                assert not await column(inbound, col, "UPDATE"), col

            chosen = "channel_preferences"
            assert await table(chosen, "SELECT")
            assert await table(chosen, "INSERT")
            for verb in ("UPDATE", "DELETE", "TRUNCATE"):
                assert not await table(chosen, verb), verb
            assert await column(chosen, "tenant_id", "UPDATE")
            assert await column(chosen, "workspace_id", "UPDATE")
            assert not await column(chosen, "user_id", "UPDATE")

            # Migration of channels Z3: the API queues a webhook
            # update, the worker's drain takes (deletes) it; nothing edits one.
            queued = "channel_inbound_updates"
            for verb in ("SELECT", "INSERT", "DELETE"):
                assert await table(queued, verb), verb
            for verb in ("UPDATE", "TRUNCATE"):
                assert not await table(queued, verb), verb
    finally:
        await migrator.dispose()


async def test_the_application_may_only_record_views_and_spend_or_revoke_codes(
    db_urls: DatabaseUrls,
) -> None:
    """Migration e399be8c0a2d. `approval_view_receipts`: `dw_app` reads and
    inserts, never edits or deletes a receipt. `approval_decision_codes`: reads,
    inserts, and updates only `used_at`, `revoked_at`, `revoked_reason` and
    `failed_attempts` — never the hash, the comment, the owner, the approval or
    the expiry — and deletes nothing; the sweep runs through
    `prune_approval_decision_codes()`, which it may execute. Asked of the
    catalog."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:

            async def table(name: str, verb: str) -> bool:
                return bool(
                    await conn.scalar(
                        sa.text("SELECT has_table_privilege('dw_app', :t, :verb)"),
                        {"t": f"platform.{name}", "verb": verb},
                    )
                )

            async def column(name: str, col: str, verb: str) -> bool:
                return bool(
                    await conn.scalar(
                        sa.text("SELECT has_column_privilege('dw_app', :t, :col, :verb)"),
                        {"t": f"platform.{name}", "col": col, "verb": verb},
                    )
                )

            receipts = "approval_view_receipts"
            assert await table(receipts, "SELECT")
            assert await table(receipts, "INSERT")
            for verb in ("UPDATE", "DELETE", "TRUNCATE"):
                assert not await table(receipts, verb), verb

            codes = "approval_decision_codes"
            assert await table(codes, "SELECT")
            assert await table(codes, "INSERT")
            for verb in ("UPDATE", "DELETE", "TRUNCATE"):
                assert not await table(codes, verb), verb
            for col in ("used_at", "revoked_at", "revoked_reason", "failed_attempts"):
                assert await column(codes, col, "UPDATE"), col
            for col in (
                "id",
                "tenant_id",
                "workspace_id",
                "approval_id",
                "user_id",
                "receipt_id",
                "code_hash",
                "comment",
                "expires_at",
                "created_at",
            ):
                assert not await column(codes, col, "UPDATE"), col
            assert await conn.scalar(
                sa.text(
                    "SELECT has_function_privilege("
                    "'dw_app', 'platform.prune_approval_decision_codes()', 'EXECUTE')"
                )
            )
    finally:
        await migrator.dispose()


async def test_the_application_may_only_record_a_decision_on_an_approval(
    db_urls: DatabaseUrls,
) -> None:
    """`platform.approval_requests` (migration 36dabf47619c): a decision writes
    `status`, `decided_at` and `version`, and nothing else may move. Above all
    `required_scope`, the stamp of who may decide (ADR 0004). Asked of the
    catalog, so a later blanket GRANT that restored table-wide UPDATE goes red."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:

            async def table(verb: str) -> bool:
                return bool(
                    await conn.scalar(
                        sa.text(
                            "SELECT has_table_privilege('dw_app',"
                            " 'platform.approval_requests', :verb)"
                        ),
                        {"verb": verb},
                    )
                )

            async def column(name: str, verb: str) -> bool:
                return bool(
                    await conn.scalar(
                        sa.text(
                            "SELECT has_column_privilege('dw_app',"
                            " 'platform.approval_requests', :col, :verb)"
                        ),
                        {"col": name, "verb": verb},
                    )
                )

            assert await table("SELECT")
            assert await table("INSERT")
            # The offboarding lane deletes every table dw_app may DELETE.
            assert await table("DELETE")
            assert not await table("UPDATE")  # no table-wide UPDATE
            for name in ("status", "decided_at", "version"):
                assert await column(name, "UPDATE"), name
            for name in (
                "required_scope",
                "approval_type",
                "requested_by",
                "payload",
                "tenant_id",
                "workspace_id",
                "run_id",
            ):
                assert not await column(name, "UPDATE"), name
    finally:
        await migrator.dispose()


async def test_support_access_privileges(db_urls: DatabaseUrls) -> None:
    """Migration af8ee878b4ab (ADR 0024). `support_staff`: `dw_app` reads, the
    provisioner reads, adds and removes. `support_grants`: `dw_app` reads,
    inserts the customer's columns and updates only the columns of the
    customer's steps (approve, reject, revoke), never the assignment and never
    a DELETE; the provisioner reads and updates only the assignment, and may
    append to the tenant's audit log. Asked of the catalog."""
    customer_update = (
        "status",
        "granted_by",
        "granted_at",
        "rejected_by",
        "rejected_at",
        "reject_reason",
        "revoked_by",
        "revoked_at",
    )
    assignment = ("staff_user_id", "assigned_by", "activated_at", "expires_at")
    stamped = ("tenant_id", "workspace_id", "scopes", "scope_set_key", "requested_by", "code")
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:

            async def table(role: str, name: str, verb: str) -> bool:
                return bool(
                    await conn.scalar(
                        sa.text("SELECT has_table_privilege(:r, :t, :v)"),
                        {"r": role, "t": f"platform.{name}", "v": verb},
                    )
                )

            async def column(role: str, col: str, verb: str) -> bool:
                return bool(
                    await conn.scalar(
                        sa.text(
                            "SELECT has_column_privilege(:r, 'platform.support_grants', :c, :v)"
                        ),
                        {"r": role, "c": col, "v": verb},
                    )
                )

            assert await table("dw_app", "support_staff", "SELECT")
            for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not await table("dw_app", "support_staff", verb), verb
            assert await table("dw_app", "support_grants", "SELECT")
            for verb in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
                assert not await table("dw_app", "support_grants", verb), verb
            for col in customer_update:
                assert await column("dw_app", col, "UPDATE"), col
            for col in (*assignment, *stamped):
                assert not await column("dw_app", col, "UPDATE"), col
            for col in assignment:
                assert not await column("dw_app", col, "INSERT"), col

            for verb in ("SELECT", "INSERT", "DELETE"):
                assert await table("dw_provisioner", "support_staff", verb), verb
            assert await table("dw_provisioner", "support_grants", "SELECT")
            for verb in ("INSERT", "UPDATE", "DELETE"):
                assert not await table("dw_provisioner", "support_grants", verb), verb
            for col in assignment:
                assert await column("dw_provisioner", col, "UPDATE"), col
            for col in (*customer_update[1:], *stamped):
                assert not await column("dw_provisioner", col, "UPDATE"), col
            assert await table("dw_provisioner", "audit_events", "INSERT")
            for verb in ("UPDATE", "DELETE"):
                assert not await table("dw_provisioner", "audit_events", verb), verb
    finally:
        await migrator.dispose()


# ---------------------------------------------------------------------------
# The studio schema (studio-skeleton R2): SELECT by default, writes per table,
# and nobody but its owner and dw_app reaches it.
# ---------------------------------------------------------------------------

# SECURITY DEFINER functions in `studio`, each with why it must run as its
# owner. Empty until a Studio table needs one (R2.10); the test fails a definer
# that is not here and a name here that no longer exists.
_STUDIO_DEFINERS: dict[str, str] = {}


async def test_a_studio_table_is_readable_and_not_writable_by_default(
    app_engine: AsyncEngine, db_urls: DatabaseUrls
) -> None:
    """R2.1, R2.2: the schema's default privileges are SELECT and nothing else,
    so a Studio table whose migration forgot its writes fails on the first write
    instead of being open to every write the application can make (ADR 0100
    point 4). Created by the migrator, as every Studio table will be."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text("CREATE TABLE studio.grant_probe (id uuid PRIMARY KEY, name text)")
            )
        try:
            async with app_engine.connect() as conn:
                await conn.execute(sa.text("SELECT count(*) FROM studio.grant_probe"))
                await conn.rollback()
                for statement in (
                    "INSERT INTO studio.grant_probe (id) VALUES (gen_random_uuid())",
                    "UPDATE studio.grant_probe SET name = 'x'",
                    "DELETE FROM studio.grant_probe",
                ):
                    with pytest.raises(Exception, match="permission denied"):
                        await conn.execute(sa.text(statement))
                    await conn.rollback()
        finally:
            async with migrator.begin() as conn:
                await conn.execute(sa.text("DROP TABLE studio.grant_probe"))
    finally:
        await migrator.dispose()


async def test_the_studio_schema_holds_nothing_it_should_not(db_urls: DatabaseUrls) -> None:
    """R2.3-R2.5, R2.7, R2.9, R2.10 on the migrated checkout."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            assert await studio_schema_violations(conn, _STUDIO_DEFINERS) == []
    finally:
        await migrator.dispose()


async def test_only_its_owner_may_write_the_partition_registry(db_urls: DatabaseUrls) -> None:
    """R3.5: the registry is the input of a SECURITY DEFINER function, so a role
    that could write it could choose the tables that function runs DDL on."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            assert [v for v in await registry_violations(conn) if v.startswith("R3.5")] == []
    finally:
        await migrator.dispose()
    app = create_async_engine(db_urls.app, poolclass=NullPool)
    try:
        async with app.connect() as conn:
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(
                    sa.text(
                        "INSERT INTO platform.time_partitioned_tables"
                        " VALUES ('studio', 'x', false, 'probe')"
                    )
                )
    finally:
        await app.dispose()


# A probe table owned by the migrator, so the schema's default privileges apply
# exactly as they will to a real Studio table.
_PROBE = (
    "SET LOCAL ROLE dw_migrator",
    "CREATE TABLE studio.grant_probe (id uuid PRIMARY KEY, tenant_id uuid, name text)",
    "RESET ROLE",
)

# One planted defect each, with the line the check must print for it.
_PLANTED: dict[str, tuple[tuple[str, ...], str]] = {
    "a table granted to dw_provisioner": (
        ("GRANT SELECT ON studio.grant_probe TO dw_provisioner",),
        "R2.3 dw_provisioner reaches grant_probe",
    ),
    "a table granted to dw_admin": (
        ("GRANT SELECT ON studio.grant_probe TO dw_admin",),
        "R2.3 grant_probe: dw_admin holds SELECT",
    ),
    "a column granted to dw_agent_ro": (
        ("GRANT SELECT (tenant_id) ON studio.grant_probe TO dw_agent_ro",),
        "R2.3 dw_agent_ro reaches grant_probe",
    ),
    "dw_agent_ro made a member of dw_app": (
        ("GRANT dw_app TO dw_agent_ro",),
        "R2.3 dw_agent_ro is a member of dw_app",
    ),
    "dw_agent_ro made a member of the owner": (
        ("GRANT dw_migrator TO dw_agent_ro",),
        "R2.3 dw_agent_ro is a member of dw_migrator",
    ),
    "dw_agent_ro made a member of pg_read_all_data": (
        ("GRANT pg_read_all_data TO dw_agent_ro",),
        "R2.3 dw_agent_ro is a member of pg_read_all_data",
    ),
    "dw_agent_ro made a member of pg_write_all_data": (
        ("GRANT pg_write_all_data TO dw_agent_ro",),
        "R2.3 dw_agent_ro is a member of pg_write_all_data",
    ),
    "a function left executable by PUBLIC": (
        ("CREATE FUNCTION studio.probe_fn() RETURNS int LANGUAGE sql AS 'SELECT 1'",),
        "R2.4 probe_fn: PUBLIC holds EXECUTE",
    ),
    "a sequence": (("CREATE SEQUENCE studio.probe_seq",), "R2.5 sequence probe_seq"),
    "an identity column": (
        ("CREATE TABLE studio.identity_probe (id int GENERATED ALWAYS AS IDENTITY)",),
        "R2.5 identity column identity_probe.id",
    ),
    "TRUNCATE for dw_app": (
        ("GRANT TRUNCATE ON studio.grant_probe TO dw_app",),
        "R2.7 dw_app holds TRUNCATE on grant_probe",
    ),
    "CREATE on the schema for dw_app": (
        ("GRANT CREATE ON SCHEMA studio TO dw_app",),
        "R2.7 dw_app holds CREATE on schema studio",
    ),
    "a table-wide UPDATE for dw_app": (
        ("GRANT UPDATE ON studio.grant_probe TO dw_app",),
        "R2.7 dw_app holds UPDATE on grant_probe",
    ),
    "UPDATE of tenant_id for dw_app": (
        ("GRANT UPDATE (tenant_id) ON studio.grant_probe TO dw_app",),
        "R2.7 dw_app holds UPDATE on grant_probe.tenant_id",
    ),
    "a view that runs as its owner": (
        ("CREATE VIEW studio.probe_view AS SELECT id FROM studio.grant_probe",),
        "R2.9 view probe_view",
    ),
    "a materialized view": (
        ("CREATE MATERIALIZED VIEW studio.probe_mv AS SELECT 1 AS one",),
        "R2.9 materialized view probe_mv",
    ),
    "a definer with no search_path": (
        (
            "CREATE FUNCTION studio.probe_definer() RETURNS int LANGUAGE sql"
            " SECURITY DEFINER AS 'SELECT 1'",
            "REVOKE ALL ON FUNCTION studio.probe_definer() FROM PUBLIC",
        ),
        "R2.10 definer probe_definer pins no search_path",
    ),
    "an unlisted definer": (
        (
            "CREATE FUNCTION studio.probe_definer() RETURNS int LANGUAGE sql"
            " SECURITY DEFINER SET search_path = pg_catalog AS 'SELECT 1'",
            "REVOKE ALL ON FUNCTION studio.probe_definer() FROM PUBLIC",
        ),
        "R2.10 definer probe_definer is not listed",
    ),
}


async def _studio_violations_after(conn: AsyncConnection, statements: tuple[str, ...]) -> list[str]:
    for statement in (*_PROBE, *statements):
        await conn.execute(sa.text(statement))
    return await studio_schema_violations(conn, _STUDIO_DEFINERS)


@pytest.mark.parametrize("case", sorted(_PLANTED))
async def test_each_planted_studio_defect_is_named(db_urls: DatabaseUrls, case: str) -> None:
    """The check above can fail: every defect planted in a rolled-back
    transaction is named, by requirement and object."""
    statements, expected = _PLANTED[case]
    admin = create_async_engine(admin_url(db_urls), poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            found = await _studio_violations_after(conn, statements)
            await conn.rollback()
    finally:
        await admin.dispose()
    assert expected in found, found


async def test_a_column_update_on_a_plain_column_is_allowed(db_urls: DatabaseUrls) -> None:
    """R2.7 forbids the identity columns and table-wide UPDATE, not the
    column-level writes ADR 0100 point 4 asks Studio tables to grant."""
    admin = create_async_engine(admin_url(db_urls), poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            found = await _studio_violations_after(
                conn, ("GRANT UPDATE (name) ON studio.grant_probe TO dw_app",)
            )
            await conn.rollback()
    finally:
        await admin.dispose()
    assert found == [], found


@pytest.mark.parametrize("role", ["dw_app", "dw_provisioner"])
async def test_a_write_grant_on_the_registry_is_named(db_urls: DatabaseUrls, role: str) -> None:
    admin = create_async_engine(admin_url(db_urls), poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            await conn.execute(
                sa.text(f"GRANT INSERT ON platform.time_partitioned_tables TO {role}")
            )
            found = await registry_violations(conn)
            await conn.rollback()
    finally:
        await admin.dispose()
    assert any(v.startswith("R3.5") and role in v for v in found), found
