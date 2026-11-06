"""owner coverage per transaction, hold rule per anchor, separation of duties
skips keys outside every rule

Revision ID: a7ca12c36ec7
Revises: fece6611d786
Create Date: 2026-11-05 14:34:33.515111+00:00

tenant-rbac ticket 08 (discovery/08 findings 2-4; R3.12, R5.1, R6.1, R6.3,
R9.5; RB14-RB16, RB40; ADR-0104 decisions 6, 9, 10). Three triggers cost by
the anchors and rules they judge, not by the assignments a role has. Every
write is accepted or refused as before, with the same constraint, reason code
and missing keys; the one answer that changes, on purpose, is the warning of a
fall below two holders that a transaction itself undoes before it commits.

- `platform.owner_coverage_after_write()` runs from one deferred constraint
  trigger per covered table, at commit, instead of three statement triggers
  that ran `platform.check_owner_coverage` at every statement. A mark per
  tenant per transaction (`dw_owner_coverage.t_<tenant>`) holds the tenant's
  access version read right after the check; every write of the four tables
  moves that version (`trg_z_bump_access_version`), so a row firing on a stale
  or missing mark checks again. `SET CONSTRAINTS ALL IMMEDIATE` therefore
  checks every statement that wrote, as the statement triggers did, and
  `ROLLBACK TO SAVEPOINT` rolls the mark back with the version.
  `check_owner_coverage` itself is unchanged.
- `platform.rbac_refusals`, ops `add`, `raise`, `remove`, `lower` on a role
  someone holds: the hold rule judged once at `tenant` depth
  (`holder_covers_grant(..., NULL)`, true only when the actor holds the key at
  `tenant`, where it is true at every anchor), then at each distinct workspace
  the role is assigned at, as `role_delete` does, instead of at every
  assignment. The rule is still `platform.holder_covers_grant`.
- `platform.enforce_role_separation_of_duties()` on `tenant_role_permissions`:
  a key in no rule's sides makes no holder hold one more side, so one
  set-based question asks whether any holder breaks a rule already; nobody,
  and no `platform.sod_violation` runs. Anybody, and the path of before runs
  unchanged (same refusal, detail, hint and `FOR SHARE` on the waiver).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

from alembic import op

revision = "a7ca12c36ec7"
down_revision = "fece6611d786"
branch_labels = None
depends_on = None


def _earlier(filename: str) -> ModuleType:
    """An earlier revision's module, for the function bodies this one patches
    (and restores on the way down) without a second copy of them."""
    path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(f"dw_rev_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_ROLES_02 = _earlier("b5677d345bc1_tenant_roles.py")
_OBJECTS_04 = _earlier("ef68083f2905_object_and_field_privileges_in_roles.py")


def _patched(body: str, *edits: tuple[str, str]) -> str:
    """``body`` with each (old, new) applied once; an anchor that moved fails
    the migration instead of shipping the old function."""
    for old, new in edits:
        if body.count(old) != 1:
            raise RuntimeError(f"tenant-rbac/08: anchor not found exactly once: {old[:60]!r}")
        body = body.replace(old, new)
    return body


def _replace(body: str) -> str:
    return _patched(body, ("CREATE FUNCTION", "CREATE OR REPLACE FUNCTION"))


def _statement(statements: tuple[str, ...], name: str) -> str:
    (found,) = [s for s in statements if f"FUNCTION {name}(" in s]
    return found


# -- 1. owner coverage, once per tenant per transaction ---------------------------

_COVERAGE_BEFORE = _statement(_ROLES_02._COVERAGE, "platform.owner_coverage_after_write")

# A constraint trigger has no transition table: the row's tenant (both, when an
# update moves it) is checked unless the mark says the tenant was checked at
# the access version it still has. The mark is a version, never "checked": a
# later write moves the version, so the mark goes stale on its own.
_COVERAGE = """
    CREATE OR REPLACE FUNCTION platform.owner_coverage_after_write() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_tenant uuid;
        v_mark text;
        v_version text;
    BEGIN
        FOR v_tenant IN
            SELECT DISTINCT t.id
            FROM unnest(ARRAY[
                CASE WHEN TG_OP <> 'INSERT' THEN OLD.tenant_id END,
                CASE WHEN TG_OP <> 'DELETE' THEN NEW.tenant_id END
            ]) AS t(id)
            WHERE t.id IS NOT NULL
        LOOP
            v_mark := 'dw_owner_coverage.t_' || replace(v_tenant::text, '-', '');
            SELECT v.version::text INTO v_version
            FROM platform.tenant_access_versions v WHERE v.tenant_id = v_tenant;
            IF v_version IS NULL
               OR current_setting(v_mark, true) IS DISTINCT FROM v_version THEN
                PERFORM platform.check_owner_coverage(v_tenant);
                SELECT v.version::text INTO v_version
                FROM platform.tenant_access_versions v WHERE v.tenant_id = v_tenant;
                PERFORM set_config(v_mark, coalesce(v_version, ''), true);
            END IF;
        END LOOP;
        RETURN NULL;
    END
    $$
