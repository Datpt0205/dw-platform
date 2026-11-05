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

import re
import uuid
from collections.abc import AsyncIterator

import pytest
import sqlalchemy as sa
from pg_harness import DatabaseUrls, admin_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import NullPool
from studio_catalog import registry_violations, studio_schema_violations
from test_rls_coverage import tenant_schemas

from dw_platform.adapters.persistence.retention_terms import pinned_terms
from dw_platform.retention_policy import load_retention_policy
from dw_platform.testing.members import TENANT_MEMBER_SQL, tenant_member_params

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
    assert terms == len(pinned_terms(load_retention_policy()))


async def test_effect_keys_are_written_once_and_read_by_no_other_role(
    db_urls: DatabaseUrls,
) -> None:
    """app-standards ticket 02 (3c54129c940c): `dw_app` reads, inserts and
    deletes an effect key (offboarding, and replacing an expired one, R2.37) and
    never rewrites one; `dw_agent_ro` holds nothing on either key table, whose
    rows carry another caller's stored response. The three functions, the
    idempotency keys' purge of ticket 04 among them (b248d0664f47), run for
    `dw_app` and for nobody else. Asked of the catalog."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {
                (row.rolname, row.tbl, row.verb)
                for row in await conn.execute(
                    sa.text(
                        """
                        SELECT r.rolname, t.tbl, v.verb
                        FROM pg_roles r
                        CROSS JOIN unnest(ARRAY['platform.effect_keys',
                                                'platform.idempotency_keys']) AS t(tbl)
                        CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE',
                                                'TRUNCATE']) AS v(verb)
                        WHERE r.rolname IN ('dw_app', 'dw_agent_ro')
                          AND has_table_privilege(r.rolname, t.tbl, v.verb)
                        """
                    )
                )
            }
            executes = {
                (row.rolname, row.fn)
                for row in await conn.execute(
                    sa.text(
                        """
                        SELECT r.rolname, f.fn
                        FROM pg_roles r
                        CROSS JOIN unnest(ARRAY['platform.effect_key_cutoff()',
                                                'platform.purge_expired_effect_keys()',
                                                'platform.purge_expired_idempotency_keys()'])
                            AS f(fn)
                        WHERE r.rolname IN ('dw_app', 'dw_agent_ro', 'public')
                          AND has_function_privilege(r.rolname, f.fn, 'EXECUTE')
                        """
                    )
                )
            }
    finally:
        await migrator.dispose()
    assert {
        verb for role, tbl, verb in held if role == "dw_app" and tbl == "platform.effect_keys"
    } == {
        "SELECT",
        "INSERT",
        "DELETE",
    }
    assert {role for role, _, _ in held} <= {"dw_app"}, "dw_agent_ro reads a key table"
    assert executes == {
        ("dw_app", "platform.effect_key_cutoff()"),
        ("dw_app", "platform.purge_expired_effect_keys()"),
        ("dw_app", "platform.purge_expired_idempotency_keys()"),
    }


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


async def test_the_application_never_updates_or_truncates_an_identity(
    db_urls: DatabaseUrls,
) -> None:
    """`platform.external_identities` (migration 6887b6020075, R4.4): `dw_app`
    reads, links and unlinks, and that is all. No path of it updates an
    identity, and TRUNCATE would skip the triggers that keep a login identity."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {
                verb: bool(
                    await conn.scalar(
                        sa.text(
                            "SELECT has_table_privilege('dw_app',"
                            " 'platform.external_identities', :verb)"
                        ),
                        {"verb": verb},
                    )
                )
                for verb in ("SELECT", "INSERT", "DELETE", "UPDATE", "TRUNCATE")
            }
    finally:
        await migrator.dispose()

    assert held == {
        "SELECT": True,
        "INSERT": True,
        "DELETE": True,
        "UPDATE": False,
        "TRUNCATE": False,
    }


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
_STUDIO_DEFINERS: dict[str, str] = {
    # record-access ticket 02 (migration f6ea6e818d0c): the reach ledger is
    # written only by these, and `dw_app` holds SELECT on it alone.
    "ensure_principal_scope": "the door: writes the caller's own ledger row, read-only to dw_app",
    "mark_principal_stale": "trigger: marks a principal's row stale for every writer of an input",
    "bump_access_epoch": "trigger: bumps the tenant's epoch for every writer of an input",
    "purge_access_epoch": "offboarding's step for the epoch row dw_app may not delete",
    # record-access ticket 03 (migration 2c2095fbb4c7).
    "check_record_owner": (
        "trigger: reads the row's company members, which a definer caller may not, to refuse"
        " an owner who is not an active member (ck_records_owner_in_tenant)"
    ),
    # record-access ticket 04 (migration 996c234cfde3): dw_app writes no boundary row.
    "record_actor_boundary": (
        "the one writer of a data boundary and its object and field rows, which dw_app may"
        " not INSERT, so a published boundary cannot gain a row after its transaction"
    ),
    "refuse_boundary_change": (
        "trigger: reads the company's status and the parent boundary whatever the caller's"
        " settings, to refuse a change of a boundary (ck_actor_boundaries_frozen)"
    ),
}


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


# The artifact envelope (tenant-config ticket 02, step 3): table-wide INSERT
# and DELETE (the offboarding lane deletes as `dw_app`, and a trigger refuses
# it elsewhere), UPDATE only of these columns, never of the table.
# `_SLOTS` stands for every slot column of `studio.records`, read from the
# catalog, so the slot set keeps one owner (`dw_studio`'s `field_types.SLOTS`).
_SLOTS = "<slots>"
_SLOT_NAME = re.compile(r"^[tuifdzb][0-9]{2}$")
_STUDIO_WRITES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "artifact_kinds": (frozenset(), frozenset()),
    "artifacts": (
        frozenset({"INSERT", "DELETE"}),
        frozenset(
            {"api_name", "labels", "last_version_no", "row_version", "deleted_at", "updated_at"}
        ),
    ),
    "artifact_versions": (
        frozenset({"INSERT", "DELETE"}),
        frozenset(
            {
                "stage",
                "document_schema",
                "document",
                "version_no",
                "content_hash",
                "definition_hash",
                "row_version",
                "change_note",
                # The lifecycle columns (agent-lifecycle ticket 03, R1.1).
                "gate_run_id",
                "publish_approval_id",
                "tighten_only",
                "compared_live_hash",
                "contributor_ids",
                "submitted_by",
                "submitted_at",
                "published_by",
                "published_at",
                "retired_by",
                "retired_at",
                "retire_reason_code",
            }
        ),
    ),
    # A view read under the reader's own RLS (agent-lifecycle R1.5): SELECT only.
    "artifact_display_stage": (frozenset(), frozenset()),
    "definition_manifests": (frozenset({"INSERT", "DELETE"}), frozenset()),
    "dependencies": (frozenset({"INSERT", "DELETE"}), frozenset()),
    # Custom objects (custom-objects ticket 02): the definitions change only in
    # what the publish hook writes; a record never moves owner, workspace or object.
    "object_defs": (
        frozenset({"INSERT", "DELETE"}),
        frozenset(
            {
                "labels",
                "default_access",
                "ai_description",
                "applied_version_id",
                "schema_version",
                "next_field_no",
                "updated_at",
                "updated_by",
            }
        ),
    ),
    "field_defs": (
        frozenset({"INSERT", "DELETE"}),
        frozenset(
            {
                "labels",
                "ai_description",
                "required",
                "max_length",
                "pd_category",
                "sensitive_type",
                "subject_identifier",
                "updated_at",
                "updated_by",
            }
        ),
    ),
    "picklist_options": (
        frozenset({"INSERT", "DELETE"}),
        frozenset({"labels", "position", "active", "updated_at", "updated_by"}),
    ),
    # A role's field permissions (tenant-rbac ticket 04): a row changes only its
    # access, and who granted it when.
    "field_permissions": (
        frozenset({"INSERT", "DELETE"}),
        frozenset({"access", "granted_by", "granted_at"}),
    ),
    # Data boundaries (record-access ticket 04): written only by
    # `studio.record_actor_boundary`; DELETE for the offboarding lane and a
    # provisional boundary's end, the trigger refusing the rest (R6.8).
    "actor_boundaries": (frozenset({"DELETE"}), frozenset()),
    "actor_boundary_objects": (frozenset({"DELETE"}), frozenset()),
    "actor_boundary_fields": (frozenset({"DELETE"}), frozenset()),
    "records": (
        frozenset({"INSERT", "DELETE"}),
        frozenset(
            {
                "name",
                "data",
                _SLOTS,
                "version",
                "updated_at",
                "updated_by",
                "deleted_at",
                "deleted_by",
            }
        ),
    ),
}


