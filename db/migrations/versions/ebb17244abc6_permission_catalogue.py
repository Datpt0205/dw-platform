"""permission catalogue

Revision ID: ebb17244abc6
Revises: 1fb796131647
Create Date: 2026-11-02

tenant-rbac ticket 01 (R1.1-R1.3, R1.6; RB1, RB2; ADR-0104 decision 1): one
row per permission key the platform knows, written by migrations only. A
global table (no `tenant_id`, no RLS): what a key means is the platform's
fact, not a tenant's. No application role writes it; `dw_app` and
`dw_agent_ro` read it, `dw_provisioner` does not (it holds only what its code
runs).

Seed, the keys in use on 2/11/2026, each with a state by three rules that
`test_permission_catalogue.py` holds: a key a seeded role or permission set
grants is never `unassigned`; a key code checks is never `retired`; an
`active` key has a check or a listed exception. The anomalies carry their
reason:

- `retired`: `approvals.pending` (granted to approver, manager, director and
  `approver_boost`; only a page cursor's key, `approvals.py`) and
  `feedback.inbox` (granted to org_admin; only a page cursor's key,
  `feedback.py`, the route checks `platform.members.read`);
- `unassigned`: `runs.cancel`, `knowledge.publish_global`,
  `crm.records.all.read` (checked, granted by no role or set) and
  `platform.usage.read` (taken from org_admin in 0013; usage-and-limits uses
  it again and makes it `active` in its own migration, the one usage key).

Classification:

- `risk`: `critical` for `platform.admin` and `platform.sod_waivers.write`,
  `elevated` for every other `platform.*`, `standard` for the rest;
- `scope_kind`: `tenant` for the keys of routes reading across the tenant
  (`platform.*`, `support.*`), `workspace` for the rest. `dw.read` and
  `dw.manage` are workspace keys although a DW row is tenant-wide with an
  owning workspace (be93e0c26a4c): they are held by a membership of one
  workspace and checked there, so tenant-rbac/02 anchors them at the
  workspace a role is assigned to.

From now on each Studio cluster registers every key it checks in its own
migration, with every NOT NULL column of the catalogue at that time.
"""

from __future__ import annotations

from alembic import op

revision = "ebb17244abc6"
down_revision = "1fb796131647"
branch_labels = None
depends_on = None

_TABLE = "platform.permissions"
_ROLES = ("dw_app", "dw_provisioner", "dw_agent_ro")