"""

_COVERED_TABLES: tuple[str, ...] = _ROLES_02._COVERED_TABLES
_STATEMENT_TRIGGERS = tuple(
    statement
    for statement in _ROLES_02._behaviour_triggers()
    if "owner_coverage_after_write" in statement
)
assert len(_STATEMENT_TRIGGERS) == 3 * len(_COVERED_TABLES)

_CONSTRAINT_TRIGGERS = tuple(
    f"CREATE CONSTRAINT TRIGGER trg_{table}_owner_coverage"
    f" AFTER INSERT OR UPDATE OR DELETE ON platform.{table}"
    " DEFERRABLE INITIALLY DEFERRED FOR EACH ROW"
    " EXECUTE FUNCTION platform.owner_coverage_after_write()"
    for table in _COVERED_TABLES
)

# -- 2. the hold rule, per anchor -------------------------------------------------

_REFUSALS_BEFORE = _OBJECTS_04._REFUSALS

_REFUSALS = _patched(
    _REFUSALS_BEFORE,
    (
        """                ) THEN EXISTS (
                    SELECT 1 FROM platform.role_assignments a
                    WHERE a.tenant_id = p_tenant_id AND a.role_id = v_role
                      AND NOT platform.holder_covers_grant(
                          p_tenant_id, p_actor_id, v_key, v_depth, a.workspace_id
                      )
                )""",
        """                ) THEN CASE
                    -- At `tenant` depth the actor covers every anchor.
                    WHEN platform.holder_covers_grant(
                        p_tenant_id, p_actor_id, v_key, v_depth, NULL
                    ) THEN false
                    -- Materialized: a stable call would otherwise be pushed below
                    -- the DISTINCT and run once per assignment again (measured).
                    ELSE EXISTS (
                        WITH w AS MATERIALIZED (
                            SELECT DISTINCT a.workspace_id FROM platform.role_assignments a
                            WHERE a.tenant_id = p_tenant_id AND a.role_id = v_role
                        )
                        SELECT 1 FROM w
                        WHERE NOT platform.holder_covers_grant(
                            p_tenant_id, p_actor_id, v_key, v_depth, w.workspace_id
                        )
                    )
                END""",
    ),
)

# -- 3. separation of duties, keys outside every rule -----------------------------

_SOD_BEFORE = _statement(_ROLES_02._SOD, "platform.enforce_role_separation_of_duties")

# A privilege whose key is on neither side of any rule adds no side to anyone,
# so after the write a holder breaks a rule exactly when they did before. The
# trigger still refuses that case (ADR-0104 decision 9: no change may leave a
# holder in breach), so it asks once, over the same people and the same keys
# as `platform.sod_held_keys` (every assigned key but `tenant_owner`'s), whether
# anyone breaks a rule, waivers aside; only then does the path of before run.
# Ignoring waivers here only runs that path more often, never skips a refusal.
_SOD = _patched(
    _replace(_SOD_BEFORE),
    (
        """                WHERE a.tenant_id = NEW.tenant_id AND a.role_id = NEW.role_id
            );
        END IF;""",
        """                WHERE a.tenant_id = NEW.tenant_id AND a.role_id = NEW.role_id
            );
            IF NOT EXISTS (
                SELECT 1 FROM platform.sod_rules s
                WHERE EXISTS (SELECT 1 FROM jsonb_array_elements_text(s.left_scopes) l(key)
                              WHERE l.key = NEW.permission_key)
                   OR EXISTS (SELECT 1 FROM jsonb_array_elements_text(s.right_scopes) r(key)
                              WHERE r.key = NEW.permission_key)
            ) AND NOT EXISTS (
                SELECT 1
                FROM (
                    SELECT g.user_id, array_agg(DISTINCT g.permission_key) AS keys
                    FROM platform.assigned_grants(NEW.tenant_id) g
                    WHERE g.user_id = ANY (v_people) AND g.role_key <> 'tenant_owner'
                    GROUP BY g.user_id
                ) h
                CROSS JOIN platform.sod_rules s
                WHERE platform.sod_rule_broken(s.key, h.keys)
            ) THEN
                RETURN NULL;
            END IF;
        END IF;""",
    ),
)


def upgrade() -> None:
    # Replacing a body keeps its owner, SECURITY DEFINER and EXECUTE grants.
    op.execute(_COVERAGE)
    for table in _COVERED_TABLES:
        for event in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER trg_{table}_owner_coverage_{event} ON platform.{table}")
    for statement in _CONSTRAINT_TRIGGERS:
        op.execute(statement)
    op.execute(_REFUSALS)
    op.execute(_SOD)


def downgrade() -> None:
    op.execute(_replace(_SOD_BEFORE))
    op.execute(_REFUSALS_BEFORE)
    for table in _COVERED_TABLES:
        op.execute(f"DROP TRIGGER trg_{table}_owner_coverage ON platform.{table}")
    op.execute(_replace(_COVERAGE_BEFORE))
    for statement in _STATEMENT_TRIGGERS:
        op.execute(statement)