async def test_the_artifact_envelope_grants_dw_app_its_writes_and_no_more(
    db_urls: DatabaseUrls,
) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            for table, (verbs, columns) in _STUDIO_WRITES.items():
                held = {
                    verb
                    for verb in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE")
                    if await conn.scalar(
                        sa.text("SELECT has_table_privilege('dw_app', :t, :v)"),
                        {"t": f"studio.{table}", "v": verb},
                    )
                }
                updatable = {
                    row[0]
                    for row in await conn.execute(
                        sa.text(
                            "SELECT a.attname FROM pg_attribute a"
                            " WHERE a.attrelid = CAST(:t AS regclass) AND a.attnum > 0"
                            "   AND NOT a.attisdropped"
                            "   AND has_column_privilege('dw_app', a.attrelid, a.attnum, 'UPDATE')"
                        ),
                        {"t": f"studio.{table}"},
                    )
                }
                assert held == {"SELECT", *verbs}, table
                if _SLOTS in columns:
                    slots = {
                        row[0]
                        for row in await conn.execute(
                            sa.text(
                                "SELECT attname FROM pg_attribute"
                                " WHERE attrelid = CAST(:t AS regclass) AND attnum > 0"
                                "   AND NOT attisdropped"
                            ),
                            {"t": f"studio.{table}"},
                        )
                        if _SLOT_NAME.match(row[0])
                    }
                    assert slots, table
                    columns = (columns - {_SLOTS}) | slots
                assert updatable == columns, table
                # record-access/03: a record never moves (R1.3), its key is generated.
                if table == "records":
                    assert not updatable & {
                        "owner_id",
                        "owner_kind",
                        "workspace_id",
                        "object_id",
                        "access_key",
                    }
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


# foundations-hardening ticket 03 (R5.1, R5.2, R5.4; FH12, FH13).

_REPO = __import__("pathlib").Path(__file__).resolve().parents[5]


def _module(path: str, name: str) -> object:
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, _REPO / path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _declared(grants: object) -> set[tuple[str, str, str]]:
    """(table, privilege, column) triples; a table grant has column '*'."""
    found: set[tuple[str, str, str]] = set()
    for table, verbs, columns in grants:  # type: ignore[attr-defined]
        found |= {(table, verb.strip(), "*") for verb in verbs.split(",")}
        found |= {(table, "UPDATE", column) for column in columns}
    return found


_PROVISIONER_GRANTS = sa.text(
    """
    SELECT table_schema || '.' || table_name AS tbl, privilege_type AS verb, '*' AS col
    FROM information_schema.role_table_grants WHERE grantee = 'dw_provisioner'
    UNION
    SELECT c.table_schema || '.' || c.table_name, c.privilege_type, c.column_name
    FROM information_schema.column_privileges c
    WHERE c.grantee = 'dw_provisioner'
      AND NOT EXISTS (
        SELECT 1 FROM information_schema.role_table_grants t
        WHERE t.grantee = 'dw_provisioner' AND t.table_schema = c.table_schema
          AND t.table_name = c.table_name AND t.privilege_type = c.privilege_type)
    """
)


async def test_the_application_cannot_make_operators_or_rewrite_plans_or_users(
    app_engine: AsyncEngine,
) -> None:
    """R5.1 (FH12): asked by statement and by the catalog, so a restored grant
    turns this red whichever way it comes back."""
    async with app_engine.connect() as conn:
        for statement in (
            "INSERT INTO platform.platform_operators (user_id) VALUES (gen_random_uuid())",
            "UPDATE platform.plans SET name = name",
            "UPDATE platform.users SET display_name = display_name",
            "DELETE FROM platform.users WHERE false",
        ):
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(sa.text(statement))
            await conn.rollback()
        for table, verbs in (
            ("platform.platform_operators", ("INSERT", "UPDATE", "DELETE", "TRUNCATE")),
            ("platform.plans", ("INSERT", "UPDATE", "DELETE", "TRUNCATE")),
            ("platform.users", ("UPDATE", "DELETE", "TRUNCATE")),
        ):
            for verb in verbs:
                held = await conn.scalar(
                    sa.text("SELECT has_table_privilege('dw_app', :t, :v)"), {"t": table, "v": verb}
                )
                assert held is False, f"dw_app holds {verb} on {table}"
        assert await conn.scalar(
            sa.text("SELECT has_table_privilege('dw_app', 'platform.users', 'INSERT')")
        ), "first sign-in and invitations create users"


async def test_the_provisioner_holds_exactly_what_its_code_runs(db_urls: DatabaseUrls) -> None:
    """R5.2 (FH13): the catalog, the migration and the role script name one set,
    down to the columns of `support_grants` the provisioner may update."""
    migration = _module(
        "db/migrations/versions/0fdd32a39d87_narrow_app_role_writes.py", "narrow_app_role_writes"
    )
    # A later revision that grants the provisioner a new table declares it the same way.
    tenant_members = _module("db/migrations/versions/349080a62e41_tenant_members.py", "tm")
    tenant_roles = _module("db/migrations/versions/b5677d345bc1_tenant_roles.py", "tr")
    switches = _module(
        "db/migrations/versions/8efd60e59d32_control_switches_and_platform_freezes.py", "cs"
    )
    script = _module("scripts/create_provisioner_role.py", "create_provisioner_role")
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            catalog = {(r.tbl, r.verb, r.col) for r in await conn.execute(_PROVISIONER_GRANTS)}
    finally:
        await migrator.dispose()
    declared = (
        _declared(migration.PROVISIONER)  # type: ignore[attr-defined]
        | _declared(tenant_members.PROVISIONER)  # type: ignore[attr-defined]
        | _declared(tenant_roles.PROVISIONER)  # type: ignore[attr-defined]
        | _declared(switches.PROVISIONER)  # type: ignore[attr-defined]
    )
    assert _declared(script.GRANTS) == declared, "the role script and the migration disagree"  # type: ignore[attr-defined]
    assert catalog == declared, (
        f"catalog only: {sorted(catalog - declared)}; declared only: {sorted(declared - catalog)}"
    )


async def test_only_the_provisioner_adds_an_operator_login_identity(db_urls: DatabaseUrls) -> None:
    """R5.4 (FH13): the one write path of R4.4 that no repository runs today; the
    grant it needs is held to the code by running it as the role."""
    from pg_harness import provisioner_url

    user = __import__("uuid").uuid4()
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    provisioner = create_async_engine(provisioner_url(db_urls.migrator), poolclass=NullPool)
    try:
        async with migrator.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.users (id, subject, display_name) VALUES (:u, :s, 'Op')"
                ),
                {"u": user, "s": f"op-{user}"},
            )
            await conn.execute(
                sa.text("INSERT INTO platform.platform_operators (user_id) VALUES (:u)"),
                {"u": user},
            )
        async with provisioner.begin() as conn:
            await conn.execute(
                sa.text(
                    "INSERT INTO platform.external_identities"
                    " (id, user_id, provider, issuer, subject)"
                    " VALUES (gen_random_uuid(), :u, 'oidc', 'https://idp.example', :s)"
                ),
                {"u": user, "s": f"op-{user}"},
            )
    finally:
        async with migrator.begin() as conn:
            for table, column in (
                ("platform.external_identities", "user_id"),
                ("platform.platform_operators", "user_id"),
                ("platform.users", "id"),
            ):
                await conn.execute(sa.text(f"DELETE FROM {table} WHERE {column} = :u"), {"u": user})
        await provisioner.dispose()
        await migrator.dispose()