# (key, area, label_vi, scope_kind, risk, status, status_reason, owner_package)
_SEED: tuple[tuple[str, str, str, str, str, str, str | None, str], ...] = (
    (
        "approvals.read",
        "approvals",
        "Xem yêu cầu duyệt",
        "workspace",
        "standard",
        "active",
        None,
        "dw_platform",
    ),
    (
        "approvals.decide",
        "approvals",
        "Quyết yêu cầu duyệt",
        "workspace",
        "standard",
        "active",
        None,
        "dw_platform",
    ),
    (
        "approvals.pending",
        "approvals",
        "Danh sách chờ duyệt (cũ)",
        "workspace",
        "standard",
        "retired",
        "chỉ là khóa con trỏ trang của approvals.py; không route nào kiểm, approvals.read thay",
        "dw_platform",
    ),
    (
        "audit.events",
        "audit",
        "Xem nhật ký audit",
        "workspace",
        "standard",
        "active",
        None,
        "dw_platform",
    ),
    (
        "crm.records.all.read",
        "crm",
        "Xem mọi bản ghi của workspace",
        "workspace",
        "standard",
        "unassigned",
        "membership_lookup đọc để mở rộng tầm xem bản ghi; chưa vai trò hay bộ quyền nào cấp",
        "dw_platform",
    ),
    (
        "directory.read",
        "directory",
        "Xem danh bạ",
        "workspace",
        "standard",
        "active",
        None,
        "dw_platform",
    ),
    ("dw.read", "dw", "Xem Digital Worker", "workspace", "standard", "active", None, "dw_platform"),
    (
        "dw.manage",
        "dw",
        "Quản lý Digital Worker",
        "workspace",
        "standard",
        "active",
        None,
        "dw_platform",
    ),
    (
        "feedback.inbox",
        "feedback",
        "Hộp góp ý (cũ)",
        "workspace",
        "standard",
        "retired",
        "chỉ là khóa con trỏ trang của feedback.py; route kiểm platform.members.read",
        "dw_platform",
    ),
    (
        "integrations.read",
        "integrations",
        "Xem tích hợp",
        "workspace",
        "standard",
        "active",
        None,
        "dw_platform",
    ),
    (
        "knowledge.read",
        "knowledge",
        "Đọc tri thức",
        "workspace",
        "standard",
        "active",
        None,
        "dw_knowledge",
    ),
    (
        "knowledge.write",
        "knowledge",
        "Thêm và sửa tri thức",
        "workspace",
        "standard",
        "active",
        None,
        "dw_knowledge",
    ),
    (
        "knowledge.publish_global",
        "knowledge",
        "Xuất bản tri thức dùng chung",
        "workspace",
        "standard",
        "unassigned",
        "cổng tri thức kiểm; chưa vai trò hay bộ quyền nào cấp",
        "dw_knowledge",
    ),
    ("memory.read", "memory", "Xem bộ nhớ", "workspace", "standard", "active", None, "dw_memory"),
    (
        "runs.read",
        "runs",
        "Xem lượt chạy",
        "workspace",
        "standard",
        "active",
        None,
        "dw_agent_runtime",
    ),
    (
        "runs.cancel",
        "runs",
        "Dừng lượt chạy",
        "workspace",
        "standard",
        "unassigned",
        "route dừng lượt chạy kiểm; chưa vai trò hay bộ quyền nào cấp",
        "dw_agent_runtime",
    ),
    (
        "platform.admin",
        "platform",
        "Quản trị nền tảng",
        "tenant",
        "critical",
        "active",
        None,
        "dw_platform",
    ),
    (
        "platform.members.read",
        "platform",
        "Xem thành viên",
        "tenant",
        "elevated",
        "active",
        None,
        "dw_platform",
    ),
    (
        "platform.members.write",
        "platform",
        "Quản lý thành viên",
        "tenant",
        "elevated",
        "active",
        None,
        "dw_platform",
    ),
    (
        "platform.roles.read",
        "platform",
        "Xem vai trò và quyền",
        "tenant",
        "elevated",
        "active",
        None,
        "dw_platform",
    ),
    (
        "platform.sod_waivers.write",
        "platform",
        "Miễn trừ tách nhiệm",
        "tenant",
        "critical",
        "active",
        None,
        "dw_platform",
    ),
    (
        "platform.tenant.settings.write",
        "platform",
        "Sửa cài đặt công ty",
        "tenant",
        "elevated",
        "active",
        None,
        "dw_platform",
    ),
    (
        "platform.workspaces.write",
        "platform",
        "Quản lý workspace",
        "tenant",
        "elevated",
        "active",
        None,
        "dw_platform",
    ),
    (
        "platform.usage.read",
        "platform",
        "Xem mức sử dụng",
        "tenant",
        "elevated",
        "unassigned",
        "usage-and-limits dùng lại và đưa về active trong migration của nó",
        "dw_platform",
    ),
    (
        "support.request",
        "support",
        "Xin truy cập hỗ trợ",
        "tenant",
        "standard",
        "active",
        None,
        "dw_platform",
    ),
    (
        "support.grant",
        "support",
        "Cấp truy cập hỗ trợ",
        "tenant",
        "standard",
        "active",
        None,
        "dw_platform",
    ),
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


def _literal(value: str | None) -> str:
    return "NULL" if value is None else "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {_TABLE} (
            key text NOT NULL,
            area text NOT NULL,
            label_vi text NOT NULL,
            description_vi text,
            scope_kind text NOT NULL,
            risk text NOT NULL,
            status text NOT NULL,
            status_reason text,
            owner_package text NOT NULL,
            created_at timestamp with time zone DEFAULT now() NOT NULL,
            CONSTRAINT pk_permissions PRIMARY KEY (key),
            CONSTRAINT ck_permissions_key
                CHECK (key ~ '^[a-z][a-z0-9_]*(\\.[a-z0-9_]+)+$'),
            CONSTRAINT ck_permissions_label_vi CHECK (btrim(label_vi) <> ''),
            CONSTRAINT ck_permissions_scope_kind
                CHECK (scope_kind IN ('tenant', 'workspace', 'record')),
            CONSTRAINT ck_permissions_risk CHECK (risk IN ('standard', 'elevated', 'critical')),
            CONSTRAINT ck_permissions_status CHECK (status IN ('active', 'unassigned', 'retired')),
            CONSTRAINT ck_permissions_status_reason
                CHECK (status = 'active' OR btrim(coalesce(status_reason, '')) <> '')
        )
        """
    )
    rows = ",\n".join("(" + ", ".join(_literal(v) for v in row) + ")" for row in _SEED)
    op.execute(
        f"INSERT INTO {_TABLE} (key, area, label_vi, scope_kind, risk, status, status_reason,"
        f" owner_package) VALUES\n{rows}"
    )
    for role in _ROLES:
        op.execute(
            _for_role(role, f"REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON {_TABLE} FROM {role};")
        )
    # The readers. Not `dw_provisioner`: it holds exactly what its code runs
    # (`test_the_provisioner_holds_exactly_what_its_code_runs`), and none of
    # it reads the catalogue; sign-in reads scopes as `dw_app`.
    for role in ("dw_app", "dw_agent_ro"):
        op.execute(_for_role(role, f"GRANT SELECT ON {_TABLE} TO {role};"))


def downgrade() -> None:
    op.execute(f"DROP TABLE {_TABLE}")
