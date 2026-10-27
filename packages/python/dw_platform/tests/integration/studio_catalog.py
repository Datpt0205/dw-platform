"""Catalog checks of the studio skeleton (studio-skeleton ticket 01).

Each check is a function of one connection that returns what it found wrong,
one line per defect, prefixed with the requirement it guards. A test asks it of
the migrated checkout and expects nothing, then asks it again inside a
transaction that plants one defect and rolls back, and expects that defect
named. The second half is what proves the first can fail (failure-modes #3).

All of them read the running catalog, never migration text (failure-modes #0).

Two kinds of role are judged differently, because the catalog answers
differently for them:

- a superuser holds every privilege by definition, so `has_*_privilege` says
  nothing about it; for a superuser (here `dw_admin`) and for PUBLIC, the
  question is whether anything was GRANTed explicitly, asked of the ACL itself;
- any other role is asked by effective privilege, table-wide or per column, and
  by membership too: `dw_agent_ro` is NOINHERIT, so a role it is a member of
  lends it nothing `has_*_privilege` can see, yet `SET ROLE` reaches it all.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from dw_platform.adapters.persistence.partition_maintenance import RetentionTerm

STUDIO = "studio"

# Roles whose membership hands over what they hold: the owner of studio's
# objects is added per check, from the catalog.
_PRIVILEGED_ROLES = ("dw_app", "pg_read_all_data", "pg_write_all_data")

# Who a check judges: every role but superusers and Postgres's predefined ones.
# A predefined role (`pg_read_all_data`) is reached through membership instead.
_JUDGED = "NOT r.rolsuper AND r.rolname NOT LIKE 'pg\\_%'"


async def _lines(conn: AsyncConnection, sql: str, **params: object) -> list[str]:
    rows = await conn.execute(sa.text(sql), params)
    return [str(row[0]) for row in rows]


async def _explicit_grants(conn: AsyncConnection, objects_sql: str, **params: object) -> list[str]:
    """Explicit ACL entries to PUBLIC or to a superuser on the given objects.

    `objects_sql` yields (label, acl, owner, kind) with kind an `acldefault`
    letter, so an object still on its default ACL is read as that default:
    a function no one revoked from PUBLIC is executable by PUBLIC.
    """
    return await _lines(
        conn,
        f"""
        SELECT o.label || ': ' || CASE a.grantee WHEN 0 THEN 'PUBLIC'
                                  ELSE a.grantee::regrole::text END
               || ' holds ' || a.privilege_type
        FROM ({objects_sql}) AS o(label, acl, owner, kind),
             aclexplode(coalesce(o.acl, acldefault(o.kind, o.owner))) a
        WHERE a.grantee <> o.owner
          AND (a.grantee = 0
               OR EXISTS (SELECT 1 FROM pg_roles s WHERE s.oid = a.grantee AND s.rolsuper))
        ORDER BY 1
        """,
        **params,
    )


async def studio_schema_violations(conn: AsyncConnection, definers: Mapping[str, str]) -> list[str]:
    """R2.3, R2.4, R2.5, R2.7, R2.9, R2.10 of the studio schema."""
    found: list[str] = []
    # R2.3: effective privilege of every judged role but the owner and dw_app.
    found += [
        f"R2.3 {line}"
        for line in await _lines(
            conn,
            f"""
            SELECT r.rolname || ' reaches schema studio'
            FROM pg_roles r, pg_namespace n
            WHERE n.nspname = :s AND {_JUDGED} AND r.oid <> n.nspowner
              AND r.rolname <> 'dw_app'
              AND has_schema_privilege(r.oid, n.oid, 'USAGE,CREATE')
            UNION ALL
            SELECT r.rolname || ' reaches ' || c.relname
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, pg_roles r
            WHERE n.nspname = :s AND {_JUDGED} AND r.oid <> c.relowner
              AND r.rolname <> 'dw_app'
              AND CASE WHEN c.relkind = 'S'
                       THEN has_sequence_privilege(r.oid, c.oid, 'USAGE,SELECT,UPDATE')
                       ELSE has_table_privilege(
                                r.oid, c.oid,
                                'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                            OR has_any_column_privilege(
                                r.oid, c.oid, 'SELECT,INSERT,UPDATE,REFERENCES')
                  END
            UNION ALL
            SELECT r.rolname || ' executes ' || p.proname
            FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace, pg_roles r
            WHERE n.nspname = :s AND {_JUDGED} AND r.oid <> p.proowner
              AND r.rolname <> 'dw_app'
              AND has_function_privilege(r.oid, p.oid, 'EXECUTE')
            UNION ALL
            SELECT DISTINCT r.rolname || ' is a member of ' || m.rolname
            FROM pg_roles r, pg_roles m
            WHERE {_JUDGED} AND r.rolname <> 'dw_app' AND r.oid <> m.oid
              AND (m.rolname = ANY(:privileged)
                   OR m.oid IN (SELECT nspowner FROM pg_namespace WHERE nspname = :s)
                   OR m.oid IN (SELECT c.relowner FROM pg_class c
                                JOIN pg_namespace n ON n.oid = c.relnamespace
                                WHERE n.nspname = :s))
              AND r.oid NOT IN (SELECT nspowner FROM pg_namespace WHERE nspname = :s)
              AND pg_has_role(r.oid, m.oid, 'MEMBER')
            ORDER BY 1
            """,
            s=STUDIO,
            privileged=list(_PRIVILEGED_ROLES),
        )
    ]
    # R2.3 and R2.4: explicit grants to PUBLIC or a superuser, the default ACL
    # included, so an unrevoked function shows PUBLIC's EXECUTE.
    explicit = await _explicit_grants(
        conn,
        """
        SELECT 'schema studio', n.nspacl, n.nspowner, 'n'::"char"
        FROM pg_namespace n WHERE n.nspname = :s
        UNION ALL
        SELECT c.relname, c.relacl, c.relowner,
               CASE c.relkind WHEN 'S' THEN 's' ELSE 'r' END::"char"
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = :s AND c.relkind IN ('r', 'p', 'v', 'm', 'S', 'f')
        UNION ALL
        SELECT c.relname || '.' || a.attname, a.attacl, c.relowner, 'c'::"char"
        FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = :s AND a.attacl IS NOT NULL
        UNION ALL
        SELECT p.proname, p.proacl, p.proowner, 'f'::"char"
        FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = :s
        """,
        s=STUDIO,
    )
    found += [f"{'R2.4' if ' holds EXECUTE' in e else 'R2.3'} {e}" for e in explicit]
    # R2.5: no sequence, no identity column (a serial column brings a sequence).
    found += [
        f"R2.5 {line}"
        for line in await _lines(
            conn,
            """
            SELECT 'sequence ' || c.relname FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :s AND c.relkind = 'S'
            UNION ALL
            SELECT 'identity column ' || c.relname || '.' || a.attname FROM pg_attribute a
            JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :s AND a.attidentity <> '' AND NOT a.attisdropped
            ORDER BY 1
            """,
            s=STUDIO,
        )
    ]
    # R2.7: dw_app holds its writes and nothing past them.
    found += [
        f"R2.7 {line}"
        for line in await _lines(
            conn,
            """
            SELECT 'dw_app holds CREATE on schema studio'
            FROM pg_namespace n
            WHERE n.nspname = :s AND has_schema_privilege('dw_app', n.oid, 'CREATE')
            UNION ALL
            SELECT 'dw_app holds ' || v.verb || ' on ' || c.relname
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace,
                 (VALUES ('TRUNCATE'), ('REFERENCES'), ('TRIGGER'), ('UPDATE')) v(verb)
            WHERE n.nspname = :s AND c.relkind IN ('r', 'p')
              AND has_table_privilege('dw_app', c.oid, v.verb)
            UNION ALL
            SELECT 'dw_app holds UPDATE on ' || c.relname || '.' || a.attname
            FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :s AND c.relkind IN ('r', 'p') AND NOT a.attisdropped
              AND a.attname IN ('id', 'tenant_id', 'workspace_id', 'owning_workspace_id')
              AND has_column_privilege('dw_app', c.oid, a.attnum, 'UPDATE')
            ORDER BY 1
            """,
            s=STUDIO,
        )
    ]
    # R2.9: a view runs as its invoker; a materialized view has no RLS at all.
    found += [
        f"R2.9 {line}"
        for line in await _lines(
            conn,
            """
            SELECT CASE c.relkind WHEN 'm' THEN 'materialized view ' ELSE 'view ' END
                   || c.relname
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = :s
              AND (c.relkind = 'm'
                   OR (c.relkind = 'v' AND NOT coalesce(
                        'security_invoker=true' = ANY(c.reloptions)
                        OR 'security_invoker=on' = ANY(c.reloptions), false)))
            ORDER BY 1
            """,
            s=STUDIO,
        )
    ]
    # R2.10: every SECURITY DEFINER function pins search_path and is listed,
    # and every listed one exists.
    present = {
        str(row[0]): bool(row[1])
        for row in await conn.execute(
            sa.text(
                "SELECT p.proname,"
                "       EXISTS (SELECT 1 FROM unnest(coalesce(p.proconfig, '{}')) c"
                "               WHERE c LIKE 'search\\_path=%')"
                " FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace"
                " WHERE n.nspname = :s AND p.prosecdef"
            ),
            {"s": STUDIO},
        )
    }
    found += [f"R2.10 definer {name} pins no search_path" for name, ok in present.items() if not ok]
    found += [f"R2.10 definer {name} is not listed" for name in present if name not in definers]
    found += [
        f"R2.10 listed definer {name} does not exist" for name in definers if name not in present
    ]
    return sorted(found)


async def studio_table_violations(
    conn: AsyncConnection | AsyncSession, reference_tables: Mapping[tuple[str, str], str]
) -> list[str]:
    """R2.8, R2.11: every studio table is a tenant table under forced RLS, but
    the platform reference tables, which hold no tenant's rows and which
    dw_app may only read."""
    rows = (
        await conn.execute(
            sa.text(
                """
                SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                       EXISTS (SELECT 1 FROM pg_attribute a WHERE a.attrelid = c.oid
                               AND a.attname = 'tenant_id' AND NOT a.attisdropped),
                       has_table_privilege('dw_app', c.oid,
                           'INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                       OR has_any_column_privilege('dw_app', c.oid, 'INSERT,UPDATE,REFERENCES')
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = :s AND c.relkind IN ('r', 'p') AND NOT c.relispartition
                ORDER BY 1
                """
            ),
            {"s": STUDIO},
        )
    ).all()
    found: list[str] = []
    listed = {table for schema, table in reference_tables if schema == STUDIO}
    for name, enabled, forced, has_tenant, writes in rows:
        if name in listed:
            if has_tenant:
                found.append(f"R2.11 reference table {name} has tenant_id")
            if writes:
                found.append(f"R2.11 dw_app may write reference table {name}")
            continue
        if not has_tenant:
            found.append(f"R2.8 {name} has no tenant_id")
        if not (enabled and forced):
            found.append(f"R2.8 {name} does not enable and force row security")
    existing = {row[0] for row in rows}
    found += [f"R2.11 listed reference table {t} does not exist" for t in listed - existing]
    return found


async def registry_violations(conn: AsyncConnection) -> list[str]:
    """R3.4, R3.5: the registry equals the range-partitioned parents that have a
    DEFAULT partition, both ways, and only its owner may write it."""
    found = await _lines(
        conn,
        """
        WITH parents AS (
            SELECT n.nspname AS schema_name, c.relname AS table_name
            FROM pg_partitioned_table p
            JOIN pg_class c ON c.oid = p.partrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE p.partstrat = 'r' AND NOT c.relispartition
              AND EXISTS (
                  SELECT 1 FROM pg_inherits i JOIN pg_class d ON d.oid = i.inhrelid
                  WHERE i.inhparent = c.oid AND d.relpartbound IS NOT NULL
                    AND pg_get_expr(d.relpartbound, d.oid) = 'DEFAULT')
        )
        SELECT 'R3.4 ' || p.schema_name || '.' || p.table_name
               || ' is range-partitioned with a DEFAULT partition and not registered'
        FROM parents p
        WHERE NOT EXISTS (SELECT 1 FROM platform.time_partitioned_tables r
                          WHERE r.schema_name = p.schema_name AND r.table_name = p.table_name)
        UNION ALL
        SELECT 'R3.4 registered ' || r.schema_name || '.' || r.table_name
               || ' (registered_by ' || r.registered_by
               || ') is not a range-partitioned table with a DEFAULT partition'
        FROM platform.time_partitioned_tables r
        WHERE NOT EXISTS (SELECT 1 FROM parents p
                          WHERE p.schema_name = r.schema_name AND p.table_name = r.table_name)
        ORDER BY 1
        """,
    )
    found += await _lines(
        conn,
        f"""
        SELECT 'R3.5 ' || r.rolname || ' may write platform.time_partitioned_tables'
        FROM pg_roles r, pg_class c
        WHERE c.oid = 'platform.time_partitioned_tables'::regclass AND {_JUDGED}
          AND r.oid <> c.relowner
          AND (has_table_privilege(r.oid, c.oid, 'INSERT,UPDATE,DELETE,TRUNCATE')
               OR has_any_column_privilege(r.oid, c.oid, 'INSERT,UPDATE'))
        UNION ALL
        SELECT 'R3.5 dw_app holds a privilege on platform.time_partitioned_tables'
        WHERE has_table_privilege('dw_app', 'platform.time_partitioned_tables',
                  'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
           OR has_any_column_privilege('dw_app', 'platform.time_partitioned_tables',
                  'SELECT,INSERT,UPDATE,REFERENCES')
        ORDER BY 1
        """,
    )
    found += [
        f"R3.5 {e}"
        for e in await _explicit_grants(
            conn,
            "SELECT 'platform.time_partitioned_tables', c.relacl, c.relowner, 'r'::\"char\""
            " FROM pg_class c WHERE c.oid = 'platform.time_partitioned_tables'::regclass",
        )
    ]
    return found


async def partition_violations(conn: AsyncConnection, schemas: Iterable[str]) -> list[str]:
    """R3.6: no role but the owner holds anything on a partition of a registered
    table, nor on any partition in studio or the given schemas: rows are read and
    written through the parent."""
    where = """
        c.relispartition
        AND (n.nspname = ANY(:schemas)
             OR EXISTS (SELECT 1 FROM pg_inherits i
                        JOIN pg_class parent ON parent.oid = i.inhparent
                        JOIN pg_namespace pn ON pn.oid = parent.relnamespace
                        JOIN platform.time_partitioned_tables r
                          ON r.schema_name = pn.nspname AND r.table_name = parent.relname
                        WHERE i.inhrelid = c.oid))
    """
    params = {"schemas": sorted({STUDIO, *schemas})}
    found = await _lines(
        conn,
        f"""
        WITH holders AS (
            SELECT n.nspname || '.' || c.relname AS part, r.oid AS role, r.rolname
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace, pg_roles r
            WHERE {where} AND {_JUDGED} AND r.oid <> c.relowner
              AND (has_table_privilege(r.oid, c.oid,
                       'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER')
                   OR has_any_column_privilege(r.oid, c.oid, 'SELECT,INSERT,UPDATE,REFERENCES'))
        )
        SELECT 'R3.6 ' || h.rolname || ' holds a privilege on partition ' || h.part
        FROM holders h
        UNION ALL
        SELECT DISTINCT 'R3.6 ' || r.rolname || ' reaches partition ' || h.part
               || ' as a member of ' || h.rolname
        FROM holders h, pg_roles r
        WHERE {_JUDGED} AND r.oid <> h.role AND pg_has_role(r.oid, h.role, 'MEMBER')
        ORDER BY 1
        """,
        **params,
    )
    found += [
        f"R3.6 {e}"
        for e in await _explicit_grants(
            conn,
            f"""
            SELECT n.nspname || '.' || c.relname, c.relacl, c.relowner, 'r'::"char"
            FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE {where}
            UNION ALL
            SELECT n.nspname || '.' || c.relname || '.' || a.attname, a.attacl, c.relowner,
                   'c'::"char"
            FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE {where} AND a.attacl IS NOT NULL
            """,
            **params,
        )
    ]
    return found


async def append_only_violations(
    conn: AsyncConnection, term_of: Callable[[str], RetentionTerm | None]
) -> list[str]:
    """R3.7, R3.8: every registered table has a retention term, and its
    `append_only` flag says what dw_app's grants on the parent say."""
    rows = (
        await conn.execute(
            sa.text(
                """
                SELECT r.schema_name || '.' || r.table_name, r.append_only, r.registered_by,
                       coalesce(has_table_privilege('dw_app', c.oid, 'UPDATE')
                                OR has_any_column_privilege('dw_app', c.oid, 'UPDATE'), false),
                       coalesce(has_table_privilege('dw_app', c.oid, 'DELETE'), false)
                FROM platform.time_partitioned_tables r
                LEFT JOIN pg_namespace n ON n.nspname = r.schema_name
                LEFT JOIN pg_class c ON c.relnamespace = n.oid AND c.relname = r.table_name
                ORDER BY 1
                """
            )
        )
    ).all()
    found: list[str] = []
    for key, append_only, registered_by, updates, deletes in rows:
        if term_of(key) is None:
            found.append(f"R3.7 {key} (registered_by {registered_by}) has no retention term")
        if append_only and (updates or deletes):
            found.append(f"R3.8 {key} is append_only but dw_app holds UPDATE or DELETE")
        if not append_only and not (updates or deletes):
            found.append(
                f"R3.8 {key} is not append_only but dw_app holds neither UPDATE nor DELETE"
            )
    return found