async def test_tool_executions_are_appended_and_claims_never_rewritten(
    db_urls: DatabaseUrls,
) -> None:
    """runtime-hardening R6.3 and R6.1 (3f1cb1d4cece): `dw_app` appends a tool
    execution and never rewrites one (an outcome is a further row; DELETE stays
    for offboarding), and replaces a claim by delete-then-insert under its token,
    never by UPDATE. `dw_agent_ro` holds nothing on the claims. Asked of the
    catalog."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {
                (row.rolname, row.tbl, row.verb)
                for row in await conn.execute(
                    sa.text(
                        """
                        SELECT r.rolname, t.tbl, v.verb
                        FROM pg_roles r
                        CROSS JOIN unnest(ARRAY['platform.tool_executions',
                                                'platform.tool_execution_claims']) AS t(tbl)
                        CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE',
                                                'TRUNCATE']) AS v(verb)
                        WHERE r.rolname IN ('dw_app', 'dw_agent_ro')
                          AND has_table_privilege(r.rolname, t.tbl, v.verb)
                        """
                    )
                )
            }
    finally:
        await migrator.dispose()
    for table in ("platform.tool_executions", "platform.tool_execution_claims"):
        assert {verb for role, tbl, verb in held if role == "dw_app" and tbl == table} == {
            "SELECT",
            "INSERT",
            "DELETE",
        }, table
    assert not {
        verb
        for role, tbl, verb in held
        if role == "dw_agent_ro" and tbl == "platform.tool_execution_claims"
    }


# ---------------------------------------------------------------------------
# Digital Workers (migration be93e0c26a4c, digital-worker ticket 01).
# ---------------------------------------------------------------------------

_DW_TABLES = (
    "platform.service_principals",
    "platform.digital_workers",
    "platform.dw_decision_classes",
)


async def test_digital_worker_tables_are_the_applications_and_nobody_elses(
    db_urls: DatabaseUrls,
) -> None:
    """`dw_app` reads and writes the three tables, and DELETE is held for
    offboarding, which purges exactly what `dw_app` may delete; nothing
    truncates them and `dw_agent_ro` reads none of them. The three trigger
    functions run as their owner and are nobody's to call."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {
                (row.rolname, row.tbl, row.verb)
                for row in await conn.execute(
                    sa.text(
                        """
                        SELECT r.rolname, t.tbl, v.verb
                        FROM pg_roles r
                        CROSS JOIN unnest(CAST(:tables AS text[])) AS t(tbl)
                        CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE',
                                                'TRUNCATE']) AS v(verb)
                        WHERE r.rolname IN ('dw_app', 'dw_agent_ro')
                          AND has_table_privilege(r.rolname, t.tbl, v.verb)
                        """
                    ),
                    {"tables": list(_DW_TABLES)},
                )
            }
            callable_by_public = (
                await conn.execute(
                    sa.text(
                        """
                        SELECT count(*) FROM unnest(ARRAY[
                            'platform.guard_accountable_owner()',
                            'platform.external_identities_human_only()',
                            'platform.dw_principal_roles_fixed()'
                        ]) AS f(fn)
                        WHERE has_function_privilege('public', f.fn, 'EXECUTE')
                        """
                    )
                )
            ).scalar_one()
    finally:
        await migrator.dispose()
    for table in _DW_TABLES:
        assert {verb for role, tbl, verb in held if role == "dw_app" and tbl == table} == {
            "SELECT",
            "INSERT",
            "UPDATE",
            "DELETE",
        }, table
    assert {role for role, _, _ in held} == {"dw_app"}, "dw_agent_ro reads a DW table"
    assert callable_by_public == 0


# R1.18 (DWK41): every role or permission set a DW's principal holds that a
# service principal may not: a critical role by name, or one carrying an
# administrative scope (`platform.*`, the platform's prefix, or `admin.*`).
# Read from the catalog after every migration, so a role the catalogue widens
# later is caught without anyone looking at the DW.
_CRITICAL_PRINCIPAL_ROLES = sa.text(
    """
    SELECT d.key AS dw, d.tenant_id, r.key AS role
    FROM platform.digital_workers d
    JOIN platform.memberships m ON m.user_id = d.principal_user_id
    JOIN platform.roles r ON m.role_keys ? r.key
    WHERE r.key IN ('tenant_owner', 'org_admin', 'platform_admin')
       OR EXISTS (
           SELECT 1 FROM jsonb_array_elements_text(r.scopes) AS s(scope)
           WHERE s.scope LIKE 'platform.%' OR s.scope LIKE 'admin.%'
       )
    UNION ALL
    SELECT d.key, d.tenant_id, p.key
    FROM platform.digital_workers d
    JOIN platform.memberships m ON m.user_id = d.principal_user_id
    JOIN platform.permission_sets p ON m.permission_set_keys ? p.key
    WHERE EXISTS (
        SELECT 1 FROM jsonb_array_elements_text(p.scopes) AS s(scope)
        WHERE s.scope LIKE 'platform.%' OR s.scope LIKE 'admin.%'
    )
    ORDER BY 1, 3
    """
)


async def critical_principal_roles(conn: AsyncConnection) -> list[str]:
    return [
        f"DW {row.dw} of tenant {row.tenant_id} holds {row.role}"
        for row in (await conn.execute(_CRITICAL_PRINCIPAL_ROLES)).all()
    ]


async def test_no_digital_worker_principal_holds_a_critical_role(db_urls: DatabaseUrls) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            assert await critical_principal_roles(conn) == []
    finally:
        await migrator.dispose()


_MEMBER = '["member"]'


async def test_the_critical_role_check_names_a_planted_principal(db_urls: DatabaseUrls) -> None:
    """DWK41: `org_admin` given to a DW's principal by a role that can (the
    migrator, as the table's owner, past the trigger the application meets)
    turns the check red and names the DW; taken away, green again. In a
    transaction rolled back."""
    tenant, ws, owner, principal, dw = (uuid.uuid4() for _ in range(5))
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn, conn.begin() as tx:
            for sql, values in (
                (
                    "INSERT INTO platform.tenants (id, slug, name) VALUES (:t, :s, :s)",
                    {"t": tenant, "s": f"crit-{tenant.hex[:12]}"},
                ),
                (
                    "INSERT INTO platform.workspaces (id, tenant_id, slug, name)"
                    " VALUES (:w, :t, 'main', 'main')",
                    {"w": ws, "t": tenant},
                ),
                (
                    "INSERT INTO platform.users (id, subject, display_name)"
                    " VALUES (:u, :s, 'owner')",
                    {"u": owner, "s": f"crit-{owner}"},
                ),
                (TENANT_MEMBER_SQL, tenant_member_params(tenant, owner)),
                (
                    "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id,"
                    " role_keys) VALUES (:id, :t, :w, :u, CAST(:r AS jsonb))",
                    {"id": uuid.uuid4(), "t": tenant, "w": ws, "u": owner, "r": _MEMBER},
                ),
                (
                    "INSERT INTO platform.users (id, subject, display_name, kind,"
                    " owner_tenant_id) VALUES (:u, :s, 'dw', 'service', :t)",
                    {"u": principal, "s": f"service:{principal}", "t": tenant},
                ),
                (
                    "INSERT INTO platform.service_principals (user_id, tenant_id,"
                    " owning_workspace_id, name, owner_user_id) VALUES (:u, :t, :w, 'dw', :o)",
                    {"u": principal, "t": tenant, "w": ws, "o": owner},
                ),
                (TENANT_MEMBER_SQL, tenant_member_params(tenant, principal)),
                (
                    "INSERT INTO platform.memberships (id, tenant_id, workspace_id, user_id,"
                    " role_keys) VALUES (:id, :t, :w, :u, CAST(:r AS jsonb))",
                    {"id": uuid.uuid4(), "t": tenant, "w": ws, "u": principal, "r": _MEMBER},
                ),
                (
                    "INSERT INTO platform.digital_workers (id, tenant_id, workspace_id,"
                    " principal_user_id, key, name, mandate, work_kinds, allowed_tools,"
                    " workflow_key, workflow_version, technical_owner_id, work_assigner_id,"
                    " validator_id, created_by) VALUES (:d, :t, :w, :u, 'planted_dw', 'dw',"
                    " 'dw', ARRAY['lead'], ARRAY[]::text[], 'wf', '1.0.0', :o, :o, :o, :o)",
                    {"d": dw, "t": tenant, "w": ws, "u": principal, "o": owner},
                ),
            ):
                await conn.execute(sa.text(sql), values)
            assert await critical_principal_roles(conn) == []

            # The DW's fixed roles live on the assignments since tenant-rbac 03.
            await conn.execute(
                sa.text(
                    "ALTER TABLE platform.role_assignments"
                    " DISABLE TRIGGER trg_role_assignments_dw_principal_roles_fixed"
                )
            )
            # And past org-and-principals 03's guard, which refuses a critical
            # role to any service user: the check under test is the net below it.
            await conn.execute(
                sa.text(
                    "ALTER TABLE platform.role_assignments"
                    " DISABLE TRIGGER guard_service_principal_grants"
                )
            )
            await conn.execute(
                sa.text(
                    "UPDATE platform.memberships"
                    " SET role_keys = role_keys || CAST(:r AS jsonb) WHERE user_id = :u"
                ),
                {"u": principal, "r": '["org_admin"]'},
            )
            assert await critical_principal_roles(conn) == [
                f"DW planted_dw of tenant {tenant} holds org_admin"
            ]

            await conn.execute(
                sa.text(
                    "UPDATE platform.memberships SET role_keys = CAST(:r AS jsonb)"
                    " WHERE user_id = :u"
                ),
                {"u": principal, "r": _MEMBER},
            )
            assert await critical_principal_roles(conn) == []
            await tx.rollback()
    finally:
        await migrator.dispose()


