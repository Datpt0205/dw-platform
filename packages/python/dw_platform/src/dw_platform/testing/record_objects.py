"""Planting a company object and its fields for a test, in raw SQL
(tenant-rbac ticket 04).

What a role's object privileges and field permissions name is a live
definition: a `studio.object_defs` row (and its `object` artifact and version)
and `studio.field_defs` rows. Written as the migrator past every policy, the
way `dw_platform.testing.rbac` plants roles; the publish hook
(`MetadataService.apply`) is custom-objects' and tested there.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import sqlalchemy as sa

from dw_platform.testing.rbac import Conn, PlantedTenant


@dataclass(frozen=True)
class Lead:
    """A live `lead` object of one tenant and its fields."""

    object_id: uuid.UUID
    fields: dict[str, uuid.UUID]

    def __getitem__(self, api_name: str) -> uuid.UUID:
        return self.fields[api_name]


async def plant_object(
    conn: Conn,
    tenant: PlantedTenant,
    api_name: str = "lead",
    fields: dict[str, str] | None = None,
) -> Lead:
    """An `object` artifact, a version and its live definition with ``fields``
    (api_name -> pd_category), as the migrator past every policy."""
    fields = {"phone": "basic", "cccd": "sensitive", "note": "none"} if fields is None else fields
    artifact, version, author = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO studio.artifacts (id, tenant_id, kind, api_name, owning_workspace_id,"
            " row_version) VALUES (:a, :t, 'object', :n, :w, 1)"
        ),
        {"a": artifact, "t": tenant.tenant_id, "n": api_name, "w": tenant.main},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO studio.artifact_versions (id, tenant_id, artifact_id, stage,"
            " document_schema, document, row_version, contributor_ids)"
            " VALUES (:v, :t, :a, 'draft', 'dw.object/v1', '{}', 1, ARRAY[:u]::uuid[])"
        ),
        {"v": version, "t": tenant.tenant_id, "a": artifact, "u": author},
    )
    await conn.execute(
        sa.text(
            "INSERT INTO studio.object_defs (id, tenant_id, api_name, labels, applied_version_id,"
            " schema_version, created_by, updated_by)"
            ' VALUES (:a, :t, :n, \'{"vi": "Khách hàng tiềm năng"}\', :v, 1, :u, :u)'
        ),
        {"a": artifact, "t": tenant.tenant_id, "n": api_name, "v": version, "u": author},
    )
    made: dict[str, uuid.UUID] = {}
    for n, (field, category) in enumerate(fields.items(), start=1):
        made[field] = await add_field(conn, tenant.tenant_id, artifact, field, category, n)
    return Lead(artifact, made)


async def add_field(
    conn: Conn,
    tenant_id: uuid.UUID,
    object_id: uuid.UUID,
    api_name: str,
    category: str = "basic",
    field_no: int = 1,
) -> uuid.UUID:
    field = uuid.uuid4()
    await conn.execute(
        sa.text(
            "INSERT INTO studio.field_defs (id, tenant_id, object_id, api_name, labels, type,"
            " required, is_unique, indexed, pd_category, sensitive_type, storage_kind,"
            " field_no, max_length, created_by, updated_by)"
            " VALUES (:f, :t, :o, :n, '{\"vi\": \"Trường\"}', 'text', false, false, false,"
            " :c, CASE WHEN :c = 'sensitive' THEN 'identity_credentials' END, 'data',"
            " :no, 255, :u, :u)"
        ),
        {
            "f": field,
            "t": tenant_id,
            "o": object_id,
            "n": api_name,
            "c": category,
            "no": field_no,
            "u": uuid.uuid4(),
        },
    )
    return field
