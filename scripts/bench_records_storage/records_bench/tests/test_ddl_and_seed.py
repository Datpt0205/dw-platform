# ruff: noqa: TID252  (relative: `records_bench` is reachable only through its own directory)
"""The DDL each variant measures and the seed's shape: what ticket 01 step 2 and 3 name."""

from __future__ import annotations

import re
import uuid

import pytest

from ..ddl import VARIANTS, cell_ddl, record_policies
from ..model import (
    CAMPAIGN,
    LEAD,
    W1_FAMILIES,
    bench_uuid,
    object_layouts,
    organisation,
    record_uuid,
)
from ..report import READ_PROFILES
from ..scales import D12, SCALES, SMOKE
from ..seed import SeedFacts, profiles_and_scopes, tenant_plans

pytestmark = pytest.mark.unit

# System indexes of the spec's Data section: PK, create_key, created_at,
# updated_at, name, (tenant_id, workspace_id), and record-access/03's
# access_key and owner_id.
SYSTEM_INDEXES = 8


def test_a0_has_one_partial_index_per_proposed_slot_and_a_unique_per_u_slot() -> None:
    ddl = cell_ddl(VARIANTS["A0"], 8)
    slots = sum(count for _t, count in W1_FAMILIES.values())
    assert slots == 72  # t01-t24, i01-i12, f01-f08, d01-d08, z01-z08, b01-b08, u01-u04
    assert len(ddl.indexes) == SYSTEM_INDEXES + slots + 4
    partial = [s for s in ddl.post_load if "WHERE t07 IS NOT NULL" in s]
    assert partial == [
        "CREATE INDEX ix_records_t07 ON studio.records (tenant_id, object_id, t07, id)"
        " WHERE t07 IS NOT NULL AND deleted_at IS NULL"
    ]
    assert any(
        "CREATE UNIQUE INDEX uq_records_tenant_id_object_id_u01 ON studio.records"
        " (tenant_id, object_id, u01) WHERE u01 IS NOT NULL AND deleted_at IS NULL" in s
        for s in ddl.post_load
    )
    assert any("(tenant_id, workspace_id)" in s for s in ddl.post_load)


def test_a1_adds_w2s_known_part() -> None:
    a0, a1 = cell_ddl(VARIANTS["A0"], 8), cell_ddl(VARIANTS["A1"], 8)
    # GIN read_grants, name_key, 6 l/m slot partials and their 6 FK-side indexes.
    assert len(a1.indexes) - len(a0.indexes) == 2 + 6 + 6
    text = "\n".join(a1.schema + a1.post_load)
    assert "USING gin (read_grants)" in text
    assert 'name_key text COLLATE "C" GENERATED ALWAYS AS (studio.search_key(name)) STORED' in text
    assert "REFERENCES studio.records (tenant_id, id) ON DELETE SET NULL (l01)" in text
    assert "REFERENCES studio.records (tenant_id, id) ON DELETE CASCADE" in text


def test_a2_swaps_the_updated_at_btree_for_brin_and_a3_drops_the_b_family() -> None:
    a1, a2, a3 = (cell_ddl(VARIANTS[v], 8) for v in ("A1", "A2", "A3"))
    assert "ix_records_tenant_id_object_id_updated_at" in a1.indexes
    assert "ix_records_tenant_id_object_id_updated_at" not in a2.indexes
    assert "ix_records_updated_at" in a2.indexes
    assert len(a2.indexes) == len(a1.indexes)
    assert not [i for i in a3.indexes if re.fullmatch(r"ix_records_b\d\d", i)]
    assert len(a1.indexes) - len(a3.indexes) == 8


def test_every_partition_carries_the_parents_policies_and_no_dw_app_privilege() -> None:
    for modulus in (8, 4):
        schema = "\n".join(cell_ddl(VARIANTS["A1"], modulus).schema)
        for r in range(modulus):
            part = f"studio.records_p{r}"
            assert f"FOR VALUES WITH (MODULUS {modulus}, REMAINDER {r})" in schema
            assert f"ALTER TABLE {part} FORCE ROW LEVEL SECURITY" in schema
            assert f"CREATE POLICY tenant_isolation_records_p{r} ON {part} AS RESTRICTIVE" in schema
            assert f"REVOKE ALL ON {part} FROM dw_app" in schema
        assert f"studio.records_p{modulus}" not in schema