async def test_the_work_queue_is_the_applications_and_its_functions_only_dw_apps(
    db_urls: DatabaseUrls,
) -> None:
    """Migration cfbd906be98b: `dw_app` reads, writes and (for offboarding)
    deletes work items, `dw_agent_ro` nothing; the lane's cross-tenant read and
    the retirement of a principal run for `dw_app` and for nobody else."""
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
                        WHERE r.rolname IN ('dw_app', 'dw_agent_ro')
                          AND has_table_privilege(r.rolname, 'platform.work_items', v.verb)
                        """
                    )
                )
            }
            executes = {
                (row.rolname, row.fn)
                for row in await conn.execute(
                    sa.text(
                        """
                        SELECT r.rolname, f.fn
                        FROM pg_roles r
                        CROSS JOIN unnest(ARRAY['platform.dw_work_scopes_due(integer)',
                                                'platform.retire_dw_principal(uuid)',
                                                'platform.work_item_payload_fixed()']) AS f(fn)
                        WHERE r.rolname IN ('dw_app', 'dw_agent_ro', 'dw_provisioner', 'public')
                          AND has_function_privilege(r.rolname, f.fn, 'EXECUTE')
                        """
                    )
                )
            }
    finally:
        await migrator.dispose()
    assert held == {("dw_app", v) for v in ("SELECT", "INSERT", "UPDATE", "DELETE")}
    assert executes == {
        ("dw_app", "platform.dw_work_scopes_due(integer)"),
        ("dw_app", "platform.retire_dw_principal(uuid)"),
    }


async def test_the_monitor_role_reads_statistics_and_no_tenant_row(db_urls: DatabaseUrls) -> None:
    """runtime-hardening R8.4 (RH24): `dw_monitor`, made by the same script a
    deployed cluster runs, holds `pg_monitor` and nothing else: no bypass, no
    superuser, and a tenant table answers "permission denied". The control:
    the statistics the exporter reads are there."""
    from scripts.create_monitor_role import create_monitor_role
    from sqlalchemy.engine import make_url

    password = "monitor-test-password"
    server = db_urls.admin.rsplit("/", 1)[0] + "/postgres"
    await create_monitor_role(server, password, database=db_urls.app.rsplit("/", 1)[1])
    admin = create_async_engine(admin_url(db_urls), poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            role = (
                await conn.execute(
                    sa.text(
                        "SELECT rolsuper, rolbypassrls, rolcreaterole, rolcreatedb,"
                        " ARRAY(SELECT b.rolname FROM pg_auth_members m"
                        "       JOIN pg_roles b ON b.oid = m.roleid WHERE m.member = r.oid)"
                        " AS member_of FROM pg_roles r WHERE rolname = 'dw_monitor'"
                    )
                )
            ).one()
    finally:
        await admin.dispose()
    assert (role.rolsuper, role.rolbypassrls, role.rolcreaterole, role.rolcreatedb) == (
        False,
        False,
        False,
        False,
    )
    assert list(role.member_of) == ["pg_monitor"]

    url = make_url(db_urls.app).set(username="dw_monitor", password=password)
    monitor = create_async_engine(url, poolclass=NullPool)
    try:
        async with monitor.connect() as conn:
            assert await conn.scalar(sa.text("SELECT count(*) FROM pg_stat_database")) > 0
        for table in ("platform.tenants", "platform.audit_events", "platform.work_items"):
            async with monitor.connect() as conn:
                with pytest.raises(sa.exc.ProgrammingError, match="permission denied"):
                    await conn.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1"))
    finally:
        await monitor.dispose()


async def test_workflow_drafts_are_the_applications_only(db_urls: DatabaseUrls) -> None:
    """Migration 100d1de08d37 (wf-ai R6.13): `dw_app` reads, writes and (for
    offboarding) deletes a DW's draft and simulation; `dw_agent_ro` nothing;
    nobody truncates."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            for table in ("platform.dw_workflow_drafts", "platform.dw_workflow_simulations"):
                held = {
                    (row.rolname, row.verb)
                    for row in await conn.execute(
                        sa.text(
                            """
                            SELECT r.rolname, v.verb
                            FROM pg_roles r
                            CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE',
                                                    'TRUNCATE']) AS v(verb)
                            WHERE r.rolname IN ('dw_app', 'dw_agent_ro')
                              AND has_table_privilege(r.rolname, :t, v.verb)
                            """
                        ),
                        {"t": table},
                    )
                }
                assert held == {
                    ("dw_app", "SELECT"),
                    ("dw_app", "INSERT"),
                    ("dw_app", "UPDATE"),
                    ("dw_app", "DELETE"),
                }, table
    finally:
        await migrator.dispose()


async def test_published_workflow_versions_are_append_only(db_urls: DatabaseUrls) -> None:
    """Migration 1fb796131647 (wf-ai R6.5, R6.13): `dw_app` reads and inserts
    a tenant's published versions and deletes them only for offboarding; it
    updates none, `dw_agent_ro` reads none, nobody truncates."""
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
                        WHERE r.rolname IN ('dw_app', 'dw_agent_ro')
                          AND has_table_privilege(r.rolname, 'platform.dw_workflow_versions',
                                                  v.verb)
                        """
                    )
                )
            }
    finally:
        await migrator.dispose()
    assert held == {("dw_app", "SELECT"), ("dw_app", "INSERT"), ("dw_app", "DELETE")}


async def test_the_permission_catalogue_is_read_only_to_every_application_role(
    db_urls: DatabaseUrls, app_engine: AsyncEngine
) -> None:
    """Migration ebb17244abc6 (tenant-rbac R1.3, RB1): `dw_app`,
    `dw_provisioner` and `dw_agent_ro` write none of the catalogue; all three
    read it (the provisioner since b5677d345bc1: the depth trigger and
    `install_system_roles` read `scope_kind`); asked of the catalog for every
    verb, and tried as `dw_app`."""
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
                          AND has_table_privilege(r.rolname, 'platform.permissions', v.verb)
                        """
                    )
                )
            }
    finally:
        await migrator.dispose()
    assert held == {("dw_app", "SELECT"), ("dw_agent_ro", "SELECT"), ("dw_provisioner", "SELECT")}
    async with app_engine.connect() as conn:
        for statement in (
            "UPDATE platform.permissions SET status = 'active'",
            "DELETE FROM platform.permissions",
            "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
            " owner_package) VALUES ('x.y', 'x', 'x', 'workspace', 'standard', 'active', 'p')",
        ):
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(sa.text(statement))
            await conn.rollback()


# org-and-principals ticket 02 (migration 349080a62e41).


