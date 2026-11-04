# ruff: noqa: TID252  (relative: `records_bench` is reachable only through its own directory)
"""What record-access/01 adds after `seed(scale)`, from the same seed (ticket step 3).

No record, person, team or workspace is seeded here. Added: the effective
grants the door reads (a stand-in shaped like `platform.effective_grants`,
ADR-0104 decision 5), derived from the seed's organisation; the actor
boundaries; one access epoch per tenant; and `grants_valid_until` in the past on
1% of T1's records that carry grant keys, chosen by the seed's salt.

Who holds what:
- each profile principal holds exactly what `profiles_and_scopes` gives it, as
  privileges with a depth (own, team, workspace, workspace_subtree, tenant);
- the person of the Toàn công ty profile also holds assign and share at tenant
  depth on every object (gate HIGH 20): they make step 5's assignments and shares;
- the writer (the service account) holds read, update, create and delete at
  tenant depth, as the harness's arrays say;
- everyone else holds read, update and create at own depth on every object,
  anchored at their home workspace (the harness's `own_everywhere`);
- T2's reader and each small tenant's first person read their tenant whole.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import asyncpg

from ..ddl import Variant
from ..model import (
    LEAD,
    PERSON_COMPANY,
    PERSON_OWN,
    PERSON_PUBLIC,
    PERSON_SHARE,
    PERSON_TEAM,
    PERSON_WS1,
    PERSON_WS40,
)
from ..seed import SEED, SeedFacts
from .variants import AGENT_BOUNDARY, WRITER_BOUNDARY, PolicyVariant, post_load, schema

EXPIRED_AT = datetime(2025, 1, 1, tzinfo=UTC)  # in the past, the same on every run
EXPIRED_EVERY = 100  # 1% of the records carrying grant keys


Grant = tuple[uuid.UUID, uuid.UUID, str, str, uuid.UUID]


def profile_grants(facts: SeedFacts) -> list[Grant]:
    """The profile principals' privileges, the writer's, and T2's and the small tenants' readers."""
    t1, org = facts.t1, facts.org
    tid = t1.tenant_id
    apis = [lay.api_name for lay in facts.layouts[: t1.objects]]
    out: list[Grant] = []

    def hold(person_no: int, actions: tuple[str, ...], depth: str, anchor: uuid.UUID) -> None:
        for api in apis:
            for action in actions:
                out.append((tid, t1.person(person_no), f"obj.{api}.{action}", depth, anchor))

    def home(person_no: int) -> uuid.UUID:
        return t1.workspace(org.home_workspace(person_no))

    for person_no in (PERSON_OWN, PERSON_PUBLIC, PERSON_SHARE, org.M50, org.M500, org.M5000):
        hold(person_no, ("read",), "own", home(person_no))
    hold(PERSON_TEAM, ("read",), "team", home(PERSON_TEAM))
    hold(PERSON_WS1, ("read",), "workspace", t1.workspace(org.leaf_workspace()))
    hold(PERSON_WS40, ("read",), "workspace_subtree", t1.workspace(org.workspace_near(40)))
    hold(PERSON_COMPANY, ("read", "assign", "share"), "tenant", home(PERSON_COMPANY))
    hold(org.service_account, ("read", "update", "create", "delete"), "tenant", home(0))
    for plan in facts.plans[1:]:
        for lay in facts.layouts[: plan.objects]:
            out.append(
                (
                    plan.tenant_id,
                    plan.person(0),
                    f"obj.{lay.api_name}.read",
                    "tenant",
                    plan.workspace(0),
                )
            )
    return out


def profile_people(facts: SeedFacts) -> list[int]:
    org = facts.org
    return [
        PERSON_OWN,
        PERSON_PUBLIC,
        PERSON_SHARE,
        PERSON_TEAM,
        PERSON_WS1,
        PERSON_WS40,
        PERSON_COMPANY,
        org.M50,
        org.M500,
        org.M5000,
        org.service_account,
    ]


async def seed_inputs(conn: asyncpg.Connection, facts: SeedFacts) -> None:
    t1 = facts.t1
    await conn.copy_records_to_table(
        "bench_effective_grants",
        schema_name="studio",
        columns=["tenant_id", "principal_id", "permission_key", "depth", "anchor_workspace_id"],
        records=profile_grants(facts),
    )
    # Everyone else: read, update and create at own depth, anchored at home.
    await conn.execute(
        "INSERT INTO studio.bench_effective_grants (tenant_id, principal_id, permission_key,"
        " depth, anchor_workspace_id)"
        " SELECT p.tenant_id, p.id, 'obj.' || o.api_name || '.' || a.action, 'own',"
        " p.home_workspace_id"
        " FROM studio.bench_people p JOIN studio.object_defs o ON o.tenant_id = p.tenant_id"
        " CROSS JOIN unnest(ARRAY['read', 'update', 'create']) AS a(action)"
        " WHERE p.tenant_id = $1 AND NOT p.id = ANY ($2::uuid[])",
        t1.tenant_id,
        [t1.person(p) for p in profile_people(facts)],
    )
    await conn.copy_records_to_table(
        "actor_boundaries",
        schema_name="studio",
        columns=["tenant_id", "boundary_id", "object_ids"],
        records=[
            (t1.tenant_id, AGENT_BOUNDARY, [t1.object_id(LEAD)]),
            (t1.tenant_id, WRITER_BOUNDARY, [t1.object_id(k) for k in range(t1.objects)]),
        ],
    )
    await conn.copy_records_to_table(
        "access_epochs",
        schema_name="studio",
        columns=["tenant_id", "epoch"],
        records=[(plan.tenant_id, 1) for plan in facts.plans],
    )
    await conn.execute(
        "UPDATE studio.records SET grants_valid_until = $2"
        " WHERE tenant_id = $1 AND cardinality(read_grants) > 0"
        f" AND abs(hashtextextended(id::text, {SEED})) % {EXPIRED_EVERY} = 0",
        t1.tenant_id,
        EXPIRED_AT,
    )


@dataclass(frozen=True)
class PolicyCell:
    """The `CellExtension` of one policy variant: A1 plus its declared replacement."""

    variant: PolicyVariant
    base: Variant

    def schema(self, modulus: int) -> list[str]:
        return schema(self.variant, modulus)

    async def seed(self, conn: asyncpg.Connection, facts: SeedFacts) -> None:
        await seed_inputs(conn, facts)

    def post_load(self, modulus: int) -> list[str]:
        del modulus
        return post_load(self.variant)
