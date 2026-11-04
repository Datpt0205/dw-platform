"""config versions and bindings

Revision ID: 045712d63ec7
Revises: ae3c7ee10b50
Create Date: 2026-11-04 18:56:26.752384+00:00

tenant-config ticket 05 (R2.18, R3.6-R3.8, R7, R8; TC15-TC21, TC25, TC26,
TC29, TC31, TC33, TC34; ADR-0110 decisions 1-8; ADR-0104 decision 11). A
tenant's own configuration, versioned and approved by a second person:

- `platform.config_versions`: every proposal of a kind's key (W1: one kind,
  `binding_set`, keyed by an artifact's id), numbered per key and never
  renumbered; `workspace_id` is where it was proposed, the key's owning
  workspace, held to its `config.version` request by the composite key
  `(tenant_id, workspace_id, approval_id)` to
  `uq_approval_requests_tenant_id_workspace_id_id`, RESTRICT (R8.16). One
  `proposed` and one `approved` row per key (partial uniques); the decider is
  never the proposer (`ck_config_versions_checker_not_maker`); and
  `platform.config_version_transition()` (trigger `approved_by_approval`)
  allows `proposed` to `approved` (only while the linked request is
  `approved`), `rejected` or `withdrawn`, and `approved` to `superseded`,
  nothing else (R8.12). `document` is a JSON object of at most 256 KiB in NFC;
  `base_bindings_hash` is the hash of what the base version declared, and
  `base_approved_id` the approved row in force when it was proposed (no key:
  a record of history), which the decision guard and the settlement compare.
  Tenant-wide under the tenant policy, ENABLEd and FORCEd: a row's workspace
  is the key's, and a reader in another workspace is refused by the kind's
  read key, not by RLS.
- `platform.run_manifest_keys.config_version_id`: the Binding set a manifest
  pins, by the composite key to `uq_config_versions_tenant_id_id`, RESTRICT
  (R2.18), indexed and unique per manifest; exactly one of it and
  `artifact_version_id` per row (`ck_run_manifest_keys_one_target`), so the
  latter loses its NOT NULL in the same step.
- `dw_app` holds SELECT, INSERT, DELETE and UPDATE of the five decision
  columns only; the DELETE serves the offboarding lane's pass alone,
  `platform.refuse_delete_outside_offboarding()` refuses it elsewhere (R3.8).
  The order of the purge comes from the catalog's RESTRICT edges: the keys
  before the versions, the versions before the requests (R3.6).
- `studio.bindings.propose` and `studio.bindings.approve` in the catalogue:
  workspace depth, `standard` risk, `active`, `dw_studio`, tenant-grantable.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "045712d63ec7"
down_revision = "ae3c7ee10b50"
branch_labels = None
depends_on = None

# The shape `test_rls_coverage.py` requires.
_TENANT = "(tenant_id = (SELECT NULLIF(current_setting('app.tenant_id', true), '')::uuid))"
_HASH = "~ '^sha256:[0-9a-f]{64}$'"
_KIB_256 = 262144

PERMISSIONS = (
    ("studio.bindings.propose", "Đề xuất giá trị điểm gắn của thành phần"),
    ("studio.bindings.approve", "Duyệt giá trị điểm gắn của thành phần"),
)

_TABLE = (
    f"""
    CREATE TABLE platform.config_versions (
        id uuid NOT NULL,
        tenant_id uuid NOT NULL,
        workspace_id uuid NOT NULL,
        kind text NOT NULL,
        key text NOT NULL,
        action text NOT NULL,
        version_no integer NOT NULL,
        base_version integer NOT NULL,
        base_bindings_hash text NOT NULL,
        base_approved_id uuid,
        document jsonb NOT NULL,
        document_hash text NOT NULL,
        status text NOT NULL,
        approval_id uuid NOT NULL,
        proposed_by uuid NOT NULL,
        proposed_at timestamp with time zone DEFAULT now() NOT NULL,
        decided_by uuid,
        decided_at timestamp with time zone,
        decision_comment text,
        superseded_at timestamp with time zone,
        CONSTRAINT pk_config_versions PRIMARY KEY (id),
        CONSTRAINT uq_config_versions_tenant_id_id UNIQUE (tenant_id, id),
        CONSTRAINT uq_config_versions_tenant_id_kind_key_version_no
            UNIQUE (tenant_id, kind, key, version_no),
        CONSTRAINT fk_config_versions_tenant_id_tenants FOREIGN KEY (tenant_id)
            REFERENCES platform.tenants (id) ON DELETE RESTRICT,
        CONSTRAINT fk_config_versions_approval_id_approval_requests
            FOREIGN KEY (approval_id, tenant_id, workspace_id)
            REFERENCES platform.approval_requests (id, tenant_id, workspace_id)
            ON DELETE RESTRICT,
        CONSTRAINT ck_config_versions_kind CHECK (kind IN ('binding_set')),
        CONSTRAINT ck_config_versions_action CHECK (action IN ('set')),
        CONSTRAINT ck_config_versions_status
            CHECK (status IN ('proposed', 'approved', 'rejected', 'withdrawn', 'superseded')),
        CONSTRAINT ck_config_versions_key CHECK (char_length(key) BETWEEN 1 AND 200),
        CONSTRAINT ck_config_versions_version_no CHECK (version_no >= 1),
        CONSTRAINT ck_config_versions_base_version CHECK (base_version >= 1),
        CONSTRAINT ck_config_versions_base_bindings_hash CHECK (base_bindings_hash {_HASH}),
        CONSTRAINT ck_config_versions_document_hash CHECK (document_hash {_HASH}),
        CONSTRAINT ck_config_versions_document_object CHECK (jsonb_typeof(document) = 'object'),
        CONSTRAINT ck_config_versions_document_size
            CHECK (octet_length(document::text) <= {_KIB_256}),
        CONSTRAINT ck_config_versions_document_nfc CHECK (document::text IS NFC NORMALIZED),
        CONSTRAINT ck_config_versions_comment CHECK (char_length(decision_comment) <= 2000),
        CONSTRAINT ck_config_versions_checker_not_maker
            CHECK (decided_by IS NULL OR decided_by <> proposed_by),
        CONSTRAINT ck_config_versions_decided CHECK (
            (status = 'proposed' AND decided_by IS NULL AND decided_at IS NULL)
            OR (status = 'withdrawn' AND decided_by IS NULL AND decided_at IS NOT NULL)
            OR (status IN ('approved', 'rejected', 'superseded')
                AND decided_by IS NOT NULL AND decided_at IS NOT NULL)
        ),
        CONSTRAINT ck_config_versions_superseded
            CHECK ((status = 'superseded') = (superseded_at IS NOT NULL))
    )
    """,
    # The request's key, its own index (R8.16); one row per request.
    "CREATE UNIQUE INDEX ix_config_versions_tenant_id_workspace_id_approval_id"
    " ON platform.config_versions (tenant_id, workspace_id, approval_id)",
    "CREATE UNIQUE INDEX uq_config_versions_tenant_id_kind_key_proposed"
    " ON platform.config_versions (tenant_id, kind, key) WHERE status = 'proposed'",
    "CREATE UNIQUE INDEX uq_config_versions_tenant_id_kind_key_approved"
    " ON platform.config_versions (tenant_id, kind, key) WHERE status = 'approved'",
)

# Written out, not looped: `scripts/verify_invariants.py` reads this text.
_RLS = (
    "ALTER TABLE platform.config_versions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE platform.config_versions FORCE ROW LEVEL SECURITY",
    "CREATE POLICY tenant_isolation_config_versions ON platform.config_versions"
    f" USING {_TENANT} WITH CHECK {_TENANT}",
)

_KEYS = (
    "ALTER TABLE platform.run_manifest_keys ADD COLUMN config_version_id uuid",
    "ALTER TABLE platform.run_manifest_keys ALTER COLUMN artifact_version_id DROP NOT NULL",
    """
    ALTER TABLE platform.run_manifest_keys
        ADD CONSTRAINT fk_run_manifest_keys_config_version_id_config_versions
            FOREIGN KEY (config_version_id, tenant_id)
            REFERENCES platform.config_versions (id, tenant_id) ON DELETE RESTRICT,
        ADD CONSTRAINT ck_run_manifest_keys_one_target
            CHECK (num_nonnulls(artifact_version_id, config_version_id) = 1),
        ADD CONSTRAINT uq_run_manifest_keys_tenant_id_manifest_hash_config_version_id
            UNIQUE (tenant_id, manifest_hash, config_version_id)
    """,
    "CREATE INDEX ix_run_manifest_keys_tenant_id_config_version_id"
    " ON platform.run_manifest_keys (tenant_id, config_version_id)",
)

# R8.12 (TC17): `approved` only through an approved request, and the four
# moves; a definer so the request is read whoever writes, under its tenant.
_TRANSITION = """
    CREATE FUNCTION platform.config_version_transition() RETURNS trigger
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, platform
    AS $$
    DECLARE
        v_request text;
    BEGIN
        IF NOT ((OLD.status = 'proposed'
                 AND NEW.status IN ('approved', 'rejected', 'withdrawn'))
                OR (OLD.status = 'approved' AND NEW.status = 'superseded')) THEN
            RAISE EXCEPTION 'a configuration version moves proposed -> approved, rejected or'
                ' withdrawn, and approved -> superseded'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_config_versions_status_transition';
        END IF;
        IF (NEW.id, NEW.tenant_id, NEW.workspace_id, NEW.kind, NEW.key, NEW.action,
            NEW.version_no, NEW.base_version, NEW.base_bindings_hash, NEW.base_approved_id,
            NEW.document, NEW.document_hash, NEW.approval_id, NEW.proposed_by,
            NEW.proposed_at)
           IS DISTINCT FROM
           (OLD.id, OLD.tenant_id, OLD.workspace_id, OLD.kind, OLD.key, OLD.action,
            OLD.version_no, OLD.base_version, OLD.base_bindings_hash, OLD.base_approved_id,
            OLD.document, OLD.document_hash, OLD.approval_id, OLD.proposed_by,
            OLD.proposed_at) THEN
            RAISE EXCEPTION 'a configuration version keeps what was proposed'
                USING ERRCODE = '23514', CONSTRAINT = 'ck_config_versions_status_transition';
        END IF;
        IF NEW.status = 'approved' THEN
            SELECT r.status INTO v_request FROM platform.approval_requests r
            WHERE r.tenant_id = NEW.tenant_id AND r.id = NEW.approval_id;
            IF v_request IS DISTINCT FROM 'approved' THEN
                RAISE EXCEPTION 'a configuration version is approved by its approved request'
                    USING ERRCODE = '23514',
                          CONSTRAINT = 'ck_config_versions_approved_by_approval';
            END IF;
        END IF;
        RETURN NEW;
    END
    $$
    """

_TRIGGERS = (
    "CREATE TRIGGER approved_by_approval BEFORE UPDATE ON platform.config_versions"
    " FOR EACH ROW EXECUTE FUNCTION platform.config_version_transition()",
    # R3.8 (TC31): only the offboarding lane's pass deletes these rows.
    "CREATE TRIGGER refuse_delete_outside_offboarding BEFORE DELETE"
    " ON platform.config_versions"
    " FOR EACH ROW EXECUTE FUNCTION platform.refuse_delete_outside_offboarding()",
)

# `ALTER DEFAULT PRIVILEGES` hands `dw_app` every verb and `dw_agent_ro`
# SELECT on a new platform table; these hold exactly what the service, the
# settlement and the offboarding lane run.
_GRANTS = (
    ("dw_app", "REVOKE ALL ON platform.config_versions FROM dw_app;"),
    ("dw_app", "GRANT SELECT, INSERT, DELETE ON platform.config_versions TO dw_app;"),
    (
        "dw_app",
        "GRANT UPDATE (status, decided_by, decided_at, decision_comment, superseded_at)"
        " ON platform.config_versions TO dw_app;",
    ),
    ("dw_agent_ro", "REVOKE ALL ON platform.config_versions FROM dw_agent_ro;"),
)


def _for_role(role: str, statement: str) -> str:
    return f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                {statement}
            END IF;
        END
        $$
        """