async def test_company_members_are_the_applications_and_the_provisioners_to_add(
    db_urls: DatabaseUrls,
) -> None:
    """`dw_app` reads and writes `platform.tenant_members` (DELETE for the
    offboarding purge), never truncates it; `dw_agent_ro` holds nothing; the
    provisioner reads and adds (its exact set is the test above). The activation
    function is `dw_app`'s alone to call."""
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
                        WHERE r.rolname IN ('dw_app', 'dw_agent_ro', 'dw_provisioner')
                          AND has_table_privilege(r.rolname, 'platform.tenant_members', v.verb)
                        """
                    )
                )
            }
            calls = {
                role: await conn.scalar(
                    sa.text(
                        "SELECT has_function_privilege(:r,"
                        " 'platform.activate_invited_members(uuid)', 'EXECUTE')"
                    ),
                    {"r": role},
                )
                for role in ("public", "dw_app", "dw_agent_ro")
            }
    finally:
        await migrator.dispose()
    assert {verb for role, verb in held if role == "dw_app"} == {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
    }
    assert {verb for role, verb in held if role == "dw_agent_ro"} == set()
    assert {verb for role, verb in held if role == "dw_provisioner"} == {"SELECT", "INSERT"}
    assert calls == {"public": False, "dw_app": True, "dw_agent_ro": False}


# usage-and-limits ticket 01 (migration 764b0e239f95).


async def test_the_plan_catalogue_is_read_only_to_every_application_role(
    db_urls: DatabaseUrls, app_engine: AsyncEngine
) -> None:
    """R1.3: only a migration writes `platform.plan_limits`. `ALTER DEFAULT
    PRIVILEGES` handed `dw_app` INSERT, UPDATE and DELETE on every new
    platform table, so this asks the catalog for every verb of every
    application role, and tries each write as `dw_app`."""
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
                          AND has_table_privilege(r.rolname, 'platform.plan_limits', v.verb)
                        """
                    )
                )
            }
    finally:
        await migrator.dispose()
    assert held == {("dw_app", "SELECT")}
    async with app_engine.connect() as conn:
        assert await conn.scalar(
            sa.text("SELECT runs_per_day FROM platform.plan_limits WHERE plan_id = 'basic'")
        )
        for statement in (
            "UPDATE platform.plan_limits SET runs_per_day = NULL",
            "DELETE FROM platform.plan_limits",
            "TRUNCATE platform.plan_limits",
            "INSERT INTO platform.plan_limits (plan_id, max_cost_usd_per_run, max_tokens_per_run,"
            " max_steps_per_run, max_model_calls_per_run, max_tool_calls_per_run)"
            " VALUES ('basic', 1, 1, 1, 1, 1)",
        ):
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(sa.text(statement))
            await conn.rollback()


# model-connections ticket 02 (migration d66d6913b249).


async def test_the_plan_model_catalogue_is_read_only_to_every_application_role(
    db_urls: DatabaseUrls, app_engine: AsyncEngine
) -> None:
    """R2.1: only a migration writes `platform.plan_model_profiles`, as only one
    writes `platform.plan_limits`: every verb of every application role asked
    of the catalog, and each write tried as `dw_app`."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {
                (row.rolname, row.verb)
                for row in await conn.execute(_HELD_VERBS, {"t": "platform.plan_model_profiles"})
            }
    finally:
        await migrator.dispose()
    assert held == {("dw_app", "SELECT")}
    async with app_engine.connect() as conn:
        assert await conn.scalar(
            sa.text("SELECT count(*) FROM platform.plan_model_profiles WHERE plan_id = 'basic'")
        )
        for statement in (
            "INSERT INTO platform.plan_model_profiles VALUES ('basic', 'premium')",
            "UPDATE platform.plan_model_profiles SET profile_id = 'premium'",
            "DELETE FROM platform.plan_model_profiles",
            "TRUNCATE platform.plan_model_profiles",
        ):
            with pytest.raises(Exception, match="permission denied"):
                await conn.execute(sa.text(statement))
            await conn.rollback()


# tenant-rbac ticket 02 (migration b5677d345bc1).

_HELD_VERBS = sa.text(
    """
    SELECT r.rolname, v.verb
    FROM pg_roles r
    CROSS JOIN unnest(ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE']) AS v(verb)
    WHERE r.rolname IN ('dw_app', 'dw_provisioner', 'dw_agent_ro')
      AND has_table_privilege(r.rolname, :t, v.verb)
    """
)


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        (
            table,
            {
                ("dw_app", "SELECT"),
                ("dw_app", "INSERT"),
                ("dw_app", "UPDATE"),
                ("dw_app", "DELETE"),
                ("dw_provisioner", "SELECT"),
                ("dw_provisioner", "INSERT"),
            },
        )
        for table in (
            "platform.tenant_roles",
            "platform.tenant_role_permissions",
            "platform.role_assignments",
        )
    ]
    + [("platform.tenant_access_versions", {("dw_app", "SELECT")})],
)
async def test_the_role_tables_are_the_applications_and_the_version_only_the_databases(
    db_urls: DatabaseUrls, table: str, expected: set[tuple[str, str]]
) -> None:
    """Step 5 and 9: `dw_app` reads and writes the three role tables (DELETE
    for offboarding), never truncates; the provisioner reads and adds; the
    version row is written by `platform.bump_access_version()` alone, so no
    application role may write it; `dw_agent_ro` holds nothing."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {(r.rolname, r.verb) for r in await conn.execute(_HELD_VERBS, {"t": table})}
    finally:
        await migrator.dispose()
    assert held == expected


async def test_only_dw_app_may_purge_a_version_row_and_no_one_calls_the_trigger_functions(
    db_urls: DatabaseUrls,
) -> None:
    """The SECURITY DEFINER functions of the migration are revoked from PUBLIC;
    the purge step is `dw_app`'s alone."""
    definers = (
        "platform.sod_violation(uuid, uuid)",
        "platform.bump_access_version()",
        "platform.purge_tenant_access_version(uuid)",
        "platform.complete_tenant_setup()",
        "platform.guard_operator_tenant_grants()",
        "platform.check_owner_coverage(uuid)",
    )
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            calls = {
                (role, function): await conn.scalar(
                    sa.text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                    {"r": role, "f": function},
                )
                for role in ("public", "dw_app", "dw_agent_ro")
                for function in definers
            }
    finally:
        await migrator.dispose()
    allowed = {k for k, v in calls.items() if v}
    assert allowed == {("dw_app", "platform.purge_tenant_access_version(uuid)")}


# org-and-principals ticket 04 (migration 555dad01f629).


async def test_only_dw_app_may_ask_who_is_in_an_audience(db_urls: DatabaseUrls) -> None:
    """Step 3: `platform.audience_matches` is revoked from PUBLIC and granted
    to `dw_app` alone; it is SECURITY INVOKER, so RLS still applies to it."""
    function = "platform.audience_matches(uuid, uuid, jsonb)"
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            calls = {
                role: await conn.scalar(
                    sa.text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                    {"r": role, "f": function},
                )
                for role in ("public", "dw_app", "dw_agent_ro", "dw_provisioner")
            }
            definer = await conn.scalar(
                sa.text("SELECT prosecdef FROM pg_proc WHERE oid = CAST(:f AS regprocedure)"),
                {"f": function},
            )
    finally:
        await migrator.dispose()
    assert calls == {
        "public": False,
        "dw_app": True,
        "dw_agent_ro": False,
        "dw_provisioner": False,
    }
    assert definer is False


# org-and-principals ticket 03 (migration 557e6907195e).


async def test_only_dw_app_calls_the_service_account_functions_and_no_one_the_triggers(
    db_urls: DatabaseUrls,
) -> None:
    """Steps 2, 4, 6, 9: every SECURITY DEFINER function of the migration is
    revoked from PUBLIC and runs on a fixed `search_path`; `dw_app` alone calls
    the DW flag and the purge step (R6.9: a role that may call the purge is a
    role that may delete a tenant's service users)."""
    definers = (
        "platform.guard_service_user_tenant()",
        "platform.guard_service_principal_grants()",
        "platform.service_principal_grants_changed()",
        "platform.is_digital_worker_principal(uuid)",
        "platform.purge_tenant_service_users(uuid)",
    )
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            calls = {
                (role, function): await conn.scalar(
                    sa.text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                    {"r": role, "f": function},
                )
                for role in ("public", "dw_app", "dw_agent_ro", "dw_provisioner")
                for function in definers
            }
            shapes = {
                function: tuple(
                    (
                        await conn.execute(
                            sa.text(
                                "SELECT prosecdef, proconfig FROM pg_proc"
                                " WHERE oid = CAST(:f AS regprocedure)"
                            ),
                            {"f": function},
                        )
                    ).one()
                )
                for function in definers
            }
    finally:
        await migrator.dispose()
    allowed = {k for k, v in calls.items() if v}
    assert allowed == {
        ("dw_app", "platform.is_digital_worker_principal(uuid)"),
        ("dw_app", "platform.purge_tenant_service_users(uuid)"),
    }
    for function, (definer, config) in shapes.items():
        assert definer is True, function
        assert config == ["search_path=pg_catalog, platform"], function


_SECRET_DOORS = (
    "platform.put_secret(text, uuid, text, integer, text, bytea, text, integer, bytea, bytea)",
    "platform.open_secret(text, uuid, text, integer)",
    "platform.secret_status(text, uuid, text)",
    "platform.delete_secret(text, uuid, text)",
    # The fifth door, the revocation for compromise (ticket 04, 388a31c46bdf).
    "platform.revoke_connection_secrets(uuid)",
)
_SECRET_INTERNALS = (
    "platform.guard_connection_owning_workspace()",
    "platform.secret_subject_column(text)",
    "platform.guard_connection_status()",
    "platform.guard_connection_compromised_at()",
)
_CONNECTION_UPDATABLE = {
    "share_scope",
    "external_account",
    "status",
    "scopes",
    "last_used_at",
    "updated_at",
    # Renamed by `PATCH` (ticket 04); never `disabled_at` or `compromised_at`,
    # which only the status trigger and the revocation door write.
    "name",
}


async def test_the_envelopes_are_reached_only_through_dw_apps_door(db_urls: DatabaseUrls) -> None:
    """connections-and-vault R1.3 (CV2), migration 70d8a4564454: no role but
    the migrator holds a privilege on `platform.secret_envelopes`; the five
    door functions (ticket 04's revocation the fifth) are SECURITY DEFINER on a
    fixed `search_path`, revoked from PUBLIC and executable by `dw_app` alone;
    the four internal functions by no application role. `platform.connections`:
    SELECT, INSERT and DELETE on the table (the offboarding catalog asks those),
    UPDATE of seven named columns."""
    verbs = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
    roles = ("public", "dw_app", "dw_agent_ro", "dw_provisioner")
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            on_envelopes = {
                (role, verb)
                for role in roles
                for verb in verbs
                if await conn.scalar(
                    sa.text("SELECT has_table_privilege(:r, 'platform.secret_envelopes', :v)"),
                    {"r": role, "v": verb},
                )
            }
            on_connections = {
                (role, verb)
                for role in roles
                for verb in verbs
                if await conn.scalar(
                    sa.text("SELECT has_table_privilege(:r, 'platform.connections', :v)"),
                    {"r": role, "v": verb},
                )
            }
            updatable = set(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT a.attname FROM pg_attribute a"
                            " WHERE a.attrelid = 'platform.connections'::regclass"
                            "   AND a.attnum > 0 AND NOT a.attisdropped"
                            "   AND has_column_privilege('dw_app', a.attrelid, a.attnum,"
                            "                            'UPDATE')"
                        )
                    )
                ).scalars()
            )
            calls = {
                (role, function)
                for role in roles
                for function in (*_SECRET_DOORS, *_SECRET_INTERNALS)
                if await conn.scalar(
                    sa.text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                    {"r": role, "f": function},
                )
            }
            shapes = {
                function: tuple(
                    (
                        await conn.execute(
                            sa.text(
                                "SELECT prosecdef, proconfig, proacl::text[] FROM pg_proc"
                                " WHERE oid = CAST(:f AS regprocedure)"
                            ),
                            {"f": function},
                        )
                    ).one()
                )
                for function in _SECRET_DOORS
            }
    finally:
        await migrator.dispose()
    assert on_envelopes == set()
    assert on_connections == {("dw_app", v) for v in ("SELECT", "INSERT", "DELETE")}
    assert updatable == _CONNECTION_UPDATABLE
    assert calls == {("dw_app", function) for function in _SECRET_DOORS}
    for function, (definer, config, acl) in shapes.items():
        assert definer is True, function
        assert config == ["search_path=pg_catalog, platform"], function
        # No `=X/...` entry: PUBLIC holds nothing (an ACL entry with no grantee).
        assert not any(entry.startswith("=") for entry in acl), (function, acl)