def test_the_w1_policy_has_three_arms_for_people_and_w2_six_for_any_actor() -> None:
    def select_arms(w2: bool) -> int:
        select = next(s for s in record_policies("studio.records", "records", w2) if "_select" in s)
        return select.count("\n            OR ") + 1

    assert select_arms(False) == 3
    assert select_arms(True) == 6
    w1 = "\n".join(record_policies("studio.records", "records", False))
    assert "(SELECT studio.acl_actor_kind()) = 'user'" in w1
    assert "(SELECT current_setting('app.workspace_scope', true)) = 'tenant'" in w1


def test_c_is_a_pivot_whose_rows_carry_the_records_reach() -> None:
    ddl = cell_ddl(VARIANTS["C"], 4)
    text = "\n".join(ddl.schema)
    assert "t01 " not in text.split("CREATE TABLE studio.records (")[1].split(")")[0]
    for fam in ("t", "i", "d", "m"):
        assert f"CREATE TABLE studio.record_values_{fam} (" in text
        assert f"CREATE POLICY record_access_record_values_{fam}_select" in text
    assert "access_key uuid NOT NULL, read_grants uuid[]" in text


def test_ids_are_the_same_in_python_and_sql_shape() -> None:
    assert bench_uuid(4, 0, 777) == uuid.UUID("00040000000000000000000000000309")
    rid = record_uuid(0, 12345, 1_704_067_200_000)
    assert rid.version == 7 and str(rid)[19] == "8"


def test_the_organisation_has_the_ticket_shape() -> None:
    org = organisation(SMOKE)
    assert org.max_manager_depth == 8
    assert org.max_workspace_depth == 6
    assert len(org.subordinates(org.M50)) == 50
    assert len(org.subordinates(org.M500)) == 500
    assert len(org.subordinates(org.M5000)) == org.people - 1
    assert abs(len(org.workspace_subtree(org.workspace_near(40))) - 40) <= 5


def test_every_profile_the_report_expects_is_a_principal_of_the_seed() -> None:
    """One list of profiles, read by the report and made by the seed (failure-modes #2)."""
    for scale in (SMOKE, D12):
        facts = SeedFacts(
            scale=scale,
            plans=tenant_plans(scale, bench_uuid(1, 1, 0), [bench_uuid(1, 2, 0)]),
            layouts=object_layouts(scale.objects),
            org=organisation(scale),
        )
        profiles_and_scopes(facts, VARIANTS["A1"])
        assert tuple(p.name for p in facts.profiles) == READ_PROFILES
        principals = {p.principal for p in facts.profiles}
        scoped = {s[1] for s in facts.scopes}
        assert principals <= scoped, "a profile with no reach row reads nothing"


def test_record_numbers_map_to_their_objects() -> None:
    plan = tenant_plans(SMOKE, bench_uuid(1, 1, 0), [])[0]
    assert plan.object_of(0) == LEAD and plan.object_of(10) == LEAD
    assert plan.object_of(plan.first_campaign) == CAMPAIGN
    assert plan.leads == SMOKE.t1_records // SMOKE.lead_every


def test_smoke_keeps_d12s_shape_at_a_fiftieth_of_the_records() -> None:
    assert D12.t1_records // SMOKE.t1_records == 50
    for field in ("t2_records", "campaign_children", "service_account_leads"):
        assert getattr(D12, field) // getattr(SMOKE, field) == 50, field
    assert (SMOKE.people, SMOKE.workspaces, SMOKE.teams) == (D12.people, D12.workspaces, D12.teams)
    assert D12.read_samples >= 1_000 and SMOKE.read_samples >= 1_000
    assert D12.t1_partition_reloptions == ()
    assert set(SCALES) == {"tiny", "smoke", "d12"}