def upgrade() -> None:
    for statement in _TABLE:
        op.execute(statement)
    for statement in _RLS:
        op.execute(statement)
    for statement in _KEYS:
        op.execute(statement)
    op.execute(_TRANSITION)
    # Called by its trigger and by no role.
    op.execute("REVOKE ALL ON FUNCTION platform.config_version_transition() FROM PUBLIC")
    for statement in _TRIGGERS:
        op.execute(statement)
    for role, statement in _GRANTS:
        op.execute(_for_role(role, statement))
    # Every NOT NULL column of the catalogue (tenant-rbac/01, /02).
    for key, label in PERMISSIONS:
        op.execute(
            sa.text(
                "INSERT INTO platform.permissions (key, area, label_vi, scope_kind, risk, status,"
                " status_reason, owner_package, tenant_grantable)"
                " VALUES (:k, 'studio', :l, 'workspace', 'standard', 'active', NULL,"
                " 'dw_studio', true)"
                " ON CONFLICT (key) DO NOTHING"
            ).bindparams(k=key, l=label)
        )


def downgrade() -> None:
    for key, _label in PERMISSIONS:
        op.execute(
            sa.text(
                "DELETE FROM platform.tenant_role_permissions WHERE permission_key = :k"
            ).bindparams(k=key)
        )
        op.execute(sa.text("DELETE FROM platform.permissions WHERE key = :k").bindparams(k=key))
    op.execute("DROP INDEX platform.ix_run_manifest_keys_tenant_id_config_version_id")
    op.execute(
        "ALTER TABLE platform.run_manifest_keys"
        " DROP CONSTRAINT uq_run_manifest_keys_tenant_id_manifest_hash_config_version_id,"
        " DROP CONSTRAINT ck_run_manifest_keys_one_target,"
        " DROP CONSTRAINT fk_run_manifest_keys_config_version_id_config_versions,"
        " DROP COLUMN config_version_id"
    )
    op.execute("ALTER TABLE platform.run_manifest_keys ALTER COLUMN artifact_version_id SET NOT NULL")
    op.execute("DROP TABLE platform.config_versions")
    op.execute("DROP FUNCTION platform.config_version_transition()")