async def test_the_application_cannot_read_an_envelope_and_the_provisioner_not_call_the_door(
    db_urls: DatabaseUrls, app_engine: AsyncEngine
) -> None:
    """R1.3: the statements themselves, not only the catalog's answer."""
    async with app_engine.connect() as conn:
        with pytest.raises(Exception, match="permission denied for table secret_envelopes"):
            await conn.execute(sa.text("SELECT * FROM platform.secret_envelopes"))
    admin = create_async_engine(admin_url(db_urls), poolclass=NullPool)
    try:
        async with admin.connect() as conn:
            await conn.execute(sa.text("SET LOCAL ROLE dw_provisioner"))
            with pytest.raises(Exception, match="permission denied for function put_secret"):
                await conn.execute(
                    sa.text(
                        "SELECT platform.put_secret('connection', gen_random_uuid(), 'api_key',"
                        " 1, 'aes-256-gcm', decode('00', 'hex'), 'tenant-x', 1,"
                        " decode('00', 'hex'), decode('00', 'hex'))"
                    )
                )
            await conn.rollback()
    finally:
        await admin.dispose()


_ALLOWED_HOSTS_UPDATABLE = {"removed_at", "removed_by"}


async def test_the_allowed_hosts_are_read_inserted_and_only_marked_removed(
    db_urls: DatabaseUrls,
) -> None:
    """connections-and-vault ticket 03, migration 20bb9a2210cf: `dw_app` holds
    SELECT, INSERT and DELETE (the offboarding lane's) on
    `platform.egress_allowed_hosts`, and UPDATE of `removed_at` and
    `removed_by` only, so no write moves a row's pattern, ports or purpose; no
    other application role holds anything."""
    verbs = ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE", "REFERENCES", "TRIGGER")
    roles = ("public", "dw_app", "dw_agent_ro", "dw_provisioner")
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {
                (role, verb)
                for role in roles
                for verb in verbs
                if await conn.scalar(
                    sa.text("SELECT has_table_privilege(:r, 'platform.egress_allowed_hosts', :v)"),
                    {"r": role, "v": verb},
                )
            }
            updatable = set(
                (
                    await conn.execute(
                        sa.text(
                            "SELECT a.attname FROM pg_attribute a"
                            " WHERE a.attrelid = 'platform.egress_allowed_hosts'::regclass"
                            "   AND a.attnum > 0 AND NOT a.attisdropped"
                            "   AND has_column_privilege('dw_app', a.attrelid, a.attnum,"
                            "                            'UPDATE')"
                        )
                    )
                ).scalars()
            )
    finally:
        await migrator.dispose()
    assert held == {("dw_app", v) for v in ("SELECT", "INSERT", "DELETE")}
    assert updatable == _ALLOWED_HOSTS_UPDATABLE


# usage-and-limits ticket 02 (migration 2354ad4d2e3c).


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        # Append-only: written and read through the parent, never rewritten (R3.4).
        ("platform.usage_events", {("dw_app", "SELECT"), ("dw_app", "INSERT")}),
        # The roll-up recomputes a day and offboarding deletes it (R3.8).
        (
            "platform.usage_daily",
            {
                ("dw_app", "SELECT"),
                ("dw_app", "INSERT"),
                ("dw_app", "UPDATE"),
                ("dw_app", "DELETE"),
            },
        ),
        # Nobody but the owner on a partition, the DEFAULT included (R3.7, DO-02.2).
        ("platform.usage_events_default", set()),
    ],
)
async def test_the_usage_ledger_is_appended_and_its_roll_up_the_applications(
    db_urls: DatabaseUrls, table: str, expected: set[tuple[str, str]]
) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {(r.rolname, r.verb) for r in await conn.execute(_HELD_VERBS, {"t": table})}
    finally:
        await migrator.dispose()
    assert held == expected


async def test_only_dw_app_runs_the_registry_s_purge_and_drop_functions(
    db_urls: DatabaseUrls,
) -> None:
    """The three SECURITY DEFINER functions are revoked from PUBLIC and
    executable by `dw_app` alone (R3.9, R3.10)."""
    definers = (
        "platform.drop_expired_partitions(jsonb)",
        "platform.append_only_tables()",
        "platform.purge_tenant_append_only(uuid, text[])",
    )
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            calls = {
                (role, function): await conn.scalar(
                    sa.text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                    {"r": role, "f": function},
                )
                for role in ("public", "dw_app", "dw_agent_ro")
                for function in definers
            }
            definer = {
                function: await conn.scalar(
                    sa.text("SELECT prosecdef FROM pg_proc WHERE oid = CAST(:f AS regprocedure)"),
                    {"f": function},
                )
                for function in definers
            }
    finally:
        await migrator.dispose()
    assert {k for k, v in calls.items() if v} == {("dw_app", f) for f in definers}
    assert all(definer.values())


# tenant-config ticket 04 (migration 28a94cda6fdf): a run manifest and its keys
# are written once and never rewritten; DELETE serves the offboarding lane alone
# (its trigger refuses it elsewhere, R3.8); `dw_agent_ro` reads neither.


@pytest.mark.parametrize("table", ["platform.run_manifests", "platform.run_manifest_keys"])
async def test_a_run_manifest_is_inserted_read_and_only_purged(
    db_urls: DatabaseUrls, table: str
) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {(r.rolname, r.verb) for r in await conn.execute(_HELD_VERBS, {"t": table})}
            trigger_call = await conn.scalar(
                sa.text(
                    "SELECT has_function_privilege('public',"
                    " 'platform.match_run_manifest()', 'EXECUTE')"
                )
            )
    finally:
        await migrator.dispose()
    assert held == {("dw_app", "SELECT"), ("dw_app", "INSERT"), ("dw_app", "DELETE")}
    assert trigger_call is False


# tenant-config ticket 05 (migration 045712d63ec7): a configuration version is
# proposed by `dw_app` and moved only through its five decision columns, so
# what was proposed cannot be rewritten; DELETE serves the offboarding lane
# alone (its trigger refuses it elsewhere, R3.8); `dw_agent_ro` reads nothing.

_DECISION_COLUMNS = ("status", "decided_by", "decided_at", "decision_comment", "superseded_at")
_PROPOSED_COLUMNS = (
    "kind",
    "key",
    "workspace_id",
    "version_no",
    "base_version",
    "base_bindings_hash",
    "base_approved_id",
    "document",
    "document_hash",
    "approval_id",
    "proposed_by",
    "proposed_at",
)


async def test_a_config_version_is_proposed_decided_by_column_and_only_purged(
    db_urls: DatabaseUrls,
) -> None:
    table = "platform.config_versions"
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {(r.rolname, r.verb) for r in await conn.execute(_HELD_VERBS, {"t": table})}
            updatable = {
                column: await conn.scalar(
                    sa.text("SELECT has_column_privilege('dw_app', :t, :col, 'UPDATE')"),
                    {"t": table, "col": column},
                )
                for column in (*_DECISION_COLUMNS, *_PROPOSED_COLUMNS)
            }
            trigger_call = await conn.scalar(
                sa.text(
                    "SELECT has_function_privilege('public',"
                    " 'platform.config_version_transition()', 'EXECUTE')"
                )
            )
    finally:
        await migrator.dispose()
    assert held == {("dw_app", "SELECT"), ("dw_app", "INSERT"), ("dw_app", "DELETE")}
    assert {column for column, granted in updatable.items() if granted} == set(_DECISION_COLUMNS)
    assert trigger_call is False


# agent-lifecycle ticket 01 (migration 8efd60e59d32): a company's switch is
# inserted and lifted by `dw_app` (only the lift columns), deleted only by
# the offboarding lane (its trigger refuses it elsewhere, R7.5, R10.1); the
# operators' switches are the provisioner's; `dw_agent_ro` reads neither.

_LIFT_COLUMNS = ("lifted_by", "lifted_at", "lift_reason", "lift_approval_id")
_OTHER_COLUMNS = ("reason", "reason_code", "set_by", "action", "origin", "tenant_id")


async def test_the_switches_are_written_only_by_the_roles_that_set_and_lift_them(
    db_urls: DatabaseUrls,
) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {
                table: {(r.rolname, r.verb) for r in await conn.execute(_HELD_VERBS, {"t": table})}
                for table in ("platform.control_switches", "platform.platform_freezes")
            }

            async def updates(role: str, table: str, column: str) -> bool:
                return bool(
                    await conn.scalar(
                        sa.text("SELECT has_column_privilege(:r, :t, :c, 'UPDATE')"),
                        {"r": role, "t": table, "c": column},
                    )
                )

            app_lifts = {
                c: await updates("dw_app", "platform.control_switches", c) for c in _LIFT_COLUMNS
            }
            app_other = {
                c: await updates("dw_app", "platform.control_switches", c) for c in _OTHER_COLUMNS
            }
            operator_lifts = {
                c: await updates("dw_provisioner", "platform.control_switches", c)
                for c in (*_LIFT_COLUMNS, *_OTHER_COLUMNS)
            }
            freeze_lifts = {
                (role, c): await updates(role, "platform.platform_freezes", c)
                for role in ("dw_app", "dw_provisioner")
                for c in ("lifted_by", "lifted_at", "reason")
            }
            trigger_calls = [
                await conn.scalar(
                    sa.text("SELECT has_function_privilege('public', :f, 'EXECUTE')"), {"f": f}
                )
                for f in (
                    "platform.guard_control_switch()",
                    "platform.notify_control_switch()",
                    "platform.notify_platform_freeze()",
                )
            ]
    finally:
        await migrator.dispose()
    assert held["platform.control_switches"] == {
        ("dw_app", "SELECT"),
        ("dw_app", "INSERT"),
        ("dw_app", "DELETE"),
        ("dw_provisioner", "SELECT"),
        ("dw_provisioner", "INSERT"),
    }
    assert held["platform.platform_freezes"] == {
        ("dw_app", "SELECT"),
        ("dw_provisioner", "SELECT"),
        ("dw_provisioner", "INSERT"),
    }
    assert all(app_lifts.values()) and not any(app_other.values())
    assert {c for c, v in operator_lifts.items() if v} == {"lifted_by", "lifted_at", "lift_reason"}
    assert {k for k, v in freeze_lifts.items() if v} == {
        ("dw_provisioner", "lifted_by"),
        ("dw_provisioner", "lifted_at"),
    }
    assert not any(trigger_calls)


# workflow-engine ticket 02 (migration 703be798341f): the Studio run columns
# change no grant on `platform.worker_runs` (`dw_app` writes a run as before,
# `dw_agent_ro` and the provisioner hold nothing), and the trigger that makes
# a run its own root is called by its trigger alone.


async def test_the_run_columns_change_no_grant_and_their_trigger_is_no_ones(
    db_urls: DatabaseUrls,
) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {
                (r.rolname, r.verb)
                for r in await conn.execute(_HELD_VERBS, {"t": "platform.worker_runs"})
            }
            callers = {
                role: await conn.scalar(
                    sa.text(
                        "SELECT has_function_privilege(:r,"
                        " 'platform.default_root_run_id()', 'EXECUTE')"
                    ),
                    {"r": role},
                )
                for role in ("public", "dw_app", "dw_agent_ro", "dw_provisioner")
            }
    finally:
        await migrator.dispose()
    assert held == {
        ("dw_app", "SELECT"),
        ("dw_app", "INSERT"),
        ("dw_app", "UPDATE"),
        ("dw_app", "DELETE"),
    }
    assert not any(callers.values()), callers


# tenant-rbac ticket 03 (migration d2b57239ef50): `dw_app` proposes, settles and
# (at offboarding) purges role change requests, and updates only the three
# settling columns; nobody calls the trigger functions; `dw_app` alone calls the
# refusal and privilege readers, the provisioner the template reader it
# installs `member` through.

_RCR_SETTLING = ("status", "confirmed_by", "decided_at")
_RCR_OTHER = (
    "id",
    "tenant_id",
    "kind",
    "payload",
    "role_id",
    "base_version",
    "required_permission",
    "proposed_by",
    "proposed_at",
    "expires_at",
)
_RBAC_TRIGGER_FUNCTIONS = (
    "platform.guard_role_change_request()",
    "platform.role_change_in_force()",
    "platform.rbac_guard()",
    "platform.dw_principal_first_role(uuid, uuid, uuid)",
    "platform.bump_tenant_role_version()",
    "platform.bump_parent_role_version()",
    "platform.refuse_losing_the_last_owner()",
    "platform.remove_owner_assignments_first()",
    "platform.guard_legacy_role_columns()",
    "platform.guard_membership_identity()",
    "platform.guard_user_created_at()",
)
_RBAC_READERS = (
    "platform.rbac_refusals(uuid, uuid, jsonb, boolean)",
    "platform.role_privileges(uuid, uuid)",
    "platform.role_template_privileges(text)",
)


async def test_role_change_requests_are_proposed_and_settled_by_dw_app_alone(
    db_urls: DatabaseUrls,
) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {
                (r.rolname, r.verb)
                for r in await conn.execute(_HELD_VERBS, {"t": "platform.role_change_requests"})
            }
            column_updates = {
                column: await conn.scalar(
                    sa.text(
                        "SELECT has_column_privilege('dw_app', 'platform.role_change_requests',"
                        " :c, 'UPDATE')"
                    ),
                    {"c": column},
                )
                for column in (*_RCR_SETTLING, *_RCR_OTHER)
            }
            calls = {
                (role, function): await conn.scalar(
                    sa.text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                    {"r": role, "f": function},
                )
                for role in ("public", "dw_app", "dw_agent_ro", "dw_provisioner")
                for function in (*_RBAC_TRIGGER_FUNCTIONS, *_RBAC_READERS)
            }
    finally:
        await migrator.dispose()
    # UPDATE is held by column only (below), never on the whole table.
    assert held == {("dw_app", "SELECT"), ("dw_app", "INSERT"), ("dw_app", "DELETE")}
    assert {c for c, v in column_updates.items() if v} == set(_RCR_SETTLING)
    assert {k for k, v in calls.items() if v} == {
        ("dw_app", "platform.rbac_refusals(uuid, uuid, jsonb, boolean)"),
        ("dw_app", "platform.role_privileges(uuid, uuid)"),
        ("dw_app", "platform.role_template_privileges(text)"),
        ("dw_provisioner", "platform.role_template_privileges(text)"),
    }


# tenant-rbac ticket 04 (migration ef68083f2905).

_RECORD_KEY_READERS = (
    "platform.object_permission_keys(uuid)",
    "platform.field_permission_keys(uuid)",
    "platform.record_privilege_keys(text, jsonb)",
)
_RECORD_TRIGGER_FUNCTIONS = (
    "platform.refuse_unenforced_object_action()",
    "platform.proposal_holds_record_row(jsonb, text, jsonb)",
)


@pytest.mark.parametrize(
    ("table", "expected"),
    [
        (
            "platform.tenant_role_object_privileges",
            {
                ("dw_app", "SELECT"),
                ("dw_app", "INSERT"),
                ("dw_app", "UPDATE"),
                ("dw_app", "DELETE"),
            },
        ),
        ("platform.object_actions", {("dw_app", "SELECT"), ("dw_agent_ro", "SELECT")}),
        (
            "studio.field_permissions",
            {("dw_app", "SELECT"), ("dw_app", "INSERT"), ("dw_app", "DELETE")},
        ),
    ],
)
async def test_the_record_privilege_tables_are_the_applications_and_the_actions_read_only(
    db_urls: DatabaseUrls, table: str, expected: set[tuple[str, str]]
) -> None:
    """Step 4: `dw_app` reads and writes a role's object privileges as it does
    its other privileges (DELETE for offboarding) and a field permission by
    column; the actions are the migration's; `dw_agent_ro` reads no role's
    privileges; the provisioner, which runs none of this, holds nothing."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {(r.rolname, r.verb) for r in await conn.execute(_HELD_VERBS, {"t": table})}
            columns = {
                column
                for column in (
                    "tenant_id",
                    "role_id",
                    "field_id",
                    "access",
                    "granted_by",
                    "granted_at",
                )
                if await conn.scalar(
                    sa.text(
                        "SELECT has_column_privilege('dw_app', 'studio.field_permissions', :c,"
                        " 'UPDATE')"
                    ),
                    {"c": column},
                )
            }
    finally:
        await migrator.dispose()
    assert held == expected
    assert columns == {"access", "granted_by", "granted_at"}


async def test_dw_app_alone_reads_the_record_keys_and_no_one_calls_their_triggers(
    db_urls: DatabaseUrls,
) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            calls = {
                (role, function): await conn.scalar(
                    sa.text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                    {"r": role, "f": function},
                )
                for role in ("public", "dw_app", "dw_agent_ro", "dw_provisioner")
                for function in (*_RECORD_KEY_READERS, *_RECORD_TRIGGER_FUNCTIONS)
            }
    finally:
        await migrator.dispose()
    assert {k for k, v in calls.items() if v} == {
        ("dw_app", function) for function in _RECORD_KEY_READERS
    }


# record-access ticket 02 (migration f6ea6e818d0c): the reach ledger.

_LEDGER_DOORS = (
    "studio.ensure_principal_scope()",
    "studio.acl_user()",
    "studio.acl_objects(text, text)",
    "studio.acl_keys(text)",
    "studio.acl_create_own_keys()",
    "studio.purge_access_epoch(uuid)",
    # record-access/03 (revision 2c2095fbb4c7): the record policies read the
    # actor kind, and `dw_app`'s INSERT computes the generated `access_key`
    # (D8: without EXECUTE it is "permission denied for function access_key").
    "studio.acl_actor_kind()",
    "studio.access_key(uuid, uuid)",
)
_LEDGER_INTERNALS = (
    "studio.compute_principal_scope()",
    "studio.mark_principal_stale()",
    "studio.bump_access_epoch()",
    "studio.check_record_owner()",
)


@pytest.mark.parametrize(
    ("relation", "expected"),
    [
        ("studio.principal_scopes", {("dw_app", "SELECT")}),
        ("studio.access_epochs", {("dw_app", "SELECT")}),
        ("studio.access_input_tables", {("dw_app", "SELECT")}),
        # R4.5 (RA11): records too are no provisioner's and no agent role's.
        ("studio.records", {("dw_app", "SELECT"), ("dw_app", "INSERT"), ("dw_app", "DELETE")}),
        ("studio.v_principal_grants", set()),
        ("studio.v_principal_workspaces", set()),
    ],
)
async def test_the_reach_ledger_is_read_only_and_its_inputs_no_ones(
    db_urls: DatabaseUrls, relation: str, expected: set[tuple[str, str]]
) -> None:
    """R5.5 (RA16), R4.5, M1: `dw_app` only reads the ledger, the epochs and the
    declaration; the provisioner and `dw_agent_ro` hold nothing; nobody but the
    migrator reads the input views."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {(r.rolname, r.verb) for r in await conn.execute(_HELD_VERBS, {"t": relation})}
            public = await conn.scalar(
                sa.text("SELECT has_table_privilege('public', :t, 'SELECT')"), {"t": relation}
            )
    finally:
        await migrator.dispose()
    assert held == expected
    assert not public


async def test_dw_app_calls_the_door_and_the_readers_and_no_one_the_computation(
    db_urls: DatabaseUrls,
) -> None:
    """M1: EXECUTE of the computation, the key and the trigger functions is no
    application role's and not PUBLIC's; `dw_app` calls the door, the readers
    and the offboarding step."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            calls = {
                (role, function): await conn.scalar(
                    sa.text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                    {"r": role, "f": function},
                )
                for role in ("public", "dw_app", "dw_agent_ro", "dw_provisioner")
                for function in (*_LEDGER_DOORS, *_LEDGER_INTERNALS)
            }
    finally:
        await migrator.dispose()
    assert {k for k, v in calls.items() if v} == {("dw_app", f) for f in _LEDGER_DOORS}


# record-access ticket 04 (migration 996c234cfde3): the data boundaries.

_BOUNDARY_DOORS = (
    "studio.record_actor_boundary(text, uuid, text, uuid, jsonb, jsonb)",
    "studio.boundary_chain(uuid)",
    "studio.acl_boundary_objects(text)",
)
_BOUNDARY_TRIGGERS = (
    "studio.refuse_boundary_change()",
    "studio.check_provisional_run()",
)


@pytest.mark.parametrize(
    "relation",
    ["studio.actor_boundaries", "studio.actor_boundary_objects", "studio.actor_boundary_fields"],
)
async def test_dw_app_reads_and_deletes_a_boundary_and_writes_none(
    db_urls: DatabaseUrls, relation: str
) -> None:
    """R6.7, R6.8 (gate (i)): `dw_app` SELECT and DELETE, no INSERT or UPDATE;
    the provisioner, `dw_agent_ro` and PUBLIC nothing."""
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            held = {(r.rolname, r.verb) for r in await conn.execute(_HELD_VERBS, {"t": relation})}
            public = await conn.scalar(
                sa.text("SELECT has_table_privilege('public', :t, 'SELECT')"), {"t": relation}
            )
    finally:
        await migrator.dispose()
    assert held == {("dw_app", "SELECT"), ("dw_app", "DELETE")}
    assert not public


async def test_dw_app_calls_the_boundary_writer_and_readers_and_no_one_the_triggers(
    db_urls: DatabaseUrls,
) -> None:
    migrator = create_async_engine(db_urls.migrator, poolclass=NullPool)
    try:
        async with migrator.connect() as conn:
            calls = {
                (role, function): await conn.scalar(
                    sa.text("SELECT has_function_privilege(:r, :f, 'EXECUTE')"),
                    {"r": role, "f": function},
                )
                for role in ("public", "dw_app", "dw_agent_ro", "dw_provisioner")
                for function in (*_BOUNDARY_DOORS, *_BOUNDARY_TRIGGERS)
            }
    finally:
        await migrator.dispose()
    assert {k for k, v in calls.items() if v} == {("dw_app", f) for f in _BOUNDARY_DOORS}
